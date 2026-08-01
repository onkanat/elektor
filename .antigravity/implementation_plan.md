# Implementation Plan - Universal PDF Dataset & RAG Generator

This document details the completed technical implementation of the Universal PDF Dataset & RAG Generator pipeline, decoupling it from the original Elektor Magazine domain.

---

## 🛠️ Universal Ingestion Architecture

The pipeline supports both recursively walking folder mode (backward-compatible) and splitting a single book/manual based on bookmarks (outlines):

- **Folder Mode**: Walk directory structure recursively to parse all PDFs, using custom dataset naming tags (`dataset_name` & `dataset_name_tr`) to structure prompt context.
- **Book Mode**: Splits a single large PDF (like a reference manual) into contiguous sections using PDF outline bookmarks, with an automated 10-page split fallback when outlines are missing.

---

## ⚙️ Configuration Schema

All processing parameters are dynamically loaded from `config.json`:

```json
{
  "input_mode": "book",
  "input_path": "/path/to/document.pdf",
  "db_path": "dataset_db.db",
  "qdrant_db_path": "qdrant_db",
  "ollama_url": "http://192.168.1.14:11434",
  "model_embedding": "nomic-embed-text:latest",
  "model_analyzer": "qwen3.6:27b-mtp-q4_K_M",
  "model_translator": "translategemma:12b-it-q4_K_M",
  "llm_persona": "You are a professional software-defined radio (SDR) engineer...",
  "llm_subject": "Software-Defined Radio (SDR) design...",
  "generation_language": "en",
  "translation_target": "tr",
  "sft_qa_count": 10,
  "dataset_name": "Software-Defined Radio for Engineers",
  "dataset_name_tr": "Mühendisler İçin Yazılım Tanımlı Radyo",
  "qdrant_collection_name": "sdr_articles"
}
```

---

## 🛠️ Code Modifications & Decoupling

### 1. Extraction Layer (`pipeline/extractor.py`)
- Integrated recursive outline parser `parse_outline_nodes` and `extract_pages_range` using `pypdf` to segment books into chapter boundaries.
- Checked metadata structure for valid integer `year` formatting before binding.
- Implemented range-limit slicing (`start:end`) for bookmarks.

### 2. Analysis Layer (`pipeline/analyzer.py`)
- Formatted Qwen and TranslateGemma system prompts using dynamic `self.llm_persona` and `self.llm_subject` config variables.
- Handled remote Ollama API connection timeouts by configuring unbuffered Python logging outputs (`PYTHONUNBUFFERED=1`).
- Cleaned VRAM automatically at the end of each pass.

### 3. Vektör Veritabanı (`pipeline/vector_store.py`)
- Decoupled `self.collection_name` to read from config file (`qdrant_collection_name` key).
- Created a separate database directory per run to avoid VRAM/points overlapping.

### 4. Dataset Builder (`pipeline/dataset_builder.py`)
- Structured dynamic subfolders: exports SFT/DPO datasets directly to `exports/<db_basename>/` to prevent branch merge conflicts.
- General metadata mapping using config-level `dataset_name` and `dataset_name_tr` variables, eliminating hardcoded "Elektor" strings from SFT instructions.
