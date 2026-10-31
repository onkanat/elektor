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
