# E2E Test Infrastructure Specification: Elektor Platform

## Overview
This document defines the architectural guidelines, execution mechanics, hermetic isolation strategies, and fixture lifecycles for the end-to-end (E2E) testing track of the Elektor platform.

---

## 1. Test Harness & Runner Configuration

- **Framework**: Pytest (`pytest >= 8.0`, with `pytest-asyncio` and `anyio`)
- **Virtual Environment Interpreter**: `/home/hakan/Git/elektor/.venv/bin/python`
- **Primary Test Runner Command**:
  ```bash
  .venv/bin/pytest tests/e2e/ -v
  ```
- **Execution Target Directory**: `tests/e2e/`
- **Root Path Injection**: Handled autonomously via `tests/e2e/conftest.py`, ensuring repo root `/home/hakan/Git/elektor` is prefixed onto `sys.path`. No manual `PYTHONPATH` exports required.

---

## 2. Directory Layout & Module Ownership

```
tests/e2e/
├── conftest.py                   # Central test harness, hermetic fixtures, and milestone fallback adapters
├── test_tier1_features.py       # Tier 1: 80 Feature coverage tests (>=5 tests per feature for Features 1-16)
├── test_tier2_boundaries.py     # Tier 2: 80 Boundary and corner case tests (>=5 tests per feature for Features 1-16)
├── test_tier3_combinations.py   # Tier 3: 10 Cross-feature pairwise pipeline combination tests
└── test_tier4_scenarios.py      # Tier 4: 5 Real-world end-to-end application workflow scenarios
```

- **Write Boundaries**: The E2E Testing Track strictly owns `tests/e2e/*`, `TEST_INFRA.md`, and `TEST_READY.md`.
- **Product Immutability**: Production implementation files in `pipeline/`, `run.py`, and `api_server.py` are never directly modified by test writer agents. Any discovered bugs are documented and escalated.

---

## 3. Hermetic Mocking & Offline Test Architecture

To guarantee zero network flakiness, sub-second execution, and full offline determinism:

### A. Vector Storage (Qdrant)
- Local disk instances run against dedicated isolated `tempfile.TemporaryDirectory()` paths or `:memory:` fallbacks.
- Collections are dynamically instantiated per test and cleaned up during fixture teardown.
- Network calls to remote Qdrant endpoints are verified through configuration structure rather than live sockets.

### B. Embedding Client Mocking
- `pipeline.vector_store.get_embedding_client` is mocked with a deterministic 768-dimensional unit vector fixture (`mock_embedding_client`).
- Search vectors and point payloads match expected shapes without invoking Ollama or Hugging Face.

### C. Large Language Models (LLM) & LLM-as-a-Judge
- Chat completions and Judge arbitration calls (`evaluate_pair`, `judge_all`) are mocked using `unittest.mock.patch` with strictly validated `JudgeEvaluation` Pydantic models.
- Offline heuristic fallback logic is tested to verify graceful degradation during upstream API outages.

### D. FastAPI Backend Test Transport
- API endpoints are exercised using `httpx.AsyncClient` with `httpx.ASGITransport(app=app)`.
- No active network listening ports or live daemon processes are spawned during test execution.

---

## 4. Shared Fixture Registry (`tests/e2e/conftest.py`)

| Fixture Name | Scope | Description |
|---|---|---|
| `temp_project_dir` | Function | Creates an isolated temporary directory containing a initialized SQLite database (`articles`, `enrichments`, `synthetic_code_pairs`), Qdrant directory, export directory, and a preconfigured `config.json`. Cleans up automatically on teardown. |
| `mock_embedding_vector` | Function | Returns a deterministic 768-dimensional float vector. |
| `mock_embedding_client` | Function | Mock object simulating `openai.embeddings.create` with deterministic responses. |
| `get_db_connection` | Context | Managed SQLite connection with immediate `busy_timeout=60000;`, `WAL` mode, and automatic rollback on exception. |
| `get_db_cursor` | Context | Managed SQLite cursor that auto-commits on clean exit. |

---

## 5. Verification Commands

Run full suite:
```bash
.venv/bin/pytest tests/e2e/
```

Run specific tiers:
```bash
.venv/bin/pytest tests/e2e/test_tier1_features.py
.venv/bin/pytest tests/e2e/test_tier2_boundaries.py
.venv/bin/pytest tests/e2e/test_tier3_combinations.py
.venv/bin/pytest tests/e2e/test_tier4_scenarios.py
```
