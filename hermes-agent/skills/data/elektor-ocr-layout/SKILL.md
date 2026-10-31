---
name: elektor-ocr-layout
description: "Extract PDF layouts, OCR text, and schematic crops."
version: 1.0.0
author: Hakan KILICASLAN (onkanat), Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [ocr, pdf, layout, vision, cropping, elektor]
    category: data
    requires_toolsets: [terminal]
    config:
      - key: elektor.repo_path
        description: "Absolute path to the Elektor repository"
        default: "/home/hakan/Git/elektor"
        prompt: "Elektor repository path"
---

# Elektor OCR, Layout & Schematic Cropping Skill

Specialized skill for extracting structured Markdown text, multi-column reading order, intact register/pinout tables, and unfragmented schematic/block-diagram crops from complex technical PDFs and datasheets (such as RP2040/RP2350 datasheets and Elektor magazine issues).

## When to Use

- The user wants to ingest digital, scanned, or hybrid technical PDFs and datasheets into clean Markdown.
- You need to inspect, validate, or regenerate cropped circuit schematics, block diagrams, and `exports/<project_id>/multimodal_catalog.md`.
- Extracted text exhibits multi-column reading-order issues, header/footer pollution, or fragmented vector drawings that require layout-aware extraction (`pipeline/extractor.py`) and negative table-masked cropping (`pipeline/layout_analyzer.py`).
- You are sending high-resolution schematic crops or visual catalogs through a Hermes messaging gateway (Telegram/Discord) and must preserve lossless quality via `[[as_document]]`.

## Prerequisites

- Repository virtualenv (`.venv/bin/python`) or `python3` with PyMuPDF (`fitz`), Pillow, and `pytesseract` installed.
- System `tesseract` binary (`--dpi 300 -l eng --psm 6`) and Ollama Vision model (`model_vision: "deepseek-ocr:3b-bf16"`, plus `model_analyzer: "ornith-1.5:9b"`) for two-stage multimodal schematic synthesis.
- `terminal` toolset enabled in Hermes Agent.

## How to Run

Inspect existing visual crops, PNG pixel dimensions (`width`, `height`), and the active project's multimodal catalog using the bundled CLI helper:

```python
terminal(
    command="python3 ${HERMES_SKILL_DIR}/scripts/elektor_hermes_cli.py inspect-crops --limit 10 --as-document",
    timeout=30
)
```

For deep details on the layout engine, negative table masking, and VLM OCR tuning, load:
- `skill_view("elektor-ocr-layout", "references/layout-and-cropping.md")`
- `skill_view("elektor-ocr-layout", "references/vlm-ocr-tuning.md")`

## Quick Reference

| Task | Command (`elektor_hermes_cli.py`) | Output Location |
| :--- | :--- | :--- |
| Inspect Visual Crops & Dimensions | `elektor_hermes_cli.py inspect-crops --limit 15` | `downloads/extracted_images/*.png` & `exports/<project_id>/images/*.webp` |
| Run Layout & Image Extraction | `elektor_hermes_cli.py run-stage extract --limit 5` | SQLite `articles` + `downloads/extracted_images/` |
| Build Multimodal Catalog & JSONL | `elektor_hermes_cli.py run-stage export_visual --shards 1` | `exports/<project_id>/multimodal_catalog.md` & `multimodal_visual_dataset.jsonl` |
| Deliver High-Res Schematic in Chat | Append `[[as_document]]` to final response | Uncompressed document attachment |

## Procedure

1. **Check Input PDFs and Current Crop Inventory**
   Run `elektor_hermes_cli.py inspect-crops --limit 10` via `terminal` to inspect the current crop count in `downloads/extracted_images/`, optimized WebP count in `exports/<project_id>/images/`, and verify whether `exports/<project_id>/multimodal_catalog.md` exists (`catalog_exists: true`).
   - *Completion criterion*: JSON report returns `total_crops`, `catalog_exists`, and sample image `width`, `height`, and `size_bytes`.

2. **Execute Layout-Aware PDF Extraction**
   Run `elektor_hermes_cli.py run-stage extract --limit <N>` via `terminal`.
   During this stage, `pipeline/extractor.py` and `pipeline/layout_analyzer.py` perform:
   - Margin filtering to strip repeating running headers ($y \le 50\text{ pt}$) and footers ($y \ge \text{height} - 50\text{ pt}$).
   - Column gutter partitioning so two-column articles never interleave across columns.
   - Native PyMuPDF `page.find_tables()` Markdown table reconstruction and negative table masking (`table_masks`) so table grid strokes are never falsely cropped as schematics.
   - Drawing path clustering (`internal_drawings >= 20` to reject shaded code boxes), arrowhead/pin-label boundary expansion, and IoU deduplication.
   - *Completion criterion*: `returncode == 0` and new articles/images are recorded in SQLite without `BrokenPipeError`.

3. **Generate Multimodal Catalog & Visual Instruction Dataset**
   Run `elektor_hermes_cli.py run-stage export_visual` via `terminal`.
   - *Completion criterion*: `exports/<project_id>/multimodal_catalog.md` and `exports/<project_id>/multimodal_visual_dataset.jsonl` are updated with clean Markdown tables, zero control tokens (`<|grounding|>`, `<think>`), and valid WebP image links.

4. **Deliver Visual Artifacts Losslessly**
   When sharing cropped circuit schematics or pinout diagrams with the user over a Hermes gateway, include `[[as_document]]` in your response so fine pin labels and resistor values are not blurred by image compression.
   - *Completion criterion*: Response includes the exact file path and `[[as_document]]` directive when sending diagrams.

## Pitfalls

- **Register table border false positives**: Datasheet register bitfield tables contain dense vector lines. Never bypass `table_masks` in `DocumentLayoutAnalyzer.analyze_page(page, table_masks=...)`, or table corners will be cropped as separate PNG images (`p119_draw_119_4.png`).
- **Shaded code box false positives**: Keep the `internal_drawings >= 20` filter in `pipeline/layout_analyzer.py` active so shaded background rectangles behind code listings are not mistaken for block diagrams.
- **Gateway photo compression**: Sending schematic PNGs/WebPs without `[[as_document]]` on Telegram/Discord downscales high-aspect-ratio diagrams and makes net labels unreadable.

## Verification

Verify the visual crop inspector and layout pipeline readiness:

```python
terminal(
    command="python3 ${HERMES_SKILL_DIR}/scripts/elektor_hermes_cli.py inspect-crops --limit 5",
    timeout=15
)
```
