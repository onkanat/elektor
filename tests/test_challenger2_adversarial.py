"""
Adversarial Stress Verification Test Suite for Milestone M-FINAL (Challenger 2).

Focus Areas:
1. Broken pipe simulation mid-run (sudden stdout/stderr closure during multi-page OCR and teardown).
2. OCR/VLM sanitization, truncated streams, nested control tokens, and repetition filtering.
3. Host offline simulation and rapid endpoint switching between LAN and localhost.
4. Resource leak checks: database connection management and locks.
"""

import io
import os
import sys
import time
import socket
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pypdf
import pytest
from PIL import Image

from pipeline.project_logger import BrokenPipeShield, safe_print, safe_close_db
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
from pipeline.extractor import ArchiveExtractor


# ============================================================================
# 1. BROKEN PIPE & CLOSED STREAM SIMULATION MID-RUN
# ============================================================================

def test_safe_print_closed_file_descriptor_raises_value_error():
    """VERIFICATION: safe_print catches BrokenPipeError, IOError, and ValueError.
    When a stream is closed (e.g. sys.stdout.close() on pipe teardown), safe_print
    handles ValueError gracefully and redirects output to os.devnull.
    """
    saved_stdout = sys.stdout
    fake_stream = io.StringIO()
    fake_stream.close()
    sys.stdout = fake_stream

    try:
        # safe_print must be immune to closed streams and NOT raise ValueError
        safe_print("Message to closed stream", flush=True)
    except ValueError as e:
        pytest.fail(f"safe_print failed to handle closed stream: {e}")
    finally:
        sys.stdout = saved_stdout


def test_unshielded_print_in_extract_pages_range_crashes_on_broken_pipe(tmp_path):
    """VERIFICATION: extract_pages_range uses safe_print to guard against BrokenPipeError."""
    writer = pypdf.PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=300, height=300)

    pdf_path = tmp_path / "multi_page_ocr.pdf"
    with open(pdf_path, "wb") as f:
        writer.write(f)

    db_path = tmp_path / "test_extract.db"
    cfg = {
        "db_path": str(db_path),
        "ocr_threshold": 1000,
        "enable_vision_ocr": True,
        "model_vision": "mock"
    }
    extractor = ArchiveExtractor(config_dict=cfg)

    # Broken pipe occurs when print() is invoked
    with patch("builtins.print", side_effect=BrokenPipeError("EPIPE: stdout pipe closed mid-run")):
        try:
            extractor.extract_pages_range(pdf_path, 0, 2)
        except BrokenPipeError:
            pytest.fail("extract_pages_range must swallow BrokenPipeError via safe_print")

    extractor.close()


def test_extractor_ocr_pdf_pages_str_path_attribute_error(tmp_path):
    """VERIFICATION: ArchiveExtractor.ocr_pdf_pages converts pdf_path to Path object if passed str."""
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    pdf_path = tmp_path / "str_path_test.pdf"
    with open(pdf_path, "wb") as f:
        writer.write(f)

    extractor = ArchiveExtractor(config_dict={"db_path": str(tmp_path / "test.db")})
    try:
        # Pass pdf_path as str instead of Path; should NOT raise AttributeError
        res = extractor.ocr_pdf_pages(str(pdf_path), 0, 0)
        assert isinstance(res, (tuple, list))
    except AttributeError as e:
        pytest.fail(f"ocr_pdf_pages must accept str path without AttributeError: {e}")
    finally:
        extractor.close()


# ============================================================================
# 2. SANITIZATION, TRUNCATED STREAMS, NESTED TOKENS & REPETITION FILTER
# ============================================================================

def test_nested_think_tags_leak_internal_reasoning():
    """VERIFICATION: clean_vlm_response iteratively strips nested <think> tags."""
    input_text = "<think><think>sub-thought</think>outer thinking leaked</think>\n# Register Map\nValid text."
    cleaned = clean_vlm_response(input_text)
    assert "outer thinking leaked" not in cleaned, "Nested thought content must be cleanly stripped"
    assert "sub-thought" not in cleaned
    assert "# Register Map" in cleaned


def test_llama3_header_tokens_leak_role_names():
    """VERIFICATION: Llama 3 header tags block regex runs before individual token stripping,
    preventing role names like 'assistant' or 'system' from leaking.
    """
    input_text = "<|start_header_id|>assistant<|end_header_id|>\nOutput markdown."
    cleaned = clean_vlm_response(input_text)
    assert not cleaned.startswith("assistant"), f"Role 'assistant' must NOT leak: {cleaned!r}"
    assert "Output markdown." in cleaned

    system_text = "<|start_header_id|>system<|end_header_id|>\nYou are a helpful AI.<|eot_id|>\n# Real Content"
    cleaned_sys = clean_vlm_response(system_text)
    assert "system" not in cleaned_sys, f"Role 'system' must NOT leak: {cleaned_sys!r}"


def test_unclosed_think_wipes_subsequent_markdown_structure():
    """BEHAVIORAL EDGE CASE: If a generation cuts off inside an unclosed <think> tag,
    clean_vlm_response wipes out ALL remaining text to end-of-string even if valid markdown follows.
    """
    input_text = "Preamble.\n<think>Thinking about registers...\n# Valid Header\nRegister data."
    cleaned = clean_vlm_response(input_text)
    # The entire remaining document is wiped because of re.DOTALL on unclosed tag
    assert cleaned == "Preamble."
    assert "Valid Header" not in cleaned


def test_repetition_filter_truncates_valid_tables_without_outer_pipes():
    """VERIFICATION: filter_repetition_anti_loop recognizes CommonMark/GFM tables without
    outer pipes as valid tables and does not truncate them with metatext.
    """
    table_block = (
        "Register | Offset | Type | Description\n"
        "---|---|---|---\n"
        "CTRL | 0x00 | RW | Control register\n"
        "STATUS | 0x04 | RO | Status register"
    )
    # Repeat the register table across 6 peripheral blocks
    full_text = "\n\n".join([f"### Section {i}\n" + table_block for i in range(6)])
    cleaned = filter_repetition_anti_loop(full_text)

    assert "*(Further repetitions of" not in cleaned, "Repetition filter must NOT corrupt valid table syntax"
    assert cleaned.count("Register | Offset | Type | Description") == 6


def test_multi_section_tables_with_outer_pipes_are_preserved():
    """CONFIRMATION OF CORRECTNESS: Multi-section tables formatted with standard outer pipes
    preserve repeated table headers and row structures without truncation.
    """
    table_block = (
        "| Register | Offset | Type | Description |\n"
        "|---|---|---|---|\n"
        "| CTRL | 0x00 | RW | Control register |\n"
        "| STATUS | 0x04 | RO | Status register |"
    )
    full_text = "\n\n".join([f"### Block {i}\n" + table_block for i in range(10)])
    cleaned = filter_repetition_anti_loop(full_text)
    assert cleaned.count("| Register | Offset | Type | Description |") == 10
    assert "*(Further repetitions" not in cleaned


# ============================================================================
# 3. HOST OFFLINE SIMULATION & RAPID ENDPOINT SWITCHING
# ============================================================================

def test_resilient_ollama_client_repeats_timeout_on_every_call():
    """VERIFICATION: ResilientOllamaClient caches the active fallback URL after failover,
    preventing repeated timeouts on subsequent calls.
    """
    client = ResilientOllamaClient(
        primary_url="http://192.168.1.250:11434",
        fallback_url="http://127.0.0.1:11434",
        timeout=0.05
    )

    call_urls = []
    def mock_urlopen(req, timeout=None):
        call_urls.append(req.full_url)
        if "192.168.1.250" in req.full_url:
            raise socket.timeout("Primary offline")
        import json
        m = MagicMock()
        m.read.return_value = json.dumps({"response": "Fallback ok"}).encode("utf-8")
        ctx = MagicMock()
        ctx.__enter__.return_value = m
        return ctx

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        for i in range(3):
            res = client.generate("test-model", f"prompt {i}")
            assert res == "Fallback ok"

    # Dead primary should only be attempted once; subsequent calls use cached active fallback
    assert call_urls.count("http://192.168.1.250:11434/api/generate") == 1
    assert call_urls.count("http://127.0.0.1:11434/api/generate") == 3


def test_vision_ocr_convert_document_fails_to_fallback_to_localhost(tmp_path):
    """VERIFICATION: VisionOCRManager.convert_document_to_markdown falls back to
    localhost:11434 when configured ollama_url is unreachable.
    """
    img_path = tmp_path / "test_doc.png"
    Image.new("RGB", (30, 30), color="white").save(img_path)

    mgr = VisionOCRManager(config_dict={
        "ollama_url": "http://192.168.1.250:11434",
        "model_vision": "deepseek-ocr:3b"
    })

    def mock_urlopen(req, timeout=None):
        if "192.168.1.250" in req.full_url:
            raise urllib.error.URLError("[Errno 113] No route to host")
        # Localhost fallback mock
        import json
        m = MagicMock()
        m.read.return_value = json.dumps({"message": {"content": "# Converted Document"}}).encode("utf-8")
        ctx = MagicMock()
        ctx.__enter__.return_value = m
        return ctx

    import urllib.error
    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        with patch.object(mgr.client.chat.completions, "create", side_effect=Exception("Client unreachable")):
            res = mgr.convert_document_to_markdown(str(img_path))
            assert "# Converted Document" in res, "Must successfully fall back to localhost"


# ============================================================================
# 4. RESOURCE LEAK CHECKS: DATABASE CONNECTION LOCKING & LIFECYCLE
# ============================================================================

def test_database_locked_when_extractor_abandoned_without_close(tmp_path):
    """VERIFICATION: ArchiveExtractor.__del__ finalizer ensures connection is committed
    and closed when an instance is garbage-collected without explicit close().
    """
    db_file = tmp_path / "lock_test.db"
    cfg = {"db_path": str(db_file)}

    ext1 = ArchiveExtractor(config_dict=cfg)
    ext1.conn.execute("INSERT INTO articles (filename, title) VALUES ('test.pdf', 'Title')")

    # Abandon ext1 without explicit close() - __del__ should teardown and commit/close
    del ext1
    import gc
    gc.collect()

    # Second connection must NOT be locked
    conn2 = sqlite3.connect(str(db_file), timeout=1.0)
    conn2.execute("INSERT INTO articles (filename, title) VALUES ('test2.pdf', 'Title 2')")
    conn2.commit()
    conn2.close()


def test_safe_close_db_commits_before_closing(tmp_path):
    """CONFIRMATION OF CORRECTNESS: safe_close_db safely commits pending writes
    and closes the connection cleanly under normal teardown.
    """
    db_file = tmp_path / "safe_close.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE items (id INT);")
    conn.execute("INSERT INTO items VALUES (42);")

    safe_close_db(conn)

    verify = sqlite3.connect(str(db_file))
    row = verify.execute("SELECT id FROM items;").fetchone()
    verify.close()
    assert row[0] == 42
