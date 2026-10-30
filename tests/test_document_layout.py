import os
import re
import tempfile
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import fitz

from pipeline.extractor import (
    PageLayoutResult,
    extract_page_layout,
    stitch_page_texts,
    is_mono_font,
    is_running_header,
    is_running_footer,
    ArchiveExtractor,
)

BENCHMARK_RP2040_PATH = "/home/hakan/PDF/raspberyy/RP-008371-DS-1-rp2040-datasheet.pdf"


# ============================================================================
# 1. Interface Contract Tests
# ============================================================================

def test_page_layout_result_dataclass_contract():
    """PageLayoutResult must contain text, tables, table_masks, and code_blocks fields."""
    res = PageLayoutResult(
        text="# Test Document\n\nSome body text.",
        tables=[{"bbox": (10.0, 20.0, 100.0, 80.0), "markdown": "|A|B|\n|---|---|\n|1|2|", "caption": "Table 1"}],
        table_masks=[(10.0, 20.0, 100.0, 80.0)],
        code_blocks=[{"bbox": (10.0, 90.0, 100.0, 120.0), "code": "int x = 0;", "language": "c"}]
    )
    assert isinstance(res.text, str)
    assert len(res.tables) == 1
    assert len(res.table_masks) == 1
    assert isinstance(res.table_masks[0], tuple)
    assert len(res.table_masks[0]) == 4
    assert len(res.code_blocks) == 1
    assert res.code_blocks[0]["language"] == "c"


def test_extract_page_layout_empty_and_mock_fallback():
    """extract_page_layout handles empty pages and mock non-fitz objects gracefully."""
    doc = fitz.open()
    empty_page = doc.new_page(width=400, height=600)
    res = extract_page_layout(empty_page)
    assert isinstance(res, PageLayoutResult)
    assert res.text == ""
    assert res.tables == []
    assert res.table_masks == []
    assert res.code_blocks == []
    doc.close()

    # Mock non-fitz page object
    mock_page = MagicMock()
    del mock_page.find_tables
    mock_page.get_text.return_value = "Fallback mock text"
    res_mock = extract_page_layout(mock_page)
    assert res_mock.text == "Fallback mock text"
    assert res_mock.tables == []
    assert res_mock.table_masks == []


# ============================================================================
# 2. Feature 1: Reading Order & Gutter Detection Tests
# ============================================================================

def test_feature1_two_column_gutter_detection_deinterleaving():
    """Verify horizontal projection detects column gutters and eliminates cross-column stream interleaving."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)

    # Insert lines in alternating stream order (Left 1, Right 1, Left 2, Right 2, Left 3, Right 3)
    # This simulates worst-case PDF stream order that causes naive extractors to interleave lines horizontally.
    page.insert_text((50, 100), "Left Column Line 1", fontsize=11)
    page.insert_text((350, 100), "Right Column Line 1", fontsize=11)
    page.insert_text((50, 130), "Left Column Line 2", fontsize=11)
    page.insert_text((350, 130), "Right Column Line 2", fontsize=11)
    page.insert_text((50, 160), "Left Column Line 3", fontsize=11)
    page.insert_text((350, 160), "Right Column Line 3", fontsize=11)

    result = extract_page_layout(page)
    doc.close()

    text = result.text
    # Left column lines must strictly precede Right column lines in reading order
    idx_l1 = text.find("Left Column Line 1")
    idx_l2 = text.find("Left Column Line 2")
    idx_l3 = text.find("Left Column Line 3")
    idx_r1 = text.find("Right Column Line 1")
    idx_r2 = text.find("Right Column Line 2")
    idx_r3 = text.find("Right Column Line 3")

    assert idx_l1 != -1 and idx_l2 != -1 and idx_l3 != -1
    assert idx_r1 != -1 and idx_r2 != -1 and idx_r3 != -1
    assert idx_l1 < idx_l2 < idx_l3 < idx_r1 < idx_r2 < idx_r3, (
        f"Cross-column interleaving detected! Positions: L1={idx_l1}, L2={idx_l2}, L3={idx_l3}, "
        f"R1={idx_r1}, R2={idx_r2}, R3={idx_r3}\nExtracted text:\n{text}"
    )


def test_feature1_multi_column_with_spanning_headers():
    """Verify that full-width spanning headers properly partition multi-column vertical bands."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)

    # Spanning title
    page.insert_text((50, 70), "Main Architecture Overview", fontsize=16)

    # Region 1 alternating columns
    page.insert_text((50, 110), "Reg1 Left Line 1", fontsize=11)
    page.insert_text((350, 110), "Reg1 Right Line 1", fontsize=11)
    page.insert_text((50, 130), "Reg1 Left Line 2", fontsize=11)
    page.insert_text((350, 130), "Reg1 Right Line 2", fontsize=11)

    # Spanning separator header
    page.insert_text((50, 180), "Subsystem Bus Interconnect Specifications", fontsize=14)

    # Region 2 alternating columns
    page.insert_text((50, 220), "Reg2 Left Line 1", fontsize=11)
    page.insert_text((350, 220), "Reg2 Right Line 1", fontsize=11)

    result = extract_page_layout(page)
    doc.close()

    text = result.text
    assert "Main Architecture Overview" in text
    assert "Subsystem Bus Interconnect Specifications" in text

    idx_title = text.find("Main Architecture Overview")
    idx_r1_l1 = text.find("Reg1 Left Line 1")
    idx_r1_l2 = text.find("Reg1 Left Line 2")
    idx_r1_r1 = text.find("Reg1 Right Line 1")
    idx_r1_r2 = text.find("Reg1 Right Line 2")
    idx_sub = text.find("Subsystem Bus Interconnect Specifications")
    idx_r2_l1 = text.find("Reg2 Left Line 1")
    idx_r2_r1 = text.find("Reg2 Right Line 1")

    assert idx_title < idx_r1_l1 < idx_r1_l2 < idx_r1_r1 < idx_r1_r2 < idx_sub < idx_r2_l1 < idx_r2_r1


# ============================================================================
# 3. Feature 2: Running Header & Footer Margin Filtering Tests
# ============================================================================

def test_feature2_synthetic_header_footer_filtering():
    """Verify that headers (y <= 50) and footers (y >= height - 50) are stripped and sentence breaks stitched."""
    doc = fitz.open()

    # Page 1
    p1 = doc.new_page(width=600, height=800)
    p1.insert_text((50, 30), "RP2040 Technical Reference Manual", fontsize=9)  # Running header
    p1.insert_text((50, 200), "The DMA controller features multiple independent channels and", fontsize=11)
    p1.insert_text((50, 785), "Section 2.5 Page 1", fontsize=9)  # Running footer

    # Page 2
    p2 = doc.new_page(width=600, height=800)
    p2.insert_text((50, 30), "RP2040 Technical Reference Manual", fontsize=9)  # Running header
    p2.insert_text((50, 100), "provides high-throughput memory transfers without CPU intervention.", fontsize=11)
    p2.insert_text((50, 785), "Section 2.5 Page 2", fontsize=9)  # Running footer

    res1 = extract_page_layout(doc[0])
    res2 = extract_page_layout(doc[1])
    doc.close()

    assert "RP2040 Technical Reference Manual" not in res1.text
    assert "Section 2.5 Page 1" not in res1.text
    assert "RP2040 Technical Reference Manual" not in res2.text
    assert "Section 2.5 Page 2" not in res2.text

    # Sentence stitching test across pages
    stitched = stitch_page_texts([res1.text, res2.text])
    assert "The DMA controller features multiple independent channels and provides high-throughput memory transfers without CPU intervention." in stitched


def test_feature2_real_rp2040_running_headers_footers_stripped():
    """Verify running headers and footers are 100% stripped from benchmark pages 112-114 of RP2040 datasheet."""
    if not os.path.exists(BENCHMARK_RP2040_PATH):
        pytest.skip(f"Benchmark PDF not found at {BENCHMARK_RP2040_PATH}")

    doc = fitz.open(BENCHMARK_RP2040_PATH)
    # Check pages 112, 113, 114 (0-indexed 111, 112, 113)
    pages_text = []
    for p_idx in [111, 112, 113]:
        res = extract_page_layout(doc[p_idx])
        pages_text.append(res.text)
        # Running header must not appear on any page
        assert "RP2040 Datasheet" not in res.text, f"Running header found on page {p_idx+1}"
        # Running footers must not appear
        assert f"2.5. DMA\n{p_idx}" not in res.text
        assert f"2.5. DMA {p_idx}" not in res.text

    doc.close()

    stitched = stitch_page_texts(pages_text)
    assert "RP2040 Datasheet" not in stitched
    assert "2.5. DMA 111" not in stitched
    assert "2.5. DMA 112" not in stitched
    assert "2.5. DMA 113" not in stitched


# ============================================================================
# 4. Feature 3: Native Markdown Table Extraction & Caption Binding Tests
# ============================================================================

def test_feature3_real_rp2040_table124_extraction():
    """Verify Table 124 on page 113 of RP2040 extracts as clean Markdown with left caption bound and bitfields aligned."""
    if not os.path.exists(BENCHMARK_RP2040_PATH):
        pytest.skip(f"Benchmark PDF not found at {BENCHMARK_RP2040_PATH}")

    doc = fitz.open(BENCHMARK_RP2040_PATH)
    page113 = doc[112]  # Page 113 (0-indexed 112)
    res = extract_page_layout(page113)
    doc.close()

    # 1. Table presence and masks
    assert len(res.tables) == 1, f"Expected 1 table, found {len(res.tables)}"
    assert len(res.table_masks) == 1
    t0 = res.tables[0]
    bbox = t0["bbox"]
    assert len(bbox) == 4
    assert res.table_masks[0] == bbox

    # 2. Left caption binding
    assert t0["caption"].startswith("Table 124."), f"Caption mismatch: {t0['caption']}"
    assert "CH0_CTRL_TRIG" in t0["caption"]
    assert "Registers" in t0["caption"]

    # 3. Clean Markdown Table formatting
    md = t0["markdown"]
    assert md.startswith("### Table 124.")
    assert "|Bits|Description|Type|Reset|" in md
    assert "|---|---|---|---|" in md

    # 4. Register bitfield alignment (Bit 31 AHB_ERROR with Type RO, Reset 0x0)
    lines = [l.strip() for l in md.split("\n") if l.strip().startswith("|")]
    assert len(lines) >= 10, "Table 124 must have multiple register bitfield rows"
    # Find Bit 31 row
    bit31_rows = [l for l in lines if l.startswith("|31|")]
    assert len(bit31_rows) == 1
    assert "AHB_ERROR" in bit31_rows[0]
    assert "|RO|0x0|" in bit31_rows[0]

    # Find Bit 30 row
    bit30_rows = [l for l in lines if l.startswith("|30|")]
    assert len(bit30_rows) == 1
    assert "READ_ERROR" in bit30_rows[0]
    assert "|WC|0x0|" in bit30_rows[0]

    # 5. Caption is NOT duplicated in body text outside table
    assert res.text.count("Table 124.") == 1


def test_feature3_multi_table_page112_caption_binding():
    """Verify page 112 (containing Tables 121, 122, 123) correctly binds all 3 margin captions and creates 3 masks."""
    if not os.path.exists(BENCHMARK_RP2040_PATH):
        pytest.skip(f"Benchmark PDF not found at {BENCHMARK_RP2040_PATH}")

    doc = fitz.open(BENCHMARK_RP2040_PATH)
    page112 = doc[111]
    res = extract_page_layout(page112)
    doc.close()

    assert len(res.tables) == 3
    assert len(res.table_masks) == 3

    captions = [t["caption"] for t in res.tables]
    assert any("Table 121." in c for c in captions)
    assert any("Table 122." in c for c in captions)
    assert any("Table 123." in c for c in captions)

    for mask in res.table_masks:
        assert isinstance(mask, tuple)
        assert len(mask) == 4
        assert mask[2] > mask[0]
        assert mask[3] > mask[1]


# ============================================================================
# 5. Feature 4: Monospace Code Block Preservation Tests
# ============================================================================

def test_feature4_real_rp2040_page100_code_blocks():
    """Verify C code on page 100 of RP2040 is preserved as fenced code blocks with line numbers stripped."""
    if not os.path.exists(BENCHMARK_RP2040_PATH):
        pytest.skip(f"Benchmark PDF not found at {BENCHMARK_RP2040_PATH}")

    doc = fitz.open(BENCHMARK_RP2040_PATH)
    page100 = doc[99]  # Page 100 (0-indexed 99)
    res = extract_page_layout(page100)
    doc.close()

    assert len(res.code_blocks) >= 1
    # Check that fenced code block exists in text
    assert "```c" in res.text

    # Code block 1 verification: DMA channel IRQ setup code
    assert "dma_channel_set_irq0_enabled" in res.text
    assert "irq_set_exclusive_handler" in res.text

    # Code block 2 verification: C headers
    assert "#include <stdio.h>" in res.text
    assert '#include "hardware/dma.h"' in res.text

    # Verify line numbers were stripped: lines must not start with line numbers like '80 dma_'
    assert not re.search(r"```c\s*\n\s*\d+\s+dma_channel", res.text)


def test_feature4_synthetic_monospace_span_detection():
    """Verify synthetic monospace font flags (flags & 8) and font family names are recognized."""
    assert is_mono_font("RobotoMono-Regular", 4) is True
    assert is_mono_font("RobotoMono-Italic", 6) is True
    assert is_mono_font("Courier", 0) is True
    assert is_mono_font("mplus1mn-regular", 0) is True
    assert is_mono_font("SomeFont", 8) is True  # flags & 8
    assert is_mono_font("Roboto-Regular", 4) is False
    assert is_mono_font("TimesNewRoman", 0) is False


# ============================================================================
# 6. Feature 5: Multi-Page Range OCR Fix Tests
# ============================================================================

def test_feature5_extract_pages_range_renders_all_pages():
    """Verify extract_pages_range renders ALL pages in range start_page..end_page during DeepSeek-OCR hybrid mode."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        db_file = tmp_path / "test.db"

        config = {
            "db_path": str(db_file),
            "ocr_threshold_chars": 99999,  # Force OCR fallback
            "enable_vision_ocr": True,
            "input_mode": "folder",
            "input_path": str(tmp_path)
        }

        # Create a real 3-page PDF with minimal text so threshold triggers OCR
        doc = fitz.open()
        p0 = doc.new_page(width=300, height=300)
        p0.insert_text((50, 50), "P1", fontsize=10)
        p1 = doc.new_page(width=300, height=300)
        p1.insert_text((50, 50), "P2", fontsize=10)
        p2 = doc.new_page(width=300, height=300)
        p2.insert_text((50, 50), "P3", fontsize=10)
        pdf_path = tmp_path / "scanned_doc.pdf"
        doc.save(str(pdf_path))
        doc.close()

        extractor = ArchiveExtractor(config_path=config)

        # Mock vision_ocr and render_single_page_image
        extractor.vision_ocr = MagicMock()
        extractor.vision_ocr.convert_document_to_markdown.side_effect = lambda img_path: f"Markdown from {Path(img_path).stem}"

        rendered_pages = []

        def mock_render(path, p_idx):
            rendered_pages.append(p_idx)
            fake_img = tmp_path / f"page_{p_idx}.png"
            fake_img.write_text("fake image data")
            return str(fake_img)

        with patch.object(extractor, "render_single_page_image", side_effect=mock_render):
            text, is_ocr = extractor.extract_pages_range(pdf_path, start_page=0, end_page=2)

        extractor.close()

        # Crucial assertion: Must render pages 0, 1, AND 2 (NOT just page 0!)
        assert rendered_pages == [0, 1, 2], f"Expected rendering pages [0, 1, 2], but got {rendered_pages}"
        assert is_ocr is True
        assert "Markdown from page_0" in text
        assert "Markdown from page_1" in text
        assert "Markdown from page_2" in text


# ============================================================================
# 7. End-to-End ArchiveExtractor Integration Test
# ============================================================================

def test_archive_extractor_real_rp2040_range_extraction():
    """Verify ArchiveExtractor.extract_pages_range on real RP2040 datasheet pages 112-113."""
    if not os.path.exists(BENCHMARK_RP2040_PATH):
        pytest.skip(f"Benchmark PDF not found at {BENCHMARK_RP2040_PATH}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        db_file = tmp_path / "test.db"

        config = {
            "db_path": str(db_file),
            "ocr_threshold_chars": 50,
            "enable_vision_ocr": False,
            "input_mode": "book",
            "input_path": BENCHMARK_RP2040_PATH
        }

        extractor = ArchiveExtractor(config_path=config)
        text, is_ocr = extractor.extract_pages_range(Path(BENCHMARK_RP2040_PATH), start_page=111, end_page=112)
        extractor.close()

        assert is_ocr is False
        assert len(text) > 1000
        # Headers/footers filtered
        assert "RP2040 Datasheet" not in text
        assert "2.5. DMA 111" not in text
        assert "2.5. DMA 112" not in text
        # Tables extracted
        assert "Table 121." in text
        assert "Table 124." in text
        assert "|Bits|Description|Type|Reset|" in text
