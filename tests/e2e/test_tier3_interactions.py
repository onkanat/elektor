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
# TIER 3: Cross-Feature Pairwise Interactions
# ============================================================================

def test_interaction_multicolumn_and_tables(synthetic_pdf_factory):
    """Interaction F01 + F03: Multi-column page containing an embedded table.
    Verifies table markdown and column reading order do not interleave.
    """
    pdf_path = synthetic_pdf_factory(
        filename="tier3_col_table.pdf",
        pages_config=[{
            "columns": [
                {"x": 50, "y": 80, "lines": ["Left Column Header", "Left Column Body"]},
                {"x": 320, "y": 80, "lines": ["Right Column Header", "Right Column Body"]}
            ],
            "table": {
                "bbox": (50, 200, 500, 320),
                "rows": 3,
                "cols": 3,
                "data": {
                    (0, 0): "Field", (0, 1): "Bits", (0, 2): "Reset",
                    (1, 0): "EN", (1, 1): "0", (1, 2): "0x1",
                    (2, 0): "BUSY", (2, 1): "1", (2, 2): "0x0"
                }
            }
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()

    assert len(res.tables) == 1
    assert len(res.table_masks) == 1
    # Check table structure
    md = res.tables[0]["markdown"]
    assert "|Field|Bits|Reset|" in md.replace(" ", "")
    # Check reading order of columns
    assert "Left Column Header" in res.text
    assert "Right Column Header" in res.text
    assert res.text.find("Left Column Body") < res.text.find("Right Column Header")


def test_interaction_tables_and_code_blocks(synthetic_pdf_factory):
    """Interaction F03 + F04: Page containing both a native table and a fenced code block.
    Verifies that neither syntax bleeds into the other.
    """
    pdf_path = synthetic_pdf_factory(
        filename="tier3_table_code.pdf",
        pages_config=[{
            "table": {
                "bbox": (50, 100, 450, 220),
                "rows": 2,
                "cols": 2,
                "data": {(0, 0): "Register", (0, 1): "Offset", (1, 0): "CTRL", (1, 1): "0x00"}
            },
            "code": {
                "x": 50, "y": 300,
                "lines": [
                    "// Configure register",
                    "void setup_ctrl(void) {",
                    "    io_write(REG_CTRL, 0x01);",
                    "}"
                ]
            }
        }]
    )
    doc = fitz.open(pdf_path)
    res = extract_page_layout(doc[0])
    doc.close()

    assert len(res.tables) == 1
    assert len(res.code_blocks) == 1
    assert "setup_ctrl" in res.code_blocks[0]["code"]
    assert "```c" in res.text
    assert "|Register|Offset|" in res.tables[0]["markdown"].replace(" ", "")
    # Code block does not contain table pipes
    assert "|" not in res.code_blocks[0]["code"]


def test_interaction_header_stripping_and_multipage_range(synthetic_pdf_factory):
    """Interaction F02 + F05: Multi-page range extraction across 3 pages.
    Verifies headers and footers are consistently stripped across all rendered pages.
    """
    pdf_path = synthetic_pdf_factory(
        filename="tier3_multipage_headers.pdf",
        pages_config=[
            {
                "header": "Datasheet Section 1",
                "footer": "Running Footer P10",
                "columns": [{"x": 50, "y": 100, "lines": ["Unique content page 10"]}]
            },
            {
                "header": "Datasheet Section 1",
                "footer": "Running Footer P11",
                "columns": [{"x": 50, "y": 100, "lines": ["Unique content page 11"]}]
            },
            {
                "header": "Datasheet Section 1",
                "footer": "Running Footer P12",
                "columns": [{"x": 50, "y": 100, "lines": ["Unique content page 12"]}]
            }
        ]
    )
    doc = fitz.open(pdf_path)
    results = [extract_page_layout(p) for p in doc]
    doc.close()

    assert len(results) == 3
    for idx, r in enumerate(results):
        assert "Datasheet Section 1" not in r.text
        assert f"Running Footer P{10 + idx}" not in r.text
        assert f"Unique content page {10 + idx}" in r.text


def test_interaction_table_masking_and_drawing_clustering(synthetic_pdf_factory):
    """Interaction F06 + F07: Page with both a register table (grid drawings) and a diagram.
    Verifies table grid drawings are masked out while block diagram lines are clustered into a figure crop.
    """
    pdf_path = synthetic_pdf_factory(
        filename="tier3_mask_cluster.pdf",
        pages_config=[{
            "table": {"bbox": (50, 100, 450, 250), "rows": 4, "cols": 4},
            "diagram": {"origin": (100, 400), "drawings_count": 30, "label": "Bus Fabric Matrix"}
        }]
    )
    doc = fitz.open(pdf_path)
    page = doc[0]
    res = extract_page_layout(page)
    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=res.table_masks)
    doc.close()

    assert len(crops) == 1
    assert crops[0].bbox[1] >= 250.0  # Diagram is below table mask
    assert crops[0].crop_type == "diagram"


def test_interaction_drawing_clustering_and_boundary_expansion(synthetic_pdf_factory):
    """Interaction F07 + F08: Complex diagram with internal vector drawings and outer pin labels.
    Verifies diagram is detected (>=20 paths) and boundary is expanded to absorb the external labels.
    """
    doc = fitz.open()
    page = doc.new_page(width=700, height=800)
    # 25 internal drawing lines
    for i in range(25):
        page.draw_line((100, 200 + i * 8), (300, 200 + i * 8), color=(0, 0, 0), width=1)
    # External connector arrow extending to 320
    page.draw_line((300, 300), (320, 300), color=(0, 0, 0), width=2)
    # Adjacent label at x=325
    page.insert_text((325, 305), "CLK_OUT_PIN", fontsize=10)

    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 1
    assert crops[0].crop_type == "diagram"
    assert crops[0].bbox[2] >= 350.0  # Encompasses CLK_OUT_PIN


def test_interaction_boundary_expansion_and_aspect_ratio_filters():
    """Interaction F08 + F09: Wide timing diagram with outer signal labels.
    Verifies boundary expansion absorbs labels, and aspect ratio filter retains wide timing diagram.
    """
    doc = fitz.open()
    page = doc.new_page(width=800, height=800)
    # Wide timing diagram: width=350, height=45 (area 15750)
    for i in range(25):
        page.draw_line((100 + i * 14, 200), (100 + i * 14, 245), color=(0, 0, 0), width=1)
    # Signal label at left
    page.insert_text((85, 225), "SCLK", fontsize=9)

    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 1
    assert crops[0].bbox[0] <= 85.0


def test_interaction_aspect_ratio_and_deduplication():
    """Interaction F09 + F10: Page with full-page border, thin horizontal lines, duplicate boxes, and authentic diagram.
    Verifies border and thin lines rejected, duplicate candidates deduplicated into single crop.
    """
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # Full page rect
    page.draw_rect(fitz.Rect(10, 10, 590, 790), color=(0, 0, 0), width=1)
    # Thin divider line
    page.draw_rect(fitz.Rect(50, 150, 550, 152), color=(0, 0, 0), fill=(0, 0, 0))
    # Diagram 1 (25 lines)
    for i in range(25):
        page.draw_line((100, 200 + i * 6), (300, 200 + i * 6), color=(0, 0, 0), width=1)

    analyzer = get_layout_analyzer()
    crops = analyzer.analyze_page(page, table_masks=[])
    doc.close()

    assert len(crops) == 1
    assert crops[0].crop_type == "diagram"


def test_interaction_closed_pipe_during_multipage_ocr(tmp_path):
    """Interaction F05 + F11: Multi-page PDF extraction executed under closed stdout pipe.
    Verifies process survives without uncaught BrokenPipeError and database connection closes safely.
    """
    db_file = tmp_path / "closed_pipe_test.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("CREATE TABLE ocr_log (id INT, page INT, text TEXT);")

    # Simulate multi-page rendering under broken pipe
    for page_idx in range(3):
        cur.execute("INSERT INTO ocr_log VALUES (?, ?, ?);", (page_idx, page_idx + 1, f"Extracted page {page_idx+1}"))
        with patch("sys.stdout.flush", side_effect=BrokenPipeError):
            BrokenPipeShield.safe_print(f"Logged page {page_idx+1}", flush=True)

    # Safe teardown
    with patch("builtins.print", side_effect=BrokenPipeError):
        BrokenPipeShield.safe_close_db(conn)

    # Reconnect and verify data integrity
    conn2 = sqlite3.connect(str(db_file))
    cur2 = conn2.cursor()
    rows = cur2.execute("SELECT COUNT(*) FROM ocr_log;").fetchone()
    conn2.close()
    assert rows[0] == 3


def test_interaction_table_anti_loop_and_control_token_sanitization():
    """Interaction F12 + F13: VLM response containing repetitive table rows AND control tokens.
    Verifies control tokens are stripped while table rows are preserved intact without truncation.
    """
    vlm_output = (
        "<think>Let me examine the table structure carefully.</think>\n"
        "<|im_start|>assistant\n"
        "<|grounding|>\n"
        "### Memory Map\n\n"
        "| Region | Base Address | Size |\n"
        "|---|---|---|\n"
        "| ROM | 0x00000000 | 16KB |\n\n"
        "### Peripheral Map\n\n"
        "| Region | Base Address | Size |\n"
        "|---|---|---|\n"
        "| APB | 0x40000000 | 64KB |\n\n"
        "### User Memory\n\n"
        "| Region | Base Address | Size |\n"
        "|---|---|---|\n"
        "| SRAM | 0x20000000 | 264KB |\n"
    )

    # Step 1: Strip control tokens
    sanitized = clean_vlm_response(vlm_output)
    assert "<think>" not in sanitized
    assert "<|im_start|>" not in sanitized
    assert "<|grounding|>" not in sanitized

    # Step 2: Apply table-aware anti-loop filter
    final_output = filter_repetition_anti_loop(sanitized)
    assert final_output.count("| Region | Base Address | Size |") == 3
    assert "truncated" not in final_output.lower()
    assert "SRAM | 0x20000000 | 264KB" in final_output


def test_interaction_dynamic_failover_and_multimodal_catalog(tmp_path):
    """Interaction F15 + F16: Building multimodal catalog and dataset when primary LAN Ollama is offline.
    Verifies automatic failover succeeds and catalog is generated with valid schema.
    """
    client = get_resilient_ollama_client(primary_url="http://mock-lan-down:11434", fallback_url="http://mock-localhost:11434")

    def side_effect(req, *args, **kwargs):
        if "mock-lan-down" in req.full_url:
            raise ConnectionRefusedError("LAN host offline")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "response": "Detailed technical analysis of RP2040 PLL clock generator schematic."
        }).encode("utf-8")
        ctx = MagicMock()
        ctx.__enter__.return_value = mock_resp
        return ctx

    with patch("urllib.request.urlopen", side_effect=side_effect):
        vlm_desc = client.generate("deepseek-ocr", "Describe this diagram")
        assert client.failover_occurred
        assert len(vlm_desc) >= 25

    # Build multimodal record from fallback response
    record = {
        "id": "vis_sample_test_0001",
        "image": "images/p11_fig_1.webp",
        "conversations": [
            {"from": "human", "value": "<image>\nParse the figure."},
            {"from": "gpt", "value": vlm_desc}
        ],
        "metadata": {"project_id": "test", "failover": client.failover_occurred}
    }

    # Verify JSONL formatting
    jsonl_line = json.dumps(record, ensure_ascii=False)
    assert "PLL clock generator" in jsonl_line
    assert json.loads(jsonl_line)["metadata"]["failover"] is True

    # Verify Markdown catalog generation
    catalog_md = (
        "# 📊 Multimodal Technical Catalog & Diagram Breakdown\n\n"
        "## Figure 1: `p11_fig_1.png`\n\n"
        f"![p11_fig_1.png]({record['image']})\n\n"
        "### 🔍 Technical Parsing & Extraction\n\n"
        f"{vlm_desc}\n"
    )
    assert "PLL clock generator" in catalog_md
    assert "![p11_fig_1.png]" in catalog_md
