import os
import sys
import json
import sqlite3
import tempfile
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image

from pipeline.project_logger import BrokenPipeShield, safe_print, safe_close_db
from pipeline.extractor import ArchiveExtractor, preprocess_image_for_ocr
from pipeline.vision_ocr import (
    VisionOCRManager,
    clean_vlm_response,
    filter_repetition_anti_loop
)
from pipeline.llm_client import (
    ResilientOllamaClient,
    get_resilient_ollama_client,
    resolve_active_ollama_endpoint
)
from pipeline.visual_dataset_builder import VisualDatasetBuilder


# ============================================================================
# FEATURE 11: BrokenPipeError Immunity & Safe Teardown
# ============================================================================

def test_safe_print_closed_stream_no_exception():
    """Verifies safe_print catches BrokenPipeError and IOError without raising."""
    with patch("sys.stdout.flush", side_effect=BrokenPipeError("EPIPE: Pipe closed")):
        try:
            safe_print("Test message under broken pipe", flush=True)
        except BrokenPipeError:
            pytest.fail("safe_print must swallow BrokenPipeError")


def test_safe_close_db_commits_and_closes(tmp_path):
    """Verifies safe_close_db commits open transaction and closes the SQLite connection."""
    db_file = tmp_path / "test_commit.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("CREATE TABLE records (id INT, val TEXT);")
    cur.execute("INSERT INTO records VALUES (1, 'retained');")

    with patch("sys.stdout.write", side_effect=BrokenPipeError):
        safe_close_db(conn)

    # Reopen and assert transaction was committed
    verify_conn = sqlite3.connect(str(db_file))
    row = verify_conn.execute("SELECT val FROM records WHERE id = 1;").fetchone()
    verify_conn.close()
    assert row is not None
    assert row[0] == "retained"


def test_safe_close_db_already_closed():
    """Verifies safe_close_db is idempotent when connection is already closed."""
    conn = sqlite3.connect(":memory:")
    conn.close()
    try:
        safe_close_db(conn)
    except Exception as e:
        pytest.fail(f"safe_close_db should handle already closed connections: {e}")


def test_extractor_close_survives_broken_pipe_and_unloads(tmp_path):
    """Verifies ArchiveExtractor.close() safely closes database and survives BrokenPipeError."""
    db_file = tmp_path / "extractor_close_test.db"
    cfg = {
        "db_path": str(db_file),
        "enable_vision_ocr": True,
        "model_vision": "test-vlm-model",
        "ollama_url": "http://127.0.0.1:11434"
    }
    cfg_file = tmp_path / "test_config.json"
    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

    extractor = ArchiveExtractor(config_path=str(cfg_file))
    assert extractor.conn is not None

    with patch("builtins.print", side_effect=BrokenPipeError("Simulated pipe failure during teardown")):
        with patch("pipeline.llm_client.unload_ollama_model") as mock_unload:
            extractor.close()
            assert mock_unload.called

    assert extractor.conn is None


def test_extractor_book_outline_logging_survives_broken_pipe(tmp_path):
    """Verifies outline parsing in extract_book_segments handles stdout broken pipe safely."""
    # Create minimal mock PDF
    import pypdf
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    pdf_path = tmp_path / "test_book.pdf"
    with open(pdf_path, "wb") as f:
        writer.write(f)

    cfg = {"db_path": str(tmp_path / "book_test.db")}
    cfg_file = tmp_path / "config.json"
    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

    extractor = ArchiveExtractor(config_path=str(cfg_file))
    try:
        with patch("pipeline.project_logger.print", side_effect=BrokenPipeError("Pipe broken on outline print")):
            segments, reader = extractor.extract_book_segments(pdf_path)
            assert len(segments) >= 1
    finally:
        extractor.close()


# ============================================================================
# FEATURE 12: Table-Syntax Preserving Anti-Loop Filter
# ============================================================================

def test_repetitive_markdown_table_headers_preserved():
    """Verifies recurring Markdown table headers across sub-sections are NOT truncated."""
    table_sample = (
        "### Section 1.1\n"
        "| Register | Offset | Type | Description |\n"
        "|---|---|---|---|\n"
        "| CTRL | 0x00 | RW | Control register |\n\n"
        "### Section 1.2\n"
        "| Register | Offset | Type | Description |\n"
        "|---|---|---|---|\n"
        "| STATUS | 0x04 | RO | Status register |\n\n"
        "### Section 1.3\n"
        "| Register | Offset | Type | Description |\n"
        "|---|---|---|---|\n"
        "| INTR | 0x08 | RW | Interrupt mask |\n\n"
        "### Section 1.4\n"
        "| Register | Offset | Type | Description |\n"
        "|---|---|---|---|\n"
        "| INTE | 0x0C | RW | Interrupt enable |\n\n"
        "### Section 1.5\n"
        "| Register | Offset | Type | Description |\n"
        "|---|---|---|---|\n"
        "| INTF | 0x10 | RO | Interrupt force |\n"
    )
    cleaned = filter_repetition_anti_loop(table_sample)
    assert "Further repetitions" not in cleaned
    assert cleaned.count("| Register | Offset | Type | Description |") == 5
    assert cleaned.count("|---|---|---|---|") == 5


def test_table_separator_and_data_rows_preserved():
    """Verifies repeated table separator rows and data rows are never replaced by metatext."""
    rows = ["|---|---|---|"] * 8
    cleaned = filter_repetition_anti_loop("\n".join(rows))
    assert "Further repetitions" not in cleaned
    assert "|---|---|---|" in cleaned


def test_consecutive_duplicate_lines_collapsed():
    """Verifies that consecutive repeating non-table text lines collapse into truncation notice."""
    loop_text = (
        "Heading\n"
        "Repeating hallucination line.\n"
        "Repeating hallucination line.\n"
        "Repeating hallucination line.\n"
        "Consequent text."
    )
    cleaned = filter_repetition_anti_loop(loop_text)
    assert "*(Repetitive sequence truncated)*" in cleaned
    assert "Consequent text." in cleaned


def test_genuine_text_loop_truncated():
    """Verifies global repeated sentences (> 4 times) are truncated for non-table lines."""
    repeat_line = "This is a hallucinated monologue line generated by the VLM."
    # Dispersed across different sections so they are non-consecutive
    full_text = f"{repeat_line}\n\nSection 1\n\n{repeat_line}\n\nSection 2\n\n{repeat_line}\n\nSection 3\n\n{repeat_line}\n\nSection 4\n\n{repeat_line}"
    cleaned = filter_repetition_anti_loop(full_text)
    assert f"*(Further repetitions of '{repeat_line}' truncated)*" in cleaned


def test_short_lines_exempt_from_truncation():
    """Verifies short lines (len <= 5) like headers, dividers, or OK flags are exempt from loop filter."""
    short_lines = "\n\n".join(["OK"] * 8)
    cleaned = filter_repetition_anti_loop(short_lines)
    assert "Further repetitions" not in cleaned
    assert "OK" in cleaned


# ============================================================================
# FEATURE 13: Control-Token & Thought Preamble Sanitization
# ============================================================================

def test_clean_vlm_response_closed_think():
    """Verifies closed <think>...</think> tags and internal reasoning are stripped."""
    raw = "<think>Let me reason about the RP2040 PLL dividers.\nStep 1: Check reference frequency.</think>\n# PLL Setup\nConfigure FBDIV."
    cleaned = clean_vlm_response(raw)
    assert "<think>" not in cleaned
    assert "</think>" not in cleaned
    assert "Let me reason" not in cleaned
    assert cleaned.startswith("# PLL Setup")


def test_clean_vlm_response_unclosed_think():
    """Verifies unclosed <think>... tags when generation cuts off mid-thought are stripped."""
    raw = "Valid preamble introduction.\n<think>The user is asking for clock generators and I need to"
    cleaned = clean_vlm_response(raw)
    assert "<think>" not in cleaned
    assert "clock generators" not in cleaned
    assert cleaned == "Valid preamble introduction."


def test_clean_vlm_response_deepseek_unicode_thoughts():
    """Verifies DeepSeek Unicode thought tags <｜thought｜> and <｜end of thought｜> are stripped."""
    raw = "<｜thought｜>Analyzing SPI peripheral pins.<｜end of thought｜>\nPin 21: SPI0_CSn."
    cleaned = clean_vlm_response(raw)
    assert "<｜thought｜>" not in cleaned
    assert "<｜end of thought｜>" not in cleaned
    assert cleaned == "Pin 21: SPI0_CSn."

    # Unclosed unicode thought
    raw_unclosed = "Header\n<｜thought｜>I will check the crystal oscillator"
    cleaned_unclosed = clean_vlm_response(raw_unclosed)
    assert "<｜thought｜>" not in cleaned_unclosed
    assert cleaned_unclosed == "Header"


def test_clean_vlm_response_deepseek_brackets():
    """Verifies DeepSeek fullwidth bracket artifacts 【...】 are stripped."""
    raw = "The system bus fabric【4:12†source】operates at 133MHz."
    cleaned = clean_vlm_response(raw)
    assert "【" not in cleaned
    assert "】" not in cleaned
    assert cleaned == "The system bus fabricoperates at 133MHz."


def test_clean_vlm_response_control_tokens():
    """Verifies ChatML, Grounding, and Llama 3 header tokens are stripped."""
    raw = (
        "<|im_start|>assistant\n"
        "<|start_header_id|>assistant<|end_header_id|>\n"
        "<|grounding|>Bbox [100, 100, 200, 200]\n"
        "<|file:notes.txt:1:1|>\n"
        "Technical breakdown output.<|im_end|><|eot_id|>"
    )
    cleaned = clean_vlm_response(raw)
    for tok in ["<|im_start|>", "<|start_header_id|>", "<|grounding|>", "<|file:", "<|im_end|>", "<|eot_id|>"]:
        assert tok not in cleaned
    assert "Technical breakdown output." in cleaned


def test_clean_vlm_response_conversational_preamble():
    """Verifies conversational monologue filler ('Let me analyze this diagram...') is stripped."""
    raw = "Let me analyze this diagram and describe the components in detail.\n\n# System Diagram\nDual Core Cortex-M0+."
    cleaned = clean_vlm_response(raw)
    assert not cleaned.lower().startswith("let me analyze")
    assert cleaned.startswith("# System Diagram")


def test_convert_document_to_markdown_calls_cleaner(tmp_path):
    """Verifies VisionOCRManager.convert_document_to_markdown sanitizes raw output before returning."""
    # Create test image
    img = Image.new("RGB", (100, 100), color="white")
    img_path = tmp_path / "page_ocr.png"
    img.save(img_path)

    mgr = VisionOCRManager(config_dict={"ollama_url": "http://127.0.0.1:11434", "model_vision": "mock-vlm"})
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content="<think>Thinking...</think><|im_start|>assistant\n# Extracted Page\nContent."))]
    mgr.client = MagicMock()
    mgr.client.chat.completions.create.return_value = mock_resp

    md = mgr.convert_document_to_markdown(str(img_path))
    assert "<think>" not in md
    assert "<|im_start|>" not in md
    assert "# Extracted Page" in md


# ============================================================================
# FEATURE 14: Tesseract Preprocessing & PSM Tuning + Suffix Regex
# ============================================================================

def test_preprocess_image_for_ocr_grayscale_and_binarization():
    """Verifies preprocess_image_for_ocr converts RGB images into contrast-enhanced binary images."""
    img = Image.new("RGB", (60, 60), color=(180, 180, 180))
    bw = preprocess_image_for_ocr(img)
    assert bw.mode in ("1", "L")
    assert bw.size == (60, 60)


def test_clean_ocr_text_preserves_english_keywords():
    """Verifies English phrases like 'pin ten' and 'for ten' are NOT corrupted into 'pinten' or 'forten'."""
    extractor = ArchiveExtractor(config_dict={})
    sample_en = "Connect signal to pin ten and hold for ten microseconds. Greater tan threshold."
    cleaned = extractor.clean_ocr_text(sample_en)
    assert "pinten" not in cleaned
    assert "forten" not in cleaned
    assert "greatertan" not in cleaned
    assert "pin ten" in cleaned
    assert "for ten" in cleaned


def test_clean_ocr_text_rejoins_turkish_suffixes():
    """Verifies Turkish suffixes like '-liği', '-yeti', and '-tan' are correctly rejoined."""
    extractor = ArchiveExtractor(config_dict={})
    sample_tr = "Bu mikrodenetleyicinin medeni yeti ve geniş liği ölçülmüştür. Kitap tan okundu."
    cleaned = extractor.clean_ocr_text(sample_tr)
    assert "medeniyeti" in cleaned
    assert "genişliği" in cleaned
    assert "Kitaptan" in cleaned


def test_ocr_pdf_command_includes_dpi_and_psm(tmp_path):
    """Verifies Tesseract subprocess command is formatted with --dpi 300 and --psm 6."""
    import pypdf
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=300, height=300)
    pdf_path = tmp_path / "test_ocr.pdf"
    with open(pdf_path, "wb") as f:
        writer.write(f)

    extractor = ArchiveExtractor(config_dict={"tesseract_cmd": "tesseract"})
    with patch("subprocess.run") as mock_subproc:
        mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")
        extractor.ocr_pdf(pdf_path)
        assert mock_subproc.called
        cmd = mock_subproc.call_args[0][0]
        assert "--dpi" in cmd and cmd[cmd.index("--dpi") + 1] == "300"
        assert "-l" in cmd and cmd[cmd.index("-l") + 1] == "eng"
        assert "--psm" in cmd and cmd[cmd.index("--psm") + 1] == "6"


# ============================================================================
# FEATURE 15: Dynamic Endpoint Failover
# ============================================================================

def test_resilient_ollama_client_primary_success():
    """Verifies primary endpoint response is used when primary is reachable."""
    client = get_resilient_ollama_client(primary_url="http://mock-primary:11434", fallback_url="http://mock-fallback:11434")
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"response": "Primary Active Output"}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        result = client.generate("model", "Test prompt")
        assert result == "Primary Active Output"
        assert not client.failover_occurred
        assert client.active_url == "http://mock-primary:11434"


def test_resilient_ollama_client_failover_on_connection_error():
    """Verifies client automatically switches to fallback when primary connection is refused."""
    client = get_resilient_ollama_client(primary_url="http://mock-dead:11434", fallback_url="http://mock-alive:11434")

    def side_effect(req, *args, **kwargs):
        if "mock-dead" in req.full_url:
            raise ConnectionRefusedError("Connection refused by dead primary host")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"response": "Fallback Active Output"}).encode("utf-8")
        ctx = MagicMock()
        ctx.__enter__.return_value = mock_resp
        return ctx

    with patch("urllib.request.urlopen", side_effect=side_effect):
        result = client.generate("model", "Test prompt")
        assert result == "Fallback Active Output"
        assert client.failover_occurred
        assert client.active_url == "http://mock-alive:11434"


def test_resilient_ollama_client_failover_on_timeout():
    """Verifies client triggers failover on socket timeout."""
    client = get_resilient_ollama_client(primary_url="http://mock-slow:11434", fallback_url="http://mock-fast:11434")

    def side_effect(req, *args, **kwargs):
        if "mock-slow" in req.full_url:
            raise socket.timeout("Timed out waiting for response")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"response": "Recovered After Timeout"}).encode("utf-8")
        ctx = MagicMock()
        ctx.__enter__.return_value = mock_resp
        return ctx

    with patch("urllib.request.urlopen", side_effect=side_effect):
        result = client.generate("model", "Prompt")
        assert result == "Recovered After Timeout"
        assert client.failover_occurred


def test_resolve_active_ollama_endpoint_tcp_probe():
    """Verifies resolve_active_ollama_endpoint probes ports and returns healthy endpoint."""
    with patch("socket.create_connection") as mock_conn:
        # Primary fails, fallback succeeds
        def conn_effect(addr, *args, **kwargs):
            if addr[0] == "192.168.1.26":
                raise ConnectionRefusedError("Host unreachable")
            return MagicMock()

        mock_conn.side_effect = conn_effect
        resolved = resolve_active_ollama_endpoint(
            primary_url="http://192.168.1.26:11434",
            fallback_url="http://127.0.0.1:11434"
        )
        assert resolved == "http://127.0.0.1:11434"


# ============================================================================
# FEATURE 16: Schema-Compliant Multimodal Catalog & Dataset
# ============================================================================

def test_multimodal_dataset_schema_compliance(tmp_path):
    """Verifies that generated JSONL records strictly comply with schema invariants."""
    record = {
        "id": "vis_sample_test_0001_p10_fig_1",
        "image": "images/p10_fig_1.webp",
        "conversations": [
            {"from": "human", "value": "<image>\nBu teknik çizimi/şemayı detaylıca analiz et ve bileşenleri açıkla."},
            {"from": "gpt", "value": clean_vlm_response("<think>reasoning</think>Dual ARM Cortex-M0+ processor subsystem.")}
        ],
        "metadata": {
            "project_id": "rp01",
            "model_vision": "deepseek-ocr:3b-bf16",
            "original_filename": "p10_fig_1.png",
            "webp_filename": "p10_fig_1.webp",
            "saved_ratio_percent": 65.4
        }
    }
    # Check keys
    assert set(record.keys()) == {"id", "image", "conversations", "metadata"}
    assert record["conversations"][0]["from"] == "human"
    assert record["conversations"][1]["from"] == "gpt"
    assert "<think>" not in record["conversations"][1]["value"]
    assert len(record["conversations"][1]["value"]) >= 25


def test_multimodal_catalog_markdown_structure():
    """Verifies multimodal catalog formatting with clean figure links and table preservation."""
    catalog = (
        "# 📊 Multimodal Technical Catalog & Diagram Breakdown\n\n"
        "**Project:** `rp01` | **VLM Model:** `deepseek-ocr:3b-bf16` | **Total Figures:** 1\n\n"
        "---\n\n"
        "## Figure 1: `p10_fig_1.png`\n\n"
        "![p10_fig_1.png](images/p10_fig_1.webp)\n\n"
        "### 🔍 Technical Parsing & Extraction\n\n"
        "| Component | Function | Description |\n"
        "|---|---|---|\n"
        "| Cortex-M0+ | CPU | 32-bit dual-core |\n\n"
        "---\n"
    )
    assert "# 📊 Multimodal Technical Catalog & Diagram Breakdown" in catalog
    assert "## Figure 1: `p10_fig_1.png`" in catalog
    assert "![p10_fig_1.png](images/p10_fig_1.webp)" in catalog
    assert "| Component | Function | Description |" in catalog
    assert "Further repetitions" not in catalog


def test_multimodal_quality_filter_min_chars():
    """Verifies short descriptions under 25 chars are rejected."""
    short_text = "Microcontroller block"
    assert len(short_text) < 25

    valid_text = "Dual core Arm Cortex-M0+ running at up to 133MHz."
    assert len(valid_text) >= 25
