# Qdrant Vector Store & SQLite Schema Reference

## 1. Qdrant Vector Collection (`pipeline/vector_store.py`)

- **Collection Name**: Configured via flat `qdrant_collection_name` in `config.json` (e.g., `rp01_articles` for project `rp01`).
- **Storage Path**: Configured via flat `qdrant_db_path` in `config.json` (e.g., `qdrant_rp01`).
- **Chunking Strategy**: Deterministic word-boundary semantic chunking (`chunk_size: 1000`, `chunk_overlap: 150`). Never splits words or Markdown table rows mid-token.
- **Embedding Model**: `model_embedding: "nomic-embed-text:latest"` with automatic cloud-to-local embedding fallback (`get_embedding_client()`).
- **Payload Schema**:
  ```json
  {
    "article_id": 12,
    "chunk_index": 3,
    "title": "RP2040 Datasheet - Chapter 3: PIO",
    "filename": "RP-008371-DS-1-rp2040-datasheet.pdf",
    "year": 2026,
    "text": "Full semantic chunk text..."
  }
  ```

---

## 2. SQLite Database Schema (`db_path`, e.g., `database/rp01.db`)

### Table: `articles`
Stores extracted PDF documents, book chapters, and Kiwix entries:
- `id` (`INTEGER PRIMARY KEY AUTOINCREMENT`)
- `file_path` (`TEXT UNIQUE`)
- `filename` (`TEXT`)
- `title` (`TEXT`)
- `year` (`INTEGER`)
- `extracted_text` (`TEXT` — cleaned, reading-order-reconstructed Markdown + tables)
- `is_ocr` (`INTEGER DEFAULT 0`)
- `is_enriched` (`INTEGER DEFAULT 0`)
- `is_embedded` (`INTEGER DEFAULT 0`)
- `is_excluded` (`INTEGER DEFAULT 0` — set to `1` for boilerplate/colophon articles)
- `source_type` (`TEXT DEFAULT 'pdf'`)

### Table: `enrichments`
Stores LLM-synthesized English and Turkish SFT, DPO, and Chat payloads linked to `articles.id`:
- `id` (`INTEGER PRIMARY KEY AUTOINCREMENT`)
- `article_id` (`INTEGER`, foreign key to `articles.id`)
- `summary` (`TEXT`)
- `turkish_title` (`TEXT`)
- `sft_qa` (`TEXT` — JSON array of English SFT/DPO Q&A records)
- `tr_sft_qa` (`TEXT` — JSON array of direct Turkish SFT/DPO Q&A records)
- `multi_turn_chat` / `tr_multi_turn_chat` (`TEXT` — JSON multi-turn diagnostic dialogues)
