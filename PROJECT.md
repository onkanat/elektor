# Project: Elektor Layout, Cropping & OCR/VLM Hardening

## Architecture
The Elektor PDF extraction, multimodal dataset synthesis, and visual document processing pipeline is upgraded to provide reading-order fidelity, clean Markdown tables, unfragmented figure cropping, high-fidelity OCR/VLM extraction, and closed-pipe resilience.

### Upgraded Pipeline Architecture & Data Flow
```
[Complex Technical PDF / Datasheet]
       │
       ▼
[LayoutAwarePdfExtractor] (pipeline/extractor.py)
   ├── Margin Filtering: Strip running headers (y <= 50) & footers (y >= height - 50)
   ├── PyMuPDF Table Detection: `page.find_tables()` -> clean GitHub-flavored Markdown
   ├── Column Gutter Partitioning: Deterministic left-to-right reading order
   ├── Monospace Span Grouping: Monospace fonts (`flags & 8`) -> fenced code blocks
   └── Multi-page range OCR rendering
       │
       ├───► [Table Bounding Boxes (Negative Masks)]
       │            │
       │            ▼
       ├───► [VisualDiagramExtractor] (pipeline/layout_analyzer.py)
       │        ├── Table Mask Filtering: Reject table cells / grid strokes
       │        ├── Drawing Path Clustering: Internal drawing count >= 20 (reject shaded code boxes)
       │        ├── Boundary Expansion: Include outer arrowheads, pin names, and text labels
       │        ├── Aspect Ratio & Dimension Filters: Eliminate border strips / micro-crops
       │        └── Non-Overlapping Deduplication: Merge nested/overlapping figure boxes
       │            │
       │            ▼ [Clean, Complete PNG Crops]
       │
       ▼
[VisionOcrEngine & VisualDatasetBuilder] (pipeline/vision_ocr.py & visual_dataset_builder.py)
   ├── Table-Aware Anti-Loop Filter: Preserve repeated Markdown headers & valid syntax
   ├── Control-Token & Thought Stripper: Clean `<|grounding|>`, unclosed `<think>`, DeepSeek/Llama tags
   ├── Tesseract Fallback Optimization: Grayscale/binarization, --dpi 300, -l eng, --psm 6
   ├── Resilient Ollama Client: Automatic failover (LAN 192.168.1.26 -> localhost 127.0.0.1)
   └── BrokenPipeError Shield: Guarded stdout/stderr printing & reliable DB teardown
       │
       ▼
[Verified Outputs & Multimodal Catalog]
   ├── `multimodal_catalog.md` (clean Markdown tables, valid figure links)
   └── `multimodal_visual_dataset.jsonl` (schema-compliant SFT records)
```

---

## Feature Inventory
Every feature from the Survey phase appears here with its assigned milestone:
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Layout-Aware Reading Order & Gutter Detection | Partition multi-column pages via horizontal projection and column gutter detection in `pipeline/extractor.py` to prevent text interleaving | M1 | Survey R1 |
| 2 | Running Header & Footer Margin Filtering | Detect and strip repeating running headers and footers using spatial thresholds ($y \le 50$ pt, $y \ge \text{height} - 50$ pt) and title pattern matching | M1 | Survey R1 |
| 3 | Native PyMuPDF Table Extraction & Markdown Conversion | Replace naive text extraction for tables with PyMuPDF `find_tables()` and `to_markdown()`, preserving register bitfield alignment and binding left captions | M1 | Survey R1 |
| 4 | Monospace Span Grouping & Fenced Code Blocks | Detect monospaced font spans (`flags & 8`, `RobotoMono`) and preserve them as indented, fenced code blocks (````c ... ````) | M1 | Survey R1 |
| 5 | Multi-Page Range OCR Image Rendering Fix | Fix `extract_pages_range` in `pipeline/extractor.py` to render all pages `start_page` through `end_page` instead of dropping pages after `start_page` | M1 | Survey R3 |
| 6 | Table Negative Masking in Layout Analyzer | Pass table bounding boxes from `find_tables()` as exclusion masks to `pipeline/layout_analyzer.py` to eliminate false-positive table-cell crops (`p119_draw_119_4.png`) | M2 | Survey R2 |
| 7 | Drawing Path Clustering & Code Box Rejection | Enforce internal drawing count check (`internal_drawings >= 20` for diagrams vs 0 for shaded code backgrounds) and prevent gap-induced column slicing | M2 | Survey R2 |
| 8 | Boundary Expansion for Arrowheads & Labels | Expand figure bounding boxes adaptively to encompass outer connector lines, arrowheads, and adjacent pin/signal text labels without clipping | M2 | Survey R2 |
| 9 | Aspect Ratio, Dimension & Density Filters | Reject thin border strips and micro-crops while preserving legitimate wide architecture blocks and timing diagrams (remove hardcoded `h < 80`) | M2 | Survey R2 |
| 10 | Non-Overlapping Figure Deduplication | Implement non-maximum suppression / IoU-based deduplication to prevent duplicate, nested, or fragmented sub-diagram crops | M2 | Survey R2 |
| 11 | BrokenPipeError Immunity & Safe Teardown | Guard all stdout/stderr printing and logging in `pipeline/extractor.py:613,812` and `project_logger.py`, guaranteeing database connection closure during pipe breaks | M3 | Survey R4 |
| 12 | Table-Syntax Preserving Anti-Loop Filter | Modify repetition filter in `pipeline/vision_ocr.py:98-117` to recognize Markdown table row syntax (`|---|---|`) and avoid injecting metatext into valid tables | M3 | Survey R3 |
| 13 | Control-Token & Thought Preamble Sanitization | Apply comprehensive sanitization (`<|grounding|>`, unclosed `<think>`, `<|im_start|>`, DeepSeek/Llama tags) across all document conversion endpoints | M3 | Survey R3 |
| 14 | Tesseract OCR Preprocessing & PSM Tuning | Add grayscale/binarization, `--dpi 300`, `-l eng`, and appropriate `--psm` modes; fix aggressive suffix regex word merging | M3 | Survey R3 |
| 15 | Dynamic Endpoint Failover | Automatically failover from LAN endpoint `http://192.168.1.26:11434` to local `http://127.0.0.1:11434` when LAN host is offline or timed out | M3 | Survey R3 |
| 16 | Schema-Compliant Multimodal Catalog Generation | Ensure `multimodal_catalog.md` and `multimodal_visual_dataset.jsonl` satisfy all schema invariants with zero control tokens or loop warnings | M3 | Survey R3 |
| 17 | 4-Tier E2E Test Suite & Adversarial Hardening | Comprehensive opaque-box test suite (Tiers 1-4) covering all 16 features, plus Tier 5 adversarial stress testing and Victory Audit | M-FINAL | Acceptance Criteria |
| 18 | Nous Research Hermes Agent Skills & Stdio MCP Server | Expose the entire Elektor dataset, OCR/layout, RAG, and curation pipeline to Hermes agents via `hermes-agent/skills/data/*`, `elektor_hermes_cli.py`, and `elektor_mcp_server.py` | M4 | Hermes Agent Integration |

---

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | Requirement-Driven E2E Test Suite | Build test infra and test cases for Tiers 1-4 across all 16 features; produce `TEST_READY.md` | None (parallel track) | DONE |
| M1 | Document Layout, Reading-Order & Table Extraction | Features 1, 2, 3, 4, 5 (`pipeline/extractor.py`, `tests/test_document_layout.py`) | None | DONE |
| M2 | Complete, Unfragmented Visual & Diagram Cropping | Features 6, 7, 8, 9, 10 (`pipeline/layout_analyzer.py`, `tests/test_visual_cropper.py`) | M1 | DONE |
| M3 | OCR / VLM Fidelity, Catalog Quality & Resilience | Features 11, 12, 13, 14, 15, 16 (`pipeline/vision_ocr.py`, `visual_dataset_builder.py`, `llm_client.py`) | M1, M2 | DONE |
| M-FINAL | 100% E2E Test Pass & Tier 5 Adversarial Coverage Hardening | Feature 17 (Pass all E2E Tiers 1-4, Phase 2 Tier 5 Adversarial Hardening, Victory Audit) | E2E, M1, M2, M3 | DONE |
| M4 | Nous Research Hermes Agent Skills & MCP Server | Feature 18 (`hermes-agent/`, `tests/test_hermes_agent_skills.py`, 405 passing tests) | M-FINAL | DONE |

---

## Interface Contracts

### `pipeline/extractor.py` ↔ `pipeline/layout_analyzer.py`
```python
@dataclass
class PageLayoutResult:
    text: str                                  # Clean Markdown text with reading order preserved
    tables: list[dict]                         # Extracted tables: [{"bbox": (x0, y0, x1, y1), "markdown": str, "caption": str}]
    table_masks: list[tuple[float, float, float, float]]  # Negative exclusion bboxes for visual cropper
    code_blocks: list[dict]                    # Fenced code blocks detected via monospace font spans

def extract_page_layout(page: fitz.Page) -> PageLayoutResult:
    """Extracts text, tables, and exclusion masks from a PDF page using PyMuPDF."""
    ...
```

### `pipeline/layout_analyzer.py` ↔ `pipeline/visual_dataset_builder.py`
```python
@dataclass
class FigureCrop:
    crop_id: str                              # Unique identifier (e.g. 'p15_fig_1')
    page_number: int                          # 1-indexed page number
    bbox: tuple[float, float, float, float]   # (x0, y0, x1, y1) in PDF points
    image_path: str                           # Saved PNG crop path
    caption: str                              # Associated caption or heading
    crop_type: str                            # 'diagram', 'schematic', 'chart', 'drawing'

class DocumentLayoutAnalyzer:
    def analyze_page(
        self,
        page: fitz.Page,
        table_masks: list[tuple[float, float, float, float]] = None
    ) -> list[FigureCrop]:
        """Extracts complete, unfragmented figures while excluding table masks and shaded text blocks."""
        ...
```

### `pipeline/llm_client.py` Resilient Endpoint Interface
```python
class ResilientOllamaClient:
    def __init__(self, primary_url: str = "http://192.168.1.26:11434", fallback_url: str = "http://127.0.0.1:11434", timeout: float = 30.0): ...
    def generate(self, model: str, prompt: str, images: list[str] = None) -> str: ...
```

### `hermes-agent/scripts/` ↔ `pipeline/mcp_tools.py`
```python
# Stdio JSON-RPC 2.0 MCP tools exposed by elektor_mcp_server.py:
search_vector_rag(query: str, top_k: int = 4) -> dict
query_sqlite_knowledge(query: str, limit: int = 3) -> dict
inject_sft_dpo_context(query: str, limit: int = 3) -> dict
evaluate_knowledge_gap(base_response: str, enriched_response: str, context_text: str = "") -> dict
```

---

## Code Layout
- `pipeline/extractor.py`: PDF layout extraction, margin filtering, PyMuPDF table extraction, code block preservation, safe close teardown.
- `pipeline/layout_analyzer.py`: Visual diagram extraction, table exclusion masking, drawing path clustering, boundary expansion, deduplication.
- `pipeline/vision_ocr.py`: VLM response sanitization, table-aware repetition filtering, Tesseract preprocessing and invocation.
- `pipeline/visual_dataset_builder.py`: Multimodal catalog & dataset generation, VRAM lifecycle management.
- `pipeline/llm_client.py`: Resilient HTTP client with automatic endpoint failover (LAN -> localhost).
- `pipeline/mcp_tools.py`: Native Qdrant RAG, SQLite, SFT/DPO context, and knowledge gap evaluation functions.
- `hermes-agent/`: Nous Research Hermes Agent skill definitions (`skills/data/*`), CLI tool bridge (`scripts/elektor_hermes_cli.py`), Stdio MCP server (`scripts/elektor_mcp_server.py`), and installer (`scripts/install_skills.sh`).
- `tests/test_document_layout.py`: Unit and layout tests for M1.
- `tests/test_visual_cropper.py`: Unit and geometry tests for M2.
- `tests/test_ocr_resilience.py`: Unit and resilience tests for M3.
- `tests/test_hermes_agent_skills.py`: Automated validation of Hermes Agent skills, CLI subcommands, and MCP server.
- `tests/e2e/`: Opaque-box 5-tier E2E test suite.


## Token katmanı (FAZ-24, 10.11.2026)
Atropos arşivli; yalnız token katmanı vendored edildi (`pipeline/token_layer.py`, MIT, NousResearch/atropos @ 296a0bc5). Sözleşme: her satır tek örnek, `len(tokens)==len(loss_mask)`, mask {0,1} (0=prompt, 1=completion), DPO iki satır, kesme sondan. Komut: `python run.py tokens --project <id> --tokenizer <hf-id>`. Tam şartname: `~/Aikonsol/urunler/elektor/SARTNAME-token-katmani-ve-strata-20261110.md` (sha256 e68b31e5).
