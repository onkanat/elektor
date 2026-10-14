# Project: Elektor Hardening & Dataset Optimization

## Architecture
The Elektor platform is an end-to-end data processing, RAG, and fine-tuning dataset generation system for embedded systems and technical engineering domains. It supports dual deployment across local Ollama clusters and hybrid Gemini cloud architectures.

### Component Boundaries & Data Flow
```
[Unstructured Raw Docs] (PDF, Kiwix ZIM, Git repos)
       │
       ▼
[ArchiveExtractor] (pipeline/extractor.py)
  ├── PDF layout / printed TOC parsing / OCR fallback (Tesseract / DeepSeek-OCR)
  └── Clean text & chapter normalization
       │
       ├───► [Database Session Manager] (pipeline/db.py) ──► SQLite (database/rp01.db)
       │
       ├───► [SmartTextChunker] (pipeline/chunking.py)
       │       └── Word-boundary, Markdown structure & sentence preservation
       │       └── [ArchiveVectorStore] (pipeline/vector_store.py) ──► Qdrant (local/server)
       │
       ▼
[ArchiveAnalyzer] (pipeline/analyzer.py)
  ├── Direct Turkish generation (ornith-1.5:9b)
  ├── English enrichment + TranslateGemma translation
  └── Resilient JSON repair
       │
       ▼
[JudgeEngine] (pipeline/judge_engine.py)
  └── Gemini Flash arbitration (strict scoring, hybrid surgical rewrite, batch API)
       │
       ▼
[DatasetBuilder] (pipeline/dataset_builder.py)
  ├── Targeted boilerplate & colophon filtering
  ├── Strict Alpaca schema enforcement ("input": "")
  ├── Strict DPO triplet schema enforcement ({"prompt", "chosen", "rejected"})
  └── JSONL & Parquet serialization (exports/<project>/)
       │
       ▼
[CloudGPUOffloader] (pipeline/cloud_gpu_offloader.py)
  └── Unsloth Desktop & TRL formatting (SFT / DPO / Chat)

[API Server & CLI] (api_server.py & run.py)
  └── Unified entry points, health check, sharded parallel execution, graceful teardown
```

---

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Dedicated Word-Boundary Chunker | Recursive delimiter splitting (`\n\n`, `\n`, sentence endings), code block and table preservation, no character-severing or whitespace flattening | M1 | Survey R1 |
| 2 | Modernized Qdrant Vector Storage | Support for remote `qdrant_url` / `qdrant_api_key` alongside local `qdrant_db_path`, elimination of silent `:memory:` fallback, batch embedding upserts | M1 | Survey R1 |
| 3 | Deterministic Semantic Retrieval | Score-based filtering (`score_threshold`), return complete payload (`article_id`, `chunk_index`, `point_id`, `score`), payload indexing | M1 | Survey R1 |
| 4 | Vector-to-Document Linking | Payload indexing on `article_id` and indexed join to SQLite `articles` and `enrichments` | M1 | Survey R1 |
| 5 | Strict Alpaca SFT Schema Enforcement | Ensure 100% of SFT records have `"input": ""` across standard, Kiwix, and synthetic code exports with zero `Context:`/`Bağlam:` leakage | M2 | Survey R2 |
| 6 | Strict DPO Triplet Normalization | Clean `{"prompt", "chosen", "rejected"}` schema with zero extraneous `"metadata"` or `"input"` keys across English, Turkish, and Kiwix DPO | M2 | Survey R2 |
| 7 | Targeted Boilerplate Filtering | Refine `BOILERPLATE_PATTERNS` to target legal/copyright notices without pruning legitimate hardware IP (Synopsys DesignWare) | M2 | Survey R2 |
| 8 | Turkish Terminology & LaTeX Preservation | Maintain technical engineering terms and LaTeX notation in direct Turkish prompts and translation pipelines | M3 | Survey R3 |
| 9 | Hybrid LLM Arbitration & Resilience | Gemini Flash arbitration with model cascading fallbacks, offline heuristic fallback, rate limit pacing, and batch API | M3 | Survey R3 |
| 10 | Unsloth & TRL Fine-Tuning Compatibility | Standardize dataset mapping, tokenizer padding/eos safety, and notebook/script generation for base LLMs and LoRA | M3 | Survey R3 |
| 11 | Centralized Database Session & Teardown | `pipeline/db.py` context manager with WAL mode, `busy_timeout=60000`, `try...finally` teardown, batch commits, and rollback | M4 | Survey R4 |
| 12 | Multi-GPU VRAM & Directory Lock Teardown | Explicit `unload_ollama_model` in `VisualDatasetBuilder`, `store.close()` in `run.py`, and pooled async HTTP clients in `llm_client.py` | M4 | Survey R4 |
| 13 | API Server Lifecycle & Concurrency Fix | Fix `/api/pipeline/run` race condition, add `"export_visual"` to valid commands, dynamic port and paths in `/api/health` | M4 | Survey R4 |
| 14 | Documentation Purge & Link Remediation | Replace 40+ `file:///Users/hakankilicaslan/...` links with relative paths across all markdown docs; fix guide image paths | M5 | Survey R5 |
| 15 | CLI Command & Config Schema Synchronization | Fix `README.md` command examples; synchronize `config.json`, `gemini.json`, `ollama_cloud.json` and templates | M5 | Survey R5 |
| 16 | Root Pytest Configuration & Test Optimization | Add root `pytest.ini` (`pythonpath = .`), optimize real image fixtures in integration test, add export validation test | M5 | Survey R5 |
| 17 | Full E2E Test Suite & Adversarial Hardening | 100% pass of 4-tier E2E test suite + Tier 5 adversarial stress testing + Victory Audit | M-FINAL | Acceptance Criteria |

---

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Vector Store & RAG Navigation Hardening | Features 1, 2, 3, 4 (`pipeline/chunking.py`, `pipeline/vector_store.py`, `tests/test_vector_store.py`) | None | DONE |
| M2 | Dataset Compilation & Decomposition Pipeline | Features 5, 6, 7 (`pipeline/dataset_builder.py`, `tests/test_export_schema_compliance.py`) | None | DONE |
| M3 | Turkish Fine-Tuning Synthesis & Hybrid Arbitration | Features 8, 9, 10 (`pipeline/analyzer.py`, `pipeline/judge_engine.py`, `pipeline/cloud_gpu_offloader.py`) | None | DONE |
| M4 | Architectural Modularity, Resource Teardown & API/CLI Hardening | Features 11, 12, 13 (`pipeline/db.py`, `run.py`, `api_server.py`, `pipeline/visual_dataset_builder.py`) | M1 | DONE |
| M5 | Documentation Cleansing & Schema Synchronization | Features 14, 15, 16 (`pytest.ini`, docs, config templates, `tests/test_real_data_pipelines.py`) | M2, M4 | DONE |
| M-FINAL | Final E2E Test Pass (100%) & Adversarial Coverage Hardening | Feature 17 (Pass all E2E Tiers 1-4, Tier 5 Adversarial Hardening, Victory Audit) | M1, M2, M3, M4, M5 | DONE |

---

## Interface Contracts

### `pipeline/chunking.py` ↔ `pipeline/vector_store.py`
```python
@dataclass
class TextChunk:
    text: str
    chunk_index: int
    total_chunks: int
    start_char: int
    end_char: int
    token_estimate: int

class SmartTextChunker:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 150): ...
    def chunk_text(self, text: str, max_chunks: int = 500) -> list[TextChunk]: ...
```

### `pipeline/db.py` ↔ All Pipeline Modules
```python
@contextmanager
def get_db_connection(db_path: str | Path, timeout: float = 60.0, wal_mode: bool = True) -> Generator[sqlite3.Connection, None, None]:
    """Provides a managed SQLite connection with WAL mode, busy timeout, and automatic rollback on exception."""
    ...

@contextmanager
def get_db_cursor(db_path: str | Path, timeout: float = 60.0) -> Generator[sqlite3.Cursor, None, None]:
    """Provides a managed cursor that automatically commits on normal exit and rolls back on exception."""
    ...
```

### `pipeline/vector_store.py` ↔ API & CLI
```python
class ArchiveVectorStore:
    def __init__(self, config: dict = None): ...
    def load_to_vector_db(self, limit: int = None, batch_size: int = 32) -> int: ...
    def search(self, query: str, top_k: int = 5, score_threshold: float = 0.40) -> list[dict]:
        """Returns list of dicts:
        {
            "score": float,
            "article_id": int | None,
            "chunk_index": int,
            "point_id": str,
            "title": str,
            "year": str | int,
            "filename": str,
            "text": str
        }
        """
        ...
    def close(self) -> None: ...
```

### `pipeline/dataset_builder.py` Schema Invariants
- **Alpaca SFT Output**:
  ```json
  {"instruction": "<instruction text>", "input": "", "output": "<response text>"}
  ```
  `input` must be strictly `""`. No `Context:...` or `Bağlam:...` static string leakage.
- **DPO Triplet Output**:
  ```json
  {"prompt": "<prompt text>", "chosen": "<chosen response>", "rejected": "<rejected response>"}
  ```
  Exact 3 keys, zero extraneous fields (no `input`, no `metadata`).
