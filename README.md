# Elektor Magazine Archive Processing Pipeline

An end-to-end Python pipeline designed to extract, enrich, embed, and query the complete historical archive (1974-2025) of Elektor Magazine. The pipeline is optimized to run on resource-constrained local hardware, preparing datasets for AI training and enabling semantic search (RAG).

---

## 🚀 Features

1. **PDF Text Extraction**: Extracts digital text from PDFs and falls back to **Tesseract OCR** (via `pypdfium2` rendering at 300 DPI) for scanned articles.
2. **Local AI Enrichment (Ollama)**: Uses decoupled models in a **Two-Pass Batch** architecture:
   - **Pass 1 (English Technical Analysis)**: Uses `qwen3.6:35b-a3b-mtp-q4_K_M` to generate summaries, topics, SFT Q&A pairs, and DPO pairs (with realistic hardware errors).
   - **Pass 2 (Turkish Translation)**: Uses `translategemma:12b-it-q4_K_M` to translate the generated title and summary into high-quality Turkish.
3. **Local Vector Database (RAG)**: Chunks article text based on word boundaries and indexes them in a local **Qdrant DB** using Ollama's `nomic-embed-text:latest` embedding model.
4. **Dataset Export**: Compiles enriched articles into training datasets (`sft_dataset.jsonl`, `dpo_dataset.jsonl`, `chat_dataset.jsonl`, and `tr_sft_dataset.jsonl`).

---

## 🛠️ Performance & Memory Optimizations

To support high-capacity batch runs without memory leakage or excessive model reload overhead:
- **Two-Pass Batch Architecture**: The enrichment step executes in two distinct passes. First, it processes all articles using the Qwen analyzer model, then unloads it. Next, it processes the batch translation using the TranslateGemma model. This completely eliminates model reload overhead per article.
- **VRAM Voids (`keep_alive=0`)**: Explicitly unloads each model from memory at the end of its respective pass, preventing memory leakage and freeing VRAM.
- **Prompt Truncation**: Truncates article text to the first 4000 characters to reduce prompt ingestion time and RAM usage.
- **Suppressed Reasoning (`think=False`)**: Forces reasoning models to skip internal thought processes, generating output directly to prevent timeouts.

---

## 📁 Directory Structure

```
elektor/
  ├── config.json            # Configuration settings (Ollama URL, paths, limits)
  ├── run.py                 # Unified Command Line Interface (CLI)
  ├── pipeline/
  │    ├── __init__.py
  │    ├── extractor.py      # PDF text extraction and SQLite metadata indexing
  │    ├── analyzer.py       # Ollama JSON enrichment generator
  │    ├── vector_store.py   # Word-boundary chunking & Qdrant database loader
  │    └── dataset_builder.py# Compiles training datasets to JSONL
  ├── .antigravity/          # Memory, walkthrough, and design artifacts
  │    ├── implementation_plan.md
  │    ├── task.md
  │    └── walkthrough.md
  └── README.md
```

---

## ⚙️ Requirements & Installation

### System Dependencies
- **Python 3.11**
- **Tesseract OCR CLI**: Installed and available in PATH (e.g. `/opt/homebrew/bin/tesseract` on macOS).
- **Ollama**: Installed and running locally. Pull the required models:
  ```bash
  ollama pull qwen3.5:2b
  ollama pull nomic-embed-text:latest
  ```

### Python Packages
Ensure the following packages are installed:
```bash
pip install pypdf pypdfium2 ollama qdrant-client pandas pytest
```

---

## 🔧 Configuration (`config.json`)

Adjust parameters in the `config.json` file:
```json
{
  "usb_path": "/Volumes/USB DISK",
  "db_path": "elektor_archive.db",
  "qdrant_db_path": "qdrant_db",
  "ollama_url": "http://192.168.1.14:11434",
  "model_embedding": "nomic-embed-text:latest",
  "model_analyzer": "qwen3.6:35b-a3b-mtp-q4_K_M",
  "model_translator": "translategemma:12b-it-q4_K_M",
  "chunk_size": 800,
  "chunk_overlap": 150,
  "ocr_threshold_chars": 100,
  "tesseract_cmd": "/opt/homebrew/bin/tesseract"
}
```

---

## 💻 Usage & CLI Subcommands

A unified orchestrator interface is provided in `run.py`:

### 1. Run full pipeline (Quick Test on 5 samples)
Extracts, enriches, embeds, and exports datasets for a sample limit of 5 files:
```bash
python3.11 run.py pipeline --limit 5
```

### 2. PDF Extraction & Database Indexing
Scans `/Volumes/USB DISK/articles` recursively and stores text in local SQLite (`elektor_archive.db`):
```bash
python3.11 run.py extract --limit 10
```

### 3. Generate Ollama Enrichments
Processes extracted SQLite articles using the local LLM:
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

## 📈 Migrating to Production Server

When migrating from local testing to a high-capacity production server:
1. Update `"usb_path"` in `config.json` if directories have changed.
2. Update `"ollama_url"` to point to the production Ollama network server (e.g., `http://192.168.1.14:11434`).
3. Set the target `"model_analyzer"` (e.g. `qwen3.6:35b-a3b-mtp-q4_K_M`) and `"model_translator"` (e.g. `translategemma:12b-it-q4_K_M`).
4. Run without limit parameters to ingest the complete archive:
   ```bash
   python3.11 run.py pipeline
   ```
