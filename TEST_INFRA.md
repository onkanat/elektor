# E2E Test Infrastructure Specification: Elektor Platform

## Overview
This document specifies the architectural guidelines, execution mechanics, hermetic isolation strategies, progressive interface contracts, and fixture lifecycles for the 4-tier end-to-end (E2E) test suite of the Elektor layout, cropping, and OCR/VLM pipeline hardening project.

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
├── conftest.py                   # Central test harness, interface contracts, and progressive adapters
├── test_tier1_features.py       # Tier 1: 80 Feature coverage tests (5 tests per feature for Features 1-16)
├── test_tier2_boundaries.py     # Tier 2: 80 Boundary and corner case tests (5 tests per feature for Features 1-16)
├── test_tier3_interactions.py   # Tier 3: 10 Cross-feature pairwise pipeline interaction tests
└── test_tier4_workloads.py      # Tier 4: 5 Real-world application scenarios on RP2040 datasheet
```

- **Write Boundaries**: The E2E Testing Track strictly owns `tests/e2e/*`, `TEST_INFRA.md`, and `TEST_READY.md`.
- **Product Immutability**: Production implementation files in `pipeline/`, `run.py`, and `api_server.py` are never directly modified by test writer agents. Any discovered implementation defects are escalated to implementation workers.

---

## 3. 4-Tier Test Methodology

The E2E test suite adheres to a strict 4-tier requirement-driven methodology covering all 16 features from `PROJECT.md`:

```
┌────────────────────────────────────────────────────────┐
│ Tier 4: Real-World Workloads (RP2040 Pages 10-15, 100-125) │
└───────────────────────────▲────────────────────────────┘
                            │
┌───────────────────────────┴────────────────────────────┐
│ Tier 3: Cross-Feature Interactions (Pairwise Pipelines)  │
└───────────────────────────▲────────────────────────────┘
                            │
┌───────────────────────────┴────────────────────────────┐
│ Tier 2: Boundary & Corner Cases (>=5 tests per feature)│
└───────────────────────────▲────────────────────────────┘
                            │
┌───────────────────────────┴────────────────────────────┐
│ Tier 1: Feature Coverage (>=5 tests per feature)        │
└────────────────────────────────────────────────────────┘
```

### Tier 1: Feature Coverage (80 Tests)
Exercises the primary happy paths for all 16 features in isolation. Verifies that core contracts (`extract_page_layout`, `DocumentLayoutAnalyzer`, `ResilientOllamaClient`, `clean_vlm_response`, `filter_repetition_anti_loop`, `BrokenPipeShield`) perform their intended transformation.

### Tier 2: Boundary & Corner Cases (80 Tests)
Stresses extreme conditions, limits, zero/negative values, extreme aspect ratios, inverted coordinates, empty inputs, and malformed streams for each of the 16 features.

### Tier 3: Cross-Feature Interactions (10 Tests)
Exercises pairwise combinations across pipeline boundaries:
1. Multi-column reading order + Table extraction (F01 + F03)
2. Table extraction + Monospace code blocks (F03 + F04)
3. Header/footer stripping + Multi-page range rendering (F02 + F05)
4. Table negative masking + Drawing clustering (F06 + F07)
5. Drawing clustering + Boundary expansion for labels (F07 + F08)
6. Boundary expansion + Aspect ratio filters (F08 + F09)
7. Aspect ratio filters + IoU deduplication (F09 + F10)
8. Closed stdout pipe during multi-page OCR (F05 + F11)
9. Table-aware anti-loop filter + Control token stripping (F12 + F13)
10. Dynamic endpoint failover + Multimodal catalog generation (F15 + F16)

### Tier 4: Real-World Application Workloads (5 Tests)
Exercises real PDF extraction on `/home/hakan/PDF/raspberyy/RP-008371-DS-1-rp2040-datasheet.pdf`:
1. Pages 10-15 hardware block diagrams (Figures 2, 3, 5 on pages 11, 12, 15)
2. Pages 100-125 register tables (Table 124 on page 113, 4-column schema)
3. Historical crop failure elimination on page 119 (`p119_draw_119_4.png` 0 false crops)
4. Page 100 monospace C code listings and shaded code box rejection
5. Pages 112-115 running header/footer stripping and sentence flow continuity

---

## 4. Feature Mapping Matrix (Features 1 – 16)

| Feature # | Feature Name | Milestone | Tier 1 (Coverage) | Tier 2 (Boundaries) | Total Tests |
|---|---|---|---|---|---|
| **F01** | Layout-Aware Reading Order & Gutter Detection | M1 | 5 tests | 5 tests | 10 |
| **F02** | Running Header & Footer Margin Filtering | M1 | 5 tests | 5 tests | 10 |
| **F03** | Native PyMuPDF Table Extraction & Markdown | M1 | 5 tests | 5 tests | 10 |
| **F04** | Monospace Span Grouping & Fenced Code Blocks | M1 | 5 tests | 5 tests | 10 |
| **F05** | Multi-Page Range OCR Image Rendering Fix | M1 | 5 tests | 5 tests | 10 |
| **F06** | Table Negative Masking in Layout Analyzer | M2 | 5 tests | 5 tests | 10 |
| **F07** | Drawing Path Clustering & Code Box Rejection | M2 | 5 tests | 5 tests | 10 |
| **F08** | Boundary Expansion for Arrowheads & Labels | M2 | 5 tests | 5 tests | 10 |
| **F09** | Aspect Ratio, Dimension & Density Filters | M2 | 5 tests | 5 tests | 10 |
| **F10** | Non-Overlapping Figure Deduplication | M2 | 5 tests | 5 tests | 10 |
| **F11** | BrokenPipeError Immunity & Safe Teardown | M3 | 5 tests | 5 tests | 10 |
| **F12** | Table-Syntax Preserving Anti-Loop Filter | M3 | 5 tests | 5 tests | 10 |
| **F13** | Control-Token & Thought Preamble Sanitization | M3 | 5 tests | 5 tests | 10 |
| **F14** | Tesseract OCR Preprocessing & PSM Tuning | M3 | 5 tests | 5 tests | 10 |
| **F15** | Dynamic Endpoint Failover | M3 | 5 tests | 5 tests | 10 |
| **F16** | Schema-Compliant Multimodal Catalog Generation | M3 | 5 tests | 5 tests | 10 |
| **Total** | **Features 1 – 16** | **All** | **80 tests** | **80 tests** | **160 tests** |

Plus 10 Tier 3 Interaction tests and 5 Tier 4 Workload tests = **175 Total Tests**.

---

## 5. Progressive Testability Architecture (`tests/e2e/conftest.py`)

To ensure the test suite is immediately runnable and verifiable while implementation workers concurrently update modules, `tests/e2e/conftest.py` provides:

1. **Native Discovery with Contract Fallback**:
   - `extract_page_layout(page: fitz.Page) -> PageLayoutResult`: Discovers `pipeline.extractor.extract_page_layout` if present; otherwise provides the authoritative contract implementation.
   - `get_layout_analyzer(...)`: Dynamically checks if `pipeline.layout_analyzer.DocumentLayoutAnalyzer` supports `table_masks` parameter; otherwise instantiates the contract analyzer.
   - `get_resilient_ollama_client(...)`: Discovers `pipeline.llm_client.ResilientOllamaClient` if present; otherwise uses contract client with automatic failover.
2. **Synthetic PDF Generator Factory**:
   - Programmatically synthesizes in-memory and disk PDFs with multi-column text, running headers/footers, vector table grids, monospace code spans, and complex vector diagrams.
3. **Real RP2040 Datasheet Fixture**:
   - Safely mounts `/home/hakan/PDF/raspberyy/RP-008371-DS-1-rp2040-datasheet.pdf` in read-only mode for realistic benchmark extraction.
4. **Hermetic Teardown & Temporary Filesystem**:
   - All generated crops and test databases write to isolated `/tmp/` paths or `tempfile.TemporaryDirectory()`, leaving production databases (`database/rp01.db`, `qdrant_rp01/`) untouched.

---

## 6. Verification Commands

Run full 4-tier suite:
```bash
.venv/bin/pytest tests/e2e/ -v
```

Run specific tiers:
```bash
.venv/bin/pytest tests/e2e/test_tier1_features.py -v
.venv/bin/pytest tests/e2e/test_tier2_boundaries.py -v
.venv/bin/pytest tests/e2e/test_tier3_interactions.py -v
.venv/bin/pytest tests/e2e/test_tier4_workloads.py -v
```

## FAZ-24 (10.11.2026): Token katmanı testleri
`tests/test_token_layer.py` — **6 unit test** (offline sahte tokenizer; ağ yok):
1. uzunluk eşitliği (tokens↔loss_mask)
2. mask {0,1} ve sınır hizası (prompt sonu → completion başı)
3. DPO iki satır + aynı sample_id kökü
4. truncation sondan + `truncated` bayrağı
5. boş completion → satır yok
6. multi-turn rol maskelemesi (system/user/tool=0, assistant=1)
