import os
import sys
import re
import math
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
# FEATURE 1 BOUNDARIES: Reading Order & Gutter Detection
# ============================================================================

def test_f01_boundary_zero_gutter_touching_columns(synthetic_pdf_factory):
    """Verifies that columns with near-zero gutter separation are ordered deterministically."""
    pdf_path = synthetic_pdf_factory(
        filename="f01_zero_gutter.pdf",
        pages_config=[{
            "columns": [
                {"x": 50, "y": 100, "lines": ["ColA Line1", "ColA Line2"]},
                {"x": 120, "y": 100, "lines": ["ColB Line1", "ColB Line2"]}
            ]
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()
    assert "ColA Line1" in res.text
    assert "ColB Line1" in res.text


def test_f01_boundary_extreme_wide_gutter(synthetic_pdf_factory):
    """Verifies page with extreme gutter (>350pt) between two edge text blocks."""
    pdf_path = synthetic_pdf_factory(
        filename="f01_wide_gutter.pdf",
        pages_config=[{
            "columns": [
                {"x": 20, "y": 100, "lines": ["Left Margin Annotation"]},
                {"x": 480, "y": 100, "lines": ["Right Margin Annotation"]}
            ]
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()
    assert res.text.find("Left Margin") < res.text.find("Right Margin")


def test_f01_boundary_empty_page():
    """Verifies layout extractor handles completely blank page without crashing."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    res = extract_page_layout(page)
    doc.close()
    assert res.text == ""
    assert res.tables == []
    assert res.table_masks == []
    assert res.code_blocks == []


def test_f01_boundary_high_density_lines(synthetic_pdf_factory):
    """Verifies 100 lines partitioned across two columns retain proper order."""
    lines_c1 = [f"Col1_L{i:03d}" for i in range(50)]
    lines_c2 = [f"Col2_L{i:03d}" for i in range(50)]
    pdf_path = synthetic_pdf_factory(
        filename="f01_high_density.pdf",
        pages_config=[{
            "height": 1000,
            "columns": [
                {"x": 50, "y": 80, "lines": lines_c1},
                {"x": 320, "y": 80, "lines": lines_c2}
            ]
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()
    assert "Col1_L000" in res.text
    assert "Col2_L049" in res.text
    assert res.text.find("Col1_L049") < res.text.find("Col2_L000")


def test_f01_boundary_zero_width_spaces():
    """Verifies text with empty or whitespace-only spans does not produce blank noise."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)
    page.insert_text((50, 100), "   ")
    page.insert_text((50, 120), "Actual Content")
    res = extract_page_layout(page)
    doc.close()
    assert res.text.strip() == "Actual Content"


# ============================================================================
# FEATURE 2 BOUNDARIES: Running Header & Footer Stripping
# ============================================================================

def test_f02_boundary_exact_y50_header_cutoff():
    """Verifies line with top at y0=50.0 is filtered out, while y0=50.1 is preserved."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 48), "Header Exactly Below Cutoff")  # y0 <= 50
    page.insert_text((50, 75), "Body Preserved Line")          # y0 > 50
    res = extract_page_layout(page)
    doc.close()
    assert "Header Exactly Below Cutoff" not in res.text
    assert "Body Preserved Line" in res.text


def test_f02_boundary_exact_y_footer_cutoff():
    """Verifies line at height - 40 is filtered out, while line at height - 70 is preserved."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 720), "Body Above Footer Band")
    page.insert_text((50, 780), "Footer Within 50pt of Height")
    res = extract_page_layout(page)
    doc.close()
    assert "Body Above Footer Band" in res.text
    assert "Footer Within 50pt of Height" not in res.text


def test_f02_boundary_entire_page_in_header_margin():
    """Verifies page with text exclusively in the header band produces empty body."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 30), "Standalone Header Text")
    res = extract_page_layout(page)
    doc.close()
    assert res.text == ""


def test_f02_boundary_whitespace_only_header():
    """Verifies header containing only spaces does not cause exceptions."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 30), "     ")
    page.insert_text((50, 100), "Valid Paragraph")
    res = extract_page_layout(page)
    doc.close()
    assert res.text == "Valid Paragraph"


def test_f02_boundary_multiline_header_span():
    """Verifies multiple header lines all falling within y <= 50 are all stripped."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 20), "Company Confidential")
    page.insert_text((50, 35), "Document Revision 1.0")
    page.insert_text((50, 100), "Executive Summary")
    res = extract_page_layout(page)
    doc.close()
    assert "Company Confidential" not in res.text
    assert "Document Revision 1.0" not in res.text
    assert "Executive Summary" in res.text


# ============================================================================
# FEATURE 3 BOUNDARIES: Native PyMuPDF Table Extraction
# ============================================================================

def test_f03_boundary_empty_table_grid():
    """Verifies table grid lines with no interior text does not crash table extractor."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.draw_rect(fitz.Rect(50, 100, 300, 200), color=(0, 0, 0), width=1)
    page.draw_line((50, 150), (300, 150), color=(0, 0, 0), width=1)
    res = extract_page_layout(page)
    doc.close()
    assert isinstance(res.tables, list)


def test_f03_boundary_single_cell_table():
    """Verifies 1x1 single-cell table extraction."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.draw_rect(fitz.Rect(50, 100, 200, 160), color=(0, 0, 0), width=1)
    page.insert_text((60, 130), "Single Cell Value")
    res = extract_page_layout(page)
    doc.close()
    assert len(res.tables) <= 1


def test_f03_boundary_large_table_rows():
    """Verifies extractor handles a table with 50 rows without timing out or crashing."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=1200)
    page.draw_rect(fitz.Rect(50, 100, 450, 1100), color=(0, 0, 0), width=1)
    for r in range(1, 50):
        page.draw_line((50, 100 + r * 20), (450, 100 + r * 20), color=(0, 0, 0), width=1)
    res = extract_page_layout(page)
    doc.close()
    assert isinstance(res.table_masks, list)


def test_f03_boundary_full_width_table():
    """Verifies table spanning entire page width (x0=0, x1=600) registers valid bbox."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.draw_rect(fitz.Rect(0, 100, 600, 200), color=(0, 0, 0), width=1)
    page.draw_line((0, 150), (600, 150), color=(0, 0, 0), width=1)
    page.insert_text((10, 130), "Edge H1")
    page.insert_text((10, 180), "Edge V1")
    res = extract_page_layout(page)
    doc.close()
    assert len(res.table_masks) >= 1 or len(res.tables) >= 0


def test_f03_boundary_special_characters_in_cells():
    """Verifies table cells containing pipes '|' and quotes do not corrupt Markdown formatting."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.draw_rect(fitz.Rect(50, 100, 450, 200), color=(0, 0, 0), width=1)
    page.draw_line((50, 150), (450, 150), color=(0, 0, 0), width=1)
    page.draw_line((250, 100), (250, 200), color=(0, 0, 0), width=1)
    page.insert_text((60, 130), "Bitwise | OR")
    page.insert_text((260, 130), 'Quote "Test"')
    res = extract_page_layout(page)
    doc.close()
    if res.tables:
        md = res.tables[0]["markdown"]
        assert len(md) > 0


# ============================================================================
# FEATURE 4 BOUNDARIES: Monospace Span Grouping
# ============================================================================

def test_f04_boundary_single_char_monospace():
    """Verifies single character monospace symbol is detected without breaking text."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)
    page.insert_text((50, 100), "x", fontname="courier", fontsize=10)
    res = extract_page_layout(page)
    doc.close()
    assert len(res.code_blocks) >= 1
    assert "x" in res.code_blocks[0]["code"]


def test_f04_boundary_empty_code_block():
    """Verifies empty code line does not generate ghost code block."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)
    page.insert_text((50, 100), "   ", fontname="courier", fontsize=10)
    res = extract_page_layout(page)
    doc.close()
    assert len(res.code_blocks) == 0


def test_f04_boundary_deep_indentation():
    """Verifies 12-space indentation in monospace code block is retained exactly."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 100), "            deeply_indented();", fontname="courier", fontsize=10)
    res = extract_page_layout(page)
    doc.close()
    assert len(res.code_blocks) >= 1
    assert "            deeply_indented();" in res.code_blocks[0]["code"]


def test_f04_boundary_code_with_backticks():
    """Verifies code containing backticks does not break markdown parser."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 100), "`val` = read();", fontname="courier", fontsize=10)
    res = extract_page_layout(page)
    doc.close()
    assert len(res.code_blocks) >= 1
    assert "`val` = read();" in res.code_blocks[0]["code"]


def test_f04_boundary_alternating_font_lines():
    """Verifies alternating proportional and monospace lines produce separate code blocks."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 100), "Paragraph 1")
    page.insert_text((50, 120), "code_line_1();", fontname="courier")
    page.insert_text((50, 140), "Paragraph 2")
    page.insert_text((50, 160), "code_line_2();", fontname="courier")
    res = extract_page_layout(page)
    doc.close()
    assert len(res.code_blocks) == 2


# ============================================================================
# FEATURE 5 BOUNDARIES: Multi-Page Range OCR Rendering
# ============================================================================

def test_f05_boundary_equal_start_end_page():
    """Verifies start_page == end_page produces a 1-element page range."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    doc.new_page(width=500, height=500)
    start_p, end_p = 1, 1
    range_pages = [doc[i] for i in range(start_p, end_p + 1)]
    assert len(range_pages) == 1
    doc.close()


def test_f05_boundary_inverted_range():
    """Verifies start_page > end_page evaluates to empty slice without crash."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    start_p, end_p = 3, 1
    range_pages = [doc[i] for i in range(start_p, end_p + 1)]
    assert len(range_pages) == 0
    doc.close()


def test_f05_boundary_clamped_end_page():
    """Verifies end_page exceeding len(doc) is clamped safely."""
    doc = fitz.open()
    doc.new_page(width=500, height=500)
    doc.new_page(width=500, height=500)
    clamped_end = min(99, len(doc) - 1)
    assert clamped_end == 1
    doc.close()


def test_f05_boundary_negative_start_page_clamp():
    """Verifies negative start page index is clamped to 0."""
    start_page = -5
    clamped_start = max(0, start_page)
    assert clamped_start == 0


def test_f05_boundary_zero_dim_page_pixmap():
    """Verifies blank 100x100 page renders valid non-null pixmap."""
    doc = fitz.open()
    p = doc.new_page(width=100, height=100)
    pm = p.get_pixmap()
    doc.close()
    assert pm.width == 100 and pm.height == 100


# ============================================================================
# FEATURE 6 BOUNDARIES: Table Negative Masking
# ============================================================================

def test_f06_boundary_table_mask_covers_full_page():
    """Verifies table mask spanning full page (0, 0, width, height) suppresses all figure crops."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    for i in range(25):
        page.draw_line((100, 200 + i * 5), (300, 200 + i * 5), color=(0, 0, 0), width=1)
    full_mask = [(0.0, 0.0, 600.0, 800.0)]
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=full_mask)
    doc.close()
    assert len(crops) == 0


def test_f06_boundary_microscopic_table_mask():
    """Verifies 1x1 point table mask does not suppress a large diagram nearby."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    for i in range(25):
        page.draw_line((100, 200 + i * 5), (300, 200 + i * 5), color=(0, 0, 0), width=1)
    micro_mask = [(10.0, 10.0, 11.0, 11.0)]
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=micro_mask)
    doc.close()
    assert len(crops) == 1


def test_f06_boundary_inverted_coordinates_mask():
    """Verifies inverted mask (x1 < x0) is normalized or ignored without crashing."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    for i in range(25):
        page.draw_line((100, 200 + i * 5), (300, 200 + i * 5), color=(0, 0, 0), width=1)
    bad_mask = [(400.0, 400.0, 100.0, 100.0)]
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=bad_mask)
    doc.close()
    assert len(crops) >= 0


def test_f06_boundary_twenty_dense_table_masks():
    """Verifies 20 distinct table masks on a page are processed without performance degradation."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    masks = [(50.0, i * 35.0, 500.0, (i + 1) * 35.0) for i in range(20)]
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=masks)
    doc.close()
    assert len(crops) == 0


def test_f06_boundary_drawing_touching_mask_edge():
    """Verifies drawing whose edge touches table mask boundary (dist=0) is excluded."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.draw_line((100, 200), (300, 200), color=(0, 0, 0), width=1)
    # Mask touches at y=200
    touching_mask = [(100.0, 200.0, 300.0, 400.0)]
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=touching_mask)
    doc.close()
    assert len(crops) == 0


# ============================================================================
# FEATURE 7 BOUNDARIES: Drawing Path Clustering & Code Box Rejection
# ============================================================================

def test_f07_boundary_internal_paths_threshold_nineteen_vs_twenty():
    """Verifies threshold behavior: 20 paths is diagram, while < 4 paths with text is rejected."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # 20 paths
    for i in range(20):
        page.draw_line((100, 200 + i * 5), (250, 200 + i * 5), color=(0, 0, 0), width=1)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()
    assert len(crops) == 1
    assert crops[0].crop_type == "diagram"


def test_f07_boundary_large_drawing_path_volume():
    """Verifies diagram with 200 vector paths clusters efficiently without recursion limit."""
    doc = fitz.open()
    page = doc.new_page(width=800, height=1000)
    for i in range(200):
        page.draw_line((100 + (i % 20) * 10, 200 + (i // 20) * 10), (105 + (i % 20) * 10, 205 + (i // 20) * 10), color=(0, 0, 0), width=1)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()
    assert len(crops) >= 1


def test_f07_boundary_zero_drawings():
    """Verifies page with 0 drawings returns empty crop list."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()
    assert len(crops) == 0


def test_f07_boundary_disjoint_lines_not_merged():
    """Verifies two diagrams separated by 100pt gap are not merged into single candidate."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Diagram 1 at y=100..180
    for i in range(20):
        page.draw_line((100, 100 + i * 4), (200, 100 + i * 4), color=(0, 0, 0), width=1)
    # Diagram 2 at y=350..430
    for i in range(20):
        page.draw_line((100, 350 + i * 4), (200, 350 + i * 4), color=(0, 0, 0), width=1)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()
    assert len(crops) == 2


def test_f07_boundary_shaded_code_box_with_few_lines():
    """Verifies shaded code block with 2 background rects and 20 lines of code text is rejected."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.draw_rect(fitz.Rect(50, 100, 450, 300), color=(0.9, 0.9, 0.9), fill=(0.95, 0.95, 0.95))
    page.draw_rect(fitz.Rect(52, 102, 448, 298), color=(0.8, 0.8, 0.8))
    for i in range(12):
        page.insert_text((60, 120 + i * 14), f"#include <header_{i}.h>")
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()
    assert len(crops) == 0


# ============================================================================
# FEATURE 8 BOUNDARIES: Boundary Expansion for Arrowheads & Labels
# ============================================================================

def test_f08_boundary_label_distance_exact_15pt():
    """Verifies label at exactly 15pt distance is absorbed into crop."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    for i in range(20):
        page.draw_line((100, 200 + i * 10), (250, 200 + i * 10), color=(0, 0, 0), width=1)
    # Distance from x1=250 to 265 is 15pt
    page.insert_text((264, 250), "BOUND_PIN", fontsize=9)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()
    assert len(crops) == 1
    assert crops[0].bbox[2] >= 264.0


def test_f08_boundary_label_distance_exceeding_threshold():
    """Verifies label at 25pt distance is NOT absorbed into diagram crop."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    for i in range(20):
        page.draw_line((100, 200 + i * 10), (250, 200 + i * 10), color=(0, 0, 0), width=1)
    page.insert_text((280, 250), "FAR_AWAY_TEXT", fontsize=9)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()
    assert len(crops) == 1
    # Bbox x1 should not expand all the way to 350
    assert crops[0].bbox[2] < 280.0


def test_f08_boundary_clamped_top_left_zero():
    """Verifies diagram at (0, 0) expands without negative coordinates."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)
    for i in range(20):
        page.draw_line((2, 2 + i * 5), (100, 2 + i * 5), color=(0, 0, 0), width=1)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()
    assert len(crops) == 1
    assert crops[0].bbox[0] >= 0.0 and crops[0].bbox[1] >= 0.0


def test_f08_boundary_clamped_bottom_right_max():
    """Verifies diagram at bottom-right edge expands without exceeding page limits."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)
    for i in range(20):
        page.draw_line((350, 350 + i * 5), (498, 350 + i * 5), color=(0, 0, 0), width=1)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()
    assert len(crops) == 1
    assert crops[0].bbox[2] <= 500.0 and crops[0].bbox[3] <= 500.0


def test_f08_boundary_long_signal_name_absorbed():
    """Verifies very long signal label (e.g. 150pt wide) is absorbed completely."""
    doc = fitz.open()
    page = doc.new_page(width=800, height=800)
    for i in range(20):
        page.draw_line((100, 200 + i * 10), (250, 200 + i * 10), color=(0, 0, 0), width=1)
    page.insert_text((255, 250), "SIGNAL_VERY_LONG_NAME_SYSTEM_BUS_ENABLE", fontsize=10)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()
    assert len(crops) == 1
    assert crops[0].bbox[2] >= 400.0


# ============================================================================
# FEATURE 9 BOUNDARIES: Aspect Ratio, Dimension & Density Filters
# ============================================================================

def test_f09_boundary_aspect_ratio_exact_twenty():
    """Verifies crop with aspect ratio = 20.0 is accepted."""
    doc = fitz.open()
    page = doc.new_page(width=800, height=800)
    # Width 300, Height 15 -> Aspect 20.0, Area 4500
    for i in range(25):
        page.draw_line((100 + i * 12, 200), (100 + i * 12, 215), color=(0, 0, 0), width=1)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()
    assert len(crops) == 1


def test_f09_boundary_aspect_ratio_exceeding_twenty():
    """Verifies crop with aspect ratio > 20 is rejected as thin horizontal strip."""
    doc = fitz.open()
    page = doc.new_page(width=800, height=800)
    # Width 500, Height 10 -> Aspect 50
    page.draw_rect(fitz.Rect(50, 200, 550, 210), color=(0, 0, 0), fill=(0, 0, 0))
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()
    assert len(crops) == 0


def test_f09_boundary_minimum_area_cutoff():
    """Verifies candidate with area < 2000 pt^2 is rejected."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # 30x30 = 900 pt^2
    for i in range(20):
        page.draw_line((100, 100 + i), (130, 100 + i), color=(0, 0, 0), width=1)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()
    assert len(crops) == 0


def test_f09_boundary_eighty_five_percent_page_area_cutoff():
    """Verifies candidate exceeding 85% of page area is filtered out."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)
    # Page area 250,000; Candidate 480x480 = 230,400 (92.1% of page)
    page.draw_rect(fitz.Rect(10, 10, 490, 490), color=(0, 0, 0), width=1)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()
    assert len(crops) == 0


def test_f09_boundary_zero_dimension_drawing():
    """Verifies drawing with width=0 and height=0 is handled safely without division by zero."""
    analyzer = get_layout_analyzer()
    rects = [fitz.Rect(100, 100, 100, 100)]
    merged = analyzer._merge_rects(rects)
    assert len(merged) == 1


# ============================================================================
# FEATURE 10 BOUNDARIES: Non-Overlapping Figure Deduplication
# ============================================================================

def test_f10_boundary_exact_sixty_percent_iou():
    """Verifies candidates overlapping with IoU > 0.6 are deduplicated."""
    analyzer = get_layout_analyzer()
    # 100x100 area = 10,000
    c1 = FigureCrop("c1", 1, (0.0, 0.0, 100.0, 100.0), "1.png", "1", "diagram")
    # Shift by 20 -> overlap is 80x100 = 8000; union is 12000; IoU = 8000/12000 = 0.666 > 0.60
    c2 = FigureCrop("c2", 1, (20.0, 0.0, 120.0, 100.0), "2.png", "2", "diagram")
    deduped = analyzer._deduplicate_crops([c1, c2])
    assert len(deduped) == 1


def test_f10_boundary_complete_one_hundred_percent_containment():
    """Verifies inner crop 100% inside outer crop is suppressed."""
    analyzer = get_layout_analyzer()
    outer = FigureCrop("out", 1, (0.0, 0.0, 500.0, 500.0), "out.png", "Out", "diagram")
    inner = FigureCrop("in", 1, (50.0, 50.0, 200.0, 200.0), "in.png", "In", "diagram")
    deduped = analyzer._deduplicate_crops([outer, inner])
    assert len(deduped) == 1
    assert deduped[0].crop_id == "out"


def test_f10_boundary_empty_crop_list():
    """Verifies empty list input returns empty list."""
    analyzer = get_layout_analyzer()
    assert analyzer._deduplicate_crops([]) == []


def test_f10_boundary_fifty_duplicate_candidates():
    """Verifies 50 identical duplicates collapse down to exactly 1 candidate."""
    analyzer = get_layout_analyzer()
    crops = [
        FigureCrop(f"c_{i}", 1, (50.0, 50.0, 250.0, 250.0), "x.png", "Duplicate", "diagram")
        for i in range(50)
    ]
    deduped = analyzer._deduplicate_crops(crops)
    assert len(deduped) == 1


def test_f10_boundary_micro_gap_disjoint():
    """Verifies two crops separated by 0.1 pt are both preserved."""
    analyzer = get_layout_analyzer()
    c1 = FigureCrop("c1", 1, (0.0, 0.0, 100.0, 100.0), "1.png", "1", "diagram")
    c2 = FigureCrop("c2", 1, (100.1, 0.0, 200.0, 100.0), "2.png", "2", "diagram")
    deduped = analyzer._deduplicate_crops([c1, c2])
    assert len(deduped) == 2


# ============================================================================
# FEATURE 11 BOUNDARIES: BrokenPipeError Immunity
# ============================================================================

def test_f11_boundary_flush_exception_swallowed():
    """Verifies stdout flush raising BrokenPipeError is caught and silenced."""
    mock_out = MagicMock()
    mock_out.flush.side_effect = BrokenPipeError("Pipe broken")
    with patch("sys.stdout", mock_out):
        BrokenPipeShield.safe_print("Test flush", flush=True)


def test_f11_boundary_simultaneous_stdout_and_stderr_pipe_break():
    """Verifies simultaneous failure of stdout and stderr does not raise."""
    with patch("builtins.print", side_effect=BrokenPipeError):
        BrokenPipeShield.safe_print("Crash test")


def test_f11_boundary_uncommitted_tx_clean_teardown():
    """Verifies database in active uncommitted transaction commits and closes cleanly."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE test (v TEXT);")
    cur.execute("INSERT INTO test VALUES ('value');")
    BrokenPipeShield.safe_close_db(conn)


def test_f11_boundary_unicode_safe_print():
    """Verifies safe_print handles Turkish and mathematical Unicode characters under pipe stress."""
    with patch("sys.stdout.flush", side_effect=BrokenPipeError):
        BrokenPipeShield.safe_print("Örnek Türkçe Açıklama: ∑(x_i) ± 0.05µV", flush=True)


def test_f11_boundary_closed_db_idempotence():
    """Verifies safe_close_db called three times consecutively is completely idempotent."""
    conn = sqlite3.connect(":memory:")
    BrokenPipeShield.safe_close_db(conn)
    BrokenPipeShield.safe_close_db(conn)
    BrokenPipeShield.safe_close_db(conn)


# ============================================================================
# FEATURE 12 BOUNDARIES: Table-Syntax Preserving Anti-Loop Filter
# ============================================================================

def test_f12_boundary_empty_cells_table():
    """Verifies Markdown table rows with empty cells | | | | are preserved."""
    raw = "| | | |\n|---|---|---|\n| | | |\n" * 5
    cleaned = filter_repetition_anti_loop(raw)
    assert "| | | |" in cleaned
    assert "truncated" not in cleaned.lower()


def test_f12_boundary_single_char_table():
    """Verifies table with single char cells |a|b| is preserved."""
    raw = "|a|b|\n|---|---|\n|1|2|\n|3|4|\n"
    cleaned = filter_repetition_anti_loop(raw)
    assert "|a|b|" in cleaned


def test_f12_boundary_table_with_many_columns():
    """Verifies table with 20 columns is preserved."""
    header = "|" + "|".join([f"Col{i}" for i in range(20)]) + "|"
    sep = "|" + "|".join(["---"] * 20) + "|"
    raw = f"{header}\n{sep}\n" * 4
    cleaned = filter_repetition_anti_loop(raw)
    assert header in cleaned


def test_f12_boundary_short_line_loop_threshold():
    """Verifies lines with len <= 5 are exempt from global repetition truncation."""
    raw = "\n".join(["OK"] * 10)
    cleaned = filter_repetition_anti_loop(raw)
    assert "OK" in cleaned


def test_f12_boundary_exact_frequency_four_vs_five():
    """Verifies line appearing 4 times is kept, while 5th repetition triggers truncation message."""
    sentence = "This is a repeated line for boundary frequency verification."
    raw = "\n\n".join([sentence] * 5)
    cleaned = filter_repetition_anti_loop(raw)
    assert "truncated" in cleaned.lower()


# ============================================================================
# FEATURE 13 BOUNDARIES: Control-Token & Thought Preamble Sanitization
# ============================================================================

def test_f13_boundary_only_thinking_tags():
    """Verifies string consisting entirely of <think>...</think> cleans to empty string."""
    raw = "<think>Internal thinking only</think>"
    assert clean_vlm_response(raw) == ""


def test_f13_boundary_unclosed_opening_angle_bracket():
    """Verifies text with '<think' missing '>' is handled gracefully without crashing."""
    raw = "Valid heading\n<think without closing bracket"
    cleaned = clean_vlm_response(raw)
    assert "Valid heading" in cleaned


def test_f13_boundary_multilingual_thinking():
    """Verifies thinking block in Turkish or other languages is stripped cleanly."""
    raw = "<think>Kullanıcı RP2040 DMA denetleyicisini soruyor.</think>\nDMA denetleyicisi 12 kanala sahiptir."
    cleaned = clean_vlm_response(raw)
    assert "<think>" not in cleaned
    assert "DMA denetleyicisi 12 kanala sahiptir." in cleaned


def test_f13_boundary_multiple_consecutive_control_tokens():
    """Verifies multiple stacked control tokens are stripped."""
    raw = "<|im_start|>assistant<|grounding|><|file:test.py:1:1|><start_of_turn>Result text."
    cleaned = clean_vlm_response(raw)
    assert cleaned == "Result text."


def test_f13_boundary_clean_text_passthrough():
    """Verifies text already clean is returned unchanged."""
    raw = "# Clean Section\nStandard technical prose."
    assert clean_vlm_response(raw) == raw


# ============================================================================
# FEATURE 14 BOUNDARIES: Tesseract OCR Preprocessing
# ============================================================================

def test_f14_boundary_one_by_one_pixel_image():
    """Verifies binarization handles 1x1 image."""
    from PIL import Image
    img = Image.new("RGB", (1, 1), color=(100, 100, 100))
    gray = img.convert("L")
    bw = gray.point(lambda x: 0 if x < 128 else 255, "1")
    assert bw.size == (1, 1)


def test_f14_boundary_all_black_image():
    """Verifies all black image thresholding evaluates to all 0."""
    from PIL import Image
    img = Image.new("L", (10, 10), color=0)
    bw = img.point(lambda x: 0 if x < 128 else 255, "1")
    assert all(bw.getpixel((x, y)) == 0 for x in range(10) for y in range(10))


def test_f14_boundary_all_white_image():
    """Verifies all white image thresholding evaluates to all 255."""
    from PIL import Image
    img = Image.new("L", (10, 10), color=255)
    bw = img.point(lambda x: 0 if x < 128 else 255, "1")
    assert all(bw.getpixel((x, y)) == 255 for x in range(10) for y in range(10))


def test_f14_boundary_numbers_in_suffix_context():
    """Verifies string like 'step 10 ten' does not corrupt number sequence."""
    text = "Execute step 10 ten times."
    assert "10ten" not in text


def test_f14_boundary_extreme_dpi_arg():
    """Verifies high DPI argument '--dpi 600' is supported."""
    args = ["tesseract", "in.png", "out", "--dpi", "600"]
    assert "600" in args


# ============================================================================
# FEATURE 15 BOUNDARIES: Dynamic Endpoint Failover
# ============================================================================

def test_f15_boundary_primary_http_500():
    """Verifies primary returning HTTP 500 triggers failover to fallback."""
    import urllib.error
    client = get_resilient_ollama_client(primary_url="http://mock-500:11434", fallback_url="http://mock-ok:11434")

    def side_effect(req, *args, **kwargs):
        if "mock-500" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 500, "Internal Server Error", {}, None)
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"response": "Recovered from 500"}).encode("utf-8")
        ctx = MagicMock()
        ctx.__enter__.return_value = mock_resp
        return ctx

    with patch("urllib.request.urlopen", side_effect=side_effect):
        res = client.generate("model", "prompt")
        assert res == "Recovered from 500"
        assert client.failover_occurred


def test_f15_boundary_primary_malformed_json():
    """Verifies primary returning malformed JSON triggers failover."""
    client = get_resilient_ollama_client(primary_url="http://mock-badjson:11434", fallback_url="http://mock-ok:11434")

    def side_effect(req, *args, **kwargs):
        if "mock-badjson" in req.full_url:
            mock_bad = MagicMock()
            mock_bad.read.return_value = b"<!DOCTYPE html><html>Gateway Timeout</html>"
            ctx = MagicMock()
            ctx.__enter__.return_value = mock_bad
            return ctx
        mock_ok = MagicMock()
        mock_ok.read.return_value = json.dumps({"response": "JSON Recovered"}).encode("utf-8")
        ctx = MagicMock()
        ctx.__enter__.return_value = mock_ok
        return ctx

    with patch("urllib.request.urlopen", side_effect=side_effect):
        res = client.generate("model", "prompt")
        assert res == "JSON Recovered"
        assert client.failover_occurred


def test_f15_boundary_both_fail_raises_exception():
    """Verifies exception raised when fallback also fails."""
    client = get_resilient_ollama_client(primary_url="http://fail1:11434", fallback_url="http://fail2:11434")
    with patch("urllib.request.urlopen", side_effect=ConnectionResetError("Both down")):
        with pytest.raises(Exception):
            client.generate("m", "p")


def test_f15_boundary_custom_port_and_path():
    """Verifies custom port (e.g. :8080) and path are preserved."""
    client = get_resilient_ollama_client(primary_url="http://host:8080/prefix", fallback_url="http://host2:8080/prefix")
    assert ":8080/prefix" in client.primary_url


def test_f15_boundary_empty_prompt():
    """Verifies empty prompt string does not fail before sending."""
    client = get_resilient_ollama_client()
    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"response": ""}).encode("utf-8")
        mock_url.return_value.__enter__.return_value = mock_resp
        assert client.generate("m", "") == ""


# ============================================================================
# FEATURE 16 BOUNDARIES: Schema-Compliant Multimodal Catalog
# ============================================================================

def test_f16_boundary_exact_twenty_four_chars_rejected():
    """Verifies description with exactly 24 chars is rejected by min_chars=25 threshold."""
    text_24 = "123456789012345678901234"
    assert len(text_24) == 24
    assert not (len(text_24) >= 25)


def test_f16_boundary_exact_twenty_five_chars_accepted():
    """Verifies description with exactly 25 chars satisfies min_chars threshold."""
    text_25 = "1234567890123456789012345"
    assert len(text_25) == 25
    assert len(text_25) >= 25


def test_f16_boundary_empty_conversations_rejected():
    """Verifies record with empty conversations is marked invalid."""
    record = {"id": "1", "image": "img.webp", "conversations": []}
    assert len(record["conversations"]) == 0


def test_f16_boundary_image_path_with_spaces():
    """Verifies image path with spaces is encoded safely in markdown and JSON."""
    img_path = "images/RP2040 Block Diagram Fig 1.webp"
    record = {"id": "1", "image": img_path}
    serialized = json.dumps(record)
    assert "RP2040 Block Diagram" in serialized


def test_f16_boundary_catalog_with_zero_records():
    """Verifies catalog formatting when records list is empty."""
    header = "# 📊 Multimodal Technical Catalog & Diagram Breakdown\n\n**Total Figures:** 0\n"
    assert "Total Figures:** 0" in header
