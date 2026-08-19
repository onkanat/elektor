import os
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional

try:
    from huggingface_hub import HfApi, create_repo
    HAS_HF_HUB = True
except ImportError:
    HAS_HF_HUB = False

class HFDeployer:
    def __init__(self, exports_dir: str = "exports"):
        self.exports_dir = Path(exports_dir)

    def generate_dataset_card(
        self,
        project_id: str,
        dataset_name: str,
        repo_id: str,
        stats: Optional[Dict[str, int]] = None
    ) -> str:
        """
        Generates a comprehensive Hugging Face Dataset Card (README.md) with metadata,
        tables of dataset splits, schema details, and load_dataset code snippets.
        """
        stats_md = ""
        if stats:
            stats_md = "\n".join([f"- **`{k}`**: {v:,} örnek (samples)" for k, v in stats.items()])
        else:
            stats_md = "- Standart çoklu SFT, DPO ve Chat veri kümeleri içerir."

        # Build dynamic file architecture list based on files actually existing
        file_descriptions = {
            "sft_dataset.jsonl": "English technical SFT Q&A.",
            "dpo_dataset.jsonl": "English DPO chosen/rejected preference pairs (LLM-as-a-Judge approved).",
            "chat_dataset.jsonl": "English multi-turn conversational dialogs.",
            "tr_sft_dataset.jsonl": "Turkish SFT dataset (direct generation).",
            "tr_chat_dataset.jsonl": "Turkish multi-turn technical dialogs.",
            "tr_dpo_dataset.jsonl": "Turkish DPO preference pairs (Editor-in-Chief refined).",
            "code_sft_dataset.jsonl": "Synthetic code diversity dataset (`explanation`, `completion`, `bug_fix`, `unit_test`).",
            "tr_code_sft_dataset.jsonl": "Turkish synthetic code dataset.",
            "langextract_grounded_dataset.jsonl": "Google LangExtract source grounded entity dataset with character offsets and attributes.",
            "multimodal_visual_dataset.jsonl": "Multimodal Visual VLM dataset (LLaVA/Qwen2-VL format with optimized WebP images).",
            "multimodal_catalog.md": "Rich technical diagram breakdown and visual catalog.",
        }
        
        dynamic_file_arch = []
        proj_export_dir = self.exports_dir / project_id
        if proj_export_dir.exists():
            for filename in sorted(file_descriptions.keys()):
                base_name = filename.split(".")[0]
                jsonl_file = proj_export_dir / f"{base_name}.jsonl"
                parquet_file = proj_export_dir / f"{base_name}.parquet"
                md_file = proj_export_dir / filename
                if jsonl_file.exists() or parquet_file.exists() or md_file.exists():
                    dynamic_file_arch.append(f"- `{filename}`: {file_descriptions[filename]}")
                    
        if not dynamic_file_arch:
            dynamic_file_arch.append("- No datasets exported yet.")
            
        file_arch_md = "\n".join(dynamic_file_arch)

        card_content = f"""---
license: mit
task_categories:
- text-generation
- question-answering
language:
- tr
- en
tags:
- synthetic
- code
- python
- dpo
- sft
- elektor
- universal-pipeline
size_categories:
- 1K<n<100K
pretty_name: {dataset_name}
dataset_info:
  features:
  - name: instruction
    dtype: string
  - name: input
    dtype: string
  - name: output
    dtype: string
  - name: quality_status
    dtype: string
---

# 🤗 {dataset_name}

This dataset was automatically generated and verified using the **Universal PDF & Rendergit Code Dataset Generator Pipeline** (Phase 1-4).

It contains high-quality synthetic code pairs, technical SFT Q&A, DPO (Direct Preference Optimization) preference pairs, and multi-turn technical chat sequences in both **English** and **Turkish**.

---

## 📊 Dataset Summary & Splits

{stats_md}

### File Architecture (`exports/{project_id}/`)
{file_arch_md}

---

## 🚀 How to Load in Python

Using the Hugging Face `datasets` library:

```python
from datasets import load_dataset

# Load Turkish Code SFT split
dataset = load_dataset("{repo_id}", data_files="tr_code_sft_dataset.jsonl")
print(dataset['train'][0])

# Load DPO preference dataset
dpo_dataset = load_dataset("{repo_id}", data_files="dpo_dataset.jsonl")
print(dpo_dataset['train'][0])
```

---

## 🛡️ Quality & Verification
- **AST Code Analysis**: Extracted directly from Python AST nodes.
- **DPO Verification**: Filtered via automated technical plausibility validator.
- **Traceability**: Embedded with metadata tags (`quality_status`, `language`, `dataset_type`).

*Generated on {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())} via Elektor Universal Pipeline (Phase 4).*
"""
        return card_content

    def audit_upload(
        self,
        project_id: str,
        repo_id: str,
        hf_token: Optional[str] = None,
        private: bool = False
    ) -> Dict[str, Any]:
        """
        Performs a safe dry-run audit before uploading to Hugging Face.
        Scans files, verifies token availability, generates Dataset Card preview, and commands.
        """
        audit_start = time.time()
        checks = []
        warnings = []
        errors = []

        repo_id = repo_id.strip()
        if not repo_id:
            errors.append("Hugging Face Repository ID (repo_id) boş olamaz.")

        if "/" not in repo_id:
            warnings.append(f"Repository ID '{repo_id}' kullanıcı veya organizasyon adı içermiyor (örn: 'onkanat/{repo_id}').")

        proj_export_dir = self.exports_dir / project_id
        if not proj_export_dir.exists():
            errors.append(f"Proje ihraç dizini bulunamadı: '{proj_export_dir}'. Lütfen önce veri setini ihraç edin veya birleştirin.")

        files_info = []
        total_bytes = 0
        total_samples = 0
        stats = {}

        if proj_export_dir.exists():
            for filepath in sorted(proj_export_dir.glob("*")):
                if filepath.is_file() and not filepath.name.startswith(".") and not filepath.name.endswith(".log"):
                    size_kb = round(filepath.stat().st_size / 1024.0, 2)
                    total_bytes += filepath.stat().st_size
                    samples = 0

                    if filepath.suffix == ".jsonl":
                        try:
                            with open(filepath, "r", encoding="utf-8") as f:
                                samples = sum(1 for line in f if line.strip())
                                total_samples += samples
                                stats[filepath.name] = samples
                        except Exception:
                            pass

                    files_info.append({
                        "filename": filepath.name,
                        "size_kb": size_kb,
                        "samples": samples
                    })

        if not files_info:
            errors.append(f"'{proj_export_dir}' klasöründe yüklenecek JSONL/Parquet veri kümesi dosyası bulunamadı.")

        checks.append({
            "name": "1. Dosya ve Veri Kümesi Yapısı Denetimi",
            "status": "error" if not files_info else "ok",
            "message": f"Toplam {len(files_info)} dosya ve {total_samples:,} veri örneği doğrulandı ({round(total_bytes/1024/1024, 2)} MB)."
        })

        # Token Check
        token = hf_token or os.environ.get("HF_TOKEN")
        has_token = bool(token)

        checks.append({
            "name": "2. Hugging Face Erişim Anahtarı (Token) Kontrolü",
            "status": "ok" if has_token else "warning",
            "message": "HF Token bulundu." if has_token else "HF Token bulunamadı. Public yükleme denenir ancak giriş gerekebilir."
        })

        # Dataset Card Preview
        card_preview = self.generate_dataset_card(
            project_id=project_id,
            dataset_name=project_id,
            repo_id=repo_id,
            stats=stats
        )

        cli_command = f"huggingface-cli upload {repo_id} ./{proj_export_dir} --repo-type=dataset{' --private' if private else ''}"
        python_snippet = f"from datasets import load_dataset\ndataset = load_dataset('{repo_id}')"

        checks.append({
            "name": "3. Dataset Card (README.md) Sentaks ve Şema Önizlemesi",
            "status": "ok",
            "message": "Metadata tag'leri (tr, en, sft, dpo, code) ile Otomatik Dataset Card hazırlandı."
        })

        can_proceed = len(errors) == 0

        return {
            "status": "failed" if errors else "warning" if warnings else "passed",
            "can_proceed": can_proceed,
            "project_id": project_id,
            "repo_id": repo_id,
            "private": private,
            "duration_ms": round((time.time() - audit_start) * 1000, 2),
            "checks": checks,
            "warnings": warnings,
            "errors": errors,
            "files_to_upload": files_info,
            "total_size_mb": round(total_bytes / 1024 / 1024, 2),
            "total_samples": total_samples,
            "cli_command": cli_command,
            "python_snippet": python_snippet,
            "dataset_card_preview": card_preview[:600] + "\n... (devamı otomatik README.md olarak yüklenecek)"
        }

    def upload_dataset(
        self,
        project_id: str,
        repo_id: str,
        hf_token: Optional[str] = None,
        private: bool = False
    ) -> Dict[str, Any]:
        """
        Uploads all exported dataset files for project_id to Hugging Face Datasets Hub.
        """
        if not HAS_HF_HUB:
            raise RuntimeError("`huggingface_hub` kütüphanesi ortamda yüklü değil. Lütfen 'pip install huggingface_hub' çalıştırın.")

        token = hf_token or os.environ.get("HF_TOKEN")
        if not token:
            raise ValueError("Hugging Face erişim anahtarı (HF_TOKEN) bulunamadı. Lütfen bir HF Token sağlayın.")

        proj_export_dir = self.exports_dir / project_id
        if not proj_export_dir.exists():
            raise FileNotFoundError(f"Proje ihraç dizini bulunamadı: {proj_export_dir}")

        stats = {}
        for jsonl_path in proj_export_dir.glob("*.jsonl"):
            try:
                with open(jsonl_path, "r", encoding="utf-8") as f:
                    cnt = sum(1 for line in f if line.strip())
                    stats[jsonl_path.name] = cnt
            except Exception:
                pass

        card_md = self.generate_dataset_card(
            project_id=project_id,
            dataset_name=project_id,
            repo_id=repo_id,
            stats=stats
        )
        card_file = proj_export_dir / "README.md"
        with open(card_file, "w", encoding="utf-8") as f:
            f.write(card_md)

        api = HfApi(token=token)
        try:
            repo_url = api.create_repo(
                repo_id=repo_id,
                repo_type="dataset",
                private=private,
                exist_ok=True
            )
        except Exception:
            repo_url = f"https://huggingface.co/datasets/{repo_id}"

        api.upload_folder(
            folder_path=str(proj_export_dir),
            repo_id=repo_id,
            repo_type="dataset",
            ignore_patterns=["*.log"]
        )

        return {
            "status": "success",
            "project_id": project_id,
            "repo_id": repo_id,
            "repo_url": f"https://huggingface.co/datasets/{repo_id}",
            "uploaded_files": list(stats.keys()) + ["README.md"],
            "total_samples": sum(stats.values())
        }
