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

    def export_multimodal_dataset(self, clean_raw_crops: bool = True) -> Dict[str, Any]:
        """Processes extracted images, converts them to optimized WebP format,

        generates visual QA pairs via DeepSeek-OCR, and writes multimodal_visual_dataset.jsonl.
        """
        self.export_images_dir.mkdir(parents=True, exist_ok=True)

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

        print(f"=== FAZ-11: Generating Multimodal Visual Dataset ({len(image_mappings)} image crops) ===")

        # Step 2: Initialize Vision Manager / Client
        vision_manager = VisionOCRManager(config_path="config.json")
        client = get_openai_client(self.config)

        multimodal_records = []
        total_original_bytes = 0
        total_optimized_bytes = 0

        for idx, item in enumerate(image_mappings, 1):
            relative_img_path = item["relative_image_path"]
            webp_full_path = Path(item["webp_path"])
            total_original_bytes += item.get("original_bytes", 0)
            total_optimized_bytes += item.get("optimized_bytes", 0)

            # DeepSeek-OCR official prompt standards for figures:
            # <image>\nParse the figure.
            prompt = "<image>\nParse the figure."
            visual_description = ""

            try:
                # Describe image via DeepSeek-OCR
                if webp_full_path.exists():
                    visual_description = vision_manager.describe_cropped_image(
                        image_path=str(webp_full_path),
                        caption_context="Technical schematic / diagram analysis"
                    )
            except Exception as e:
                print(f"Warning: DeepSeek-OCR description failed for {webp_full_path.name}: {e}")
                visual_description = f"Technical schematic figure ({webp_full_path.stem})."

            if not visual_description or not visual_description.strip():
                visual_description = f"Detailed technical schematic diagram for {webp_full_path.stem}."

            # Construct LLaVA & Qwen2-VL standardized JSONL record
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
                        "value": visual_description.strip()
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
            multimodal_records.append(record)

        # Step 3: Write multimodal_visual_dataset.jsonl
        jsonl_output_path = self.export_dir / "multimodal_visual_dataset.jsonl"
        with open(jsonl_output_path, 'w', encoding='utf-8') as f:
            for rec in multimodal_records:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')

        # Step 4: Clean up raw PNG files from downloads/extracted_images/ if requested
        cleaned_files_count = 0
        if clean_raw_crops and self.raw_images_dir.exists():
            cleaned_files_count = self.optimizer.cleanup_raw_images(self.raw_images_dir, image_mappings)

        overall_saved = round((1 - (total_optimized_bytes / max(1, total_original_bytes))) * 100, 1)

        print(f"Multimodal Visual Dataset exported successfully:")
        print(f"  Visual JSONL      : {len(multimodal_records)} samples -> {jsonl_output_path}")
        print(f"  Optimized Images  : {len(image_mappings)} WebP files in {self.export_images_dir}")
        print(f"  Storage Saved     : {overall_saved}% reduction (Cleaned {cleaned_files_count} raw PNG crops)")

        return {
            "status": "success",
            "jsonl_path": str(jsonl_output_path),
            "exported_records": len(multimodal_records),
            "cleaned_raw_crops": cleaned_files_count,
            "saved_ratio_percent": overall_saved
        }
