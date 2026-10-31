---
name: elektor-rag-memory
description: "Query Elektor Qdrant vectors and SQLite knowledge."
version: 1.0.0
author: Hakan KILICASLAN (onkanat), Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [rag, qdrant, sqlite, mcp, vector-search, elektor]
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

# Elektor RAG Vector Memory & SQLite Knowledge Skill

Semantic vector retrieval and structured SQLite querying skill for Hermes agents. It exposes Elektor's Qdrant vector database (`qdrant_collection_name`, e.g., `rp01_articles`), SQLite `articles` and `enrichments` tables (`db_path`, e.g., `database/rp01.db`), and the zero-dependency Stdio MCP server (`elektor_mcp_server.py`) so agents can ground hardware/electronics answers in verified datasheet chunks.

## When to Use

- The user asks a technical hardware, microcontroller (RP2040, RP2350, ESP32, STM32), or electronics question that should be grounded in indexed PDFs and datasheets.
- You need to search Qdrant vector memory (`rag-search`) or run keyword lookups across SQLite `articles` and LLM `enrichments` (`sqlite-search`).
- You want to evaluate whether a topic has sufficient SFT/DPO coverage (`dataset-context --evaluate-gap`) before synthesizing new training data.
- You want to register Elektor as a native MCP server in Hermes Agent (`hermes mcp`).

## Prerequisites

- Repository virtualenv (`.venv/bin/python`) with `qdrant-client` installed.
- Populated SQLite database (`db_path`, e.g., `database/rp01.db`) and Qdrant storage (`qdrant_db_path`, e.g., `qdrant_rp01/`).
- Embedding model accessible via Ollama (`model_embedding: "nomic-embed-text:latest"`).

## How to Run

Run a semantic vector search directly from Hermes using `terminal`:

```python
terminal(
    command="python3 ${HERMES_SKILL_DIR}/scripts/elektor_hermes_cli.py rag-search --query 'RP2040 PIO state machine FIFO' --limit 5 --json",
    timeout=30
)
```

For schema details and MCP registration instructions, load:
- `skill_view("elektor-rag-memory", "references/qdrant-and-sqlite.md")`
- `skill_view("elektor-rag-memory", "references/mcp-integration.md")`

## Quick Reference

| Retrieval Mode | Command (`elektor_hermes_cli.py`) | Underlying Module |
| :--- | :--- | :--- |
| Semantic Vector Search (Qdrant) | `elektor_hermes_cli.py rag-search -q "<query>" -k 5 --json` | `pipeline.mcp_tools.search_vector_rag` |
| SQLite Article Keyword Search | `elektor_hermes_cli.py sqlite-search -k "<keyword>" --table articles` | `pipeline.mcp_tools.query_sqlite_knowledge` |
| SQLite Enrichment Search | `elektor_hermes_cli.py sqlite-search -k "<keyword>" --table enrichments` | `pipeline.mcp_tools.query_sqlite_knowledge` |
| Fetch Exported SFT/DPO Samples | `elektor_hermes_cli.py dataset-context -t "<topic>" --max-samples 3` | `pipeline.mcp_tools.inject_sft_dpo_context` |
| Knowledge Gap Audit | `elektor_hermes_cli.py dataset-context -t "<topic>" --evaluate-gap` | `pipeline.mcp_tools.evaluate_knowledge_gap` |

## Procedure

1. **Semantic Retrieval First (`rag-search`)**
   Execute `elektor_hermes_cli.py rag-search --query "<technical query>" --limit 5 --json` via `terminal`.
   - *Completion criterion*: Returns top-k semantic chunks from `qdrant_collection_name` (`rp01_articles`) with similarity scores, source PDF filenames, and article titles.

2. **Cross-Check Exact Register Names or Part Numbers (`sqlite-search`)**
   When searching for exact hexadecimal addresses, register names, or part numbers (e.g., `IO_BANK0`, `0x40014000`, `RP2040`), run `elektor_hermes_cli.py sqlite-search --keyword "<symbol>" --table articles`.
   - *Completion criterion*: Returns matching article excerpts (`extracted_text_snippet`) and metadata directly from SQLite (`db_path`).

3. **Inspect Synthesized SFT/DPO Knowledge & Coverage Gaps (`dataset-context`)**
   Run `elektor_hermes_cli.py dataset-context --topic "<topic>" --evaluate-gap` to compare baseline vs dataset-enriched technical coverage (`knowledge_gain_percent`).
   - *Completion criterion*: Outputs structured evaluation (`knowledge_gain_percent`, `factuality`, `verdict`).

4. **Synthesize Grounded Technical Answer**
   Combine retrieved Qdrant chunks and SQLite records into a concise response citing the source PDF filename and section/article title.

## Pitfalls

- **Tools answer `Database file not found` or `count: 0` although the data exists**: `pipeline/mcp_tools.py` and `pipeline/vector_store.py` resolve `config.json`, `db_path` and `qdrant_db_path` **relative to the current working directory**, not to the repo. An MCP host spawns the server from an arbitrary cwd, so the config lookup silently fails, defaults apply (`database/sdr_engineers.db`, `qdrant_rp01`) and the tools report an error or an empty result with **no exception**. `hermes-agent/scripts/elektor_mcp_server.py` pins the cwd with `os.chdir(REPO_ROOT)` (honouring `ELEKTOR_REPO_PATH`) before importing the pipeline — keep that line, and reproduce any such bug by running the server over stdio from `cd /tmp`. After editing the server script run `/reload-mcp` in the chat: the live MCP process keeps the old code until the client reconnects.
- **`/reload-mcp` does not pick up a patched server script**: the slash command tears down and re-discovers the profile's MCP servers, but a session that was already running keeps its **bound child process** from session start — the reload spawns a short-lived discovery probe (visible as an `elektor_mcp_server.py` process that exits a few seconds later) while the old child keeps serving calls with the code it loaded at 13:16. Symptom: identical errors after a successful reload. Remedy: `pgrep -f elektor_mcp_server.py`, confirm the stale child's age (`ps -o lstart=`, `/proc/<pid>/cwd`), `kill <pid>`; the MCP client waits briefly and respawns the child from the current script on the next call — no gateway restart needed.
- **Embedding endpoint down looks like an empty index**: an unreachable `ollama_url` logs `Error testing embedding model dimension ... Defaulting to 768` then `Search failed: 404 model not found`, and vector search returns `count: 0` while SQLite keeps working. Check `curl -s <ollama_url>/api/tags | grep nomic-embed-text` before blaming Qdrant.
- **Concurrent local Qdrant lock**: In local disk mode (`qdrant_<project_id>/`), Qdrant locks the folder during active writes. `ArchiveVectorStore` always closes its client in a `finally:` block to prevent lock leaks.
- **Embedding dimension mismatch**: Never change `model_embedding` (`nomic-embed-text:latest`) on an existing Qdrant collection without recreating the collection (`run-stage embed --reset`).

## Verification

Test SQLite keyword retrieval against the active database:

```python
terminal(
    command="python3 ${HERMES_SKILL_DIR}/scripts/elektor_hermes_cli.py sqlite-search --keyword 'RP2040' --table articles --limit 2 --json",
    timeout=20
)
```
