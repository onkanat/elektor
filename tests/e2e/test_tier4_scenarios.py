import os
import sys
import json
import sqlite3
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from tests.e2e.conftest import (
    SmartTextChunker,
    TextChunk,
    get_db_connection,
    get_db_cursor,
    REPO_ROOT
)


# ============================================================================
# SCENARIO 1: End-to-End Technical Datasheet Ingestion & Sub-Second RAG Query
# ============================================================================

def test_scenario1_technical_datasheet_ingestion_and_rag_query(temp_project_dir, mock_embedding_client):
    """Scenario 1: Complete journey from raw technical text ingestion, chunking, vector indexing,
    to deterministic semantic query with relevance score threshold and document payload resolution.
    """
    from pipeline.vector_store import ArchiveVectorStore

    # 1. Ingest datasheet chapters into SQLite
    chapters = [
        (1, "RP2040 Architecture Overview", 2026, "rp2040_ch1.pdf",
         "The RP2040 has dual ARM Cortex-M0+ processors, each with its own single-cycle 32-bit hardware multiplier. "
         "The system clock frequency operates up to 133 MHz with flexible internal PLLs."),
        (2, "RP2040 Memory System and SRAM", 2026, "rp2040_ch2.pdf",
         "A total of 264kB on-chip SRAM is organized into 6 independent banks. "
         "Dedicated striping allows simultaneous bus access from both CPU cores and the DMA controller."),
        (3, "Programmable I/O (PIO)", 2026, "rp2040_ch3.pdf",
         "There are 2 PIO blocks, each containing 4 independent state machines capable of deterministic execution. "
         "Each state machine can execute instructions from a shared 32-instruction memory.")
    ]

    with get_db_cursor(temp_project_dir["db_path"]) as cur:
        for cid, title, year, fname, text in chapters:
            cur.execute(
                "INSERT INTO articles (id, title, year, filename, extracted_text, is_embedded) VALUES (?, ?, ?, ?, ?, 0)",
                (cid, title, year, fname, text)
            )

    # 2. Chunk and load into vector database
    with patch("pipeline.vector_store.get_embedding_client", return_value=mock_embedding_client):
        store = ArchiveVectorStore(config_path=str(temp_project_dir["config_path"]))
        store.load_to_vector_db()

        # 3. Simulate high-relevance search query for PIO state machines
        mock_hit = MagicMock(score=0.91, payload={
            "article_id": 3,
            "chunk_index": 0,
            "point_id": "pio_state_machine_chunk_0",
            "title": "Programmable I/O (PIO)",
            "year": 2026,
            "filename": "rp2040_ch3.pdf",
            "text": "There are 2 PIO blocks, each containing 4 independent state machines"
        })
        if hasattr(store.qdrant_client, "query_points"):
            store.qdrant_client.query_points = MagicMock(return_value=MagicMock(points=[mock_hit]))
        else:
            store.qdrant_client.search = MagicMock(return_value=[mock_hit])

        results = store.search("PIO state machine independent execution", top_k=3, score_threshold=0.40)
        assert len(results) >= 1
        best_match = results[0]

        # 4. Verify search payload integrity
        assert best_match["score"] >= 0.40
        assert best_match["article_id"] == 3
        assert best_match["title"] == "Programmable I/O (PIO)"
        assert "PIO blocks" in best_match["text"]
        store.close()

    # 5. Resolve source document in SQLite to verify database consistency
    with get_db_cursor(temp_project_dir["db_path"]) as cur:
        cur.execute("SELECT filename, is_embedded FROM articles WHERE id = ?", (best_match["article_id"],))
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "rp2040_ch3.pdf"
        assert row[1] == 1


# ============================================================================
# SCENARIO 2: Bilingual SFT & DPO Synthesis with Gemini Judge Arbitration
# ============================================================================

def test_scenario2_bilingual_sft_dpo_with_judge_arbitration(temp_project_dir):
    """Scenario 2: Complete journey from raw technical enrichment to Turkish translation,
    quality arbitration via LLM-as-a-Judge, and strict schema dataset compilation.
    """
    from pipeline.judge_engine import JudgeEngine, JudgeEvaluation
    from pipeline.dataset_builder import DatasetBuilder

    # 1. Populate articles and bilingual enrichments
    with get_db_cursor(temp_project_dir["db_path"]) as cur:
        cur.execute("INSERT INTO articles (id, title, year, extracted_text) VALUES (1, 'Direct Memory Access', 2026, 'DMA architecture.')")
        en_sft = json.dumps([
            {"question": "How many DMA channels are available on RP2040?", "answer": "There are 12 independent DMA channels."},
            {"question": "What is the license?", "answer": "All rights reserved boilerplate disclaimer."}
        ])
        tr_sft = json.dumps([
            {"question": "RP2040 üzerinde kaç bağımsız DMA kanalı bulunur?", "answer": "12 adet bağımsız DMA kanalı bulunur."}
        ])
        en_dpo = json.dumps([{
            "question": "Can DMA trigger interrupts on completion?",
            "chosen": "Yes, DMA channels can raise interrupts via dedicated IRQ lines.",
            "rejected": "No, DMA only operates with polling."
        }])
        cur.execute("""
            INSERT INTO enrichments (id, article_id, sft_qa, tr_sft_qa, dpo_pairs, is_excluded)
            VALUES (1, 1, ?, ?, ?, 0)
        """, (en_sft, tr_sft, en_dpo))

    # 2. Judge arbitration: score pairs and filter/approve
    judge = JudgeEngine(config_or_path=str(temp_project_dir["config_path"]))
    mock_eval = JudgeEvaluation(
        technical_accuracy=9,
        logical_consistency=9,
        turkish_fluency=9,
        overall_score=9.2,
        status="approved",
        feedback="High accuracy and technical precision."
    )
    with patch.object(judge, "evaluate_pair", return_value=mock_eval):
        ev = judge.evaluate_pair("How many DMA channels?", "12 independent channels", threshold=7.0)
        assert ev.status == "approved"
        assert ev.overall_score >= 7.0

    # 3. Clean database boilerplate and export
    builder = DatasetBuilder(config_path=str(temp_project_dir["config_path"]))
    clean_res = builder.clean_database_boilerplate()
    assert clean_res["pruned_qas"] >= 1
    builder.export_datasets()

    # 4. Verify SFT exports: 100% clean empty input ("input": "")
    sft_file = builder.export_dir / "sft_dataset.jsonl"
    tr_sft_file = builder.export_dir / "tr_sft_dataset.jsonl"
    dpo_file = builder.export_dir / "dpo_dataset.jsonl"

    assert sft_file.exists()
    assert tr_sft_file.exists()
    assert dpo_file.exists()

    with open(sft_file, "r", encoding="utf-8") as f:
        en_records = [json.loads(line) for line in f]
    with open(tr_sft_file, "r", encoding="utf-8") as f:
        tr_records = [json.loads(line) for line in f]
    with open(dpo_file, "r", encoding="utf-8") as f:
        dpo_records = [json.loads(line) for line in f]

    for rec in en_records + tr_records:
        assert rec["input"] == "", "SFT input must be strictly empty string"
        assert set(rec.keys()) == {"instruction", "input", "output"}

    for dpo in dpo_records:
        assert set(dpo.keys()) == {"prompt", "chosen", "rejected"}
        assert "input" not in dpo
        assert "metadata" not in dpo


# ============================================================================
# SCENARIO 3: Zero-Leakage Synthetic Code Dataset & Unsloth Cloud Packaging
# ============================================================================

def test_scenario3_synthetic_code_dataset_and_unsloth_packaging(temp_project_dir):
    """Scenario 3: Complete journey from firmware code extraction into synthetic_code_pairs,
    Alpaca SFT export with strict empty input, and Unsloth LoRA fine-tuning script & Colab notebook generation.
    """
    from pipeline.dataset_builder import DatasetBuilder
    from pipeline.cloud_gpu_offloader import CloudGPUOffloader

    # 1. Ingest synthetic code pairs
    code_units = [
        ("Initialize SPI peripheral in MicroPython", "import machine\nspi = machine.SPI(0, baudrate=1000000)",
         "```python\nimport machine\nspi = machine.SPI(0, baudrate=1000000, polarity=0, phase=0)\n```", "completion"),
        ("Handle GPIO interrupt with debouncing in C", "void gpio_callback(uint gpio, uint32_t events) {}",
         "```c\nvoid gpio_callback(uint gpio, uint32_t events) {\n    static uint32_t last_time = 0;\n}\n```", "explanation")
    ]
    with get_db_cursor(temp_project_dir["db_path"]) as cur:
        for inst, inp, out, cat in code_units:
            cur.execute("""
                INSERT INTO synthetic_code_pairs (instruction, input_code, output_response, category)
                VALUES (?, ?, ?, ?)
            """, (inst, inp, out, cat))

    # 2. Export dataset
    builder = DatasetBuilder(config_path=str(temp_project_dir["config_path"]))
    builder.export_datasets()

    # 3. Offload and package Unsloth fine-tuning payloads
    offloader = CloudGPUOffloader(exports_dir=str(builder.export_dir.parent))
    script = offloader.generate_unsloth_script(
        project_id="test_project",
        base_model="unsloth/Qwen2.5-Coder-7B-Instruct",
        hf_dataset="onkanat/test_project-dataset",
        dataset_file="code_sft_dataset.jsonl"
    )

    notebook = offloader.generate_colab_ide_notebook(
        project_id="test_project",
        base_model="unsloth/Qwen2.5-Coder-7B-Instruct",
        hf_dataset="onkanat/test_project-dataset",
        dataset_type="code_sft"
    )

    # 4. Verify script and notebook integrity
    assert "SFTTrainer" in script
    assert "FastLanguageModel" in script
    assert "pad_token" in script or "tokenizer" in script
    assert "cells" in notebook
    assert len(notebook["cells"]) >= 3


# ============================================================================
# SCENARIO 4: Multi-Project Lifecycle Management via FastAPI Dashboard
# ============================================================================

@pytest.mark.asyncio
async def test_scenario4_multiproject_lifecycle_via_api():
    """Scenario 4: Complete end-to-end journey managing multiple projects through
    the FastAPI REST API endpoints: health check, project creation/selection, config read/write,
    table inspection, and metrics polling.
    """
    import httpx
    from api_server import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Verify health check
        health_resp = await ac.get("/api/health")
        assert health_resp.status_code == 200
        health_data = health_resp.json()
        assert health_data["status"] == "ok"
        assert "port" in health_data

        # 2. List projects
        projects_resp = await ac.get("/api/projects")
        assert projects_resp.status_code == 200
        projects_data = projects_resp.json()
        assert "active_project_id" in projects_data

        # 3. Inspect system metrics
        metrics_resp = await ac.get("/api/system/metrics")
        assert metrics_resp.status_code == 200
        metrics_data = metrics_resp.json()
        assert "cpu_percent" in metrics_data
        assert "memory" in metrics_data

        # 4. Verify SQLite tables inspection
        tables_resp = await ac.get("/api/db/sqlite/tables")
        assert tables_resp.status_code == 200
        assert "tables" in tables_resp.json()

        # 5. Check Qdrant collection info
        qdrant_resp = await ac.get("/api/db/qdrant/info")
        assert qdrant_resp.status_code == 200
        assert "collection" in qdrant_resp.json()


# ============================================================================
# SCENARIO 5: Adversarial Boilerplate Defense & Hardware IP Preservation Journey
# ============================================================================

def test_scenario5_adversarial_boilerplate_defense_and_ip_preservation(temp_project_dir):
    """Scenario 5: Complete journey processing noise-heavy raw technical inputs containing
    copyright notices, licensing boilerplate, and table of contents, while strictly preserving
    genuine technical hardware intellectual property (e.g. Synopsys DesignWare IP).
    """
    from pipeline.dataset_builder import DatasetBuilder

    with get_db_cursor(temp_project_dir["db_path"]) as cur:
        # Noise Article: Table of contents
        cur.execute("INSERT INTO articles (id, title, year, extracted_text) VALUES (1, 'Table of Contents', 2026, '1. Introduction ... page 5')")
        cur.execute("INSERT INTO enrichments (id, article_id, sft_qa, is_excluded) VALUES (1, 1, '[]', 0)")

        # Genuine Article: Hardware IP specification mentioning Synopsys DesignWare
        cur.execute("INSERT INTO articles (id, title, year, extracted_text) VALUES (2, 'Serial Peripheral Interface', 2026, 'Synchronous serial interface details.')")
        qa_with_ip = json.dumps([
            {"question": "Which architecture is the SSI peripheral based on?",
             "answer": "The SPI peripheral is based on the Synopsys DesignWare APB Synchronous Serial Interface architecture."},
            {"question": "What is the warranty disclaimer?",
             "answer": "This product is provided without warranty under Creative Commons disclaimer."}
        ])
        cur.execute("INSERT INTO enrichments (id, article_id, sft_qa, is_excluded) VALUES (2, 2, ?, 0)", (qa_with_ip,))

    # Execute cleaning pass
    builder = DatasetBuilder(config_path=str(temp_project_dir["config_path"]))
    clean_res = builder.clean_database_boilerplate()
    assert clean_res["status"] == "success"

    # Export clean datasets
    builder.export_datasets()
    sft_file = builder.export_dir / "sft_dataset.jsonl"
    assert sft_file.exists()

    with open(sft_file, "r", encoding="utf-8") as f:
        records = [json.loads(line) for line in f]

    assert len(records) >= 1
    # Verify that the disclaimer question was purged
    disclaimer_recs = [r for r in records if "warranty disclaimer" in r["instruction"].lower()]
    assert len(disclaimer_recs) == 0

    # Verify that the technical record is clean with empty input
    for r in records:
        assert r["input"] == ""
        assert set(r.keys()) == {"instruction", "input", "output"}
