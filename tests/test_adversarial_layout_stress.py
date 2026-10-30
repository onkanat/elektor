import math
import tempfile
import fitz
import pytest
from pathlib import Path

from pipeline.extractor import extract_page_layout, PageLayoutResult
from pipeline.layout_analyzer import DocumentLayoutAnalyzer, FigureCrop

RP2040_PATH = "/home/hakan/PDF/raspberyy/RP-008371-DS-1-rp2040-datasheet.pdf"


@pytest.fixture
def tmp_crop_dir(tmp_path):
    crop_dir = tmp_path / "adversarial_crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    return str(crop_dir)


@pytest.fixture
def analyzer(tmp_crop_dir):
    return DocumentLayoutAnalyzer(output_img_dir=tmp_crop_dir)


# ============================================================================
# 1. Zero-Dimension Vectors, Hairlines & Aspect Ratio Boundaries
# ============================================================================

def test_adversarial_zero_dimension_lines_handled_safely(analyzer):
    """Stress test: 50 zero-dimension points (x0==x1, y0==y1) must not crash or produce micro-crops."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    for i in range(50):
        # Zero-length line
        page.draw_line((200 + i * 2, 300), (200 + i * 2, 300), color=(0, 0, 0), width=1)

    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()
    assert len(crops) == 0, f"Zero-dimension lines must not produce false crops, got {len(crops)}"


def test_adversarial_hairline_extreme_aspect_ratio_rejection(analyzer):
    """Stress test: Hairline borders (0.01pt) with extreme aspect ratios (>20 or <0.05) must be rejected."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Extremely wide hairline rule (width 550, height 0.05 -> aspect 11000)
    page.draw_rect(fitz.Rect(25, 200, 575, 200.05), color=(0, 0, 0), width=0.01)
    # Extremely tall hairline line (width 0.05, height 600 -> aspect 0.00008)
    page.draw_rect(fitz.Rect(300, 100, 300.05, 700), color=(0, 0, 0), width=0.01)

    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()
    assert len(crops) == 0, "Extreme aspect ratio hairline borders must be rejected"


# ============================================================================
# 2. Out-of-Bounds Coordinate Crash & Boundary Safety
# ============================================================================

def test_adversarial_out_of_bounds_negative_coordinates_crash(analyzer):
    """
    CRITIC CHALLENGE: Drawing paths completely outside page bounds on the negative side
    must NOT cause unhandled FzErrorArgument exceptions during pixmap saving.
    """
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Cluster of drawing paths with negative coordinates
    for i in range(25):
        page.draw_line((-300, 100 + i * 5), (-100, 100 + i * 5), color=(0, 0, 0), width=1)

    # In robust code, this should either return [] without error or safely clamp
    try:
        crops = analyzer.analyze_page(page, table_masks=[])
        # If it survived, verify no invalid crops
        for c in crops:
            assert c.bbox[0] >= 0 and c.bbox[1] >= 0
    except Exception as exc:
        pytest.fail(f"Out-of-bounds negative coordinates caused unhandled crash: {type(exc).__name__}: {exc}")
    finally:
        doc.close()


def test_adversarial_out_of_bounds_positive_coordinates_crash(analyzer):
    """
    CRITIC CHALLENGE: Drawing paths completely outside page bounds on the positive side
    must NOT cause unhandled FzErrorArgument exceptions during pixmap saving.
    """
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    for i in range(25):
        page.draw_line((1200, 100 + i * 5), (1500, 100 + i * 5), color=(0, 0, 0), width=1)

    try:
        crops = analyzer.analyze_page(page, table_masks=[])
        for c in crops:
            assert c.bbox[2] <= page.rect.width and c.bbox[3] <= page.rect.height
    except Exception as exc:
        pytest.fail(f"Out-of-bounds positive coordinates caused unhandled crash: {type(exc).__name__}: {exc}")
    finally:
        doc.close()


# ============================================================================
# 3. Full-Page Decorative Perimeter Frames
# ============================================================================

def test_adversarial_four_line_perimeter_frame_false_positive(analyzer):
    """
    CRITIC CHALLENGE: 4 perimeter border lines around page margins with body text inside
    must NOT be merged into a giant false crop enclosing the text.
    """
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # 4-line perimeter frame just inside margins
    page.draw_line((20, 60), (580, 60), color=(0, 0, 0), width=1)
    page.draw_line((20, 740), (580, 740), color=(0, 0, 0), width=1)
    page.draw_line((20, 60), (20, 740), color=(0, 0, 0), width=1)
    page.draw_line((580, 60), (580, 740), color=(0, 0, 0), width=1)

    # Insert body text inside the frame
    for i in range(12):
        page.insert_text((50, 120 + i * 20), f"Regular documentation paragraph line {i} inside frame.", fontsize=11)

    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    # The 4-line decorative frame must NOT produce a false-positive figure crop of the page
    assert len(crops) == 0, (
        f"4-line decorative frame falsely extracted as figure crop: "
        f"{[(c.crop_id, c.bbox, c.crop_type) for c in crops]}"
    )


# ============================================================================
# 4. Shaded Code Box vs Diagram Classification
# ============================================================================

def test_adversarial_shaded_code_box_with_dividers_not_cropped(analyzer):
    """
    CRITIC CHALLENGE: Shaded code box with outer border and divider lines (4-19 paths, >10 words)
    must NOT be classified as a visual drawing/diagram crop.
    """
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Code box with 5 paths: rect + 3 horizontal rules + 1 line-number separator
    page.draw_rect(fitz.Rect(50, 100, 500, 400), color=(0.8, 0.8, 0.8), width=1)
    page.draw_line((50, 130), (500, 130), color=(0.8, 0.8, 0.8), width=1)
    page.draw_line((50, 160), (500, 160), color=(0.8, 0.8, 0.8), width=1)
    page.draw_line((50, 190), (500, 190), color=(0.8, 0.8, 0.8), width=1)
    page.draw_line((90, 130), (90, 400), color=(0.8, 0.8, 0.8), width=1)

    # Monospace code text
    for i in range(15):
        page.insert_text((100, 150 + i * 16), f"uint32_t val_{i} = dma_channel_get_irq({i});", fontsize=10)

    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 0, (
        f"Shaded code box with internal dividers falsely cropped as visual figure: "
        f"{[(c.crop_id, c.bbox, c.crop_type) for c in crops]}"
    )


# ============================================================================
# 5. Multi-Column Dead-Zone Line Dropping in Extractor
# ============================================================================

def test_adversarial_column_heading_causes_deadzone_line_drop():
    """
    CRITIC CHALLENGE: A large font heading (size >= 13) within Column 1 must NOT cause
    lines in Column 2 that overlap vertically to be dropped from extract_page_layout.
    """
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)

    # Column 1
    page.insert_text((50, 100), "Col1 Line 1", fontsize=10)
    page.insert_text((50, 120), "Col1 Line 2", fontsize=10)
    page.insert_text((50, 150), "Col1 Section Heading", fontsize=14)
    page.insert_text((50, 180), "Col1 Line 3", fontsize=10)

    # Column 2
    page.insert_text((350, 100), "Col2 Line 1", fontsize=10)
    page.insert_text((350, 120), "Col2 Line 2", fontsize=10)
    # Line in Column 2 positioned at y=153 (vertically parallel to the Column 1 heading)
    page.insert_text((350, 153), "Col2 Critical Overlapping Line", fontsize=10)
    page.insert_text((350, 180), "Col2 Line 3", fontsize=10)

    res = extract_page_layout(page)
    doc.close()

    assert "Col2 Critical Overlapping Line" in res.text, (
        f"Critical line was silently dropped by extractor's spanning band dead-zone! Extracted text:\n{res.text}"
    )


# ============================================================================
# 6. Page Rotation Stress
# ============================================================================

@pytest.mark.parametrize("rot", [90, 180, 270])
def test_adversarial_page_rotation_geometry_and_extractor(rot, analyzer):
    """Stress test: 90, 180, 270 degree rotated pages must extract text and figures without crashing."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.set_rotation(rot)
    page.insert_text((100, 100), f"Rotated Content rot={rot}", fontsize=12)
    for i in range(25):
        page.draw_line((150, 200 + i * 5), (350, 200 + i * 5), color=(0, 0, 0), width=1)

    res = extract_page_layout(page)
    assert f"Rotated Content rot={rot}" in res.text

    crops = analyzer.analyze_page(page, table_masks=[])
    assert len(crops) == 1
    assert crops[0].crop_type == "diagram"
    doc.close()


# ============================================================================
# 7. Real RP2040 Datasheet Table Corner Shards Elimination
# ============================================================================

def test_adversarial_rp2040_datasheet_p119_and_register_tables_100_percent_clean(analyzer):
    """
    CRITIC CHALLENGE: Comprehensive verification on RP2040 datasheet.
    - Page 119 (Table 146 SNIFF_CTRL) must produce 0 crops (eliminates p119_draw_119_4.png).
    - Pages 100-125 (all register tables) must produce 0 false table shards.
    """
    doc = fitz.open(RP2040_PATH)

    # 1. Page 119 specific verification
    p119 = doc[118]
    res119 = extract_page_layout(p119)
    crops119 = analyzer.analyze_page(p119, table_masks=res119.table_masks)
    assert len(crops119) == 0, f"Page 119 produced {len(crops119)} false crops; must be 0!"

    # 2. Pages 100-125 scan
    for p_idx in range(99, 125):
        page = doc[p_idx]
        res = extract_page_layout(page)
        crops = analyzer.analyze_page(page, table_masks=res.table_masks)
        # Page 123 has a genuine diagram ("Figure 14. Flash")
        if p_idx == 122:
            assert len(crops) == 1, f"Expected genuine Figure 14 on page 123, got {len(crops)}"
            assert "Figure 14" in crops[0].caption or "Flash" in crops[0].caption
        else:
            assert len(crops) == 0, (
                f"Page {p_idx+1} produced {len(crops)} false positive table crops: "
                f"{[(c.crop_id, c.bbox) for c in crops]}"
            )
    doc.close()
