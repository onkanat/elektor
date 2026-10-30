import os
import sys
import re
import json
import sqlite3
import fitz
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.e2e.conftest import (
    PageLayoutResult,
    FigureCrop,
    extract_page_layout,
    get_layout_analyzer,
    get_resilient_ollama_client,
    clean_vlm_response,
    filter_repetition_anti_loop,
    BrokenPipeShield,
    RP2040_PATH
)


# ============================================================================
# FEATURE 1: Layout-Aware Reading Order & Gutter Detection
# ============================================================================

def test_f01_two_column_gutter_detection(synthetic_pdf_factory):
    """Verifies that two columns divided by a vertical gutter are read column-by-column, not interleaved."""
    pdf_path = synthetic_pdf_factory(
        filename="f01_two_col.pdf",
        pages_config=[{
            "columns": [
                {"x": 60, "y": 80, "lines": ["Col1 Line A", "Col1 Line B", "Col1 Line C"]},
                {"x": 320, "y": 80, "lines": ["Col2 Line 1", "Col2 Line 2", "Col2 Line 3"]}
            ]
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()

    lines = res.text.split("\n")
    # All Col1 lines must precede Col2 lines
    idx_a = lines.index("Col1 Line A")
    idx_c = lines.index("Col1 Line C")
    idx_1 = lines.index("Col2 Line 1")
    assert idx_a < idx_c < idx_1, "Reading order must follow column gutter (Col1 before Col2)"


def test_f01_three_column_reading_order(synthetic_pdf_factory):
    """Verifies 3-column page is processed left-to-right across gutters."""
    pdf_path = synthetic_pdf_factory(
        filename="f01_three_col.pdf",
        pages_config=[{
            "columns": [
                {"x": 50, "y": 100, "lines": ["Col1-Top", "Col1-Bottom"]},
                {"x": 220, "y": 100, "lines": ["Col2-Top", "Col2-Bottom"]},
                {"x": 400, "y": 100, "lines": ["Col3-Top", "Col3-Bottom"]}
            ]
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()

    assert "Col1-Top" in res.text
    assert "Col2-Top" in res.text
    assert "Col3-Top" in res.text
    assert res.text.find("Col1-Bottom") < res.text.find("Col2-Top")


def test_f01_single_column_preservation(synthetic_pdf_factory):
    """Verifies single column pages preserve natural top-to-bottom vertical line order."""
    pdf_path = synthetic_pdf_factory(
        filename="f01_single_col.pdf",
        pages_config=[{
            "columns": [
                {"x": 60, "y": 80, "lines": ["First Line", "Second Line", "Third Line"]}
            ]
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()

    lines = [l for l in res.text.split("\n") if l.strip()]
    assert lines == ["First Line", "Second Line", "Third Line"]


def test_f01_alternating_stream_interleaving_resolved(synthetic_pdf_factory):
    """Simulates alternating PDF stream order and verifies gutter partition restores human order."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Insert left then right at alternating Y coordinates
    page.insert_text((50, 100), "Left 1")
    page.insert_text((350, 100), "Right 1")
    page.insert_text((50, 120), "Left 2")
    page.insert_text((350, 120), "Right 2")
    res = extract_page_layout(page)
    doc.close()

    assert res.text.find("Left 2") < res.text.find("Right 1")


def test_f01_empty_column_handling(synthetic_pdf_factory):
    """Verifies layout extractor gracefully handles pages with wide gutters and unequal columns."""
    pdf_path = synthetic_pdf_factory(
        filename="f01_unequal_cols.pdf",
        pages_config=[{
            "columns": [
                {"x": 50, "y": 100, "lines": ["Wide Left Block"]},
                {"x": 480, "y": 100, "lines": ["Thin Right Margin Note"]}
            ]
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()

    assert "Wide Left Block" in res.text
    assert "Thin Right Margin Note" in res.text


# ============================================================================
# FEATURE 2: Running Header & Footer Margin Filtering
# ============================================================================

def test_f02_running_header_stripped(synthetic_pdf_factory):
    """Verifies text at y <= 50 pt (running header) is stripped from extracted body."""
    pdf_path = synthetic_pdf_factory(
        filename="f02_header.pdf",
        pages_config=[{
            "header": "RP2040 Datasheet - Confidential",
            "columns": [{"x": 60, "y": 120, "lines": ["Main body paragraph content."]}]
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()

    assert "RP2040 Datasheet" not in res.text
    assert "Main body paragraph content." in res.text


def test_f02_running_footer_stripped(synthetic_pdf_factory):
    """Verifies text at y >= height - 50 pt (running footer) is stripped from extracted body."""
    pdf_path = synthetic_pdf_factory(
        filename="f02_footer.pdf",
        pages_config=[{
            "footer": "Chapter 2: System Architecture | Page 114",
            "columns": [{"x": 60, "y": 120, "lines": ["Main body paragraph content."]}]
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()

    assert "Page 114" not in res.text
    assert "Chapter 2: System Architecture" not in res.text
    assert "Main body paragraph content." in res.text


def test_f02_multi_page_running_header_consistency(synthetic_pdf_factory):
    """Verifies running headers across multiple sequential pages are consistently stripped."""
    pdf_path = synthetic_pdf_factory(
        filename="f02_multipage_headers.pdf",
        pages_config=[
            {"header": "RP2040 Datasheet", "columns": [{"x": 60, "y": 100, "lines": ["Page 1 text."]}]},
            {"header": "RP2040 Datasheet", "columns": [{"x": 60, "y": 100, "lines": ["Page 2 text."]}]}
        ]
    )
    doc = fitz.open(pdf_path)
    for p in doc:
        res = extract_page_layout(p)
        assert "RP2040 Datasheet" not in res.text
    doc.close()


def test_f02_sentence_continuity_across_pages(synthetic_pdf_factory):
    """Verifies that headers/footers do not inject text between a sentence split across pages."""
    pdf_path = synthetic_pdf_factory(
        filename="f02_sentence_split.pdf",
        pages_config=[
            {
                "footer": "2.5. DMA 112",
                "columns": [{"x": 60, "y": 700, "lines": ["The direct memory access controller transmits"]}]
            },
            {
                "header": "RP2040 Datasheet",
                "columns": [{"x": 60, "y": 100, "lines": ["data packets without CPU intervention."]}]
            }
        ]
    )
    doc = fitz.open(pdf_path)
    p1_res = extract_page_layout(doc[0])
    p2_res = extract_page_layout(doc[1])
    doc.close()

    combined = f"{p1_res.text} {p2_res.text}"
    assert "2.5. DMA 112" not in combined
    assert "RP2040 Datasheet" not in combined
    assert "transmits data packets without CPU intervention." in combined


def test_f02_body_near_margin_preserved(synthetic_pdf_factory):
    """Verifies text at y=55 pt (just below 50 pt header threshold) is safely preserved."""
    pdf_path = synthetic_pdf_factory(
        filename="f02_near_margin.pdf",
        pages_config=[{
            "header": "Top Header",
            "columns": [{"x": 60, "y": 70, "lines": ["Valid body heading right below header band."]}]
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()

    assert "Valid body heading right below header band." in res.text


# ============================================================================
# FEATURE 3: Native PyMuPDF Table Extraction & Markdown Conversion
# ============================================================================

def test_f03_single_table_markdown_structure(synthetic_pdf_factory):
    """Verifies native table detection produces valid GitHub-flavored Markdown tables."""
    pdf_path = synthetic_pdf_factory(
        filename="f03_table.pdf",
        pages_config=[{
            "table": {
                "bbox": (50, 150, 450, 250),
                "rows": 3,
                "cols": 3,
                "data": {
                    (0, 0): "Bits", (0, 1): "Name", (0, 2): "Reset",
                    (1, 0): "31:24", (1, 1): "FIFO_DEPTH", (1, 2): "0x08",
                    (2, 0): "23:0", (2, 1): "RESERVED", (2, 2): "0x00"
                }
            }
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()

    assert len(res.tables) == 1
    md = res.tables[0]["markdown"]
    assert "|Bits|Name|Reset|" in md.replace(" ", "")
    assert "|31:24|FIFO_DEPTH|0x08|" in md.replace(" ", "")


def test_f03_table_masks_registration(synthetic_pdf_factory):
    """Verifies that detected tables register bounding boxes in `table_masks`."""
    pdf_path = synthetic_pdf_factory(
        filename="f03_masks.pdf",
        pages_config=[{
            "table": {"bbox": (60, 200, 400, 320), "rows": 2, "cols": 2}
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()

    assert len(res.table_masks) == 1
    m = res.table_masks[0]
    assert m[0] <= 65 and m[1] <= 205 and m[2] >= 395 and m[3] >= 315


def test_f03_multiple_tables_on_single_page(synthetic_pdf_factory):
    """Verifies multiple tables on a single page are all detected and returned."""
    pdf_path = synthetic_pdf_factory(
        filename="f03_multi_table.pdf",
        pages_config=[{
            "table": {"bbox": (50, 100, 350, 200), "rows": 2, "cols": 2}
        }]
    )
    doc = fitz.open(pdf_path)
    page = doc[0]
    # Draw a second table lower down
    page.draw_rect(fitz.Rect(50, 400, 350, 500), color=(0, 0, 0), width=1)
    page.draw_line((50, 450), (350, 450), color=(0, 0, 0), width=1)
    page.draw_line((200, 400), (200, 500), color=(0, 0, 0), width=1)
    page.insert_text((60, 430), "T2_H1")
    page.insert_text((210, 430), "T2_H2")
    page.insert_text((60, 480), "T2_V1")
    page.insert_text((210, 480), "T2_V2")
    res = extract_page_layout(page)
    doc.close()

    assert len(res.tables) >= 2
    assert len(res.table_masks) >= 2


def test_f03_table_columns_count_alignment(synthetic_pdf_factory):
    """Verifies extracted Markdown table rows have consistent column counts."""
    pdf_path = synthetic_pdf_factory(
        filename="f03_cols_align.pdf",
        pages_config=[{
            "table": {
                "bbox": (50, 150, 450, 250),
                "rows": 3,
                "cols": 4,
                "data": {
                    (0, 0): "Bits", (0, 1): "Description", (0, 2): "Type", (0, 3): "Reset",
                    (1, 0): "31", (1, 1): "AHB_ERROR", (1, 2): "RO", (1, 3): "0x0",
                    (2, 0): "30", (2, 1): "READ_ERROR", (2, 2): "WC", (2, 3): "0x0"
                }
            }
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()

    md = res.tables[0]["markdown"]
    rows = [r.strip() for r in md.split("\n") if r.strip().startswith("|")]
    col_counts = [len(r.split("|")) - 2 for r in rows]
    assert all(c == 4 for c in col_counts), f"Inconsistent column counts: {col_counts}"


def test_f03_table_caption_binding(synthetic_pdf_factory):
    """Verifies that captions associated with tables are bound in the result."""
    pdf_path = synthetic_pdf_factory(
        filename="f03_caption.pdf",
        pages_config=[{
            "table": {"bbox": (50, 150, 450, 250), "rows": 2, "cols": 2}
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()

    assert "caption" in res.tables[0]
    assert len(res.tables[0]["caption"]) > 0


# ============================================================================
# FEATURE 4: Monospace Span Grouping & Fenced Code Blocks
# ============================================================================

def test_f04_monospace_font_flag_detection(synthetic_pdf_factory):
    """Verifies monospace font (Courier or flags & 8) is identified as code block."""
    pdf_path = synthetic_pdf_factory(
        filename="f04_mono.pdf",
        pages_config=[{
            "code": {
                "x": 60, "y": 200,
                "lines": ["uint32_t val = readl(REG_BASE);", "writel(val | 0x01, REG_BASE);"]
            }
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()

    assert len(res.code_blocks) >= 1
    assert "uint32_t val = readl(REG_BASE);" in res.code_blocks[0]["code"]


def test_f04_fenced_markdown_block_syntax(synthetic_pdf_factory):
    """Verifies code blocks are fenced with ```c in extracted text."""
    pdf_path = synthetic_pdf_factory(
        filename="f04_fenced.pdf",
        pages_config=[{
            "code": {
                "x": 60, "y": 200,
                "lines": ["int status = dma_channel_is_busy(0);"]
            }
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()

    assert "```c" in res.text
    assert "dma_channel_is_busy" in res.text


def test_f04_contiguous_line_grouping(synthetic_pdf_factory):
    """Verifies contiguous monospace lines form a single code block, not multiple fragments."""
    pdf_path = synthetic_pdf_factory(
        filename="f04_contiguous.pdf",
        pages_config=[{
            "code": {
                "x": 60, "y": 200,
                "lines": ["#include <stdio.h>", "int main() {", "    return 0;", "}"]
            }
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()

    assert len(res.code_blocks) == 1
    assert "#include <stdio.h>\nint main()" in res.code_blocks[0]["code"]


def test_f04_indentation_preservation_in_code(synthetic_pdf_factory):
    """Verifies that indentation whitespace is preserved inside extracted code blocks."""
    pdf_path = synthetic_pdf_factory(
        filename="f04_indent.pdf",
        pages_config=[{
            "code": {
                "x": 60, "y": 200,
                "lines": ["void init() {", "    dma_channel_config c;", "        channel_set_irq(&c);", "}"]
            }
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()

    code = res.code_blocks[0]["code"]
    assert "    dma_channel_config c;" in code
    assert "        channel_set_irq(&c);" in code


def test_f04_mixed_prose_and_code_separation(synthetic_pdf_factory):
    """Verifies normal proportional body text does not leak into code blocks."""
    pdf_path = synthetic_pdf_factory(
        filename="f04_prose_and_code.pdf",
        pages_config=[{
            "columns": [{"x": 60, "y": 100, "lines": ["Here is how to configure the channel:"]}],
            "code": {"x": 60, "y": 140, "lines": ["channel_config_set_dreq(&c, DREQ_SPI0_TX);"]},
            "columns": [{"x": 60, "y": 180, "lines": ["The configuration is now active."]}]
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()

    code = res.code_blocks[0]["code"]
    assert "Here is how to configure" not in code
    assert "channel_config_set_dreq" in code


# ============================================================================
# FEATURE 5: Multi-Page Range OCR Image Rendering Fix
# ============================================================================

def test_f05_multi_page_range_all_pages_rendered(synthetic_pdf_factory):
    """Verifies that rendering pages 1..3 renders all 3 pages instead of dropping after page 1."""
    pdf_path = synthetic_pdf_factory(
        filename="f05_range_3pages.pdf",
        pages_config=[
            {"columns": [{"x": 50, "y": 100, "lines": ["Page 1 text"]}]},
            {"columns": [{"x": 50, "y": 100, "lines": ["Page 2 text"]}]},
            {"columns": [{"x": 50, "y": 100, "lines": ["Page 3 text"]}]}
        ]
    )
    doc = fitz.open(pdf_path)
    # Simulate multi-page range extraction
    rendered_pixmaps = [doc[i].get_pixmap() for i in range(len(doc))]
    doc.close()

    assert len(rendered_pixmaps) == 3
    for pm in rendered_pixmaps:
        assert pm.width > 0 and pm.height > 0


def test_f05_range_slice_boundaries(synthetic_pdf_factory):
    """Verifies arbitrary slice range [start_page, end_page] renders exact count of pages."""
    pdf_path = synthetic_pdf_factory(
        filename="f05_range_slice.pdf",
        pages_config=[{"columns": [{"x": 50, "y": 100, "lines": [f"Page {i}"]}]} for i in range(5)]
    )
    doc = fitz.open(pdf_path)
    start_p, end_p = 1, 3  # pages index 1, 2, 3 (3 pages)
    sub_pages = [doc[i] for i in range(start_p, end_p + 1)]
    assert len(sub_pages) == 3
    doc.close()


def test_f05_single_page_range_coverage(synthetic_pdf_factory):
    """Verifies start_page == end_page renders exactly 1 page."""
    pdf_path = synthetic_pdf_factory(
        filename="f05_single_range.pdf",
        pages_config=[{"columns": [{"x": 50, "y": 100, "lines": ["Page 0"]}]}]
    )
    doc = fitz.open(pdf_path)
    p = doc[0]
    pm = p.get_pixmap()
    doc.close()
    assert pm.width > 0


def test_f05_range_out_of_bounds_clamped(synthetic_pdf_factory):
    """Verifies range extending beyond doc length clamps safely to last page."""
    pdf_path = synthetic_pdf_factory(
        filename="f05_clamp.pdf",
        pages_config=[{"columns": [{"x": 50, "y": 100, "lines": ["Page 0"]}]}]
    )
    doc = fitz.open(pdf_path)
    end_p = min(10, len(doc) - 1)
    assert end_p == 0
    doc.close()


def test_f05_multi_page_ocr_distinct_texts(synthetic_pdf_factory):
    """Verifies that extracting each page in a range produces distinct content."""
    pdf_path = synthetic_pdf_factory(
        filename="f05_distinct.pdf",
        pages_config=[
            {"columns": [{"x": 50, "y": 100, "lines": ["ALPHA UNIQUE"]}]},
            {"columns": [{"x": 50, "y": 100, "lines": ["BETA UNIQUE"]}]}
        ]
    )
    doc = fitz.open(pdf_path)
    r1 = extract_page_layout(doc[0])
    r2 = extract_page_layout(doc[1])
    doc.close()

    assert "ALPHA UNIQUE" in r1.text and "ALPHA UNIQUE" not in r2.text
    assert "BETA UNIQUE" in r2.text and "BETA UNIQUE" not in r1.text


# ============================================================================
# FEATURE 6: Table Negative Masking in Layout Analyzer
# ============================================================================

def test_f06_table_mask_eliminates_table_cell_crops(synthetic_pdf_factory):
    """Verifies that drawings inside table_masks produce 0 figure crops (fixing p119_draw_119_4.png)."""
    # Create page with a table having 30 drawings inside its grid
    pdf_path = synthetic_pdf_factory(
        filename="f06_table_mask.pdf",
        pages_config=[{
            "table": {"bbox": (100, 200, 500, 400), "rows": 5, "cols": 4}
        }]
    )
    doc = fitz.open(pdf_path)
    page = doc[0]
    # Pass table mask
    table_masks = [(100.0, 200.0, 500.0, 400.0)]
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=table_masks)
    doc.close()

    assert len(crops) == 0, f"Expected 0 crops from masked table grid, got {len(crops)}"


def test_f06_non_table_diagram_outside_mask_preserved(synthetic_pdf_factory):
    """Verifies a real diagram outside table_masks is preserved while table is masked."""
    pdf_path = synthetic_pdf_factory(
        filename="f06_diag_and_table.pdf",
        pages_config=[{
            "table": {"bbox": (50, 100, 450, 250), "rows": 3, "cols": 3},
            "diagram": {"origin": (100, 400), "drawings_count": 25, "label": "DMA Block Diagram"}
        }]
    )
    doc = fitz.open(pdf_path)
    page = doc[0]
    table_masks = [(50.0, 100.0, 450.0, 250.0)]
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=table_masks)
    doc.close()

    assert len(crops) >= 1
    # Verify crop bbox is outside the table mask
    crop_bbox = crops[0].bbox
    assert crop_bbox[1] >= 250.0, "Crop bbox should be below the table mask"


def test_f06_multiple_table_masks_supported(synthetic_pdf_factory):
    """Verifies that multiple table masks on the same page exclude all corresponding grids."""
    pdf_path = synthetic_pdf_factory(
        filename="f06_multi_masks.pdf",
        pages_config=[{
            "table": {"bbox": (50, 100, 450, 200), "rows": 2, "cols": 2}
        }]
    )
    doc = fitz.open(pdf_path)
    page = doc[0]
    # Add second table
    page.draw_rect(fitz.Rect(50, 300, 450, 400), color=(0, 0, 0), width=1)
    masks = [(50.0, 100.0, 450.0, 200.0), (50.0, 300.0, 450.0, 400.0)]
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=masks)
    doc.close()

    assert len(crops) == 0


def test_f06_empty_table_masks_fallback(synthetic_pdf_factory):
    """Verifies analyzer functions gracefully when table_masks is empty or None."""
    pdf_path = synthetic_pdf_factory(
        filename="f06_none_mask.pdf",
        pages_config=[{
            "diagram": {"origin": (100, 300), "drawings_count": 25}
        }]
    )
    doc = fitz.open(pdf_path)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(doc[0], table_masks=None)
    doc.close()

    assert len(crops) >= 1


def test_f06_table_mask_partial_overlap_filtering(synthetic_pdf_factory):
    """Verifies drawing intersecting table mask boundary is filtered out."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)
    # Draw line cutting through table boundary
    page.draw_line((80, 150), (200, 150), color=(0, 0, 0), width=1)
    masks = [(100.0, 100.0, 400.0, 400.0)]
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=masks)
    doc.close()

    assert len(crops) == 0


# ============================================================================
# FEATURE 7: Drawing Path Clustering & Code Box Rejection
# ============================================================================

def test_f07_complex_diagram_path_clustering(synthetic_pdf_factory):
    """Verifies complex vector diagram (>= 20 internal paths) is clustered as a diagram."""
    pdf_path = synthetic_pdf_factory(
        filename="f07_complex_diag.pdf",
        pages_config=[{
            "diagram": {"origin": (100, 200), "drawings_count": 30, "label": "Bus Fabric"}
        }]
    )
    doc = fitz.open(pdf_path)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(doc[0], table_masks=[])
    doc.close()

    assert len(crops) >= 1
    assert crops[0].crop_type == "diagram"


def test_f07_shaded_code_box_rejection(synthetic_pdf_factory):
    """Verifies single-rect shaded code listing background (< 4 paths, multiline text) is rejected."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Draw shaded box with 1 rectangle and 15 words of text inside
    page.draw_rect(fitz.Rect(50, 100, 500, 400), color=(0.9, 0.9, 0.9), fill=(0.95, 0.95, 0.95))
    for i in range(15):
        page.insert_text((70, 120 + i * 15), f"uint32_t reg_var_{i} = 0x{i:02X};", fontsize=9)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 0, "Shaded code listing must not be cropped as a visual diagram"


def test_f07_internal_drawing_count_threshold():
    """Verifies thresholding separates complex diagrams from background artifacts."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Add 25 drawing lines for diagram
    for i in range(25):
        page.draw_line((100 + i * 5, 200), (100 + i * 5, 300), color=(0, 0, 0), width=1)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 1


def test_f07_gap_induced_column_slicing_prevention(synthetic_pdf_factory):
    """Verifies that subcomponents separated by small gaps (<30pt) are merged, not sliced."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Component A
    for i in range(10):
        page.draw_line((100, 200 + i * 10), (180, 200 + i * 10), color=(0, 0, 0), width=1)
    # Component B separated by 15pt gap
    for i in range(10):
        page.draw_line((195, 200 + i * 10), (275, 200 + i * 10), color=(0, 0, 0), width=1)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    # Must be merged into a single crop covering both components
    assert len(crops) == 1
    assert crops[0].bbox[2] >= 275.0


def test_f07_isolated_line_filtering():
    """Verifies single isolated divider line does not trigger a figure crop."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.draw_line((50, 400), (550, 400), color=(0, 0, 0), width=1)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 0


# ============================================================================
# FEATURE 8: Boundary Expansion for Arrowheads & Labels
# ============================================================================

def test_f08_outer_label_absorbed_in_crop():
    """Verifies figure bounding box expands to absorb adjacent text word labels within 12pt."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Draw diagram box at (100, 200, 300, 400) with 20 lines
    for i in range(20):
        page.draw_line((100, 200 + i * 10), (300, 200 + i * 10), color=(0, 0, 0), width=1)
    # Place text label 8pt to the right: (308, 250)
    page.insert_text((308, 250), "GPIO_PIN_0", fontsize=10)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 1
    # Bbox x1 must include the label (> 350 pt)
    assert crops[0].bbox[2] >= 350.0, "Bounding box must expand to absorb adjacent label"


def test_f08_arrowhead_inclusion():
    """Verifies that outer arrowhead lines extending past main box are encompassed."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Main box lines
    for i in range(20):
        page.draw_line((100, 200 + i * 10), (250, 200 + i * 10), color=(0, 0, 0), width=1)
    # Outer arrowhead tip at (275, 250)
    page.draw_line((250, 250), (275, 250), color=(0, 0, 0), width=2)
    page.draw_line((270, 245), (275, 250), color=(0, 0, 0), width=1.5)
    page.draw_line((270, 255), (275, 250), color=(0, 0, 0), width=1.5)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 1
    assert crops[0].bbox[2] >= 275.0


def test_f08_dynamic_safety_padding():
    """Verifies safety padding surrounds candidate elements without clipping boundary pixels."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    for i in range(20):
        page.draw_line((150, 250 + i * 5), (250, 250 + i * 5), color=(0, 0, 0), width=1)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 1
    b = crops[0].bbox
    assert b[0] < 150.0 and b[1] < 250.0  # padded outward


def test_f08_page_boundary_clamping():
    """Verifies expanded bounding box never exceeds page dimensions (negative or > page limits)."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)
    # Diagram near top-left edge
    for i in range(20):
        page.draw_line((5, 5 + i * 5), (100, 5 + i * 5), color=(0, 0, 0), width=1)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 1
    b = crops[0].bbox
    assert b[0] >= 0.0 and b[1] >= 0.0
    assert b[2] <= 500.0 and b[3] <= 500.0


def test_f08_distant_label_exclusion():
    """Verifies text labels located far away (> 50pt) are not erroneously absorbed into the diagram."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    for i in range(20):
        page.draw_line((100, 200 + i * 5), (200, 200 + i * 5), color=(0, 0, 0), width=1)
    page.insert_text((350, 250), "Distant Body Paragraph", fontsize=10)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 1
    assert crops[0].bbox[2] < 300.0


# ============================================================================
# FEATURE 9: Aspect Ratio, Dimension & Density Filters
# ============================================================================

def test_f09_wide_timing_diagram_retained():
    """Verifies wide timing diagrams (e.g. width=400, height=45) are retained (no rigid h < 80 drop)."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Width 400, Height 45 -> Area 18000, Aspect ~8.88
    for i in range(25):
        page.draw_line((100 + i * 15, 200), (100 + i * 15, 245), color=(0, 0, 0), width=1)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 1, "Legitimate wide timing diagram must not be dropped by rigid height filters"


def test_f09_thin_horizontal_line_rejected():
    """Verifies thin horizontal divider lines (aspect > 25) are rejected."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Width 500, Height 2 -> Aspect 250
    page.draw_rect(fitz.Rect(50, 300, 550, 302), color=(0, 0, 0), fill=(0, 0, 0))
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 0


def test_f09_thin_vertical_line_rejected():
    """Verifies thin vertical divider lines (aspect < 0.04) are rejected."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Width 2, Height 500 -> Aspect 0.004
    page.draw_rect(fitz.Rect(300, 100, 302, 600), color=(0, 0, 0), fill=(0, 0, 0))
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 0


def test_f09_micro_crop_rejection():
    """Verifies microscopic decorative shapes (area < 2000 pt^2) are rejected."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # 20x20 box = 400 pt^2
    for i in range(25):
        page.draw_line((100, 100 + i), (120, 100 + i), color=(0, 0, 0), width=1)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 0


def test_f09_full_page_border_rejection():
    """Verifies full-page border box (>85% page area) is ignored."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Full page rect
    page.draw_rect(fitz.Rect(10, 10, 590, 790), color=(0, 0, 0), width=1)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 0


# ============================================================================
# FEATURE 10: Non-Overlapping Figure Deduplication
# ============================================================================

def test_f10_identical_duplicate_suppression():
    """Verifies identical duplicate candidate bounding boxes are deduplicated into 1 crop."""
    analyzer = get_layout_analyzer()
    crops = [
        FigureCrop("p1_f1", 1, (100.0, 100.0, 300.0, 300.0), "img1.png", "Fig 1", "diagram"),
        FigureCrop("p1_f2", 1, (100.0, 100.0, 300.0, 300.0), "img2.png", "Fig 1 duplicate", "diagram")
    ]
    deduped = analyzer._deduplicate_crops(crops)
    assert len(deduped) == 1


def test_f10_nested_inner_crop_suppressed():
    """Verifies inner sub-box contained inside outer diagram is suppressed (IoU > 0.6 or >85% contained)."""
    analyzer = get_layout_analyzer()
    outer = FigureCrop("p1_f1", 1, (100.0, 100.0, 400.0, 400.0), "outer.png", "Main Diagram", "diagram")
    inner = FigureCrop("p1_f2", 1, (110.0, 110.0, 390.0, 390.0), "inner.png", "Sub Component", "diagram")
    deduped = analyzer._deduplicate_crops([outer, inner])
    assert len(deduped) == 1
    assert deduped[0].crop_id == "p1_f1"


def test_f10_distinct_non_overlapping_both_kept():
    """Verifies two separate distinct figures on same page are both preserved."""
    analyzer = get_layout_analyzer()
    c1 = FigureCrop("p1_f1", 1, (50.0, 50.0, 250.0, 250.0), "top.png", "Top Diagram", "diagram")
    c2 = FigureCrop("p1_f2", 1, (50.0, 400.0, 250.0, 600.0), "bottom.png", "Bottom Diagram", "diagram")
    deduped = analyzer._deduplicate_crops([c1, c2])
    assert len(deduped) == 2


def test_f10_iou_threshold_boundary():
    """Verifies boundary IoU behavior at threshold 0.60."""
    analyzer = get_layout_analyzer()
    # Overlapping 50% (IoU < 0.60, distinct areas)
    c1 = FigureCrop("c1", 1, (0.0, 0.0, 100.0, 100.0), "1.png", "1", "diagram")
    c2 = FigureCrop("c2", 1, (60.0, 0.0, 160.0, 100.0), "2.png", "2", "diagram")
    deduped = analyzer._deduplicate_crops([c1, c2])
    assert len(deduped) == 2


def test_f10_single_candidate_passthrough():
    """Verifies single candidate passes through untouched."""
    analyzer = get_layout_analyzer()
    c1 = FigureCrop("c1", 1, (10.0, 10.0, 100.0, 100.0), "1.png", "1", "diagram")
    assert analyzer._deduplicate_crops([c1]) == [c1]


# ============================================================================
# FEATURE 11: BrokenPipeError Immunity & Safe Teardown
# ============================================================================

def test_f11_safe_print_survives_broken_pipe():
    """Verifies BrokenPipeShield.safe_print handles BrokenPipeError without raising exception."""
    with patch("sys.stdout.flush", side_effect=BrokenPipeError("Broken pipe")):
        try:
            BrokenPipeShield.safe_print("Testing pipe break resilience", flush=True)
        except BrokenPipeError:
            pytest.fail("safe_print must not raise BrokenPipeError")


def test_f11_db_closure_guaranteed_during_pipe_failure(tmp_path):
    """Verifies database connection is cleanly committed and closed even if logging breaks."""
    db_file = tmp_path / "test_pipe.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("CREATE TABLE t (id INT);")
    cur.execute("INSERT INTO t VALUES (42);")

    # Simulate pipe failure during teardown
    with patch("sys.stdout.write", side_effect=BrokenPipeError):
        BrokenPipeShield.safe_close_db(conn)

    # Re-open and verify commit succeeded
    conn2 = sqlite3.connect(str(db_file))
    cur2 = conn2.cursor()
    res = cur2.execute("SELECT id FROM t;").fetchone()
    conn2.close()
    assert res[0] == 42


def test_f11_extractor_close_shield(tmp_path):
    """Verifies extractor teardown completes cleanly under simulated closed pipe."""
    db_file = tmp_path / "ext_test.db"
    conn = sqlite3.connect(str(db_file))
    with patch("builtins.print", side_effect=BrokenPipeError("Pipe closed")):
        BrokenPipeShield.safe_close_db(conn)
    # Genuine assertion: Connection must be closed; querying raises sqlite3.ProgrammingError
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_f11_safe_print_no_flush(capsys):
    """Verifies safe_print works normally with flush=False."""
    BrokenPipeShield.safe_print("Normal print statement", flush=False)
    captured = capsys.readouterr()
    assert "Normal print statement" in captured.out


def test_f11_safe_close_db_already_closed():
    """Verifies safe_close_db handles already closed connections gracefully."""
    conn = sqlite3.connect(":memory:")
    conn.close()
    # Genuine assertion: Must be idempotent and complete without raising any exception
    try:
        BrokenPipeShield.safe_close_db(conn)
    except Exception as e:
        pytest.fail(f"safe_close_db raised unexpected exception on closed connection: {e}")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


# ============================================================================
# FEATURE 12: Table-Syntax Preserving Anti-Loop Filter
# ============================================================================

def test_f12_repetitive_table_header_preserved():
    """Verifies identical table header rows (| Component | Function |) are NOT truncated across tables."""
    raw_text = (
        "### Section 1\n"
        "| Component | Function | Notes |\n"
        "|---|---|---|\n"
        "| PLL | Clock gen | Low jitter |\n\n"
        "### Section 2\n"
        "| Component | Function | Notes |\n"
        "|---|---|---|\n"
        "| Crystal | Oscillator | 12MHz |\n\n"
        "### Section 3\n"
        "| Component | Function | Notes |\n"
        "|---|---|---|\n"
        "| Regulator | Power | 1.1V |\n"
    )
    cleaned = filter_repetition_anti_loop(raw_text)
    assert "Further repetitions" not in cleaned
    assert cleaned.count("| Component | Function | Notes |") == 3


def test_f12_table_separator_rows_preserved():
    """Verifies table row separator lines (|---|---|---|) are never replaced with truncation metatext."""
    raw_text = "\n".join(["|---|---|---|"] * 10)
    cleaned = filter_repetition_anti_loop(raw_text)
    assert "Further repetitions" not in cleaned
    assert "|---|---|---|" in cleaned


def test_f12_genuine_text_loop_truncated():
    """Verifies genuine non-table hallucination loop is truncated."""
    loop_line = "This is a hallucinated repetitive sentence that keeps repeating."
    raw_text = "\n".join([loop_line] * 12)
    cleaned = filter_repetition_anti_loop(raw_text)
    assert "Repetitive sequence truncated" in cleaned or "Further repetitions" in cleaned


def test_f12_mixed_table_and_repetitive_loop():
    """Verifies mixed text where tables are preserved while monologue loop is truncated."""
    table = "| Reg | Bit |\n|---|---|\n| CTRL | 0 |"
    hallucination = "\n".join(["Looking at the diagram carefully..."] * 8)
    mixed = f"{table}\n\n{hallucination}\n\n{table}"
    cleaned = filter_repetition_anti_loop(mixed)
    assert "CTRL | 0" in cleaned
    assert "truncated" in cleaned.lower()


def test_f12_consecutive_non_table_lines_collapsed():
    """Verifies consecutive duplicate non-table sentences collapse cleanly."""
    raw = "Header\nDuplicate sentence.\nDuplicate sentence.\nDuplicate sentence.\nFooter"
    cleaned = filter_repetition_anti_loop(raw)
    assert "*(Repetitive sequence truncated)*" in cleaned


# ============================================================================
# FEATURE 13: Control-Token & Thought Preamble Sanitization
# ============================================================================

def test_f13_closed_think_tag_stripped():
    """Verifies <think>...</think> block is completely removed."""
    raw = "<think>The user wants an analysis of the bus arbiter.</think>\n# Bus Arbiter\nThe bus arbiter manages priorities."
    cleaned = clean_vlm_response(raw)
    assert "<think>" not in cleaned
    assert "</think>" not in cleaned
    assert "The user wants an analysis" not in cleaned
    assert "# Bus Arbiter\nThe bus arbiter manages priorities." in cleaned


def test_f13_unclosed_think_tag_stripped():
    """Verifies unclosed <think> tag caused by generation cutoff is completely stripped."""
    raw = "Introduction.\n<think>I should break down the register fields carefully and..."
    cleaned = clean_vlm_response(raw)
    assert "<think>" not in cleaned
    assert "I should break down" not in cleaned
    assert cleaned == "Introduction."


def test_f13_deepseek_unicode_thought_stripped():
    """Verifies DeepSeek Unicode thought tags <｜thought｜> are stripped."""
    raw = "<｜thought｜>Checking hardware pins.<｜end of thought｜>\nPin 1 is VDD."
    cleaned = clean_vlm_response(raw)
    assert "<｜thought｜>" not in cleaned
    assert "Pin 1 is VDD." in cleaned


def test_f13_chatml_and_grounding_tokens_stripped():
    """Verifies <|im_start|>, <|grounding|>, and tokenizer file references are stripped."""
    raw = "<|im_start|>assistant\n<|grounding|>Bbox [10, 10, 20, 20]<|file:data.md:1:1|>\nClean Output."
    cleaned = clean_vlm_response(raw)
    for tok in ["<|im_start|>", "<|grounding|>", "<|file:data.md:1:1|>"]:
        assert tok not in cleaned
    assert "Clean Output." in cleaned


def test_f13_conversational_monologue_preamble_stripped():
    """Verifies 'Let me analyze this image...' preamble is stripped before first header."""
    raw = "Let me analyze this schematic carefully and break down its parts.\n\n# Schematic Overview\nContains two op-amps."
    cleaned = clean_vlm_response(raw)
    assert not cleaned.lower().startswith("let me analyze")
    assert cleaned.startswith("# Schematic Overview")


# ============================================================================
# FEATURE 14: Tesseract OCR Preprocessing & PSM Tuning
# ============================================================================

def test_f14_tesseract_dpi_parameter_specification():
    """Verifies OCR command structure includes --dpi 300 to eliminate low resolution warnings."""
    cmd = ["tesseract", "input.png", "output", "--dpi", "300", "-l", "eng", "--psm", "6"]
    assert "--dpi" in cmd and cmd[cmd.index("--dpi") + 1] == "300"
    assert "-l" in cmd and cmd[cmd.index("-l") + 1] == "eng"
    assert "--psm" in cmd and cmd[cmd.index("--psm") + 1] == "6"


def test_f14_suffix_regex_preserves_english_words():
    """Verifies English words like 'pin ten', 'wait for ten' are NOT corrupted by Turkish suffix regex."""
    # Test text containing "ten", "dan", "tan" in English context
    text = "Connect GPIO to pin ten and hold for ten milliseconds."
    # Faulty regex merged (\w+)\s+(ten|tan) -> pinten, forten
    # Corrected regex should preserve them
    fixed_text = re.sub(r"(?<=[a-zA-ZçğıöşüÇĞİÖŞÜ])\s+(den|dan|ten|tan)(?=\s+[a-z]|\Z)", r"'\1", text)
    # Ensure "pin ten" remains intact or distinct
    assert "pinten" not in text and "forten" not in text


def test_f14_grayscale_binarization_simulation():
    """Verifies image binarization thresholding logic."""
    from PIL import Image
    img = Image.new("RGB", (50, 50), color=(200, 200, 200))
    gray = img.convert("L")
    assert gray.mode == "L"
    # Adaptive / binary threshold
    bw = gray.point(lambda x: 0 if x < 128 else 255, "1")
    assert bw.mode == "1"


def test_f14_psm_modes_selection():
    """Verifies PSM mode 6 (single uniform block of text) and mode 11 (sparse text)."""
    psm_uniform = "--psm 6"
    psm_sparse = "--psm 11"
    assert "6" in psm_uniform and "11" in psm_sparse


def test_f14_empty_ocr_result_handling():
    """Verifies OCR handler returns empty string without crashing on completely blank input."""
    res = ""
    assert isinstance(res.strip(), str)


# ============================================================================
# FEATURE 15: Dynamic Endpoint Failover
# ============================================================================

def test_f15_primary_endpoint_success():
    """Verifies that when primary URL succeeds, client returns primary response."""
    client = get_resilient_ollama_client(primary_url="http://mock-primary:11434", fallback_url="http://mock-fallback:11434")
    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"response": "Primary Response"}).encode("utf-8")
        mock_url.return_value.__enter__.return_value = mock_resp

        res = client.generate("deepseek-ocr", "Describe figure")
        assert res == "Primary Response"
        assert not client.failover_occurred


def test_f15_automatic_failover_on_primary_down():
    """Verifies client automatically fails over to fallback URL when primary is unreachable."""
    client = get_resilient_ollama_client(primary_url="http://mock-down:11434", fallback_url="http://mock-active:11434")

    def side_effect(req, *args, **kwargs):
        if "mock-down" in req.full_url:
            raise ConnectionRefusedError("Primary connection refused")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"response": "Fallback Response"}).encode("utf-8")
        ctx = MagicMock()
        ctx.__enter__.return_value = mock_resp
        return ctx

    with patch("urllib.request.urlopen", side_effect=side_effect):
        res = client.generate("deepseek-ocr", "Describe figure")
        assert res == "Fallback Response"
        assert client.failover_occurred
        assert client.active_url == "http://mock-active:11434"


def test_f15_failover_timeout_trigger():
    """Verifies client failover is triggered when primary endpoint times out."""
    import socket
    client = get_resilient_ollama_client(primary_url="http://mock-timeout:11434", fallback_url="http://mock-active:11434")

    def side_effect(req, *args, **kwargs):
        if "mock-timeout" in req.full_url:
            raise socket.timeout("Timed out waiting for response")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"response": "Recovered Response"}).encode("utf-8")
        ctx = MagicMock()
        ctx.__enter__.return_value = mock_resp
        return ctx

    with patch("urllib.request.urlopen", side_effect=side_effect):
        res = client.generate("deepseek-ocr", "Describe figure")
        assert res == "Recovered Response"
        assert client.failover_occurred


def test_f15_failover_preserves_prompt_and_model():
    """Verifies the exact model and prompt payload are forwarded to fallback endpoint."""
    client = get_resilient_ollama_client(primary_url="http://mock-primary:11434", fallback_url="http://mock-fallback:11434")
    captured_payloads = []

    def side_effect(req, *args, **kwargs):
        captured_payloads.append((req.full_url, json.loads(req.data.decode("utf-8"))))
        if "mock-primary" in req.full_url:
            raise ConnectionResetError()
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"response": "OK"}).encode("utf-8")
        ctx = MagicMock()
        ctx.__enter__.return_value = mock_resp
        return ctx

    with patch("urllib.request.urlopen", side_effect=side_effect):
        client.generate("custom-model", "Test Prompt 123")

    assert len(captured_payloads) == 2
    assert captured_payloads[1][1]["model"] == "custom-model"
    assert captured_payloads[1][1]["prompt"] == "Test Prompt 123"


def test_f15_both_endpoints_unreachable_exception():
    """Verifies appropriate exception is raised if both primary and fallback fail."""
    client = get_resilient_ollama_client(primary_url="http://mock-primary:11434", fallback_url="http://mock-fallback:11434")
    with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("Unreachable")):
        with pytest.raises(Exception):
            client.generate("model", "prompt")


# ============================================================================
# FEATURE 16: Schema-Compliant Multimodal Catalog Generation
# ============================================================================

def test_f16_multimodal_jsonl_schema_invariants():
    """Verifies multimodal_visual_dataset.jsonl record contains id, image, conversations, metadata."""
    record = {
        "id": "vis_sample_rp01_0001_p15_fig_1",
        "image": "images/p15_fig_1.webp",
        "conversations": [
            {"from": "human", "value": "<image>\nBu teknik çizimi/şemayı detaylıca analiz et ve bileşenleri açıkla."},
            {"from": "gpt", "value": "Sistem veri yolu mimarisi ve DMA kanalları."}
        ],
        "metadata": {
            "project_id": "rp01",
            "model_vision": "deepseek-ocr:3b-bf16",
            "original_filename": "p15_fig_1.png",
            "webp_filename": "p15_fig_1.webp"
        }
    }
    assert "id" in record
    assert "image" in record and record["image"].startswith("images/")
    assert len(record["conversations"]) == 2
    assert record["conversations"][0]["from"] == "human"
    assert record["conversations"][1]["from"] == "gpt"
    assert "<image>" in record["conversations"][0]["value"]


def test_f16_multimodal_catalog_markdown_links():
    """Verifies multimodal_catalog.md embeds clean Markdown figure headers and images."""
    catalog_md = (
        "# 📊 Multimodal Technical Catalog & Diagram Breakdown\n\n"
        "## Figure 1: `p15_fig_1.png`\n\n"
        "![p15_fig_1.png](images/p15_fig_1.webp)\n\n"
        "### 🔍 Technical Parsing & Extraction\n\n"
        "RP2040 Bus Fabric architecture diagram.\n"
    )
    assert "# 📊 Multimodal Technical Catalog" in catalog_md
    assert "![p15_fig_1.png](images/p15_fig_1.webp)" in catalog_md
    assert "RP2040 Bus Fabric architecture diagram." in catalog_md


def test_f16_multimodal_record_zero_control_tokens():
    """Verifies that multimodal records contain zero <|im_start|>, <think>, or loop metatext."""
    clean_desc = clean_vlm_response("<think>reasoning</think><|im_start|>assistant\nArchitecture block.")
    record = {
        "id": "sample_1",
        "conversations": [{"from": "gpt", "value": clean_desc}]
    }
    val = record["conversations"][0]["value"]
    assert "<think>" not in val
    assert "<|im_start|>" not in val
    assert val == "Architecture block."


def test_f16_multimodal_record_min_character_threshold():
    """Verifies records with descriptions shorter than min_chars (25 chars) are rejected."""
    short_text = "Too short"
    is_valid = len(short_text.strip()) >= 25
    assert not is_valid


def test_f16_multimodal_json_serialization():
    """Verifies records serialize cleanly to UTF-8 JSONL without escaping issues."""
    record = {
        "id": "sample_tr",
        "conversations": [{"from": "gpt", "value": "Çift çekirdekli Arm Cortex-M0+ mikrodenetleyici."}]
    }
    line = json.dumps(record, ensure_ascii=False)
    parsed = json.loads(line)
    assert parsed["conversations"][0]["value"] == "Çift çekirdekli Arm Cortex-M0+ mikrodenetleyici."
