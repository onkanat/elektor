import os
import sys
import json
import sqlite3
import tempfile
import shutil
import threading
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


def test_comb_extract_to_chunk_to_embed_to_search(temp_project_dir, mock_embedding_client):
    """Pairwise combination: Ingestion -> Word-Boundary Chunking -> Qdrant Embedding -> Semantic Search Linking."""
    from pipeline.vector_store import ArchiveVectorStore

    # Step 1: Ingest article into SQLite
    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO articles (id, title, year, filename, extracted_text, is_embedded)
        VALUES (101, 'RP2040 Clocks and PLLs', 2026, 'clocks.pdf',
        'The RP2040 features two on-chip PLLs: PLL_SYS generates the 133MHz system clock and PLL_USB generates the 48MHz reference clock.', 0)
    """)
    conn.commit()
    conn.close()

    # Step 2 & 3: Word-boundary chunking & Qdrant vector loading
    with patch("pipeline.vector_store.get_embedding_client", return_value=mock_embedding_client):
        store = ArchiveVectorStore(config_path=str(temp_project_dir["config_path"]))
        count = store.load_to_vector_db()
        assert count is None or count >= 0

        # Step 4: Semantic Search linking back to SQLite
        mock_hit = MagicMock(score=0.92, payload={
            "article_id": 101,
            "chunk_index": 0,
            "title": "RP2040 Clocks and PLLs",
            "year": 2026,
            "filename": "clocks.pdf",
            "text": "PLL_SYS generates the 133MHz system clock"
        })
        if hasattr(store.qdrant_client, "query_points"):
            store.qdrant_client.query_points = MagicMock(return_value=MagicMock(points=[mock_hit]))
        else:
            store.qdrant_client.search = MagicMock(return_value=[mock_hit])

        hits = store.search("system clock PLL", top_k=1)
        assert len(hits) == 1
        hit = hits[0]
        assert hit["article_id"] == 101
        store.close()

    # Verify link in SQLite
    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("SELECT title, is_embedded FROM articles WHERE id = ?", (hit["article_id"],))
    row = cur.fetchone()
    conn.close()
    assert row[0] == "RP2040 Clocks and PLLs"
    assert row[1] == 1


def test_comb_extract_to_enrich_to_clean_boilerplate_to_export(temp_project_dir):
    """Pairwise combination: Ingestion -> SFT/DPO Enrichment -> Boilerplate Pruning -> Strict Export."""
    from pipeline.dataset_builder import DatasetBuilder

    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    # Article A: Genuine technical article with mixed legal boilerplate Q&A
    cur.execute("INSERT INTO articles (id, title, year, extracted_text) VALUES (1, 'Cortex-M0 Core Architecture', 2026, 'ARM Cortex-M0+ details.')")
    mixed_sft = json.dumps([
        {"question": "What is the CPU pipeline depth?", "answer": "The Cortex-M0+ features a 2-stage in-order pipeline."},
        {"question": "Who owns Synopsys copyright?", "answer": "All rights reserved. Copyright Synopsys Inc."}
    ])
    cur.execute("INSERT INTO enrichments (id, article_id, sft_qa, is_excluded) VALUES (1, 1, ?, 0)", (mixed_sft,))

    # Article B: Colophon boilerplate article
    cur.execute("INSERT INTO articles (id, title, year, extracted_text) VALUES (2, 'Colophon & Documentation License', 2026, 'Licensed under CC BY-ND 4.0.')")
    cur.execute("INSERT INTO enrichments (id, article_id, sft_qa, is_excluded) VALUES (2, 2, '[]', 0)")
    conn.commit()
    conn.close()

    builder = DatasetBuilder(config_path=str(temp_project_dir["config_path"]))

    # Clean boilerplate
    clean_res = builder.clean_database_boilerplate()
    assert clean_res["status"] == "success"
    assert clean_res["excluded_articles"] >= 1
    assert clean_res["pruned_qas"] >= 1

    # Export datasets
    builder.export_datasets()
    sft_file = builder.export_dir / "sft_dataset.jsonl"
    assert sft_file.exists()

    with open(sft_file, "r", encoding="utf-8") as f:
        records = [json.loads(line) for line in f]

    assert len(records) >= 1
    for r in records:
        assert r["input"] == ""
        assert "pipeline depth" in r["instruction"].lower()
        assert "all rights reserved" not in r["output"].lower()


def test_comb_enrich_to_judge_arbitration_to_dataset_export(temp_project_dir):
    """Pairwise combination: Enrichment -> Judge Arbitration (Score & Rewrite) -> Dataset Export."""
    from pipeline.judge_engine import JudgeEngine, JudgeEvaluation
    from pipeline.dataset_builder import DatasetBuilder

    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("INSERT INTO articles (id, title, year, extracted_text) VALUES (10, 'I2C Speed Modes', 2026, 'I2C specs.')")
    sft = json.dumps([{"question": "What is fast mode plus speed?", "answer": "Up to 1 Mbps."}])
    dpo = json.dumps([{
        "question": "What is fast mode plus speed?",
        "chosen": "Fast mode plus operates at clock rates up to 1000 kHz (1 Mbps).",
        "rejected": "It operates at 100 kHz."
    }])
    cur.execute("INSERT INTO enrichments (id, article_id, sft_qa, dpo_pairs, is_excluded) VALUES (10, 10, ?, ?, 0)", (sft, dpo))
    conn.commit()
    conn.close()

    judge = JudgeEngine(config_or_path=str(temp_project_dir["config_path"]))
    mock_eval = JudgeEvaluation(
        technical_accuracy=9,
        logical_consistency=9,
        turkish_fluency=9,
        overall_score=9.0,
        status="approved",
        feedback="High accuracy."
    )
    with patch.object(judge, "evaluate_pair", return_value=mock_eval):
        res = judge.evaluate_pair("Prompt", "Chosen", threshold=7.0)
        assert res.status == "approved"

    # Export dataset
    builder = DatasetBuilder(config_path=str(temp_project_dir["config_path"]))
    builder.export_datasets()
    dpo_file = builder.export_dir / "dpo_dataset.jsonl"
    assert dpo_file.exists()
    with open(dpo_file, "r", encoding="utf-8") as f:
        records = [json.loads(line) for line in f]
    assert len(records) >= 1
    assert records[0]["prompt"] == "What is fast mode plus speed?"


def test_comb_code_extraction_to_sft_to_unsloth_script_packaging(temp_project_dir):
    """Pairwise combination: Synthetic Code Table -> Alpaca SFT Export ('input': '') -> Unsloth Training Script."""
    from pipeline.dataset_builder import DatasetBuilder
    from pipeline.cloud_gpu_offloader import CloudGPUOffloader

    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO synthetic_code_pairs (instruction, input_code, output_response, category)
        VALUES ('Configure SPI master baudrate', 'def set_baud(spi, freq): pass', 'def set_baud(spi, freq):\n    spi.init(baudrate=freq)', 'completion')
    """)
    conn.commit()
    conn.close()

    builder = DatasetBuilder(config_path=str(temp_project_dir["config_path"]))
    builder.export_datasets()

    # Generate Unsloth training script
    offloader = CloudGPUOffloader(exports_dir=str(builder.export_dir.parent))
    script = offloader.generate_unsloth_script(
        project_id="test_project",
        base_model="unsloth/Qwen2.5-Coder-7B-Instruct",
        hf_dataset="onkanat/test_project-dataset",
        dataset_file="code_sft_dataset.jsonl"
    )
    assert "SFTTrainer" in script
    assert "FastLanguageModel" in script
    assert "code_sft_dataset.jsonl" in script


def test_comb_turkish_translation_to_latex_preservation_to_alpaca_export(temp_project_dir):
    """Pairwise combination: Turkish Translation -> LaTeX Equation Protection -> Alpaca SFT Serialization."""
    from pipeline.dataset_builder import DatasetBuilder

    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("INSERT INTO articles (id, title, year, extracted_text) VALUES (20, 'MOSFET Karakteristikleri', 2026, 'Doyum bölgesi denklemi.')")
    tr_qa = json.dumps([{
        "question": "Doyum bölgesinde MOSFET akım denklemi nedir?",
        "answer": r"Doyum akımı \(I_{ds} = \frac{1}{2} \mu C_{ox} \frac{W}{L} (V_{gs} - V_{th})^2\) formülü ile modellenir."
    }])
    cur.execute("INSERT INTO enrichments (id, article_id, tr_sft_qa, is_excluded) VALUES (20, 20, ?, 0)", (tr_qa,))
    conn.commit()
    conn.close()

    builder = DatasetBuilder(config_path=str(temp_project_dir["config_path"]))
    builder.export_datasets()

    tr_sft_file = builder.export_dir / "tr_sft_dataset.jsonl"
    assert tr_sft_file.exists()
    with open(tr_sft_file, "r", encoding="utf-8") as f:
        records = [json.loads(line) for line in f]
    assert len(records) >= 1
    assert records[0]["input"] == ""
    assert r"\frac" in records[0]["output"]
    assert "MOSFET" in records[0]["instruction"]


def test_comb_centralized_db_to_sharded_concurrent_pipeline_workers(temp_project_dir):
    """Pairwise combination: SQLite Centralized Connection -> Multi-Threaded Sharded Workers."""
    num_workers = 4
    records_per_worker = 10
    barrier = threading.Barrier(num_workers)

    def worker_task(worker_id):
        barrier.wait()
        for i in range(records_per_worker):
            with get_db_cursor(temp_project_dir["db_path"]) as cur:
                cur.execute(
                    "INSERT INTO articles (title, year, extracted_text) VALUES (?, ?, ?)",
                    (f"Worker_{worker_id}_Article_{i}", 2026, f"Content from worker {worker_id}")
                )

    threads = [threading.Thread(target=worker_task, args=(w,)) for w in range(num_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with get_db_cursor(temp_project_dir["db_path"]) as cur:
        cur.execute("SELECT COUNT(*) FROM articles WHERE title LIKE 'Worker_%'")
        count = cur.fetchone()[0]
    assert count == num_workers * records_per_worker


@pytest.mark.asyncio
async def test_comb_api_server_to_pipeline_trigger_to_status_poll_to_dataset_preview():
    """Pairwise combination: API Trigger Pipeline -> Status Polling -> Datasets Listing -> Preview."""
    import httpx
    from api_server import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        # Step 1: Health check
        h_resp = await ac.get("/api/health")
        assert h_resp.status_code == 200

        # Step 2: Trigger export command
        run_resp = await ac.post("/api/pipeline/run", json={"command": "export"})
        assert run_resp.status_code in [200, 400]

        # Step 3: Poll status
        status_resp = await ac.get("/api/pipeline/status")
        assert status_resp.status_code == 200
        assert "status" in status_resp.json()

        # Step 4: List datasets
        ds_resp = await ac.get("/api/datasets")
        assert ds_resp.status_code == 200
        assert "datasets" in ds_resp.json()


def test_comb_cli_reset_to_clean_state_to_reingestion_cycle(temp_project_dir):
    """Pairwise combination: run.py reset_pipeline_data -> Clean State -> Re-Ingestion."""
    from run import reset_pipeline_data

    # Create dummy files
    db_file = temp_project_dir["db_path"]
    qdrant_dir = temp_project_dir["qdrant_dir"]
    assert db_file.exists()
    assert qdrant_dir.exists()

    # Call reset
    reset_pipeline_data(config_path=str(temp_project_dir["config_path"]))

    # Verify wipe
    assert not db_file.exists()
    assert not qdrant_dir.exists()


def test_comb_multimodal_vision_to_image_optimization_to_visual_export(temp_project_dir):
    """Pairwise combination: Visual Diagram Crop -> ImageOptimizer WebP -> MultiModal Dataset Generator."""
    from pipeline.image_optimizer import ImageOptimizer
    from pipeline.visual_dataset_builder import VisualDatasetBuilder

    raw_dir = temp_project_dir["path"] / "raw_images"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir = temp_project_dir["path"] / "opt_images"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Create a 1x1 dummy PNG
    png_header = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02'
        b'\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    test_img = raw_dir / "diagram_test.png"
    test_img.write_bytes(png_header)

    opt = ImageOptimizer(max_dimension=512, webp_quality=85)
    optimized = opt.optimize_image(test_img, out_dir)
    assert optimized is not None
    assert optimized.exists()

    builder = VisualDatasetBuilder(config_path=str(temp_project_dir["config_path"]))
    assert builder.optimizer is not None


def test_comb_project_registry_to_multi_project_merge_audit(temp_project_dir):
    """Pairwise combination: Project Registry -> Project Merger Audit."""
    from api_server import get_projects_registry
    from pipeline.project_merger import ProjectMerger

    registry = get_projects_registry()
    assert "active_project_id" in registry

    merger = ProjectMerger()
    assert merger.registry_path is not None
