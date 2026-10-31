# PDF Layout Reconstruction & Intelligent Schematic Cropping Reference

## 1. Reading-Order & Structural Markdown Pipeline (`pipeline/extractor.py`)

Complex electronics datasheets (e.g., Raspberry Pi RP2040 / RP2350) and Elektor magazine articles combine two-column prose, full-width schematics, register bitfield tables, and code listings. `pipeline/extractor.py` (`extract_page_layout`) enforces five stages of structural cleanup:

1. **Running Header & Footer Margin Filtering**:
   - Strips repeating top/bottom margin text bands ($y \le 50\text{ pt}$, $y \ge \text{height} - 50\text{ pt}$), standalone page numbers, and running title headers before block assembly so sentences are never split mid-paragraph.
2. **Column Gutter Partitioning**:
   - Detects vertical column gutters via horizontal projection, separating full-width spanning headers/tables from multi-column body blocks and sorting left-column blocks top-to-bottom before right-column blocks.
3. **Native PyMuPDF Table Extraction (`page.find_tables()`)**:
   - Converts datasheet pinouts, electrical characteristics, and register bitfield tables directly into GitHub-Flavored Markdown tables (`| Bits | Name | Description | ... |`) and binds adjacent left/top captions.
4. **Monospace Span Grouping**:
   - Detects monospaced font spans (`flags & 8`, `RobotoMono`, `Courier`) and preserves them as fenced code blocks (````c ... ````).
5. **Multi-Page Range OCR Fallback (`pipeline/vision_ocr.py`)**:
   - When page character density falls below `ocr_threshold_chars` (`100`), renders all pages in `start_page..end_page` with grayscale/binarization preprocessing and invokes `tesseract` (`--dpi 300 -l eng --psm 6`) or the configured Ollama Vision model (`model_vision: "deepseek-ocr:3b-bf16"`).

---

## 2. Complete Figure & Schematic Cropping (`pipeline/layout_analyzer.py`)

Vector diagrams in technical PDFs are composed of hundreds of individual Bezier paths, rectangles, and text labels (`UART0`, `GPIO0`, `3V3`, `GND`). `DocumentLayoutAnalyzer.analyze_page(page, table_masks=...)` solves fragmentation via:

1. **Table Negative Masking (`table_masks`)**:
   - Every table bounding box detected by `page.find_tables()` is passed as a negative exclusion mask to `layout_analyzer.py`. Vector grid strokes inside table masks are rejected, eliminating partial register-table corner slices (`p119_draw_119_4.png`).
2. **Drawing Path Clustering (`internal_drawings >= 20`)**:
   - Clusters vector drawing paths across small internal gaps and verifies `internal_drawings >= 20` for pure vector regions, rejecting single-rectangle shaded code boxes and decorative divider lines.
3. **Boundary Expansion for Arrowheads & Pin Labels**:
   - Adaptively expands figure bounding boxes to encompass outer connector lines, arrowheads, pin numbers, and nearby `Figure X:` captions, clamping safely to page bounds.
4. **Aspect-Ratio, Dimension & IoU Deduplication**:
   - Rejects thin border strips and micro-crops while retaining wide timing diagrams, and merges nested/overlapping boxes via Intersection-over-Union (IoU) deduplication.
