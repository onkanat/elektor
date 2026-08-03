# Elektor & Universal PDF Dataset Generator

An end-to-end Python pipeline designed to extract, enrich, embed, and query PDF documents to generate high-quality SFT, DPO, and multi-turn Chat datasets, alongside a local Qdrant Vector database for RAG applications. 

Originally built for the Elektor Magazine Archive (1974-2025), the pipeline has been refactored into a **Universal PDF Dataset Generator** that can process either recursively nested folders of PDFs or split a single book/manual into bookmark-defined chapters.

---

## 🚀 Features

1. **Dual Ingestion Modes**:
   - **Folder Mode (`input_mode: "folder"`)**: Walks a directory structure recursively, parsing all PDF files individually (backward compatible with the Elektor Magazine layout).
   - **Book Mode (`input_mode: "book"`)**: Splits a single large PDF (like a microchip datasheet or technical textbook) into contiguous chapters using PDF outline bookmarks, with an automated 10-page split fallback when outlines are missing.
2. **PDF Extraction & OCR Fallback**: Extracts digital text from PDFs and falls back to **Tesseract OCR** (via `pypdfium2` rendering at 300 DPI) for page ranges that lack selectable text.
3. **Local AI Enrichment (Ollama)**: Uses decoupled models in a **Two-Pass Batch** architecture:
   - **Pass 1 (English Technical Analysis)**: Uses `qwen3.6:35b` to generate summaries, topics, SFT Q&A pairs, and DPO pairs (with realistic hardware errors).
   - **Pass 2 (Turkish Translation)**: Uses `translategemma:12b` to translate the generated title and summary into high-quality Turkish.
4. **Dynamic LLM Persona prompts**: Injects target expertise personas (`llm_persona`) and domain subjects (`llm_subject`) dynamically from the configuration schema into LLM prompts.
5. **Local Vector Database (RAG)**: Chunks article text based on word boundaries and indexes them in a local **Qdrant DB** using Ollama's `nomic-embed-text:latest` embedding model.
6. **Flexible Dataset Export**: Compiles enriched articles into training datasets in both English and Turkish (`sft_dataset.jsonl`, `dpo_dataset.jsonl`, `chat_dataset.jsonl`, `tr_sft_dataset.jsonl`, `tr_chat_dataset.jsonl`, `tr_dpo_dataset.jsonl`).

---

## 📁 Directory Structure

```
elektor/
  ├── config.json            # Configuration settings (Ollama URL, modes, schemas)
  ├── run.py                 # Unified Command Line Interface (CLI)
  ├── run_production.py      # Production orchestrator batch runner
  ├── pipeline/
  │    ├── __init__.py
  │    ├── extractor.py      # PDF text extraction and SQLite metadata indexing
  │    ├── analyzer.py       # Ollama JSON enrichment generator
  │    ├── vector_store.py   # Word-boundary chunking & Qdrant database loader
  │    └── dataset_builder.py# Compiles training datasets to JSONL
  ├── .antigravity/          # Yol Haritası, walktrough ve plan dosyaları
  │    └── roadmap_universal_pipeline.md
  └── README.md
```

---

## ⚙️ Requirements & Installation

### System Dependencies
- **Python 3.11**
- **Tesseract OCR CLI**: Installed and available in PATH (e.g. `/opt/homebrew/bin/tesseract` on macOS).
- **Ollama**: Installed and running locally. Pull the required models:
  ```bash
  ollama pull qwen3.6:35b-a3b-mtp-q4_K_M
  ollama pull translategemma:12b-it-q4_K_M
  ollama pull nomic-embed-text:latest
  ```

### Python Packages
Ensure the following packages are installed:
```bash
pip install pypdf pypdfium2 ollama qdrant-client pandas pytest
```

---

## 🔧 Configuration (`config.json`)

Adjust parameters in the `config.json` file for your target domain:
```json
{
  "input_mode": "book",
  "input_path": "/path/to/rp2040_datasheet.pdf",
  "db_path": "database/sdr_engineers.db",
  "qdrant_db_path": "qdrant_sdr",
  "ollama_url": "http://192.168.1.14:11434",
  "model_embedding": "nomic-embed-text:latest",
  "model_analyzer": "qwen3.6:35b-a3b-mtp-q4_K_M",
  "model_translator": "translategemma:12b-it-q4_K_M",
  "llm_persona": "You are a professional embedded systems engineer and senior hardware instructor.",
  "llm_subject": "RP2040 and RP2350 hardware architecture, GPIO configuration, and SDK development.",
  "generation_language": "en",
  "translation_target": "tr",
  "sft_qa_count": 10,
  "chunk_size": 800,
  "chunk_overlap": 150,
  "ocr_threshold_chars": 100,
  "tesseract_cmd": "/opt/homebrew/bin/tesseract"
}
```

---

## 🧠 Model ve Prompt Sandbox Ayarları Rehberi (config.json)

`config.json` ve projeye özel `projects_<project_id>.json` dosyalarında yer alan **Model ve Prompt Sandbox Ayarları**, Elektor/Synthetic Data Pipeline'ının üretken yapay zeka (LLM) modelleriyle kurduğu etkileşimin sınırlarını, uzmanlık kimliğini ve veri kalitesini doğrudan belirleyen kritik parametrelerdir.

Bu ayarların doğru yapılandırılması, modellerin genel-geçer veya yanlış alana ait yanıtlar (örneğin tarih dökümanında donanım/devre şeması yanıtı üretilmesi gibi "prompt sızıntılarını") üretmesini engeller ve domain-agnostik (alana özgü) sentetik veri seti kalitesini garanti altına alır.

### 🎯 1. Neden Kritik Önem Taşır?

1. **Domain İzolasyonu (Sınırlandırma):** LLM'e verilen roller (`llm_persona`) ve odak konuları (`llm_subject`), modelin dökümanı incelerken yalnızca hedeflenen alanın terminolojisi ve perspektifiyle SFT (Supervised Fine-Tuning) ve DPO (Direct Preference Optimization) çiftleri üretmesini sağlar.
2. **Hallüsinasyon ve Sızıntı Önleme:** Kod tabanında sabit (hardcoded) promptlar kullanıldığında model dökümandan bağımsız olarak eski şablonlara kayabilir. Sandbox parametreleri ile istemler dinamik biçimlendirilir.
3. **Dil ve Çeviri Hassasiyeti:** `generation_language` ve `translation_target` ayarları, kaynak döküman dili ile çıktı veri seti dilini ayrıştırarak çok dilli (multilingual) model eğitimine hazır veri üretir.

---

### 📋 2. Temel Sandbox Parametreleri ve Anlamları

| Parametre | Açıklama | Örnek Değer |
| :--- | :--- | :--- |
| `llm_persona` | Analizci modelin üstlendiği uzmanlık rolü | `"Akademik tarih araştırmaları uzmanı"` / `"SDR & DSP Hardware Engineer"` |
| `llm_subject` | Analiz edilen dökümanın temel konusu | `"Türk Tarihi, Cumhuriyet Dönemi"` / `"Software-Defined Radio, FPGA"` |
| `generation_language` | Analiz ve soru-cevap üretilecek hedef dil | `"tr"` / `"en"` |
| `translation_target` | İkincil çeviri veri seti hedef dili | `"tr"` |
| `model_analyzer` | Veri seti analizi ve Q&A üretecek ana LLM | `"gemma4:26b-a4b-it-qat"` / `"qwen3.5:2b"` |
| `model_embedding` | Vektör veritabanı chunk gömme modeli | `"nomic-embed-text:latest"` |
| `sft_qa_count` | Her döküman/bölüm için üretilecek SFT soru sayısı | `10` |
| `chunk_size` / `chunk_overlap` | Metin bölümleme ve çakışma karakter sayısı | `800` / `150` |
| `ocr_threshold_chars` | OCR tetikleme alt karakter eşiği | `100` |

---

### 💡 3. Konfigürasyon Örnekleri

#### Örnek A: Tarih ve Sosyal Bilimler Projesi (Türk Tarih Tezi Seti)
Tarih ve akademi odaklı dökümanlar işlenirken modelin akademik dil kullanmasını ve tarihsel terimlere sadık kalmasını sağlayan yapılandırma:

```json
{
  "project_id": "türk",
  "dataset_name": "Türk_tarih_seti",
  "input_mode": "folder",
  "input_path": "/Belgelerim/TürkTarihTezi",
  "db_path": "database/türk.db",
  "qdrant_db_path": "qdrant_türk",
  "qdrant_collection_name": "türk_articles",
  "generation_language": "tr",
  "translation_target": "tr",
  "llm_persona": "Cumhuriyet dönemi akademik tarih araştırmaları uzmanı ve historiograf",
  "llm_subject": "Türk Tarihi, Türk Tarih Tezi, 1931 Ders Kitapları Analizi",
  "model_analyzer": "gemma4:26b-a4b-it-qat",
  "model_translator": "translategemma:12b-it-q4_K_M",
  "model_embedding": "nomic-embed-text:latest",
  "sft_qa_count": 10,
  "chunk_size": 800,
  "chunk_overlap": 150,
  "ocr_threshold_chars": 100
}
```

#### Örnek B: Teknik ve Donanım Mühendisliği Projesi (SDR & RP2040)
Gömülü sistemler veya donanım dökümanları işlenirken teknik register, sinyal işleme ve devre şeması kavramlarına odaklanan yapılandırma:

```json
{
  "project_id": "sdr_engineers",
  "dataset_name": "Software-Defined Radio for Engineers",
  "input_mode": "book",
  "input_path": "/articles/SDR4Engineers.pdf",
  "db_path": "database/sdr_engineers.db",
  "qdrant_db_path": "qdrant_sdr",
  "qdrant_collection_name": "sdr_articles",
  "generation_language": "en",
  "translation_target": "tr",
  "llm_persona": "Senior SDR & DSP Hardware Architecture Engineer",
  "llm_subject": "Software-Defined Radio, FPGA, RF Front-End, SPI/I2C Protocols",
  "model_analyzer": "qwen3.5:2b",
  "model_translator": "translategemma:12b-it-q4_K_M",
  "model_embedding": "nomic-embed-text:latest",
  "sft_qa_count": 10,
  "chunk_size": 800,
  "chunk_overlap": 150,
  "ocr_threshold_chars": 100
}
```

---

### 📌 4. Önemli Kullanım Notları

> [!IMPORTANT]
> **Proje Oluştururken Sınırları Belirleyin:** Yeni bir proje açarken veya `config.json` düzenlerken `llm_persona` ve `llm_subject` alanlarını ne kadar net ve spesifik tanımlarsanız, LLM tarafından üretilecek SFT Soru-Cevap ve DPO tercih çiftlerinin kalitesi o derece yüksek olur.
>
> **Modül Uyumluğu:** `generation_language: "tr"` seçildiğinde sistem promptları ve üretilen sentetik veri seti doğrudan Türkçe olarak yapılandırılır; ek bir çeviri maliyetine gerek kalmaz.

---

## 💻 Usage & CLI Subcommands

A unified orchestrator interface is provided in `run.py`:

### 1. Run full pipeline (Quick Test on 5 samples)
Extracts, enriches, embeds, and exports datasets:
```bash
python3.11 run.py pipeline --limit 5
```

### 2. PDF Ingestion & Database Indexing
Scans the directory (in `folder` mode) or splits the single PDF outline (in `book` mode):
```bash
python3.11 run.py extract --limit 10
```

### 3. Generate Ollama Enrichments
Processes extracted SQLite segments using the configured local LLM:
```bash
python3.11 run.py enrich --limit 10
```

### 4. Build and Load Vector DB
Generates nomic embeddings and saves them to local Qdrant:
```bash
python3.11 run.py embed
```

### 5. Semantic Search Query (RAG Check)
Queries the local Qdrant collection:
```bash
python3.11 run.py query "ESP32 bluetooth low energy"
```

### 6. Compile and Export Datasets
Exports dataset files to `exports/` directory:
```bash
python3.11 run.py export
```

---

## 🔬 Unit Tests
Run unit tests to ensure extraction, database parsing, and chapter segmentation function correctly:
```bash
python3.11 -m pytest
```
