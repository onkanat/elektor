# Backend Gateway & CLI Usage Scenarios Documentation
> [!NOTE]
> This document serves as the developer gateway and integration documentation for the backend processing pipeline, prepared for the upcoming frontend design session.

---

## 📁 File & Directory Architecture

The backend project structure is organized as follows:

```
├── config.json                     # Shared backend config file (Frontend reads/writes this)
├── run.py                          # Unified CLI Entrypoint for pipeline actions
├── run_production.py               # Orchestrator daemon for batch production runs
├── database/                       # Dedicated folder for SQLite databases
│   ├── elektor_archive.db          # Elektor Magazine database
│   └── sdr_engineers.db            # SDR for Engineers database
├── exports/                        # Restructured dynamic export folder
│   ├── elektor_archive/            # JSONL dataset files for Elektor
│   └── sdr_engineers/              # JSONL dataset files for SDR Book
├── pipeline/                       # Python pipeline packages
│   ├── extractor.py                # PDF Extraction & outlines segmentation
│   ├── analyzer.py                 # Ollama LLM Enrichment & Translation (Qwen/Gemma)
│   ├── vector_store.py             # Qdrant local embedding ingestion & RAG query
│   └── dataset_builder.py          # SFT, DPO, and Chat dataset compiler
└── tests/                          # Automated Pytest suite
```

---

## ⚙️ Configuration Contract (`config.json`)

The frontend interacts with the backend by reading and writing to the `config.json` file in the project root directory.

| Key | Type | Description | Example Value |
| :--- | :---: | :--- | :--- |
| `input_mode` | `string` | Ingestion mode: `"book"` (single file bookmarks parsing) or `"folder"` (recursive PDF folder walk) | `"book"` |
| `input_path` | `string` | Absolute path to the source PDF file or folder | `"/Users/hakankilicaslan/Documents/SDR4Engineers.pdf"` |
| `db_path` | `string` | SQLite database file location | `"database/sdr_engineers.db"` |
| `qdrant_db_path` | `string` | Directory for local Qdrant Vector database files | `"qdrant_sdr"` |
| `qdrant_collection_name`| `string` | Name of the Qdrant Collection | `"sdr_articles"` |
| `ollama_url` | `string` | API endpoint for the Ollama inference server | `"http://192.168.1.14:11434"` |
| `model_embedding` | `string` | Embedding model for Qdrant indexing | `"nomic-embed-text:latest"` |
| `model_analyzer` | `string` | Teacher model used for technical analysis/SFT/DPO generation | `"qwen3.6:27b-mtp-q4_K_M"` |
| `model_translator` | `string` | Bilingual model used for translation tasks | `"translategemma:12b-it-q4_K_M"` |
| `llm_persona` | `string` | Persona description injected into the LLM system prompt | `"You are a professional software-defined radio engineer..."` |
| `llm_subject` | `string` | Main subject matter scope to frame Q&A generation | `"Software-Defined Radio design, DSP..."` |
| `generation_language` | `string` | Language code for base generation (`"en"` or `"tr"`) | `"en"` |
| `translation_target` | `string`| Target language code for bilingual alignment | `"tr"` |
| `sft_qa_count` | `int` | Number of instruction Q&A pairs to generate per segment | `10` |
| `chunk_size` | `int` | Context split chunk size for vectorization (in characters) | `800` |
| `chunk_overlap` | `int` | Context overlap size for vectorization | `150` |
| `dataset_name` | `string` | Dynamic dataset name tag used in English prompts | `"Software-Defined Radio for Engineers"` |
| `dataset_name_tr` | `string` | Dynamic dataset name tag used in Turkish prompts | `"Mühendisler İçin Yazılım Tanımlı Radyo"` |

---

## 🗄️ Database Schemas

### 1. `articles` Table
Stores raw document file metadata and page text segments.

| Column | Type | Constraints | Description |
| :--- | :---: | :--- | :--- |
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Auto-incremented unique ID |
| `file_path` | `TEXT` | `UNIQUE` | Physical path or bookmark outline node identifier |
| `filename` | `TEXT` | - | Name of source document |
| `title` | `TEXT` | - | Parsed title or section header |
| `year` | `INTEGER` | - | Publication year or document revision date |
| `extracted_text`| `TEXT` | - | Cleaned raw OCR text content |
| `is_embedded` | `INTEGER` | `DEFAULT 0` | Flag (0 or 1) indicating if chunk embeddings are loaded in Qdrant |

### 2. `enrichments` Table
Stores LLM-generated summaries, SFT questions, and DPO training pairs.

| Column | Type | Constraints | Description |
| :--- | :---: | :--- | :--- |
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Auto-incremented unique ID |
| `article_id` | `INTEGER` | `FOREIGN KEY` references `articles(id)` | ID of the source page/bookmark segment |
| `summary` | `TEXT` | - | Generated English summary paragraph |
| `topics` | `TEXT` | - | JSON array of technical keywords |
| `turkish_title`| `TEXT` | - | Translated segment title |
| `turkish_summary`| `TEXT`| - | Translated Turkish summary paragraph |
| `sft_qa` | `TEXT` | - | JSON array of English Q&A instruction pairs |
| `dpo_pairs` | `TEXT` | - | JSON array of English chosen/rejected pairs |
| `tr_sft_qa` | `TEXT` | - | JSON array of Turkish Q&A instruction pairs |
| `tr_dpo_pairs`| `TEXT` | - | JSON array of Turkish chosen/rejected pairs |
| `processed_at` | `TEXT` | - | Timestamp of database update |

---

## 🖥️ Command Line Usage Scenarios

The frontend triggers backend operations using the following CLI commands:

### Scenario A: Clean Initialization & Pipeline Execution
Triggered when starting a new document run. Wipes old database files, vector collections, and starts ingestion.
```bash
# Wipes existing outputs and runs full extraction, enrichment, embedding and export
python run.py pipeline --reset
```

### Scenario B: Incremental Extraction
Extracts pages/outlines from the PDF path specified in `config.json` and updates the SQLite database.
```bash
# Extract all segments
python run.py extract

# Extract a limited subset (e.g. bookmarks 0 to 50)
python run.py extract --limit 0:50
```

### Scenario C: Parallel Model Enrichment
Enriches raw text with summaries, SFT, and DPO pairs using remote models.
```bash
# Enrich all non-processed segments
python run.py enrich

# Enrich a limited subset (e.g. segments 50 to 100)
python run.py enrich --limit 50:100
```

### Scenario D: Vector Embedding Ingestion
Generates vectors using `model_embedding` and upserts them to the local Qdrant collection.
```bash
python run.py embed
```

### Scenario E: SFT & DPO Dataset Export
Compiles database rows and exports final SFT/Chat/DPO training JSONL files.
```bash
python run.py export
```

### Scenario F: RAG Query Simulation
Searches Qdrant and retrieves relevant context chunks with similarity scores.
```bash
python run.py query "carrier frequency synchronization Plutosdr"
```

---

## 🎨 Proposed Frontend Design Session Guidelines

The frontend can be built as a dashboard structured around three main sections:

### 1. Pipeline Control Panel
- **Configuration Form**: Input fields mapping directly to `config.json` parameters.
- **Process Actions**: Buttons to launch `extract`, `enrich`, `embed`, and `export` CLI tasks.
- **Console Log Stream**: Live output terminal displaying raw console lines in real-time.

### 2. Dataset Management & Metrics
- **Job Status Cards**: Displays total processed segments, completed translations, and active VRAM memory usage.
- **Dataset Preview Table**: Paginated view of generated English/Turkish SFT questions, summaries, and DPO pairs loaded directly from SQLite.
- **Export Action**: Button to trigger Hugging Face dataset creation and folder uploads.

### 3. RAG Sandbox (Playground)
- **Search Console**: Text box to run test queries.
- **Result Panels**: Side-by-side view showing the query, matched document source, page index, similarity score, and vectorized text snippet.
