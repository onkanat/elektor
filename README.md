# Elektor & Universal PDF / Rendergit Code Dataset Generator

An end-to-end Python pipeline and web application designed to extract, enrich, embed, and query PDF documents and Git repositories. Generates high-quality SFT, DPO, and multi-turn Chat datasets alongside a local Qdrant Vector database for RAG applications.

Originally built for the Elektor Magazine Archive (1974–2025), the pipeline has been refactored into a **Universal PDF & Git Repository Code Dataset Generator** supporting PDFs, technical textbooks, datasheets, and Python Git repositories via Karpathy's `rendergit` methodology.

---

## 🚀 Key Features

1. **Multi-Mode Ingestion**:
   - **Rendergit Mode (`input_mode: "rendergit"`)**: Clones Git repositories (or parses local source folders), flattens codebase structure into a unified Markdown file (`exports/<project_id>_rendergit.md`), and extracts Abstract Syntax Tree (AST) code units (classes, functions, loops) into SQLite `code_units`.
   - **Folder Mode (`input_mode: "folder"`)**: Recursively parses PDF document directories.
   - **Book Mode (`input_mode: "book"`)**: Splits large PDF textbooks or datasheets into contiguous chapters using PDF outline bookmarks, with a 10-page fallback slice generator.
2. **Dual-Mode Code Dataset Generation (Pragmatic vs. Pedagogical)**:
   - **Pragmatic Coder Mode**: Produces direct, zero-fluff code analysis starting at the first token (`### Purpose`, `### Attributes`, `### Refactored Version`), eliminating greetings and persona intros to prevent model memorization/overfitting.
   - **Pedagogical Mentor Mode**: Produces deep educational breakdowns (`### Overview & Pedagogy`, `### Theoretical Concepts & Design Patterns`, `### Trade-offs`), ideal for instructional fine-tuning.
   - **Adjustable Ratio (`pragmatic_ratio`)**: Configurable slider (%0 to %100, default 50/50) in Web UI and `config.json`.
3. **PDF Extraction & OCR Fallback**: Extracts text from digital PDFs and falls back to **Tesseract OCR** (via `pypdfium2` at 300 DPI) for scanned pages.
4. **Local AI Enrichment (Ollama)**: Two-pass batch LLM architecture:
   - **Pass 1 (Analysis)**: Uses local LLMs (e.g. `qwen3.6`, `ornith:35b`) to generate summaries, SFT Q&A, and AST code unit analysis.
   - **Pass 2 (Translation)**: Uses `translategemma:12b` to translate code explanations into technical Turkish while preserving code blocks intact.
5. **System Prompt Conditioning & Persona Cleanup**: Injects system roles (`{"role": "system", "content": "..."}`) into JSONL Chat datasets and automatically filters out repetitive persona intro lines (`"As a Senior Architect..."`).
6. **Local Vector Store (Qdrant RAG)**: Chunks text by word boundaries and indexes embeddings into local Qdrant collections using `nomic-embed-text:latest`.
7. **React Web UI & FastAPI Backend**: Features a modern React dashboard (`frontend/`) with real-time log terminal, VRAM/system metrics, project switching, and configuration management.

---

## 📁 Directory Structure

```
elektor/
  ├── config.json            # Active project configuration settings
  ├── projects_index.json    # Project registry and active project tracker
  ├── run.py                 # Unified Command Line Interface (CLI)
  ├── run_production.py      # Production batch orchestrator
  ├── api_server.py          # FastAPI backend server
  ├── pipeline/
  │    ├── __init__.py
  │    ├── extractor.py      # PDF text extraction & SQLite metadata indexing
  │    ├── code_extractor.py # Rendergit repo flattener & AST code parser
  │    ├── analyzer.py       # Ollama LLM enrichment & code analyzer
  │    ├── vector_store.py   # Word-boundary chunking & Qdrant DB indexer
  │    └── dataset_builder.py# JSONL & Parquet training dataset exporter
  ├── database/              # Dedicated SQLite database directory
  ├── exports/               # Project-isolated dataset export directory
  ├── frontend/              # React + Vite Web UI
  ├── .antigravity/          # Roadmap, walkthroughs, and architecture docs
  └── README.md
```

---

## ⚙️ Requirements & Installation

### System Dependencies
- **Python 3.11+**
- **Tesseract OCR CLI**: Installed and available in PATH (e.g. `/opt/homebrew/bin/tesseract` on macOS).
- **Ollama**: Installed and running locally. Pull required models:
  ```bash
  ollama pull nomic-embed-text:latest
  ollama pull translategemma:12b-it-q4_K_M
  ollama pull ornith:35b-q4_K_M
  ```

### Python & Node Setup
1. **Python Environment**:
   ```bash
   pip install pypdf pypdfium2 ollama qdrant-client pandas pytest fastapi uvicorn
   ```
2. **Frontend Web UI Build**:
   ```bash
   cd frontend
   npm install
   npm run build
   cd ..
   ```

---

## 🔧 Configuration (`config.json`)

Adjust parameters in `config.json` or project-specific configuration files (`projects_<id>.json`):

```json
{
  "input_mode": "rendergit",
  "input_path": "https://github.com/karpathy/rendergit",
  "db_path": "database/rendergit_01.db",
  "qdrant_db_path": "qdrant_rendergit_01",
  "ollama_url": "http://localhost:11434",
  "model_embedding": "nomic-embed-text:latest",
  "model_analyzer": "ornith:35b-q4_K_M",
  "model_translator": "translategemma:12b-it-q4_K_M",
  "llm_persona": "Senior Principal Software Architect & Code Auditor",
  "llm_subject": "Python Software Architecture, AST Analysis, Performance & Security",
  "generation_language": "bilingual",
  "translation_target": "tr",
  "sft_qa_count": 15,
  "pragmatic_ratio": 50,
  "dataset_name": "RenderGit_Python_veriseti",
  "dataset_name_tr": "RenderGit_Python_veriseti",
  "qdrant_collection_name": "rendergit_01_articles",
  "chunk_size": 800,
  "chunk_overlap": 150,
  "ocr_threshold_chars": 100,
  "tesseract_cmd": "/opt/homebrew/bin/tesseract",
  "project_id": "rendergit_01"
}
```

---

## 💻 Usage & Execution

### 1. Web UI Dashboard (FastAPI + React)
Launch the web interface:
```bash
python run.py api
# Or directly:
python -m uvicorn api_server:app --reload --port 8000
```
Open `http://localhost:8000` in your browser.

### 2. Command Line Interface (CLI)

- **Full Pipeline Run**:
  ```bash
  python run.py pipeline --limit 10
  ```
- **Text & Code Unit Extraction**:
  ```bash
  python run.py extract --limit 10
  ```
- **LLM Enrichment & Code Pass Analysis**:
  ```bash
  python run.py enrich --limit 10
  ```
- **Vector Embedding (Qdrant Indexing)**:
  ```bash
  python run.py embed
  ```
- **Export Datasets (JSONL & Parquet)**:
  ```bash
  python run.py export
  ```

---

## 🔬 Unit Tests
Run unit tests to verify AST code parsing, rendergit repository flattening, and persona intro filtering:
```bash
PYTHONPATH=. python -m pytest tests/
```
