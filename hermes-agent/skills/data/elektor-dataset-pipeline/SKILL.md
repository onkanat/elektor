---
name: elektor-dataset-pipeline
description: "Orchestrate Elektor PDF-to-SFT/DPO dataset pipeline."
version: 1.0.0
author: Hakan KILICASLAN (onkanat), Hermes Agent
license: MIT
platforms: [linux, macos]
required_environment_variables:
  - name: GEMINI_API_KEY
    prompt: "Google Gemini API Key (optional for hybrid cloud synthesis/judge)"
    help: "Used when judge_model or langextract_provider uses Gemini"
    required_for: "Hybrid Gemini SFT/DPO synthesis and Judge arbitration"
metadata:
  hermes:
    tags: [dataset, pipeline, elektor, fine-tuning, sft, dpo]
    category: data
    requires_toolsets: [terminal]
    config:
      - key: elektor.repo_path
        description: "Absolute path to the Elektor repository"
        default: "/home/hakan/Git/elektor"
        prompt: "Elektor repository path"
      - key: elektor.api_url
        description: "Base URL for the Elektor FastAPI backend"
        default: "http://127.0.0.1:3456"
        prompt: "Elektor FastAPI server URL"
---

# Elektor Dataset Pipeline Skill

End-to-end orchestration skill for the Elektor Universal PDF & Rendergit Dataset Pipeline. It enables Hermes agents (`akillibidik`, `aikonsol`, CLI, and Gateway bots) to inspect project health, switch isolated workspace projects (`project_id`), and run each `run.py` pipeline stage (`extract`, `enrich`, `embed`, `export`, `export_visual`, `clean_boilerplate`, `judge`, `trigger`, `colab`) deterministically.

## When to Use

- The user asks to run, monitor, or troubleshoot the Elektor PDF-to-Dataset pipeline.
- You need to create or switch between isolated Elektor projects (e.g., `rp01`, `sdr_engineers`, custom datasheet workspaces).
- You want to verify whether the FastAPI backend (`:3456`), Ollama inference server (`ollama_url` and local fallback), SQLite database (`db_path`), and Qdrant vector store (`qdrant_db_path`) are healthy before launching a batch job.
- You need to trigger incremental PDF extraction, LLM enrichment, vector embedding, or dataset export via CLI or REST API.

## Prerequisites

- Repository located at `elektor.repo_path` (default `/home/hakan/Git/elektor`) with Python virtualenv `.venv/bin/python` (or `python3` in PATH).
- Local (`http://127.0.0.1:11434`) or LAN Ollama server (`ollama_url` in `config.json`) and/or `GEMINI_API_KEY` for Judge arbitration.
- `terminal` toolset enabled in Hermes Agent.

## How to Run

Always start by checking pipeline and backend health using the bundled helper script via `terminal`:

```python
terminal(
    command="python3 ${HERMES_SKILL_DIR}/scripts/elektor_hermes_cli.py health",
    timeout=30
)
```

To inspect detailed CLI flags or REST API routes, load the reference documentation on demand:
- `skill_view("elektor-dataset-pipeline", "references/cli-and-api.md")`
- `skill_view("elektor-dataset-pipeline", "references/config-schema.md")`
- `skill_view("elektor-dataset-pipeline", "templates/project_config.json")`

## Quick Reference

| Operation | Hermes CLI Command (`elektor_hermes_cli.py`) | Native `run.py` / REST Equivalent |
| :--- | :--- | :--- |
| System Health Check | `elektor_hermes_cli.py health` | `GET http://127.0.0.1:3456/api/health` |
| List Projects | `elektor_hermes_cli.py projects list` | `GET http://127.0.0.1:3456/api/projects` |
| Select Active Project | `elektor_hermes_cli.py projects select --project-id rp01` | `POST /api/projects/select {"project_id": "rp01"}` |
| Create New Project | `elektor_hermes_cli.py projects create --project-id my_id --project-name "My Name"` | `POST /api/projects/create` |
| Extract PDFs | `elektor_hermes_cli.py run-stage extract --limit 10` | `.venv/bin/python run.py extract --limit 10` |
| LLM SFT/DPO Enrichment | `elektor_hermes_cli.py run-stage enrich --limit 10 --shards 2 --shard-ports 11434,11435` | `.venv/bin/python run.py enrich --limit 10 --shards 2 --shard-ports 11434,11435` |
| Qdrant Embedding | `elektor_hermes_cli.py run-stage embed --limit 20` | `.venv/bin/python run.py embed --limit 20` |
| Clean Boilerplate | `elektor_hermes_cli.py run-stage clean_boilerplate` | `.venv/bin/python run.py clean_boilerplate` |
| Export SFT/DPO JSONL | `elektor_hermes_cli.py run-stage export` | `.venv/bin/python run.py export` |
| Export Visual Catalog | `elektor_hermes_cli.py run-stage export_visual --shards 1` | `.venv/bin/python run.py export_visual --shards 1` |
| **Export Tokens (FAZ-24)** | — | `.venv/bin/python run.py tokens --project <id> --tokenizer <hf-id> [--max-len 8192]` |
| Generate Notebooks | `elektor_hermes_cli.py run-stage colab --project rp01 --type all` | `.venv/bin/python run.py colab --project rp01 --type all` |

## Procedure

1. **Verify System & Project Health**
   Run `elektor_hermes_cli.py health` and `elektor_hermes_cli.py projects list` via `terminal`.
   - *Completion criterion*: JSON output confirms `sqlite.exists == true` (e.g., `database/rp01.db`), reports `active_project` (`rp01`), `qdrant.collection` (`rp01_articles`), and identifies at least one online LLM endpoint (`ollama.configured.online` or `ollama.local_fallback.online`).

2. **Select or Create Target Workspace (If Requested)**
   If the user specifies a project ID different from `active_project`, run `elektor_hermes_cli.py projects select --project-id <project_id>` (or `projects create --project-id <id> --project-name "<name>" --pdf-source "<path>"`).
   - *Completion criterion*: Active project matches the user's target `project_id` and points to its dedicated `database/<project_id>.db`, `qdrant_<project_id>/`, and `exports/<project_id>/` paths.

3. **Execute Pipeline Stages Incrementally**
   Prefer staged execution with `--limit` when testing new PDFs:
   1. `run-stage extract --limit <N>` (PDF text, tables, and visual crops -> SQLite `articles`)
   2. `run-stage enrich --limit <N> --shards <S> --pass all` (LLM summary, English & Turkish SFT/DPO synthesis -> SQLite `enrichments`)
   3. `run-stage embed --limit <N>` (Semantic word-boundary chunks -> Qdrant collection `<project_id>_articles`)
   4. `run-stage clean_boilerplate` (Purges license/copyright/TOC noise from enrichments)
   5. `run-stage export` & `run-stage export_visual` (Writes `sft_dataset.jsonl`, `tr_sft_dataset.jsonl`, `dpo_dataset.jsonl`, `tr_dpo_dataset.jsonl`, `chat_dataset.jsonl`, `multimodal_visual_dataset.jsonl`, and `multimodal_catalog.md` in `exports/<project_id>/`)
   - *Completion criterion*: Each stage returns `returncode: 0` in the CLI JSON output.

4. **Run Self-Test & Verify Outputs**
   Run `elektor_hermes_cli.py run-stage self_test` or inspect the exported JSONL line counts in `exports/<project_id>/`.
   - *Completion criterion*: Output files (`sft_dataset.jsonl`, `dpo_dataset.jsonl`, etc.) exist in `exports/<project_id>/`, are non-empty valid JSONL, and pass schema checks.

5. **Produce the trainer-ready token file (FAZ-24) — after `export`, never modifying text exports**
   `.venv/bin/python run.py tokens --project <id> --tokenizer <hf-id> [--max-len 8192]` writes
   `exports/<project_id>/dataset.tokens.jsonl` (each row: `sample_id/source_file/source_sha256/kind/tokens/loss_mask/;
   len(tokens)==len(loss_mask); mask {0,1}, prompt 0 completion 1; DPO pair = two rows; tail truncation with
   `truncated` flag; fully-cut completion = row skipped). Vendored core: Atropos `tokenize_for_trainer.py`
   (MIT, archived) inside `pipeline/token_layer.py` with local-diffs header.
   - *Completion criterion*: `pytest tests/test_token_layer.py -q` EXIT=0 and the source export files' sha256 unchanged.

## Hermes oturum korpusu (PDF yerine sohbet kaynagi)

Sohbet gecmisinden egitim verisi cikarirken PDF boru hattini kullanma — kaynak PDF degil:

```bash
.venv/bin/python hermes-agent/scripts/hermes_sessions_to_dataset.py --out exports/<proje> --split
```

- Girdi salt-okunur `~/.hermes/state.db` (tablolar `sessions` + `messages`); cikti Elektor ile ayni semada
  `chat_dataset.jsonl` / `sft_dataset.jsonl` / `dpo_dataset.jsonl` + `manifest.json` + `KAYNAK.md`.
- **Tamamen deterministik: LLM yok, ag cagrisi yok.** Hacmin %80'i `role='tool'` mesaji (olculdu: 18,5 MB'un
  15 MB'i) ve kullanici turu yalnizca ~%5 — yani zenginlestirme degil, **temizlik** darbogaz.
- Kullanici mesajina harness zarf ekler: `[IMPORTANT: The user has invoked the "<skill>" skill ...]` + skill
  govdesi. Bunlari oldugu gibi korpusa koymak talimati 1-6 KB'lik skill metnine cevirir; betik enjeksiyonu
  atar, talimati `"<skill> yeteneğini kullan: <description>"` olarak kurar (`--drop-skill-turns` ile tamamen at).
- Yerel LLM zenginlestirmesi gerekiyorsa Ollama'nin **native `/api/chat`** yolunu kullan ve `think:false` ver;
  `/v1/chat/completions` yolunda dusunme kapatilamaz ve butce dusunme izine gider (olculdu: 500 token, icerik yok).

## Pitfalls

- **Never overwrite `config.json` with nested keys**: Elektor's `config.json` uses flat top-level keys (`db_path`, `qdrant_db_path`, `ollama_url`, `qdrant_collection_name`, `project_id`). Always use `projects select --project-id <id>` or `POST /api/config` so paths stay synchronized.
- **Unreachable LAN Ollama server**: If `ollama_url` points to a LAN GPU host (e.g., `http://192.168.1.26:11434`) that is offline, `ResilientOllamaClient` automatically fails over to `http://127.0.0.1:11434`. Check `ollama.local_fallback.online` in the `health` report.
- **Qdrant file lock contention**: When running in local disk mode (`qdrant_<project_id>/`), only one process can hold the Qdrant storage lock at a time.
- **Boilerplate contamination in fine-tuning**: Always run `clean_boilerplate` before or right after `export` so license/copyright Q&A pairs do not pollute Unsloth LoRA training.
- **transformers 5.x `apply_chat_template` returns `BatchEncoding`** (`input_ids`/`attention_mask` keys), not a token list — 4.x-era vendor/chat-template code indexing the return as a list silently gets 2-element garbage. Route every call through one normalize helper (`tokenize=True` + `input_ids[0]`; pattern: `_apply_tokens` in `pipeline/token_layer.py`) and fix the return type at all call sites.
- **Policy (user, 10.11): automatic (scheduled) jobs must NOT depend on ECE_PC's Ollama** — it is hand-started and irregular. Embeddings run on the local Ollama (`embedding_url` = `127.0.0.1`, nomic pulled locally); the vision/OCR leg keeps ECE as a CONDITIONAL hop only (graceful skip when the port is closed — tesseract/local path continues); strata at `.105:8080` is the 24/7 lane. Sır: `${STRATA_API_KEY}` env; değer repo'ya yazılmaz.

## Verification

Run the dry-run and health checks to confirm the skill and pipeline bridge are operational:

```python
terminal(
    command="python3 ${HERMES_SKILL_DIR}/scripts/elektor_hermes_cli.py run-stage pipeline --limit 1 --dry-run",
    timeout=15
)
```
