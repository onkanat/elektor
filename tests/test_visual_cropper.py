import os
import fitz
import pytest
from pathlib import Path
from pipeline.layout_analyzer import DocumentLayoutAnalyzer, FigureCrop
from pipeline.extractor import extract_page_layout

RP2040_PATH = "/home/hakan/PDF/raspberyy/RP-008371-DS-1-rp2040-datasheet.pdf"


@pytest.fixture
def tmp_crop_dir(tmp_path):
    crop_dir = tmp_path / "test_crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    return str(crop_dir)


@pytest.fixture
def analyzer(tmp_crop_dir):
    return DocumentLayoutAnalyzer(output_img_dir=tmp_crop_dir)


# ============================================================================
# FEATURE 6: Table Negative Masking
# ============================================================================

def test_feature6_table_mask_eliminates_table_cell_grid(analyzer):
    """Verifies table negative masks exclude all drawing strokes within table boundaries."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Simulate table grid lines inside (100, 200, 500, 450)
    for i in range(15):
        page.draw_line((100, 200 + i * 15), (500, 200 + i * 15), color=(0, 0, 0), width=1)
    for j in range(5):
        page.draw_line((100 + j * 100, 200), (100 + j * 100, 410), color=(0, 0, 0), width=1)

    table_masks = [(100.0, 200.0, 500.0, 450.0)]
    crops = analyzer.analyze_page(page, table_masks=table_masks)
    doc.close()

    assert len(crops) == 0, f"Expected 0 crops from masked table grid, got {len(crops)}"


def test_feature6_non_table_diagram_outside_mask_preserved(analyzer):
    """Verifies that legitimate diagrams outside table masks are preserved."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Table grid at top
    for i in range(10):
        page.draw_line((50, 100 + i * 15), (450, 100 + i * 15), color=(0, 0, 0), width=1)
    # Diagram at bottom (25 lines)
    for i in range(25):
        page.draw_line((100, 400 + i * 8), (400, 400 + i * 8), color=(0, 0, 0), width=1)

    table_masks = [(50.0, 100.0, 450.0, 250.0)]
    crops = analyzer.analyze_page(page, table_masks=table_masks)
    doc.close()

    assert len(crops) == 1
    assert crops[0].bbox[1] >= 250.0, "Diagram crop must be below the table mask"
    assert crops[0].crop_type == "diagram"


def test_feature6_table_mask_touching_and_inverted_coords(analyzer):
    """Verifies edge-touching lines and inverted coordinate masks are safely handled."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Line touching mask at y=200
    page.draw_line((100, 200), (300, 200), color=(0, 0, 0), width=1)
    touching_mask = [(100.0, 200.0, 300.0, 400.0)]
    crops = analyzer.analyze_page(page, table_masks=touching_mask)
    assert len(crops) == 0

    # Inverted coordinates mask (x1 < x0, y1 < y0)
    for i in range(25):
        page.draw_line((100, 200 + i * 5), (300, 200 + i * 5), color=(0, 0, 0), width=1)
    inverted_mask = [(400.0, 400.0, 100.0, 100.0)]
    crops_inv = analyzer.analyze_page(page, table_masks=inverted_mask)
    doc.close()
    assert len(crops_inv) == 0


def test_feature6_real_rp2040_page119_zero_table_shards(analyzer):
    """Historical verification: Page 119 (Table 146 SNIFF_CTRL) yields 0 crops."""
    doc = fitz.open(RP2040_PATH)
    p119 = doc[118]
    res119 = extract_page_layout(p119)
    assert len(res119.tables) >= 1
    assert len(res119.table_masks) >= 1

    crops = analyzer.analyze_page(p119, table_masks=res119.table_masks)
    doc.close()

    assert len(crops) == 0, f"Table 146 produced {len(crops)} false crops; must be 0"


# ============================================================================
# FEATURE 7: Drawing Path Clustering & Code Box Rejection
# ============================================================================

def test_feature7_complex_diagram_path_clustering(analyzer):
    """Verifies complex drawing paths (>=20) cluster into a single 'diagram' crop."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    for i in range(25):
        page.draw_line((100 + i * 6, 200), (100 + i * 6, 350), color=(0, 0, 0), width=1)

    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 1
    assert crops[0].crop_type == "diagram"
    assert isinstance(crops[0], FigureCrop)


def test_feature7_shaded_code_box_rejection(analyzer):
    """Verifies shaded monospace code listing (<4 drawing paths, >10 words) is rejected."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Draw gray shaded box
    page.draw_rect(fitz.Rect(50, 100, 500, 400), color=(0.9, 0.9, 0.9), fill=(0.95, 0.95, 0.95))
    # Insert 15 lines of C code text
    for i in range(15):
        page.insert_text((70, 120 + i * 16), f"uint32_t channel_cfg_{i} = DMA_CH_EN;", fontsize=9)

    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 0, "Shaded code block must not be cropped as a visual diagram"


def test_feature7_drawing_clustering_across_gaps(analyzer):
    """Verifies subcomponents separated by small gaps (<30pt) are merged."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Block A
    for i in range(12):
        page.draw_line((100, 200 + i * 10), (180, 200 + i * 10), color=(0, 0, 0), width=1)
    # Block B separated by 20pt gap
    for i in range(12):
        page.draw_line((200, 200 + i * 10), (280, 200 + i * 10), color=(0, 0, 0), width=1)

    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 1
    assert crops[0].bbox[2] >= 280.0


def test_feature7_isolated_divider_lines_ignored(analyzer):
    """Verifies single isolated horizontal or vertical divider lines do not trigger crops."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.draw_line((50, 300), (550, 300), color=(0, 0, 0), width=1)

    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 0


# ============================================================================
# FEATURE 8: Boundary Expansion for Arrowheads & Labels
# ============================================================================

def test_feature8_boundary_expansion_absorbs_pin_labels(analyzer):
    """Verifies bounding box expands to absorb adjacent pin/signal text labels within 15pt."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Diagram box (100, 200, 300, 400)
    for i in range(20):
        page.draw_line((100, 200 + i * 10), (300, 200 + i * 10), color=(0, 0, 0), width=1)
    # Pin label at x=310 (distance 10pt <= 15pt)
    page.insert_text((310, 250), "TX_DATA_READY_PIN", fontsize=10)

    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 1
    assert crops[0].bbox[2] >= 380.0, "Crop bbox must expand to encompass TX_DATA_READY_PIN"


def test_feature8_boundary_expansion_includes_arrowheads(analyzer):
    """Verifies outer connector arrows extending past the main diagram box are included."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    for i in range(20):
        page.draw_line((100, 200 + i * 10), (250, 200 + i * 10), color=(0, 0, 0), width=1)
    # Connector arrow tip extending to x=280
    page.draw_line((250, 250), (280, 250), color=(0, 0, 0), width=2)
    page.draw_line((275, 245), (280, 250), color=(0, 0, 0), width=1.5)
    page.draw_line((275, 255), (280, 250), color=(0, 0, 0), width=1.5)

    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 1
    assert crops[0].bbox[2] >= 280.0


def test_feature8_safety_padding_and_page_clamping(analyzer):
    """Verifies safety padding surrounds crops and coordinates are clamped to page limits."""
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)
    # Diagram at top-left edge
    for i in range(20):
        page.draw_line((3, 3 + i * 5), (100, 3 + i * 5), color=(0, 0, 0), width=1)

    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 1
    b = crops[0].bbox
    assert b[0] >= 0.0 and b[1] >= 0.0
    assert b[2] <= 500.0 and b[3] <= 500.0


# ============================================================================
# FEATURE 9: Aspect Ratio, Dimension & Density Filters
# ============================================================================

def test_feature9_wide_timing_diagram_retained(analyzer):
    """Verifies wide timing diagrams (height < 80pt) are retained (no rigid h < 80 drop)."""
    doc = fitz.open()
    page = doc.new_page(width=700, height=800)
    # Width 350, Height 45 -> Area 15750, Aspect ~7.77
    for i in range(25):
        page.draw_line((100 + i * 14, 200), (100 + i * 14, 245), color=(0, 0, 0), width=1)

    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 1
    assert crops[0].crop_type == "diagram"


def test_feature9_thin_strips_and_micro_crops_rejected(analyzer):
    """Verifies thin horizontal/vertical borders (aspect > 20 or < 0.05) and micro-crops (area < 2000) are rejected."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Thin horizontal line (aspect = 500 / 2 = 250 > 20)
    page.draw_rect(fitz.Rect(50, 100, 550, 102), color=(0, 0, 0), fill=(0, 0, 0))
    # Microscopic 20x20 box (area = 400 < 2000)
    for i in range(25):
        page.draw_line((100, 300 + i), (120, 300 + i), color=(0, 0, 0), width=1)

    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 0


def test_feature9_full_page_border_rejected(analyzer):
    """Verifies decorative full-page border box (>85% page area) is ignored."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.draw_rect(fitz.Rect(5, 5, 595, 795), color=(0, 0, 0), width=1)

    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 0


# ============================================================================
# FEATURE 10: Non-Overlapping Figure Deduplication
# ============================================================================

def test_feature10_deduplicate_identical_and_nested_crops(analyzer):
    """Verifies identical duplicates and nested inner boxes are suppressed."""
    outer = FigureCrop("p1_f1", 1, (100.0, 100.0, 400.0, 400.0), "out.png", "Main Diagram", "diagram")
    inner = FigureCrop("p1_f2", 1, (120.0, 120.0, 380.0, 380.0), "in.png", "Sub Component", "diagram")
    duplicate = FigureCrop("p1_f3", 1, (100.0, 100.0, 400.0, 400.0), "dup.png", "Duplicate", "diagram")

    deduped = analyzer._deduplicate_crops([outer, inner, duplicate])
    assert len(deduped) == 1
    assert deduped[0].crop_id == "p1_f1"


def test_feature10_distinct_non_overlapping_both_kept(analyzer):
    """Verifies separate figures on the same page are both preserved."""
    c1 = FigureCrop("p1_f1", 1, (50.0, 50.0, 250.0, 250.0), "top.png", "Top Diagram", "diagram")
    c2 = FigureCrop("p1_f2", 1, (50.0, 400.0, 250.0, 600.0), "bottom.png", "Bottom Diagram", "diagram")

    deduped = analyzer._deduplicate_crops([c1, c2])
    assert len(deduped) == 2


# ============================================================================
# REAL BENCHMARK VERIFICATION: RP2040 Datasheet
# ============================================================================

def test_real_rp2040_block_diagrams_pages_10_to_15(analyzer):
    """Benchmark: Extract block diagrams from real RP2040 datasheet pages 11, 12, 15."""
    doc = fitz.open(RP2040_PATH)
    pages_to_test = [10, 11, 14]  # 0-indexed: pages 11, 12, 15
    extracted = []

    for p_idx in pages_to_test:
        page = doc[p_idx]
        res = extract_page_layout(page)
        crops = analyzer.analyze_page(page, table_masks=res.table_masks)
        for c in crops:
            extracted.append(c)
    doc.close()

    assert len(extracted) >= 3, f"Expected at least 3 block diagrams, found {len(extracted)}"
    for crop in extracted:
        assert crop.crop_type == "diagram"
        x0, y0, x1, y1 = crop.bbox
        width = x1 - x0
        height = y1 - y0
        assert width >= 200, f"Width {width} too small"
        assert height >= 100, f"Height {height} too small"
        assert os.path.exists(crop.image_path)
        assert os.path.getsize(crop.image_path) > 1024


def test_real_rp2040_register_table_pages_zero_false_crops(analyzer):
    """Benchmark: Verify register table pages 100-125 yield zero false figure crops."""
    doc = fitz.open(RP2040_PATH)
    sample_pages = [99, 100, 111, 112, 118, 119]  # pages 100, 101, 112, 113, 119, 120

    for p_idx in sample_pages:
        page = doc[p_idx]
        res = extract_page_layout(page)
        crops = analyzer.analyze_page(page, table_masks=res.table_masks)
        assert len(crops) == 0, f"Page {p_idx+1} produced {len(crops)} false figure crops"
    doc.close()


def test_interface_contract_and_dict_compatibility(tmp_crop_dir):
    """Verifies FigureCrop satisfies PROJECT.md:100-106 contract and dict compatibility."""
    crop = FigureCrop(
        crop_id="p15_fig_1",
        page_number=15,
        bbox=(100.0, 200.0, 450.0, 500.0),
        image_path=f"{tmp_crop_dir}/p15_fig_1.png",
        caption="Figure 1. Bus Fabric",
        crop_type="diagram"
    )

    # Contract attributes
    assert crop.crop_id == "p15_fig_1"
    assert crop.page_number == 15
    assert crop.bbox == (100.0, 200.0, 450.0, 500.0)
    assert crop.image_path.endswith(".png")
    assert crop.caption == "Figure 1. Bus Fabric"
    assert crop.crop_type == "diagram"

    # Compatibility properties & dict subscription for extractor.py
    assert crop.id == "p15_fig_1"
    assert crop.type == "diagram"
    assert crop.context == "Figure 1. Bus Fabric"
    assert crop["id"] == "p15_fig_1"
    assert crop["type"] == "diagram"
    assert crop["bbox"] == (100.0, 200.0, 450.0, 500.0)
    assert crop.get("context") == "Figure 1. Bus Fabric"
    assert crop.get("image_path") == f"{tmp_crop_dir}/p15_fig_1.png"
    assert crop.get("nonexistent", "fallback") == "fallback"
