"""Tier 5 Adversarial Coverage Hardening: Schemas, Boilerplate Filters, and API Concurrency.

Scope:
1. Adversarially challenge Alpaca SFT and DPO schema invariants in pipeline/dataset_builder.py:
   - Under ALL 4 flag combinations (clean_alpaca_input=True/False, filter_boilerplate=True/False),
     100% of SFT records have strictly `input: ""` and ZERO static metadata leakage (Context:... / Bağlam:...).
   - DPO records strictly contain only {"prompt", "chosen", "rejected"} with zero extraneous fields
     across standard, Turkish, and Kiwix exports.
2. Adversarially challenge Boilerplate Filtering:
   - Test mixed technical/legal strings: ensure genuine hardware IP descriptions mentioning
     Synopsys DesignWare (e.g. 'Synopsys DesignWare APB I2C controller') are preserved,
     while true copyright colophons and license notices are cleanly stripped.
   - Empirical discovery on Turkish dotted capital 'İ' handling in regex matching.
3. Adversarially challenge API Server (api_server.py):
   - Rapid concurrent POST /api/pipeline/run requests with a threading barrier to verify the lock
     rejects simultaneous runs with HTTP 400.
   - Test /api/health under simulated offline conditions to ensure model caches are cleared.
"""

import os
import sys
import json
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import httpx
from fastapi.testclient import TestClient

import api_server
from pipeline.dataset_builder import DatasetBuilder


@pytest.fixture(autouse=True)
def reset_api_server_state():
    """Ensure clean API server global state between test runs."""
    with api_server.pipeline_lock:
        api_server.pipeline_state["status"] = "idle"
        api_server.pipeline_state["command"] = None
        api_server.pipeline_state["start_time"] = None
        api_server.pipeline_state["end_time"] = None
        api_server.pipeline_state["exit_code"] = None
        api_server.pipeline_state["logs"] = []

    api_server.OLLAMA_CACHE["last_check"] = 0.0
    api_server.OLLAMA_CACHE["status"] = "offline"
    api_server.OLLAMA_CACHE["available_models"] = []
    api_server.OLLAMA_CACHE["vram_models"] = []
    api_server.OLLAMA_CACHE["ollama_online"] = False

    yield

    with api_server.pipeline_lock:
        api_server.pipeline_state["status"] = "idle"
        api_server.pipeline_state["command"] = None
        api_server.pipeline_state["start_time"] = None
        api_server.pipeline_state["end_time"] = None
        api_server.pipeline_state["exit_code"] = None
        api_server.pipeline_state["logs"] = []

    api_server.OLLAMA_CACHE["last_check"] = 0.0
    api_server.OLLAMA_CACHE["status"] = "offline"
    api_server.OLLAMA_CACHE["available_models"] = []
    api_server.OLLAMA_CACHE["vram_models"] = []
    api_server.OLLAMA_CACHE["ollama_online"] = False


def setup_adversarial_database(db_path: Path):
    """Initializes and populates a full-featured SQLite database with complex, adversarial records."""
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()

    c.execute("""
        CREATE TABLE articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT,
            filename TEXT,
            title TEXT,
            year INTEGER,
            zoom_snippet TEXT,
            extracted_text TEXT,
            is_ocr INTEGER DEFAULT 0,
            source_type TEXT DEFAULT 'pdf',
            tags TEXT,
            vote_score INTEGER,
            is_accepted INTEGER DEFAULT 0,
            is_vetoed INTEGER DEFAULT 0,
            metadata_json TEXT,
            processed_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE enrichments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER UNIQUE,
            summary TEXT,
            topics TEXT,
            turkish_title TEXT,
            turkish_summary TEXT,
            sft_qa TEXT,
            dpo_pairs TEXT,
            tr_sft_qa TEXT,
            tr_dpo_pairs TEXT,
            multi_turn_chat TEXT,
            tr_multi_turn_chat TEXT,
            is_excluded INTEGER DEFAULT 0,
            processed_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE synthetic_code_pairs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instruction TEXT,
            input_code TEXT,
            output_response TEXT,
            tr_instruction TEXT,
            tr_output_response TEXT,
            category TEXT
        )
    """)

    # 1. Standard technical article with injected attempts at metadata leakage
    c.execute("""
        INSERT INTO articles (id, filename, title, year, extracted_text)
        VALUES (1, 'arm_cortex.pdf', 'ARM Cortex-M0+ Core & Memory', 2026,
                'Hardware core overview with memory map and NVIC.')
    """)

    en_sft = [
        {
            "question": "What is the pipeline architecture of Cortex-M0+?",
            "answer": "It implements a two-stage pipelined von Neumann architecture.",
            "input": "Context: This should never leak into exported Alpaca input!",
            "extra_meta": {"leak_candidate": "leaked_string"}
        },
        {
            "question": "How are interrupts prioritized?",
            "answer": "NVIC supports up to 32 discrete interrupt requests with 4 programmable priority levels."
        }
    ]

    en_dpo = [
        {
            "question": "Does Cortex-M0+ support hardware integer division?",
            "chosen": "No, hardware division is not natively supported in Cortex-M0+; software routines or external acceleration are required.",
            "rejected": "Yes, Cortex-M0+ has a dedicated 32-bit hardware divider instruction (SDIV/UDIV).",
            "metadata": {"source": "adversarial_dpo_injector", "version": 1.0},
            "chosen_score": 9.5,
            "rejected_score": 1.2,
            "input": "Context: Should definitely be stripped from DPO triplet"
        }
    ]

    tr_sft = [
        {
            "question": "Cortex-M0+ boru hattı (pipeline) yapısı nasıldır?",
            "answer": "İki aşamalı von Neumann boru hattı mimarisini kullanır.",
            "input": "Bağlam: Bu metin Alpaca input alanına asla sızmamalıdır!",
            "context": "Ekstra metadata"
        }
    ]

    tr_dpo = [
        {
            "question": "Cortex-M0+ donanımsal bölme komutunu destekler mi?",
            "chosen": "Hayır, yerel donanımsal bölme komutu içermez, yazılımsal rutinlere dayanır.",
            "rejected": "Evet, yerleşik SDIV ve UDIV komutlarına sahiptir.",
            "baglam": "Türkçe DPO bağlam alanı sızma testi",
            "metadata": {"guvenilirlik": "yuksek"}
        }
    ]

    c.execute("""
        INSERT INTO enrichments (
            article_id, summary, turkish_title, turkish_summary,
            sft_qa, dpo_pairs, tr_sft_qa, tr_dpo_pairs
        ) VALUES (
            1,
            'Comprehensive technical manual for ARM Cortex-M0+ embedded processor with register sets.',
            'ARM Cortex-M0+ Gömülü İşlemci Mimarisi',
            'ARM Cortex-M0+ gömülü işlemcisinin kayıt kümeleri ve NVIC birimini ele alan teknik analiz.',
            ?, ?, ?, ?
        )
    """, (
        json.dumps(en_sft, ensure_ascii=False),
        json.dumps(en_dpo, ensure_ascii=False),
        json.dumps(tr_sft, ensure_ascii=False),
        json.dumps(tr_dpo, ensure_ascii=False)
    ))

    # 2. Kiwix StackExchange article with complex metadata and extraneous DPO attributes
    kiwix_meta = {
        "tags": ["embedded", "i2c", "hardware", "dma"],
        "question_body": "Why does the I2C bus lock up when clock stretching is initiated by an external EEPROM during high-speed DMA transfers?",
        "sft_qa": {
            "question": "I2C clock stretching DMA lockup resolution",
            "answer": "Toggle SCL 9 times manually via GPIO bit-banging to force the slave to release SDA before re-enabling DMA."
        },
        "dpo_pairs": [
            {
                "chosen": "Execute 9 manual SCL clock pulses using GPIO bit-bang mode and verify SDA goes high before resetting I2C controller registers.",
                "rejected": "Hard power-cycle the entire PCB board using a relay whenever bus hangs.",
                "chosen_score": 45,
                "rejected_score": -12,
                "chosen_is_accepted": True,
                "metadata": {"reviewer": "expert", "votes": 128},
                "input": "Context: Kiwix input field leakage candidate",
                "extra_extraneous_field": "remove_me"
            }
        ]
    }

    c.execute("""
        INSERT INTO articles (
            filename, title, year, source_type, tags, vote_score, is_accepted, metadata_json
        ) VALUES (
            'electronics.stackexchange.zim',
            'I2C Bus Lockup Resolution with Clock Stretching',
            2026,
            'stackexchange',
            'embedded, i2c, hardware, dma',
            45,
            1,
            ?
        )
    """, (json.dumps(kiwix_meta),))

    # 3. Synthetic code pairs with code input and pure instructions
    c.execute("""
        INSERT INTO synthetic_code_pairs (
            instruction, input_code, output_response, tr_instruction, tr_output_response, category
        ) VALUES (
            'Optimize this interrupt service routine for minimal execution latency.',
            'void isr_handler(void) {\n    read_uart();\n    log_to_sd();\n}',
            'void isr_handler(void) {\n    uart_buffer[idx++] = UART->DR;\n    flag = 1;\n}',
            'Bu kesme servis rutinini (ISR) minimum yürütme gecikmesi için optimize edin.',
            'void isr_handler(void) {\n    uart_buffer[idx++] = UART->DR;\n    flag = 1;\n}',
            'bug_fix'
        )
    """)

    c.execute("""
        INSERT INTO synthetic_code_pairs (
            instruction, input_code, output_response, tr_instruction, tr_output_response, category
        ) VALUES (
            'Explain how DMA double buffering prevents buffer underrun in audio streaming.',
            '',
            'Double buffering allows the DMA engine to fill buffer B while the DAC plays from buffer A, swapping seamlessly on interrupt.',
            'Çift tamponlamanın (double buffering) ses akışında tampon boşalmasını (underrun) nasıl önlediğini açıklayın.',
            'Çift tamponlama, DAC A tamponundan veri okurken DMA motorunun B tamponunu doldurmasına olanak tanır.',
            'educational'
        )
    """)

    conn.commit()
    conn.close()


# ============================================================================
# SUITE 1: Adversarial Schema Invariant Flag Matrix (4 Combinations)
# ============================================================================

@pytest.mark.parametrize("clean_alpaca_input,filter_boilerplate", [
    (True, True),
    (True, False),
    (False, True),
    (False, False)
])
def test_adversarial_sft_and_dpo_schema_flag_matrix(clean_alpaca_input, filter_boilerplate):
    """Stress-test Alpaca SFT and DPO schema invariants across ALL combinations of flags.

    Invariants:
    1. 100% of SFT records in all exported JSONL files have strictly `input: ""` (empty string).
    2. Zero static metadata leakage (`Context:...` or `Bağlam:...`) in `input`.
    3. Exactly 3 keys in standard SFT: `{"instruction", "input", "output"}`.
    4. 100% of DPO records across standard, Turkish, and Kiwix exports strictly contain only
       `{"prompt", "chosen", "rejected"}` with zero extraneous fields (no input, no metadata, no score).
    """
    with tempfile.TemporaryDirectory(prefix="adv_schema_matrix_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "matrix_test.db"
        export_dir = tmp_path / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        config_path = tmp_path / "config.json"

        setup_adversarial_database(db_path)

        cfg = {
            "db_path": str(db_path),
            "dataset_name": "Elektor Embedded Matrix",
            "dataset_name_tr": "Elektor Gömülü Matris",
            "generation_language": "bilingual",
            "clean_alpaca_input": clean_alpaca_input,
            "filter_boilerplate": filter_boilerplate
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)

        builder = DatasetBuilder(config_path=str(config_path))
        builder.export_dir = export_dir
        builder.export_datasets()

        # --- 1. Audit ALL SFT Export Files ---
        sft_files = [
            export_dir / "sft_dataset.jsonl",
            export_dir / "tr_sft_dataset.jsonl",
            export_dir / "code_sft_dataset.jsonl",
            export_dir / "tr_code_sft_dataset.jsonl"
        ]

        total_sft_evaluated = 0
        for sft_file in sft_files:
            assert sft_file.exists(), f"Expected SFT file missing: {sft_file}"
            with open(sft_file, "r", encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]

            assert len(records) > 0, f"SFT file {sft_file.name} must not be empty"
            for rec in records:
                total_sft_evaluated += 1
                # Invariant 1: input must be strictly empty string ""
                assert isinstance(rec["input"], str), f"input must be string in {rec}"
                assert rec["input"] == "", f"input must be strictly empty string, got: {rec['input']!r}"
                assert len(rec["input"]) == 0, f"input length must be 0, got {len(rec['input'])}"

                # Invariant 2: ZERO static metadata leakage
                assert "Context:" not in rec["input"], f"Context static leakage found in input: {rec}"
                assert "Bağlam:" not in rec["input"], f"Bağlam static leakage found in input: {rec}"

                # Invariant 3: Exact key set
                assert set(rec.keys()) == {"instruction", "input", "output"}, (
                    f"Extraneous or missing keys in SFT record: {rec.keys()}"
                )
                assert len(rec["instruction"].strip()) > 0, "instruction must not be blank"
                assert len(rec["output"].strip()) > 0, "output must not be blank"

        assert total_sft_evaluated >= 8, f"Expected at least 8 evaluated SFT records, got {total_sft_evaluated}"

        # --- 2. Audit ALL DPO Export Files ---
        dpo_files = [
            export_dir / "dpo_dataset.jsonl",
            export_dir / "tr_dpo_dataset.jsonl"
        ]

        total_dpo_evaluated = 0
        for dpo_file in dpo_files:
            assert dpo_file.exists(), f"Expected DPO file missing: {dpo_file}"
            with open(dpo_file, "r", encoding="utf-8") as f:
                dpo_records = [json.loads(line) for line in f if line.strip()]

            assert len(dpo_records) > 0, f"DPO file {dpo_file.name} must not be empty"
            for d_rec in dpo_records:
                total_dpo_evaluated += 1
                # Invariant 4: Exact triplet keys
                assert set(d_rec.keys()) == {"prompt", "chosen", "rejected"}, (
                    f"DPO record has invalid key schema: {d_rec.keys()} in {dpo_file.name}"
                )
                assert len(d_rec.keys()) == 3, f"DPO record must have exactly 3 keys, got {len(d_rec.keys())}"

                # Invariant 5: Zero extraneous fields
                for banned_field in [
                    "input", "metadata", "score", "chosen_score", "rejected_score",
                    "chosen_is_accepted", "context", "baglam", "extra_extraneous_field"
                ]:
                    assert banned_field not in d_rec, (
                        f"Extraneous field '{banned_field}' leaked into DPO record: {d_rec}"
                    )

                assert len(d_rec["prompt"].strip()) > 0, "DPO prompt must not be blank"
                assert len(d_rec["chosen"].strip()) > 0, "DPO chosen must not be blank"
                assert len(d_rec["rejected"].strip()) > 0, "DPO rejected must not be blank"

        assert total_dpo_evaluated >= 3, f"Expected at least 3 evaluated DPO records, got {total_dpo_evaluated}"


# ============================================================================
# SUITE 2: High-Volume Adversarial Schema Fuzzing
# ============================================================================

def test_high_volume_adversarial_schema_fuzzer():
    """Generates 50+ diverse adversarial records containing edge-case characters,
    nested structures, and malicious injection payloads to ensure 100% schema compliance.
    """
    with tempfile.TemporaryDirectory(prefix="fuzz_schema_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "fuzz.db"
        export_dir = tmp_path / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        config_path = tmp_path / "config.json"

        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        c.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, year INTEGER, extracted_text TEXT)")
        c.execute("""
            CREATE TABLE enrichments (
                id INTEGER PRIMARY KEY, article_id INTEGER UNIQUE, summary TEXT,
                turkish_title TEXT, turkish_summary TEXT, sft_qa TEXT, dpo_pairs TEXT,
                tr_sft_qa TEXT, tr_dpo_pairs TEXT, is_excluded INTEGER DEFAULT 0
            )
        """)

        # Generate 25 articles with adversarial Q&A payloads
        for i in range(1, 26):
            title = f"Adversarial Article {i}: Synopsys DesignWare Macrocell {i}"
            c.execute("INSERT INTO articles (id, title, year, extracted_text) VALUES (?, ?, ?, ?)",
                      (i, title, 2026, f"Technical details for core {i}."))

            qa_list = [
                {
                    "question": f"Question #{i} with Context: inside text and Turkish chars: ğüşiöç İI?",
                    "answer": f"Answer #{i} with Bağlam: inside body.",
                    "input": f"Adversarial input payload #{i} Context: leak",
                    "metadata": {"nested": {"depth": i}}
                }
            ]
            dpo_list = [
                {
                    "question": f"DPO Prompt #{i} - Synopsys DesignWare APB frequency {i}MHz?",
                    "chosen": f"Chosen response #{i} without boilerplate.",
                    "rejected": f"Rejected response #{i}.",
                    "input": f"Context: leaked input {i}",
                    "metadata": f"meta_{i}",
                    "extra_key": 12345
                }
            ]
            c.execute("""
                INSERT INTO enrichments (
                    article_id, summary, turkish_title, turkish_summary,
                    sft_qa, dpo_pairs, tr_sft_qa, tr_dpo_pairs
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                i,
                f"Summary #{i} describing Synopsys DesignWare macrocell peripheral configuration.",
                f"Türkçe Başlık #{i}",
                f"Türkçe Özet #{i} Synopsys DesignWare çevre birimi hakkında detaylı bilgi içerir.",
                json.dumps(qa_list, ensure_ascii=False),
                json.dumps(dpo_list, ensure_ascii=False),
                json.dumps(qa_list, ensure_ascii=False),
                json.dumps(dpo_list, ensure_ascii=False)
            ))

        conn.commit()
        conn.close()

        cfg = {
            "db_path": str(db_path),
            "dataset_name": "Fuzz Dataset",
            "dataset_name_tr": "Fuzz Veriseti",
            "generation_language": "bilingual",
            "clean_alpaca_input": False,
            "filter_boilerplate": True
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)

        builder = DatasetBuilder(config_path=str(config_path))
        builder.export_dir = export_dir
        builder.export_datasets()

        # Audit SFT
        sft_file = export_dir / "sft_dataset.jsonl"
        with open(sft_file, "r", encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]

        assert len(records) >= 25
        for r in records:
            assert r["input"] == "", f"Fuzzed record input must be empty string: {r}"
            assert set(r.keys()) == {"instruction", "input", "output"}
            assert "Context:" not in r["input"]
            assert "Bağlam:" not in r["input"]

        # Audit DPO
        dpo_file = export_dir / "dpo_dataset.jsonl"
        with open(dpo_file, "r", encoding="utf-8") as f:
            dpo_recs = [json.loads(line) for line in f if line.strip()]

        assert len(dpo_recs) >= 25
        for dr in dpo_recs:
            assert set(dr.keys()) == {"prompt", "chosen", "rejected"}
            assert "input" not in dr
            assert "metadata" not in dr
            assert "extra_key" not in dr


# ============================================================================
# SUITE 3: Adversarial Boilerplate & Hardware IP Preservation
# ============================================================================

def test_boilerplate_hardware_ip_preservation_vs_legal_colophons():
    """Adversarially challenge Boilerplate Filtering:
    - Ensure genuine hardware IP descriptions mentioning Synopsys DesignWare
      (e.g. 'Synopsys DesignWare APB I2C controller') are preserved.
    - Ensure true copyright colophons, licenses, and disclaimers are cleanly stripped.
    """
    # 1. Direct Text Classifier Vectors
    genuine_hardware_cases = [
        "The RP2040 integrates two identical instances of the Synopsys DesignWare APB I2C controller IP.",
        "Synopsys DesignWare APB I2C controller operates at up to 400kHz in fast mode.",
        "The bootrom initializes the Synopsys DesignWare Synchronous Serial Interface (SSI) for quad SPI memory execution.",
        "Synopsys DesignWare UART interface features 32-byte FIFO transmit and receive buffers.",
        "The Synopsys DesignWare timer macrocell provides deterministic microsecond interrupt generation.",
        "Synopsys DesignWare APB GPIO peripheral pin multiplexing controls hardware signals.",
        "Synopsys DW_apb_i2c macrocell timing parameters configure SCL and SDA bus setup/hold margins.",
        "The RP2040 microcontroller embeds two Synopsys DesignWare IP cores for deterministic peripheral control.",
        "Synopsys DesignWare core clock domain crossing architecture ensures metastable-free register access.",
        "Synopsys DesignWare high-speed USB 2.0 transceiver PHY integration supports OTG protocols.",
        # Turkish hardware sentences
        "RP2040, bünyesinde iki adet Synopsys DesignWare APB I2C denetleyicisi barındırır.",
        "Synopsys DesignWare SSI arayüzü dörtlü SPI (QSPI) flaş bellek ile doğrudan kod yürütmeyi (XIP) sağlar.",
        "Synopsys DesignWare UART çevre birimi donanımsal akış denetimini (RTS/CTS) yönetir."
    ]

    for hw_text in genuine_hardware_cases:
        is_bp = DatasetBuilder.is_boilerplate_text(hw_text)
        assert not is_bp, f"False positive! Genuine hardware IP marked as boilerplate: {hw_text}"

    true_legal_boilerplate_cases = [
        "Portions copyright Synopsys Inc. 2021-2026. All rights reserved.",
        "Copyright Synopsys 2026.",
        "Synopsys copyright notice: proprietary and confidential.",
        "Copyright (c) 2026 Raspberry Pi Trading Ltd. All rights reserved.",
        "Portions copyright ARM Limited. All rights reserved.",
        "Licensed under Creative Commons Attribution-NoDerivatives 4.0 International (CC BY-ND 4.0).",
        "This document is distributed under CC-BY license terms.",
        "Disclaimer: Raspberry Pi Ltd makes no warranty of merchantability or fitness for a particular purpose.",
        "This product is not designed, intended, or authorized for use in high risk activities.",
        "The customer shall indemnify, defend, and hold harmless the licensor from all claims.",
        "Table of Contents for Chapter 3.",
        "içindekiler bölümü: sayfa 1-10.",
        "Fihrist ve genel dizin.",
        "Telif hakkı üretici firmaya aittir. Tüm hakları saklıdır.",
        "Lisans şartları ve garanti muafiyeti metni.",
        "Yasal uyarı: Bu belgedeki veriler önceden bildirilmeksizin değiştirilebilir.",
        "Standard terms and conditions of commercial sale.",
        "Colophon: Typeset in LaTeX and printed in the United Kingdom.",
        "Build-date: 2026-03-01, Build-version: 1.0.4-rc2"
    ]

    for bp_text in true_legal_boilerplate_cases:
        is_bp = DatasetBuilder.is_boilerplate_text(bp_text)
        assert is_bp, f"False negative! Legal boilerplate was NOT detected: {bp_text}"

    # 2. Article Classifier Vectors
    assert not DatasetBuilder.is_boilerplate_article("Synopsys DesignWare APB I2C Controller Architecture")
    assert not DatasetBuilder.is_boilerplate_article("RP2040 Memory System & Synopsys DesignWare SSI Interface")
    assert DatasetBuilder.is_boilerplate_article("Colophon")
    assert DatasetBuilder.is_boilerplate_article("Table of Contents")
    assert DatasetBuilder.is_boilerplate_article("içindekiler ve Fihrist")
    assert DatasetBuilder.is_boilerplate_article("Legal Disclaimer & Indemnification")
    assert DatasetBuilder.is_boilerplate_article("Document Revision History")


def test_adversarial_turkish_dotted_i_evasion_finding():
    """Empirically demonstrates and audits the Turkish dotted capital 'İ' regex boundary vulnerability.

    Finding:
    Python's standard `str.lower()` converts the uppercase Turkish dotted letter 'İ' (U+0130)
    into 'i' (U+0069) combined with U+0307 (Combining Dot Above).
    As a result, regular expressions checking `r'\\biçindekiler\\b'` match lowercase 'içindekiler',
    but fail to match capitalized 'İçindekiler' unless text is normalized or pattern includes combining dot.
    """
    lower_case_toc = "içindekiler ve fihrist listesi"
    upper_case_toc = "İçindekiler ve fihrist listesi"

    # Lowercase is successfully recognized
    assert DatasetBuilder.is_boilerplate_text(lower_case_toc) is True

    # Note: 'fihrist' in upper_case_toc triggers the filter regardless
    assert DatasetBuilder.is_boilerplate_text(upper_case_toc) is True

    # When isolated: lowercase is recognized
    assert DatasetBuilder.is_boilerplate_text("içindekiler") is True

    # Empirical probe: isolated uppercase 'İçindekiler' bypasses standard regex due to U+0307
    upper_isolated_matches = DatasetBuilder.is_boilerplate_text("İçindekiler")
    # We verify the exact behavior for empirical transparency:
    # 'İçindekiler'.lower() produces 'i\u0307çindekiler', revealing the subtle edge case.
    if not upper_isolated_matches:
        # Confirmed vulnerability: capitalized Turkish TOC bypasses word-boundary regex
        assert "i\u0307çindekiler" == "İçindekiler".lower()


def test_boilerplate_database_cleaner_and_export_defense():
    """Verifies that clean_database_boilerplate and export_datasets cleanly prune legal
    colophons while rigorously preserving legitimate Synopsys DesignWare hardware Q&A pairs.
    """
    with tempfile.TemporaryDirectory(prefix="adv_bp_clean_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "bp_test.db"
        export_dir = tmp_path / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        config_path = tmp_path / "config.json"

        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        c.execute("""
            CREATE TABLE articles (
                id INTEGER PRIMARY KEY, filename TEXT, title TEXT, year INTEGER, extracted_text TEXT
            )
        """)
        c.execute("""
            CREATE TABLE enrichments (
                id INTEGER PRIMARY KEY, article_id INTEGER UNIQUE, summary TEXT,
                topics TEXT, turkish_title TEXT, turkish_summary TEXT,
                sft_qa TEXT, dpo_pairs TEXT, tr_sft_qa TEXT, tr_dpo_pairs TEXT,
                is_excluded INTEGER DEFAULT 0
            )
        """)

        # Article 1: Legitimate hardware article with MIXED Q&As (hardware IP + legal)
        c.execute("""
            INSERT INTO articles (id, filename, title, year, extracted_text)
            VALUES (1, 'dw_i2c.pdf', 'Synopsys DesignWare APB I2C Peripheral Architecture', 2026,
                    'The RP2040 embeds the Synopsys DesignWare APB I2C controller for high-speed bus arbitration.')
        """)

        mixed_sft = [
            # Legitimate Hardware IP Q&As -> MUST BE PRESERVED
            {
                "question": "Which peripheral IP core powers the I2C interfaces on the RP2040?",
                "answer": "The RP2040 utilizes the Synopsys DesignWare APB I2C controller core for both I2C0 and I2C1."
            },
            {
                "question": "What register controls clock frequency in the Synopsys DesignWare I2C block?",
                "answer": "The IC_FS_SCL_HCNT and IC_FS_SCL_LCNT registers in the Synopsys DesignWare core configure SCL timing."
            },
            # Legal / Copyright Boilerplate Q&As -> MUST BE PRUNED
            {
                "question": "Who owns Synopsys copyright in the documentation colophon?",
                "answer": "Portions copyright Synopsys Inc 2026. All rights reserved."
            },
            {
                "question": "What license and standard terms apply to this document?",
                "answer": "This document is distributed under Creative Commons CC BY-ND 4.0 license."
            }
        ]

        mixed_dpo = [
            # Legitimate Hardware IP DPO -> MUST BE PRESERVED
            {
                "question": "Can the Synopsys DesignWare I2C controller operate in high-speed mode?",
                "chosen": "Yes, the Synopsys DesignWare controller supports standard, fast, and high-speed modes up to 3.4MHz.",
                "rejected": "No, it is strictly limited to 100kHz standard mode."
            },
            # Legal Disclaimer DPO -> MUST BE PRUNED
            {
                "question": "Is the RP2040 covered by standard terms for high risk activities?",
                "chosen": "No, the legal disclaimer specifically excludes warranty for high risk activities.",
                "rejected": "Yes, it is fully certified for high risk activities."
            }
        ]

        c.execute("""
            INSERT INTO enrichments (id, article_id, summary, sft_qa, dpo_pairs, is_excluded)
            VALUES (1, 1, 'Technical architecture of the Synopsys DesignWare I2C peripheral.', ?, ?, 0)
        """, (json.dumps(mixed_sft, ensure_ascii=False), json.dumps(mixed_dpo, ensure_ascii=False)))

        # Article 2: Pure colophon & legal article -> ENTIRE ARTICLE MUST BE EXCLUDED
        c.execute("""
            INSERT INTO articles (id, filename, title, year, extracted_text)
            VALUES (2, 'colophon.pdf', 'Datasheet Colophon & Table of Contents', 2026,
                    'Colophon: Portions copyright Synopsys Inc. All rights reserved. Disclaimer: high risk activities.')
        """)
        c.execute("""
            INSERT INTO enrichments (id, article_id, summary, sft_qa, dpo_pairs, is_excluded)
            VALUES (2, 2, 'Colophon text', '[]', '[]', 0)
        """)

        conn.commit()
        conn.close()

        cfg = {
            "db_path": str(db_path),
            "dataset_name": "Boilerplate Test",
            "generation_language": "en",
            "clean_alpaca_input": True,
            "filter_boilerplate": True
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)

        builder = DatasetBuilder(config_path=str(config_path))
        builder.export_dir = export_dir

        # 1. Run database boilerplate cleaner
        clean_res = builder.clean_database_boilerplate()
        assert clean_res["status"] == "success"
        assert clean_res["excluded_articles"] == 1, "Article 2 (colophon) must be excluded"
        assert clean_res["pruned_qas"] >= 3, "At least 3 boilerplate Q&As should be pruned from Article 1"

        # Verify Article 1 remains active while Article 2 is marked is_excluded=1
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        c.execute("SELECT article_id, is_excluded, sft_qa, dpo_pairs FROM enrichments ORDER BY article_id")
        rows = c.fetchall()
        conn.close()

        art1_id, art1_excluded, art1_sft_str, art1_dpo_str = rows[0]
        art2_id, art2_excluded, _, _ = rows[1]

        assert art1_excluded == 0, "Hardware IP article must NOT be excluded!"
        assert art2_excluded == 1, "Colophon article MUST be excluded!"

        art1_sft = json.loads(art1_sft_str)
        art1_dpo = json.loads(art1_dpo_str)

        # In Article 1: 2 hardware SFT Q&As preserved, 2 legal SFT pruned
        assert len(art1_sft) == 2, f"Expected 2 preserved hardware SFT Q&As, got {len(art1_sft)}"
        for q_item in art1_sft:
            assert "Synopsys DesignWare" in q_item["question"] or "Synopsys DesignWare" in q_item["answer"]
            assert "copyright" not in q_item["question"].lower()
            assert "creative commons" not in q_item["answer"].lower()

        # In Article 1: 1 hardware DPO pair preserved, 1 legal DPO pruned
        assert len(art1_dpo) == 1, f"Expected 1 preserved hardware DPO pair, got {len(art1_dpo)}"
        assert "Synopsys DesignWare" in art1_dpo[0]["question"]
        assert "high risk activities" not in art1_dpo[0]["chosen"].lower()

        # 2. Run export datasets
        builder.export_datasets()

        sft_path = export_dir / "sft_dataset.jsonl"
        dpo_path = export_dir / "dpo_dataset.jsonl"
        assert sft_path.exists()
        assert dpo_path.exists()

        with open(sft_path, "r", encoding="utf-8") as f:
            exported_sft = [json.loads(line) for line in f if line.strip()]
        with open(dpo_path, "r", encoding="utf-8") as f:
            exported_dpo = [json.loads(line) for line in f if line.strip()]

        # Hardware IP is rigorously preserved in published datasets
        assert any("Synopsys DesignWare" in r["instruction"] for r in exported_sft)
        assert any("Synopsys DesignWare" in r["output"] for r in exported_sft)
        assert any("Synopsys DesignWare" in r["prompt"] for r in exported_dpo)
        assert any("Synopsys DesignWare" in r["chosen"] for r in exported_dpo)

        # Zero copyright or colophon noise in final export
        all_sft_text = " ".join(r["instruction"] + " " + r["output"] for r in exported_sft).lower()
        assert "portions copyright" not in all_sft_text
        assert "creative commons" not in all_sft_text

        all_dpo_text = " ".join(r["prompt"] + " " + r["chosen"] for r in exported_dpo).lower()
        assert "high risk activities" not in all_dpo_text


# ============================================================================
# SUITE 4: API Concurrency & Lock Rejection Stress Harness
# ============================================================================

def test_api_concurrency_rapid_burst_rejects_with_400():
    """Adversarially challenge API Server (api_server.py) concurrency:
    - Rapid concurrent POST /api/pipeline/run requests across 25 simultaneous threads.
    - Synchronized with a threading barrier to ensure all threads hit the endpoint at the exact same millisecond.
    - Verify that the pipeline lock allows EXACTLY 1 run to proceed (HTTP 200) and rejects
      all other 24 simultaneous attempts with HTTP 400 ('A pipeline task is already running.').
    - Verify that after completion, a subsequent run succeeds cleanly.
    """
    num_threads = 25
    barrier = threading.Barrier(num_threads)
    results = []

    def mock_run_process(*args, **kwargs):
        """Simulates an active pipeline execution for 0.15 seconds."""
        time.sleep(0.15)
        with api_server.pipeline_lock:
            api_server.pipeline_state["status"] = "completed"
            api_server.pipeline_state["end_time"] = time.time()
            api_server.pipeline_state["exit_code"] = 0

    client = TestClient(api_server.app)

    with patch("api_server.run_pipeline_process", side_effect=mock_run_process):
        def worker():
            barrier.wait()  # Synchronize all threads to launch simultaneously
            resp = client.post("/api/pipeline/run", json={"command": "pipeline"})
            results.append((resp.status_code, resp.json()))

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    # Empirical assertion of lock rejection invariants
    assert len(results) == num_threads

    success_responses = [r for r in results if r[0] == 200]
    rejected_responses = [r for r in results if r[0] == 400]
    other_responses = [r for r in results if r[0] not in [200, 400]]

    assert len(other_responses) == 0, f"Unexpected response codes: {other_responses}"
    assert len(success_responses) == 1, (
        f"Concurrency failure! Expected exactly 1 successful run, but got {len(success_responses)}"
    )
    assert len(rejected_responses) == num_threads - 1, (
        f"Expected {num_threads - 1} rejections with HTTP 400, got {len(rejected_responses)}"
    )

    # Verify error message detail in rejected responses
    for status_code, body in rejected_responses:
        assert "A pipeline task is already running" in body.get("detail", ""), (
            f"Expected 'A pipeline task is already running', got: {body}"
        )

    # Wait briefly for mock task to finish and check status endpoint
    time.sleep(0.2)
    status_resp = client.get("/api/pipeline/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "completed"

    # Subsequent run must now succeed cleanly
    with patch("api_server.run_pipeline_process", side_effect=mock_run_process):
        subsequent_resp = client.post("/api/pipeline/run", json={"command": "pipeline"})
        assert subsequent_resp.status_code == 200
        assert subsequent_resp.json()["status"] == "started"


def test_api_pipeline_run_validation_safety():
    """Verifies that invalid commands and unconfirmed resets are safely rejected with HTTP 400
    without leaking lock state or initiating background processes.
    """
    client = TestClient(api_server.app)

    # Invalid command
    resp_invalid = client.post("/api/pipeline/run", json={"command": "malicious_subcommand"})
    assert resp_invalid.status_code == 400
    assert "Geçersiz komut" in resp_invalid.json()["detail"]

    # Reset without confirmation
    resp_unconfirmed = client.post("/api/pipeline/run", json={"command": "pipeline", "reset": True, "confirm_reset": False})
    assert resp_unconfirmed.status_code == 400
    assert "GÜVENLİK UYARISI" in resp_unconfirmed.json()["detail"]

    # Lock was not acquired and status remains idle
    status_resp = client.get("/api/pipeline/status")
    assert status_resp.json()["status"] == "idle"


# ============================================================================
# SUITE 5: API Health Check Simulated Offline Resilience & Cache Eviction
# ============================================================================

@pytest.mark.asyncio
async def test_api_health_simulated_offline_clears_model_cache():
    """Adversarially challenge /api/health under simulated offline conditions:
    1. First, populate OLLAMA_CACHE with online models to simulate prior healthy operation.
    2. Then simulate network errors (ConnectError, TimeoutException, HTTP 500):
       - Verify /api/health returns ollama_online: False.
       - Verify available_models is strictly empty list [] (no stale cached models leaked!).
       - Verify OLLAMA_CACHE['vram_models'] is cleared.
    """
    original_get = httpx.AsyncClient.get

    # 1. Seed healthy online state in OLLAMA_CACHE
    api_server.OLLAMA_CACHE["last_check"] = 0.0
    api_server.OLLAMA_CACHE["status"] = "online"
    api_server.OLLAMA_CACHE["ollama_online"] = True
    api_server.OLLAMA_CACHE["available_models"] = ["qwen3.6:27b-mtp-q4_K_M", "translategemma:12b-it-q4_K_M", "nomic-embed-text"]
    api_server.OLLAMA_CACHE["vram_models"] = [{"name": "qwen3.6:27b-mtp-q4_K_M", "vram_mb": 8192}]

    # 2. Simulate Connection Refused error (ConnectError) on backend endpoints
    api_server.OLLAMA_CACHE["last_check"] = 0.0  # Force cache update
    async def mock_get_connect_error(self, url, *args, **kwargs):
        url_str = str(url)
        if "api/tags" in url_str or "models" in url_str or "api/ps" in url_str:
            raise httpx.ConnectError("Connection refused: 192.168.1.26:11434")
        return await original_get(self, url, *args, **kwargs)

    with patch.object(httpx.AsyncClient, "get", mock_get_connect_error):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_server.app), base_url="http://test") as client:
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            data = resp.json()

            assert data["status"] == "ok"
            assert data["ollama_online"] is False
            assert "offline" in data["ollama_status"]
            # Cache must be evicted: zero stale models
            assert data["available_models"] == [], f"Stale models leaked into health response: {data['available_models']}"
            assert api_server.OLLAMA_CACHE["vram_models"] == []

    # 3. Simulate Timeout error (TimeoutException) on backend endpoints
    # Re-seed online state
    api_server.OLLAMA_CACHE["last_check"] = 0.0
    api_server.OLLAMA_CACHE["status"] = "online"
    api_server.OLLAMA_CACHE["ollama_online"] = True
    api_server.OLLAMA_CACHE["available_models"] = ["stale_model:latest"]

    async def mock_get_timeout(self, url, *args, **kwargs):
        url_str = str(url)
        if "api/tags" in url_str or "models" in url_str or "api/ps" in url_str:
            raise httpx.TimeoutException("Read timed out after 3.0s")
        return await original_get(self, url, *args, **kwargs)

    with patch.object(httpx.AsyncClient, "get", mock_get_timeout):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_server.app), base_url="http://test") as client:
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            data = resp.json()

            assert data["ollama_online"] is False
            assert data["available_models"] == []
            assert api_server.OLLAMA_CACHE["vram_models"] == []

    # 4. Simulate HTTP 500 Internal Server Error from Ollama & OpenAI backend endpoints
    api_server.OLLAMA_CACHE["last_check"] = 0.0
    api_server.OLLAMA_CACHE["available_models"] = ["stale_model:latest"]

    mock_500_resp = MagicMock(status_code=500, request=MagicMock())
    async def mock_get_500(self, url, *args, **kwargs):
        url_str = str(url)
        if "api/tags" in url_str or "models" in url_str or "api/ps" in url_str:
            return mock_500_resp
        return await original_get(self, url, *args, **kwargs)

    with patch.object(httpx.AsyncClient, "get", mock_get_500):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_server.app), base_url="http://test") as client:
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            data = resp.json()

            assert data["ollama_online"] is False
            assert data["available_models"] == []
            assert api_server.OLLAMA_CACHE["vram_models"] == []
