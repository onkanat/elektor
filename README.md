# Elektor Magazine Archive Processing Pipeline

An end-to-end Python pipeline designed to extract, enrich, embed, and query the complete historical archive (1974-2025) of Elektor Magazine. The pipeline is optimized to run on resource-constrained local hardware, preparing datasets for AI training and enabling semantic search (RAG).

---

## 🚀 Features

1. **PDF Text Extraction**: Extracts digital text from PDFs and falls back to **Tesseract OCR** (via `pypdfium2` rendering at 300 DPI) for scanned articles.
2. **Local AI Enrichment (Ollama)**: Uses local LLMs (e.g. `qwen3.5:2b`) to generate:
   - Summaries and topics (English).
   - SFT (Supervised Fine-Tuning) Q&A pairs (English).
   - DPO (Direct Preference Optimization) pairs (English) with realistic hardware design errors in rejected responses.
   - Turkish title and summary translations.
3. **Local Vector Database (RAG)**: Chunks article text based on word boundaries and indexes them in a local **Qdrant DB** using Ollama's `nomic-embed-text:latest` embedding model.
4. **Dataset Export**: Compiles enriched articles into training datasets (`sft_dataset.jsonl`, `dpo_dataset.jsonl`, `chat_dataset.jsonl`, and `tr_sft_dataset.jsonl`).

---

## 🛠️ Optimizations for Local Hardware

To support running on standard laptop hardware (e.g. Apple Silicon M2 CPU/iGPU) during development, the following optimizations are implemented:
- **Single-Call AI completion**: Instead of 4 separate calls, all enrichments (Summary, Topics, Q&A, DPO, Turkish translation) are requested in **one combined JSON completions request**.
- **Prompt Truncation**: Truncates article text to the first 4000 characters to reduce prompt ingestion time and RAM usage.
- **Suppressed Reasoning (`think=False`)**: Forces the reasoning model (like Qwen 3.5 Instruct) to completely skip the internal thought process output, generating content directly to prevent timeouts and token limit cutoffs.

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
  "ollama_url": "http://localhost:11434",
  "model_embedding": "nomic-embed-text:latest",
  "model_analyzer": "qwen3.5:2b",
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
2. Update `"ollama_url"` to point to the remote/local network Ollama server.
3. Change `"model_analyzer"` to a larger model (e.g. `qwen2.5:72b` or `llama3.3:70b`).
4. Run without limit parameters to ingest the complete archive:
   ```bash
   python3.11 run.py pipeline
   ```
