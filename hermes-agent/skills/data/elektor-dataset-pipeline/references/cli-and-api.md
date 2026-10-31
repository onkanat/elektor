# Elektor CLI & FastAPI Endpoint Reference

## 1. CLI Stages (`run.py` & `elektor_hermes_cli.py run-stage`)

| Stage | Valid `run.py` Arguments | Description |
| :--- | :--- | :--- |
| `extract` | `--limit <int\|start:end> --reset` | Parses PDFs in `input_path`, reconstructs reading order & tables, crops diagrams, and saves records into SQLite `articles`. |
| `enrich` | `--limit <int\|start:end> --reset --shards <int> --shard-ports <ports> --pass <all\|english\|turkish>` | Runs local Ollama or cloud analysis to synthesize technical summaries, Q&A pairs (SFT), DPO chosen/rejected pairs, and multi-turn chat. |
| `embed` | `--limit <int\|start:end> --reset` | Splits articles into semantic word-boundary chunks and upserts embeddings into Qdrant (`qdrant_collection_name`). |
| `query` | `<query_text> --top_k <int>` (via CLI bridge: `--search "<text>" --top-k <int>`) | Queries Qdrant vector memory and prints top matching chunks. |
| `clean_boilerplate` | `--db <path>` | Marks Colophon/TOC articles as `is_excluded = 1`, strips copyright/license Q&A pairs from SQLite `enrichments`, and re-exports clean datasets. |
| `export` | `--reset` | Compiles `sft_dataset.jsonl`, `tr_sft_dataset.jsonl`, `dpo_dataset.jsonl`, `tr_dpo_dataset.jsonl`, `chat_dataset.jsonl`, `tr_chat_dataset.jsonl` (and `.parquet`) in `exports/<project_id>/`. |
| `export_visual` | `--clear --shards <int> --shard-ports <ports>` | Builds `multimodal_visual_dataset.jsonl`, `multimodal_catalog.md`, and WebP images (`exports/<project_id>/images/*.webp`) from extracted diagram crops. |
| `judge` | `--mode <strict\|hybrid_editor> --threshold <float> --limit <int\|start:end> --batch --sync-batch` | Runs `pipeline/judge_engine.py` LLM-as-a-Judge evaluation and surgical Editor-in-Chief rewriting on SFT/DPO records. |
| `trigger` | `--limit <int\|start:end> --mode <strict\|hybrid_editor> --threshold <float> --batch --daemon --interval <sec>` | Runs `pipeline/scheduled_triggers.py` autonomous batch dataset audit and Judge pass. |
| `langextract` | `--limit <int\|start:end> --reset --provider <ollama\|openai\|gemini> --preset <name> --visualize` | Extracts grounded hardware/engineering entities with character offsets (`start_char`, `end_char`) into `langextract_grounded_dataset.jsonl`. |
| `kiwix` | `--zim <path> --url <url> --mode <auto\|stackexchange\|wiki> --batch-size <int> --limit <int\|start:end> --reset` | Ingests offline Kiwix `.zim` archives into SQLite and SFT/DPO datasets. |
| `colab` | `--project <id> --model <name> --type <all\|sft\|dpo\|chat\|langextract> --hf-dataset <repo>` | Generates Unsloth Colab/Antigravity-IDE notebooks (`unsloth_colab_<type>_<project_id>.ipynb`) in `exports/<project_id>/cloud_payload/`. |
| `hf_upload` | `--repo_id <user/repo> --project_id <id> --token <token> --private` | Uploads exported project datasets and Dataset Card to Hugging Face Hub. |
| `hooks` | `--check` | Runs self-check on `.agents/hooks.json` security gate and dataset linter hooks. |
| `self_test` | *(none)* | Runs 5-stage autonomous system health diagnostics across SQLite, Qdrant, Ollama, Vision OCR, and Pytest. |
| `pipeline` | `--limit <int\|start:end> --reset --shards <int> --shard-ports <ports> --pass <all\|english\|turkish>` | Runs `extract`, `enrich`, `embed`, and `export` sequentially. |
| `api` | `--port <int> --host <ip>` | Starts the FastAPI Web UI & REST server on `0.0.0.0:3456`. |

---

## 2. FastAPI REST Endpoints (`http://127.0.0.1:3456`)

### System & Configuration
- `GET /api/health` — Returns Ollama connectivity (`ollama_online`), active model tags, and server status.
- `GET /api/status` — Returns article count, enrichment count, active pipeline jobs, and dataset metrics.
- `GET /api/config` / `POST /api/config` — Read or update flat `config.json`.

### Multi-Project Workspace Management
- `GET /api/projects` — Lists all registered projects in `projects_index.json` and `active_project_id`.
- `POST /api/projects/select` — Body: `{"project_id": "rp01"}`.
- `POST /api/projects/create` — Body: `{"project_id": "my_proj", "project_name": "My Project", "input_mode": "folder", "input_path": "/path/to/pdfs"}`.

### Pipeline Execution & Cleaning
- `POST /api/pipeline/run` — Triggers background pipeline stages.
- `POST /api/clean-boilerplate` — Triggers one-click boilerplate/colophon pruning and dataset re-export.
