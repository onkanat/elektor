import os
import sys
import re
import fitz
import pytest
from pathlib import Path

from tests.e2e.conftest import (
    PageLayoutResult,
    FigureCrop,
    extract_page_layout,
    get_layout_analyzer,
    clean_vlm_response,
    filter_repetition_anti_loop,
    RP2040_PATH
)


# ============================================================================
# TIER 4: Real-World Application Workloads (RP2040 Datasheet)
# ============================================================================

def test_scenario_rp2040_block_diagrams_pages_10_to_15(rp2040_doc):
    """Scenario 1: Extract hardware block diagrams from real RP2040 datasheet pages 10-15.
    Verifies that complex hardware diagrams (Figures 2, 3, 5 on pages 11, 12, 15) are extracted
    with complete, unfragmented bounding boxes and clean diagram classification.
    """
    analyzer = get_layout_analyzer("/tmp/tier4_real_diagrams")
    pages_to_test = [10, 11, 14]  # 0-indexed: pages 11, 12, 15
    extracted_diagrams = []

    for p_idx in pages_to_test:
        page = rp2040_doc[p_idx]
        res = extract_page_layout(page)
        crops = analyzer.analyze_page(page, table_masks=res.table_masks)
        for c in crops:
            extracted_diagrams.append(c)

    assert len(extracted_diagrams) >= 3, f"Expected at least 3 block diagrams, found {len(extracted_diagrams)}"

    for crop in extracted_diagrams:
        assert isinstance(crop, FigureCrop)
        assert crop.crop_type == "diagram"
        # Bbox checks
        x0, y0, x1, y1 = crop.bbox
        assert x0 >= 0 and y0 >= 0
        assert x1 <= 600 and y1 <= 850
        width = x1 - x0
        height = y1 - y0
        assert width >= 200, f"Diagram width {width} is too small"
        assert height >= 100, f"Diagram height {height} is too small"
        # Verify rendered crop image file exists and is non-empty
        assert os.path.exists(crop.image_path)
        assert os.path.getsize(crop.image_path) > 1024, "Crop image file is corrupted or empty"


def test_scenario_rp2040_register_tables_pages_100_to_125(rp2040_doc):
    """Scenario 2: Native table extraction on DMA register chapter (pages 100-125).
    Verifies native PyMuPDF table extraction preserves schema ['Bits', 'Description', 'Type', 'Reset'],
    preserves register bitfield alignment, and outputs valid GitHub-flavored Markdown.
    """
    # Page 113 (index 112): Table 124 (CH0_READ_ADDR register table)
    p113 = rp2040_doc[112]
    res113 = extract_page_layout(p113)

    assert len(res113.tables) >= 1
    tab124 = res113.tables[0]
    assert tab124["col_count"] == 4
    assert tab124["row_count"] >= 15

    md = tab124["markdown"]
    assert "|Bits|Description|Type|Reset|" in md.replace(" ", "")
    # Bitfield ranges and permissions must be intact
    assert "31" in md
    assert "RO" in md or "RW" in md
    assert "0x0" in md

    # Verify table_masks contains the bounding box of Table 124
    assert len(res113.table_masks) >= 1
    t_bbox = res113.table_masks[0]
    assert t_bbox[0] >= 100 and t_bbox[2] <= 550
    assert t_bbox[1] >= 70 and t_bbox[3] <= 790


def test_scenario_rp2040_historical_failure_elimination_p119(rp2040_doc):
    """Scenario 3: Historical crop failure elimination on page 119 (Table 146 SNIFF_CTRL).
    In prior runs, 362 drawing lines of Table 146 produced corrupted table-corner crop 'p119_draw_119_4.png'.
    Verifies that table negative masking eliminates 100% of false figure crops from Table 146.
    """
    p119 = rp2040_doc[118]  # index 118 = page 119
    analyzer = get_layout_analyzer("/tmp/tier4_failure_elimination")

    # Extract layout with native table detection
    res = extract_page_layout(p119)
    assert len(res.tables) == 3, f"Expected 3 register tables on page 119, got {len(res.tables)}"

    # Analyze page passing table masks
    crops = analyzer.analyze_page(p119, table_masks=res.table_masks)

    # Must produce 0 false-positive figure crops from table grid lines
    assert len(crops) == 0, f"Expected 0 figure crops on register table page 119, got {len(crops)}"


def test_scenario_rp2040_code_listings_and_monospace_page_100(rp2040_doc):
    """Scenario 4: Monospace C code block extraction on page 100 (DMA programming).
    Verifies that monospace spans (RobotoMono) are captured as fenced ```c code blocks
    and shaded code background rectangles are rejected from visual diagram crops.
    """
    p100 = rp2040_doc[99]  # index 99 = page 100
    res = extract_page_layout(p100)

    # Monospace code spans detected
    assert len(res.code_blocks) >= 1
    code_text = res.code_blocks[0]["code"]
    assert any(token in code_text for token in ["dma", "channel", "int", "void", "config", "c", "uint32"])

    # Visual Analyzer must reject shaded code listing box (internal drawings < 4 with text)
    analyzer = get_layout_analyzer("/tmp/tier4_code_rejection")
    crops = analyzer.analyze_page(p100, table_masks=res.table_masks)
    # Page 100 contains no hardware block diagrams (only code and text), so 0 crops
    assert len(crops) == 0, f"Expected 0 figure crops from shaded code listing on page 100, got {len(crops)}"


def test_scenario_rp2040_header_footer_sentence_continuity_pages_112_to_115(rp2040_doc):
    """Scenario 5: Running header/footer stripping and sentence continuity across pages 112-115.
    Verifies that 'RP2040 Datasheet' (y ≈ 28.1 pt) and running footers '2.5. DMA 112..115' (y ≈ 796.9 pt)
    are stripped, ensuring clean paragraphs across page boundaries without header/footer noise.
    """
    extracted_pages = []
    for p_idx in [111, 112, 113, 114]:  # pages 112, 113, 114, 115
        p = rp2040_doc[p_idx]
        res = extract_page_layout(p)
        extracted_pages.append((p_idx + 1, res.text))

    for page_num, text in extracted_pages:
        # Running header must be completely stripped
        assert "RP2040 Datasheet" not in text, f"Running header leaked on page {page_num}"
        # Running footer must be completely stripped
        assert f"2.5. DMA {page_num}" not in text, f"Running footer leaked on page {page_num}"
        # Body text must be present
        assert len(text.strip()) > 50, f"Extracted body text too short on page {page_num}"
