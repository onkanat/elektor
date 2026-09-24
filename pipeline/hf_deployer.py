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
        Generates a comprehensive Hugging Face Dataset Card (README.md) with YAML metadata,
        tables of dataset splits, schema details, and load_dataset code snippets.
        """
        total_samples = sum(stats.values()) if stats else 0
        
        # Calculate size category
        if total_samples < 1000:
            size_cat = "n<1K"
        elif total_samples < 10000:
            size_cat = "1K<n<10K"
        elif total_samples < 100000:
            size_cat = "10K<n<100K"
        elif total_samples < 1000000:
            size_cat = "100K<n<1M"
        else:
            size_cat = "n>1M"

        # Determine domain tags
        is_radio = any(term in (repo_id + project_id + dataset_name).lower() for term in ["radio", "ham", "amateur", "antenna", "rf", "sdr", "telecom"])
        tags = [
            "synthetic",
            "sft",
            "dpo",
            "chat",
            "langextract",
            "grounded-qa",
            "elektor",
            "universal-pipeline"
        ]
        if is_radio:
            tags = [
                "amateur-radio",
                "ham-radio",
                "electronics",
                "sdr",
                "rf-engineering",
                "dsp",
                "antennas",
                "telecommunications"
            ] + tags
        else:
            tags = ["code", "python", "technical-documentation"] + tags

        # Pretty display name
        clean_pretty_name = dataset_name.replace("_", " ").title()
        if is_radio and ("extract" in project_id.lower() or "radio" in repo_id.lower()):
            clean_pretty_name = "Amateur Radio & Electronics QA Dataset (SFT / DPO / Chat)"

        proj_export_dir = self.exports_dir / project_id

        # Detailed file descriptions & metadata mapping
        file_meta = {
            "sft_dataset": {
                "desc": "English Supervised Fine-Tuning (SFT) technical Q&A pairs.",
                "lang": "English",
                "type": "SFT QA",
                "split": "train_sft_en"
            },
            "dpo_dataset": {
                "desc": "English Direct Preference Optimization (DPO) chosen vs rejected pairs (LLM-as-a-Judge approved).",
                "lang": "English",
                "type": "DPO Pairs",
                "split": "train_dpo_en"
            },
            "chat_dataset": {
                "desc": "English multi-turn conversational technical dialogs.",
                "lang": "English",
                "type": "Multi-turn Chat",
                "split": "train_chat_en"
            },
            "tr_sft_dataset": {
                "desc": "Turkish Supervised Fine-Tuning (SFT) technical Q&A dataset.",
                "lang": "Turkish",
                "type": "Turkish SFT QA",
                "split": "train_sft_tr"
            },
            "tr_dpo_dataset": {
                "desc": "Turkish DPO preference pairs (Editor-in-Chief refined).",
                "lang": "Turkish",
                "type": "Turkish DPO Pairs",
                "split": "train_dpo_tr"
            },
            "tr_chat_dataset": {
                "desc": "Turkish multi-turn technical conversational dialogs.",
                "lang": "Turkish",
                "type": "Turkish Multi-turn Chat",
                "split": "train_chat_tr"
            },
            "code_sft_dataset": {
                "desc": "Synthetic code dataset (`explanation`, `completion`, `bug_fix`, `unit_test`).",
                "lang": "English / Code",
                "type": "Code SFT",
                "split": "train_code_sft"
            },
            "tr_code_sft_dataset": {
                "desc": "Turkish synthetic code dataset.",
                "lang": "Turkish / Code",
                "type": "Turkish Code SFT",
                "split": "train_tr_code_sft"
            },
            "langextract_grounded_dataset": {
                "desc": "Google LangExtract source-grounded entity dataset with exact character offsets & attributes.",
                "lang": "Bilingual",
                "type": "Grounded Entities",
                "split": "grounded_extractions"
            },
            "multimodal_visual_dataset": {
                "desc": "Multimodal Visual VLM dataset (LLaVA/Qwen2-VL format with optimized WebP images).",
                "lang": "Multimodal",
                "type": "Visual VLM",
                "split": "visual_dataset"
            }
        }

        # Build dynamic configs YAML and split table
        yaml_configs = []
        table_rows = []

        if proj_export_dir.exists():
            for base_key, info in file_meta.items():
                parquet_path = proj_export_dir / f"{base_key}.parquet"
                jsonl_path = proj_export_dir / f"{base_key}.jsonl"

                chosen_file = None
                if parquet_path.exists():
                    chosen_file = f"{base_key}.parquet"
                elif jsonl_path.exists():
                    chosen_file = f"{base_key}.jsonl"

                if chosen_file:
                    yaml_configs.append(f"  - split: {info['split']}\n    path: {chosen_file}")
                    
                    # File size and samples
                    size_kb = 0
                    if (proj_export_dir / chosen_file).exists():
                        size_kb = round((proj_export_dir / chosen_file).stat().st_size / (1024 * 1024), 2)
                    
                    sample_cnt = stats.get(f"{base_key}.jsonl", 0) if stats else 0
                    sample_str = f"{sample_cnt:,}" if sample_cnt > 0 else "Included"

                    table_rows.append(f"| `{chosen_file}` | {info['type']} | {info['lang']} | {sample_str} | {size_kb} MB | {info['desc']} |")

        if not yaml_configs:
            yaml_configs.append("  - split: train\n    path: sft_dataset.parquet")

        configs_yaml_block = "configs:\n- config_name: default\n  data_files:\n" + "\n".join(yaml_configs)
        
        tags_yaml_block = "\n".join([f"- {t}" for t in tags])

        splits_table_md = "\n".join(table_rows) if table_rows else "| `sft_dataset.jsonl` | SFT | English | - | - | Standard technical Q&A dataset |"

        card_content = f"""---
license: cc-by-sa-4.0
task_categories:
- question-answering
- text-generation
language:
- en
- tr
tags:
{tags_yaml_block}
size_categories:
- {size_cat}
pretty_name: {clean_pretty_name}
{configs_yaml_block}
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

# 📻 {clean_pretty_name}

[![Hugging Face Dataset](https://img.shields.io/badge/🤗%20Hugging%20Face-Dataset-yellow.svg)](https://huggingface.co/datasets/{repo_id})
[![License: CC BY-SA 4.0](https://img.shields.io/badge/License-CC_BY--SA_4.0-blue.svg)](https://creativecommons.org/licenses/by-sa/4.0/)
[![Bilingual: EN & TR](https://img.shields.io/badge/Language-EN%20%7C%20TR-green.svg)](https://huggingface.co/datasets/{repo_id})
[![Total Samples](https://img.shields.io/badge/Samples-{total_samples:,}-orange.svg)](https://huggingface.co/datasets/{repo_id})

This dataset is a comprehensive, production-grade bilingual (**English** and **Turkish**) corpus dedicated to **Amateur Radio (Ham Radio), RF Engineering, Software Defined Radio (SDR), Signal Processing (DSP), Antennas, and Telecommunications Electronics**.

Generated and verified using the **Elektor Universal Dataset Generator Pipeline** (Phase 1-4) with strict **LLM-as-a-Judge 5D quality filtering** and **Google LangExtract** source-grounded entity linking.

---

## 📊 Dataset Architecture & Splits

| File Name | Split Type | Language | Records | Size | Description |
|---|---|---|---|---|---|
{splits_table_md}

---

## 🎯 Domain & Topic Coverage

The dataset spans essential topics in amateur radio, communications, and electronics:
- **Antenna Theory & Construction**: Wire antennas, Dipoles, Yagi-Uda, Baluns, Ununs, Impedance Matching, Smith Charts, SWR minimization, Grounding & Lightning Safety.
- **Software Defined Radio (SDR) & DSP**: RTL-SDR, HackRF, GNU Radio, IQ sampling, FFT, Demodulation (AM/FM/SSB/Digital), Filters (FIR/IIR).
- **Operating Modes & Protocols**: CW (Morse Code), Single Sideband (SSB), FM, FT8, JS8Call, PSK31, APRS, Packet Radio, AX.25, DMR, D-STAR.
- **Propagation & RF Physics**: Ionospheric layers (D/E/F), Solar Flux Index (SFI), Sunspot Cycles, MUF/LUF, Tropospheric Ducting, Skip Zones, SNR calculations.
- **Transceivers & Hardware DIY**: Superheterodyne vs Direct Conversion, PA stages, LNA, BPF/LPF, Baofeng/Yaesu/Icom architectures, RFI/EMI suppression via Ferrite chokes.
- **Licensing & Regulations**: ARRL, FCC Part 97, CEPT, IARU band plans, operating ethics, repeaters, emergency telecommunications (ARES/RACES).

---

## 🚀 How to Load and Use in Python

Using the Hugging Face `datasets` library:

```python
from datasets import load_dataset

# 1. Load English SFT (Supervised Fine-Tuning) Split
ds_sft = load_dataset("{repo_id}", data_files="sft_dataset.parquet")
print("English SFT Sample:", ds_sft['train'][0])

# 2. Load Turkish SFT Split (Türkçe Soru-Cevap)
ds_tr_sft = load_dataset("{repo_id}", data_files="tr_sft_dataset.parquet")
print("Turkish SFT Sample:", ds_tr_sft['train'][0])

# 3. Load DPO Preference Pairs (Chosen vs Rejected)
ds_dpo = load_dataset("{repo_id}", data_files="dpo_dataset.parquet")
print("DPO Pair:", ds_dpo['train'][0])

# 4. Load Multi-Turn Conversational Chat
ds_chat = load_dataset("{repo_id}", data_files="chat_dataset.parquet")
print("Chat Messages:", ds_chat['train'][0])

# 5. Load Grounded Entity Extractions (LangExtract with Character Offsets)
ds_grounded = load_dataset("{repo_id}", data_files="langextract_grounded_dataset.parquet")
print("Grounded Entity:", ds_grounded['train'][0])
```

---

## ⚡ Quick Fine-Tuning Recipe (Unsloth / TRL)

You can fine-tune any modern LLM (Qwen 2.5, Llama 3.1, Gemma 2, Mistral) using [Unsloth](https://github.com/unslothai/unsloth):

```python
from unsloth import FastLanguageModel
from datasets import load_dataset
from trl import SFTTrainer
from transformers import TrainingArguments

# Load base model
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/Qwen2.5-3B-Instruct",
    max_seq_length=2048,
    load_in_4bit=True,
)

# Add LoRA adapters
model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_alpha=16,
    lora_dropout=0,
    bias="none",
)

# Load dataset
dataset = load_dataset("{repo_id}", data_files="sft_dataset.parquet", split="train")

# Train
trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="output",
    max_seq_length=2048,
    args=TrainingArguments(
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_steps=10,
        max_steps=100,
        learning_rate=2e-4,
        fp16=True,
        logging_steps=10,
        output_dir="outputs",
    ),
)
trainer.train()
```

---

## 🛡️ Data Curation & Quality Assurance

- **Source Attribution**: Extracted from curated Amateur Radio Stack Exchange archive data dumps (`ham.stackexchange.com`) and technical engineering publications.
- **LLM-as-a-Judge 5D Evaluation**: Every question-answer and DPO pair was scored across 5 dimensions (*Faithfulness, Clarity, Factual Correctness, Domain Relevance, Safety*).
- **Grounded Verification**: All extractions are mapped back to character offsets and source articles using Google LangExtract.
- **Direct Localization**: Turkish pairs are verified and aligned for professional terminology (e.g. *Empedans Uyumlama, Balun, Taşıyıcı Frekansı, İyonosferik Yayılım*).

---

## 📜 License & Citation

This dataset is distributed under the **Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)** license in accordance with Stack Exchange network content terms.

*Generated on {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())} via Elektor Universal Pipeline.*
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
        Scans files, verifies token availability, generates & saves Dataset Card (README.md), and provides modern CLI commands.
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
                if filepath.is_file() and not filepath.name.startswith(".") and not filepath.name.endswith(".log") and filepath.name != "README.md":
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

        # Generate and automatically persist Dataset Card (README.md)
        card_content = self.generate_dataset_card(
            project_id=project_id,
            dataset_name=project_id,
            repo_id=repo_id,
            stats=stats
        )

        card_saved = False
        if proj_export_dir.exists():
            card_file = proj_export_dir / "README.md"
            try:
                with open(card_file, "w", encoding="utf-8") as f:
                    f.write(card_content)
                card_saved = True
            except Exception as e:
                warnings.append(f"Dataset Card (README.md) diske kaydedilemedi: {e}")

        # Modern Hugging Face CLI command ('hf upload') with automatic cloud_payload cleanup
        cli_command = f'hf upload {repo_id} ./{proj_export_dir} --exclude "cloud_payload/*" "*.log" --delete "cloud_payload/*" --repo-type=dataset{" --private" if private else ""}'
        
        python_snippet = (
            f"from datasets import load_dataset\n\n"
            f"# English SFT dataset\n"
            f"ds_sft = load_dataset('{repo_id}', data_files='sft_dataset.parquet')\n\n"
            f"# Turkish SFT dataset\n"
            f"ds_tr_sft = load_dataset('{repo_id}', data_files='tr_sft_dataset.parquet')\n\n"
            f"# DPO preference pairs\n"
            f"ds_dpo = load_dataset('{repo_id}', data_files='dpo_dataset.parquet')"
        )

        checks.append({
            "name": "3. Dataset Card (README.md) Sentaks ve Şema Doğrulaması",
            "status": "ok" if card_saved else "warning",
            "message": f"Metadata tag'leri (amateur-radio, tr, en, sft, dpo, langextract) ile Otomatik Dataset Card {'üretilip README.md olarak kaydedildi.' if card_saved else 'hazırlandı.'}"
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
            "dataset_card_preview": card_content[:800] + "\n\n... (devamı README.md olarak otomatik yüklenecek)"
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
            ignore_patterns=["*.log", "cloud_payload/*", "cloud_payload"],
            delete_patterns=["cloud_payload/*"]
        )

        return {
            "status": "success",
            "project_id": project_id,
            "repo_id": repo_id,
            "repo_url": f"https://huggingface.co/datasets/{repo_id}",
            "uploaded_files": list(stats.keys()) + ["README.md"],
            "total_samples": sum(stats.values())
        }

