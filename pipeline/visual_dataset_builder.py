import os
import json
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional
from pipeline.llm_client import get_openai_client
from pipeline.image_optimizer import ImageOptimizer
from pipeline.vision_ocr import VisionOCRManager

class VisualDatasetBuilder:
    """FAZ-11: Multimodal Visual Dataset Generator for LLaVA & Qwen2-VL Format.

    Generates visual instruction-tuning datasets from cropped diagrams and schematics
    using DeepSeek-OCR (<image>\nParse the figure. & <image>\nDescribe this image in detail.).
    """

    def __init__(self, config_path: str = "config.json"):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

        self.project_id = self.config.get("project_id", "default_project")
        self.db_path = self.config.get("db_path", f"database/{self.project_id}.db")
        self.export_dir = Path("exports") / self.project_id
        self.export_images_dir = self.export_dir / "images"
        self.raw_images_dir = Path("downloads") / "extracted_images"
        self.vision_model = self.config.get("model_vision", "deepseek-ocr:3b-bf16")

        self.optimizer = ImageOptimizer(max_dimension=1024, webp_quality=85)

    def detect_active_ports(self, shard_ports_str: Optional[str] = None) -> List[int]:
        """Detects active Ollama ports (e.g., 11434, 11435) for 2x GPU parallel sharding."""
        import urllib.parse
        import socket

        if shard_ports_str:
            ports = [int(p.strip()) for p in shard_ports_str.split(",") if p.strip().isdigit()]
        else:
            ports = [11434, 11435, 11436]

        ollama_url = self.config.get("ollama_url", "http://localhost:11434")
        parsed = urllib.parse.urlparse(ollama_url)
        host = parsed.hostname or "localhost"

        active_ports = []
        for port in ports:
            try:
                with socket.create_connection((host, port), timeout=1.5):
                    active_ports.append(port)
            except Exception:
                pass

        return active_ports if active_ports else [parsed.port or 11434]

    def _ensure_sqlite_wal(self):
        """Configures SQLite WAL mode and busy_timeout for concurrency safety."""
        if os.path.exists(self.db_path):
            try:
                conn = sqlite3.connect(self.db_path, timeout=60.0)
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA busy_timeout=60000;")
                conn.close()
            except Exception as e:
                print(f"Notice: Could not set WAL mode on {self.db_path}: {e}")

    def export_multimodal_dataset(
        self,
        clean_raw_crops: bool = False,
        shards: int = 1,
        shard_ports: Optional[str] = None,
        min_chars: int = 25
    ) -> Dict[str, Any]:
        """Processes extracted images, converts them to WebP format,
        generates visual QA pairs via DeepSeek-OCR / VLM across parallel GPU worker ports,
        applies a 25-char/token quality filter, and writes multimodal_visual_dataset.jsonl.
        """
        self.export_images_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_sqlite_wal()

        # Step 1: Optimize raw images to WebP in exports/<project_id>/images/
        image_mappings = self.optimizer.process_raw_images(self.raw_images_dir, self.export_images_dir)

        # Also collect existing WebP images in export_images_dir if raw was already processed
        existing_webp = list(self.export_images_dir.glob("*.webp"))
        if not image_mappings and existing_webp:
            for webp_file in existing_webp:
                image_mappings.append({
                    "raw_filename": webp_file.name,
                    "raw_path": str(webp_file),
                    "webp_filename": webp_file.name,
                    "webp_path": str(webp_file),
                    "relative_image_path": f"images/{webp_file.name}",
                    "original_bytes": webp_file.stat().st_size,
                    "optimized_bytes": webp_file.stat().st_size,
                    "saved_ratio_percent": 0.0
                })

        if not image_mappings:
            print(f"Notice: No image crops found in {self.raw_images_dir} or {self.export_images_dir}. Visual dataset export skipped.")
            return {"status": "skipped", "message": "No images found", "exported_records": 0}

        # Step 2: Detect active worker ports & configure parallel sharding
        active_ports = self.detect_active_ports(shard_ports)
        worker_count = max(1, shards if shards > 1 else len(active_ports))
        print(f"=== FAZ-11: Generating Multimodal Visual Dataset ({len(image_mappings)} image crops) ===")
        print(f"  Parallel Sharding : {worker_count} workers across ports {active_ports}")
        print(f"  Quality Filter    : Minimum {min_chars} characters/tokens output threshold")

        # Create VisionOCRManager instances bound to worker ports
        import urllib.parse
        ollama_url = self.config.get("ollama_url", "http://localhost:11434")
        parsed_url = urllib.parse.urlparse(ollama_url)
        scheme = parsed_url.scheme or "http"
        host = parsed_url.hostname or "localhost"

        vision_managers = []
        for p in active_ports:
            cfg_copy = self.config.copy()
            cfg_copy["ollama_url"] = f"{scheme}://{host}:{p}"
            try:
                v_mgr = VisionOCRManager(config_dict=cfg_copy)
                if v_mgr.check_health():
                    vision_managers.append(v_mgr)
            except Exception as e:
                print(f"Notice: Failed to initialize VisionOCRManager for port {p}: {e}")

        if not vision_managers:
            # Fallback to single default manager
            v_mgr = VisionOCRManager(config_path="config.json")
            if not v_mgr.check_health():
                err_msg = (
                    f"ERROR: Vision server at '{ollama_url}' is unreachable. "
                    f"Please ensure Ollama is running and model '{self.vision_model}' is available."
                )
                print(err_msg)
                return {"status": "error", "message": err_msg, "exported_records": 0}
            vision_managers.append(v_mgr)

        import concurrent.futures

        multimodal_records = []
        failed_count = 0
        low_quality_count = 0
        total_original_bytes = 0
        total_optimized_bytes = 0

        def process_single_crop(item_tuple):
            idx, item = item_tuple
            v_mgr = vision_managers[idx % len(vision_managers)]
            relative_img_path = item["relative_image_path"]
            webp_full_path = Path(item["webp_path"])
            port = str(v_mgr.config.get("ollama_url", "11434")).split(":")[-1]

            visual_description = ""
            try:
                if webp_full_path.exists():
                    visual_description = v_mgr.describe_cropped_image(
                        image_path=str(webp_full_path),
                        caption_context="Technical schematic / diagram analysis"
                    )
            except Exception as e:
                print(f"[{idx}/{len(image_mappings)}] [Port {port}] ❌ Exception for {webp_full_path.name}: {e}", flush=True)
                visual_description = ""

            clean_text = visual_description.strip() if isinstance(visual_description, str) else ""

            is_valid = (
                clean_text
                and not clean_text.startswith("[Vision Extraction Error")
                and not clean_text.startswith("[Error:")
                and "Connection error" not in clean_text
                and not clean_text.startswith("Technical schematic and architectural diagram representation")
            )

            if not is_valid:
                print(f"[{idx}/{len(image_mappings)}] [Port {port}] ❌ Skipping {webp_full_path.name} - VLM extraction failed or empty", flush=True)
                return (None, "failed", item)

            if len(clean_text) < min_chars:
                print(f"[{idx}/{len(image_mappings)}] [Port {port}] ⚠️ Rejected {webp_full_path.name} - Too short ({len(clean_text)} chars < {min_chars} min threshold)", flush=True)
                return (None, "low_quality", item)

            print(f"[{idx}/{len(image_mappings)}] [Port {port}] ✓ Processed {webp_full_path.name} ({len(clean_text)} chars)", flush=True)

            record_id = f"vis_sample_{self.project_id}_{idx:04d}_{webp_full_path.stem}"
            record = {
                "id": record_id,
                "image": relative_img_path,
                "conversations": [
                    {
                        "from": "human",
                        "value": "<image>\nBu teknik çizimi/şemayı detaylıca analiz et ve bileşenleri açıkla."
                    },
                    {
                        "from": "gpt",
                        "value": clean_text
                    }
                ],
                "metadata": {
                    "project_id": self.project_id,
                    "model_vision": self.vision_model,
                    "original_filename": item["raw_filename"],
                    "webp_filename": item["webp_filename"],
                    "saved_ratio_percent": item.get("saved_ratio_percent", 0.0)
                }
            }
            return (record, "success", item)

        # Step 3: Run Worker Pool with live progress
        indexed_items = [(idx, item) for idx, item in enumerate(image_mappings, 1)]
        results = []

        print(f"Starting VLM processing across {len(vision_managers)} workers...\n", flush=True)

        if worker_count > 1 and len(vision_managers) > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(vision_managers)) as executor:
                futures = [executor.submit(process_single_crop, item_tuple) for item_tuple in indexed_items]
                for future in concurrent.futures.as_completed(futures):
                    results.append(future.result())
        else:
            for item in indexed_items:
                results.append(process_single_crop(item))

        for record, status, item in results:
            total_original_bytes += item.get("original_bytes", 0)
            total_optimized_bytes += item.get("optimized_bytes", 0)
            if status == "success" and record:
                multimodal_records.append(record)
            elif status == "low_quality":
                low_quality_count += 1
            else:
                failed_count += 1

        if not multimodal_records:
            err_msg = (
                f"ERROR: Failed to generate valid visual descriptions for all {len(image_mappings)} image crops. "
                f"Vision model '{self.vision_model}' failed or Ollama endpoint is unreachable. "
                f"No dummy records were written to prevent dataset corruption."
            )
            print(err_msg)
            return {
                "status": "error",
                "message": err_msg,
                "exported_records": 0,
                "failed_crops": failed_count,
                "low_quality_crops": low_quality_count
            }

        # Step 4: Write multimodal_visual_dataset.jsonl
        jsonl_output_path = self.export_dir / "multimodal_visual_dataset.jsonl"
        with open(jsonl_output_path, 'w', encoding='utf-8') as f:
            for rec in multimodal_records:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')

        # Step 4.5: Generate Rich Unified Multimodal Markdown Catalog (with embedded images)
        md_catalog_path = self.export_dir / "multimodal_catalog.md"
        with open(md_catalog_path, 'w', encoding='utf-8') as mf:
            mf.write(f"# 📊 Multimodal Technical Catalog & Diagram Breakdown\n\n")
            mf.write(f"**Project:** `{self.project_id}` | **VLM Model:** `{self.vision_model}` | **Total Figures:** {len(multimodal_records)}\n\n---\n\n")
            for idx, rec in enumerate(multimodal_records, 1):
                img_rel = rec.get("image", "")
                meta = rec.get("metadata", {})
                orig_name = meta.get("original_filename", f"figure_{idx}")
                
                # Extract conversation answer
                convs = rec.get("conversations", [])
                ans_text = ""
                for c in convs:
                    if c.get("from") in ("gpt", "assistant"):
                        ans_text = c.get("value", "")
                        break
                
                mf.write(f"## Figure {idx}: `{orig_name}`\n\n")
                mf.write(f"![{orig_name}]({img_rel})\n\n")
                mf.write(f"### 🔍 Technical Parsing & Extraction\n\n")
                mf.write(f"{ans_text}\n\n")
                mf.write(f"---\n\n")

        # Step 5: Clean up raw PNG files from downloads/extracted_images/ ONLY if clean_raw_crops (--clear) is True
        cleaned_files_count = 0
        if clean_raw_crops and self.raw_images_dir.exists():
            cleaned_files_count = self.optimizer.cleanup_raw_images(self.raw_images_dir, image_mappings)
            print(f"  Raw Crop Cleanup  : Deleted {cleaned_files_count} raw PNG crops (--clear active)")
        else:
            print(f"  Raw Crop Storage  : Raw PNG crops preserved in {self.raw_images_dir} (Use --clear flag to delete)")

        overall_saved = round((1 - (total_optimized_bytes / max(1, total_original_bytes))) * 100, 1)

        print(f"Multimodal Visual Dataset exported successfully:")
        print(f"  Visual JSONL      : {len(multimodal_records)} samples -> {jsonl_output_path}")
        print(f"  Markdown Catalog  : Embedded visual report -> {md_catalog_path}")
        print(f"  Optimized Images  : {len(image_mappings)} WebP files in {self.export_images_dir}")
        print(f"  Quality Filtered  : {low_quality_count} crops (< {min_chars} chars)")
        print(f"  Failed/Skipped    : {failed_count} crops")
        print(f"  Storage Saved     : {overall_saved}% reduction")

        return {
            "status": "success",
            "jsonl_path": str(jsonl_output_path),
            "markdown_catalog_path": str(md_catalog_path),
            "exported_records": len(multimodal_records),
            "low_quality_crops": low_quality_count,
            "failed_crops": failed_count,
            "cleaned_raw_crops": cleaned_files_count,
            "saved_ratio_percent": overall_saved
        }

    # Alias for method name consistency
    export_visual_dataset = export_multimodal_dataset
