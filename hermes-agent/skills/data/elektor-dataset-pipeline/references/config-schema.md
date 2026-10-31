# Elektor Flat `config.json` Schema Reference

The Elektor pipeline stores its active configuration as a **flat JSON object** in `/home/hakan/Git/elektor/config.json` (and per-project files in `projects_<project_id>.json`).

## Key Flat Configuration Keys

### 1. Project Identity & Storage Paths
- `project_id`: Unique project slug (e.g., `"rp01"`, `"sdr_engineers"`).
- `dataset_name` / `dataset_name_tr`: Dataset identifier for English and Turkish exports (e.g., `"rp_pico"`).
- `input_mode`: `"folder"`, `"book"`, `"rendergit"`, or `"kiwix"`.
- `input_path`: Directory or file path containing input PDFs, Git repo, or ZIM archive (e.g., `"/home/hakan/PDF/raspberyy"`).
- `db_path`: SQLite database file path (e.g., `"database/rp01.db"`).
- `qdrant_db_path`: Local Qdrant storage directory (e.g., `"qdrant_rp01"`).
- `qdrant_collection_name`: Qdrant collection name (e.g., `"rp01_articles"`).
- *Derived Exports Path*: `exports/<Path(db_path).stem>/` (e.g., `exports/rp01/`).

### 2. LLM, Vision & Embedding Endpoints
- `ollama_url`: Primary Ollama server URL (e.g., `"http://192.168.1.26:11434"` or `"http://127.0.0.1:11434"`). `ResilientOllamaClient` automatically fails over to `http://127.0.0.1:11434` if the LAN endpoint is offline.
- `embedding_url`: OpenAI-compatible embedding URL (e.g., `"http://192.168.1.26:11434/v1"`).
- `model_analyzer`: Primary text synthesis model (e.g., `"ornith-1.5:9b"`).
- `model_translator`: Turkish synthesis/translation model (e.g., `"ornith-1.5:9b"`).
- `model_vision`: Vision-Language Model for schematic/diagram captioning and VLM OCR (e.g., `"deepseek-ocr:3b-bf16"`).
- `model_embedding`: Embedding model for Qdrant vector indexing (e.g., `"nomic-embed-text:latest"`).
- `judge_model`: LLM-as-a-Judge arbitration model (e.g., `"gemini-2.5-flash"`).

### 3. Dataset Synthesis & Quality Guardrails
- `generation_language`: `"bilingual"`, `"en"`, or `"tr"`.
- `direct_tr_generation`: `true` (synthesizes Turkish SFT/DPO directly without 2-pass translation drift).
- `clean_alpaca_input`: `true` (enforces `"input": ""` in `sft_dataset.jsonl` and `tr_sft_dataset.jsonl` to prevent Unsloth template shortcut memorization).
- `filter_boilerplate`: `true` (excludes Colophon, Creative Commons license, copyright, and TOC pages/questions).
- `enable_dpo_verification`: `true`.
- `generate_multi_turn_chat`: `true`.

### 4. RAG & OCR Parameters
- `chunk_size`: Target character length per word-boundary chunk (`1000`).
- `chunk_overlap`: Overlap between consecutive chunks (`150`).
- `ocr_threshold_chars`: Character threshold below which a PDF page triggers OCR fallback (`100`).
- `tesseract_cmd`: System Tesseract binary (`"tesseract"`).
- `enable_vision_ocr`: Enables `deepseek-ocr:3b-bf16` multimodal extraction (`true`).
