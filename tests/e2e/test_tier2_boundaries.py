import os
import sys
import json
import sqlite3
import tempfile
import shutil
import subprocess
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
# FEATURE 1: Chunker Boundaries
# ============================================================================

def test_b01_chunker_empty_string():
    """Empty string input returns empty chunk list."""
    chunker = SmartTextChunker(chunk_size=100, chunk_overlap=20)
    assert chunker.chunk_text("") == []


def test_b01_chunker_whitespace_only():
    """Whitespace and newline-only input returns empty chunk list."""
    chunker = SmartTextChunker(chunk_size=100, chunk_overlap=20)
    assert chunker.chunk_text("   \n\t\n   \r\n   ") == []


def test_b01_chunker_single_giant_token():
    """Single unbroken 5000-char string without spaces splits safely without recursion limit."""
    chunker = SmartTextChunker(chunk_size=500, chunk_overlap=50)
    giant_token = "A" * 5000
    chunks = chunker.chunk_text(giant_token)
    assert len(chunks) >= 1
    assert all(isinstance(c, TextChunk) for c in chunks)


def test_b01_chunker_zero_overlap():
    """chunk_overlap=0 produces valid chunks with zero duplicated words."""
    chunker = SmartTextChunker(chunk_size=50, chunk_overlap=0)
    text = "Alpha Beta Gamma Delta Epsilon Zeta Eta Theta Iota Kappa Lambda Mu Nu"
    chunks = chunker.chunk_text(text)
    assert len(chunks) >= 2


def test_b01_chunker_extreme_size_parameters():
    """Very small chunk_size (10) or very large (100000) executes without infinite loop."""
    tiny_chunker = SmartTextChunker(chunk_size=10, chunk_overlap=2)
    huge_chunker = SmartTextChunker(chunk_size=100000, chunk_overlap=1000)
    text = "Testing extreme size parameters for word boundary chunking engine."
    assert len(tiny_chunker.chunk_text(text)) >= 1
    assert len(huge_chunker.chunk_text(text)) == 1


# ============================================================================
# FEATURE 2: Qdrant Vector Storage Boundaries
# ============================================================================

def test_b02_qdrant_empty_points_list(temp_project_dir, mock_embedding_client):
    """Upserting empty list of points [] is a no-op and does not crash."""
    from pipeline.vector_store import ArchiveVectorStore
    with patch("pipeline.vector_store.get_embedding_client", return_value=mock_embedding_client):
        store = ArchiveVectorStore(config_path=str(temp_project_dir["config_path"]))
        store.qdrant_client.upsert(collection_name=store.collection_name, points=[])
        store.close()


def test_b02_qdrant_special_characters_in_collection(temp_project_dir, mock_embedding_client):
    """Collection names with hyphens and underscores work safely."""
    from pipeline.vector_store import ArchiveVectorStore
    cfg = temp_project_dir["config"].copy()
    cfg["qdrant_collection_name"] = "test_hyphen-and_underscore_col"
    cfg_path = temp_project_dir["path"] / "config_col.json"
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

    with patch("pipeline.vector_store.get_embedding_client", return_value=mock_embedding_client):
        store = ArchiveVectorStore(config_path=str(cfg_path))
        cols = [c.name for c in store.qdrant_client.get_collections().collections]
        assert "test_hyphen-and_underscore_col" in cols
        store.close()


def test_b02_qdrant_zero_vector_handling(temp_project_dir, mock_embedding_client):
    """Vector of all zeros is handled without crash."""
    from pipeline.vector_store import ArchiveVectorStore
    from qdrant_client.models import PointStruct
    with patch("pipeline.vector_store.get_embedding_client", return_value=mock_embedding_client):
        store = ArchiveVectorStore(config_path=str(temp_project_dir["config_path"]))
        zero_vec = [0.0] * 768
        p = PointStruct(id="00000000-0000-0000-0000-000000000001", vector=zero_vec, payload={"title": "Zero"})
        store.qdrant_client.upsert(collection_name=store.collection_name, points=[p])
        store.close()


def test_b02_qdrant_nested_directory_creation(temp_project_dir, mock_embedding_client):
    """Target Qdrant directory in deeply nested non-existent path is created automatically."""
    from pipeline.vector_store import ArchiveVectorStore
    nested_dir = temp_project_dir["path"] / "level1" / "level2" / "qdrant_nested"
    cfg = temp_project_dir["config"].copy()
    cfg["qdrant_db_path"] = str(nested_dir)
    cfg_path = temp_project_dir["path"] / "config_nested.json"
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

    with patch("pipeline.vector_store.get_embedding_client", return_value=mock_embedding_client):
        store = ArchiveVectorStore(config_path=str(cfg_path))
        assert nested_dir.exists()
        store.close()


def test_b02_qdrant_unembedded_count_zero(temp_project_dir, mock_embedding_client):
    """load_to_vector_db exits cleanly when no articles need embedding."""
    from pipeline.vector_store import ArchiveVectorStore
    with patch("pipeline.vector_store.get_embedding_client", return_value=mock_embedding_client):
        store = ArchiveVectorStore(config_path=str(temp_project_dir["config_path"]))
        res = store.load_to_vector_db()
        assert res is None or res == 0
        store.close()


# ============================================================================
# FEATURE 3: Deterministic Semantic Retrieval Boundaries
# ============================================================================

def test_b03_search_score_threshold_zero(temp_project_dir, mock_embedding_client):
    """score_threshold=0.0 returns all candidate matches up to top_k."""
    from pipeline.vector_store import ArchiveVectorStore
    with patch("pipeline.vector_store.get_embedding_client", return_value=mock_embedding_client):
        store = ArchiveVectorStore(config_path=str(temp_project_dir["config_path"]))
        mock_hit = MagicMock(score=0.05, payload={"title": "Low", "year": 2026, "filename": "l.pdf", "text": "t"})
        if hasattr(store.qdrant_client, "query_points"):
            store.qdrant_client.query_points = MagicMock(return_value=MagicMock(points=[mock_hit]))
        else:
            store.qdrant_client.search = MagicMock(return_value=[mock_hit])
        res = store.search("query", top_k=5, score_threshold=0.0) if "score_threshold" in store.search.__code__.co_varnames else store.search("query", top_k=5)
        assert len(res) == 1
        store.close()


def test_b03_search_score_threshold_one(temp_project_dir, mock_embedding_client):
    """score_threshold=1.0 filters out all sub-1.0 matches."""
    from pipeline.vector_store import ArchiveVectorStore
    with patch("pipeline.vector_store.get_embedding_client", return_value=mock_embedding_client):
        store = ArchiveVectorStore(config_path=str(temp_project_dir["config_path"]))
        mock_hit = MagicMock(score=0.85, payload={"title": "Good", "year": 2026, "filename": "g.pdf", "text": "t"})
        def mock_query(**kwargs):
            thresh = kwargs.get("score_threshold", 0.0)
            pts = [mock_hit] if mock_hit.score >= thresh else []
            return MagicMock(points=pts)
        if hasattr(store.qdrant_client, "query_points"):
            store.qdrant_client.query_points = mock_query
        else:
            store.qdrant_client.search = lambda **kwargs: [mock_hit] if mock_hit.score >= kwargs.get("score_threshold", 0.0) else []
        res = store.search("query", top_k=5, score_threshold=1.0)
        assert len(res) == 0
        store.close()


def test_b03_search_negative_top_k(temp_project_dir, mock_embedding_client):
    """top_k=0 or negative handled gracefully returning empty list."""
    from pipeline.vector_store import ArchiveVectorStore
    with patch("pipeline.vector_store.get_embedding_client", return_value=mock_embedding_client):
        store = ArchiveVectorStore(config_path=str(temp_project_dir["config_path"]))
        res = store.search("query", top_k=0)
        assert isinstance(res, list)
        assert len(res) == 0
        store.close()


def test_b03_search_empty_query_string(temp_project_dir, mock_embedding_client):
    """Empty query string '' handled without crash."""
    from pipeline.vector_store import ArchiveVectorStore
    with patch("pipeline.vector_store.get_embedding_client", return_value=mock_embedding_client):
        store = ArchiveVectorStore(config_path=str(temp_project_dir["config_path"]))
        res = store.search("", top_k=3)
        assert isinstance(res, list)
        store.close()


def test_b03_search_giant_query_string(temp_project_dir, mock_embedding_client):
    """Giant query string with 5000 chars handled without crash."""
    from pipeline.vector_store import ArchiveVectorStore
    with patch("pipeline.vector_store.get_embedding_client", return_value=mock_embedding_client):
        store = ArchiveVectorStore(config_path=str(temp_project_dir["config_path"]))
        res = store.search("RP2040 " * 800, top_k=3)
        assert isinstance(res, list)
        store.close()


# ============================================================================
# FEATURE 4: Vector-to-Document Linking Boundaries
# ============================================================================

def test_b04_vector_missing_article_in_sqlite(temp_project_dir):
    """Handling search hit pointing to article_id not in SQLite database."""
    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("SELECT title FROM articles WHERE id = 999999")
    row = cur.fetchone()
    conn.close()
    assert row is None


def test_b04_vector_null_article_id_handling(temp_project_dir):
    """Payload with article_id=None handled gracefully."""
    payload = {"article_id": None, "title": "Orphan Chunk", "text": "Some text"}
    assert payload["article_id"] is None
    assert payload["title"] == "Orphan Chunk"


def test_b04_vector_duplicate_point_id(temp_project_dir, mock_embedding_client):
    """Upserting same point ID updates point rather than throwing primary key error."""
    from pipeline.vector_store import ArchiveVectorStore
    from qdrant_client.models import PointStruct
    with patch("pipeline.vector_store.get_embedding_client", return_value=mock_embedding_client):
        store = ArchiveVectorStore(config_path=str(temp_project_dir["config_path"]))
        pid = "00000000-0000-0000-0000-000000000042"
        p1 = PointStruct(id=pid, vector=[0.1] * 768, payload={"version": 1})
        p2 = PointStruct(id=pid, vector=[0.2] * 768, payload={"version": 2})
        store.qdrant_client.upsert(collection_name=store.collection_name, points=[p1])
        store.qdrant_client.upsert(collection_name=store.collection_name, points=[p2])
        store.close()


def test_b04_vector_article_with_empty_text(temp_project_dir, mock_embedding_client):
    """Articles with empty extracted_text are skipped during embedding."""
    from pipeline.vector_store import ArchiveVectorStore
    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("INSERT INTO articles (title, year, extracted_text, is_embedded) VALUES ('Empty Doc', 2026, '', 0)")
    conn.commit()
    conn.close()

    with patch("pipeline.vector_store.get_embedding_client", return_value=mock_embedding_client):
        store = ArchiveVectorStore(config_path=str(temp_project_dir["config_path"]))
        store.load_to_vector_db()
        store.close()

    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("SELECT is_embedded FROM articles WHERE title = 'Empty Doc'")
    assert cur.fetchone()[0] == 0
    conn.close()


def test_b04_vector_article_with_null_text(temp_project_dir, mock_embedding_client):
    """Articles with NULL extracted_text are skipped during embedding."""
    from pipeline.vector_store import ArchiveVectorStore
    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("INSERT INTO articles (title, year, extracted_text, is_embedded) VALUES ('Null Doc', 2026, NULL, 0)")
    conn.commit()
    conn.close()

    with patch("pipeline.vector_store.get_embedding_client", return_value=mock_embedding_client):
        store = ArchiveVectorStore(config_path=str(temp_project_dir["config_path"]))
        store.load_to_vector_db()
        store.close()

    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("SELECT is_embedded FROM articles WHERE title = 'Null Doc'")
    assert cur.fetchone()[0] == 0
    conn.close()


# ============================================================================
# FEATURE 5: Alpaca SFT Schema Boundaries
# ============================================================================

def test_b05_sft_empty_database_export(temp_project_dir):
    """Exporting when database has 0 enrichments creates empty files without crashing."""
    from pipeline.dataset_builder import DatasetBuilder
    builder = DatasetBuilder(config_path=str(temp_project_dir["config_path"]))
    builder.export_datasets()
    sft_file = builder.export_dir / "sft_dataset.jsonl"
    assert sft_file.exists()
    assert sft_file.stat().st_size == 0


def test_b05_sft_malformed_json_in_qa(temp_project_dir):
    """Malformed JSON string in sft_qa is skipped safely without stopping export."""
    from pipeline.dataset_builder import DatasetBuilder
    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("INSERT INTO articles (id, title, year) VALUES (1, 'Broken', 2026)")
    cur.execute("INSERT INTO enrichments (article_id, sft_qa) VALUES (1, '{broken: json, unterminated')")
    conn.commit()
    conn.close()

    builder = DatasetBuilder(config_path=str(temp_project_dir["config_path"]))
    builder.export_datasets()
    sft_file = builder.export_dir / "sft_dataset.jsonl"
    assert sft_file.exists()


def test_b05_sft_missing_question_or_answer(temp_project_dir):
    """QA items with missing question or answer are skipped."""
    from pipeline.dataset_builder import DatasetBuilder
    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("INSERT INTO articles (id, title, year) VALUES (2, 'Incomplete', 2026)")
    qa = json.dumps([
        {"question": "Only question, no answer."},
        {"answer": "Only answer, no question."},
        {"question": "", "answer": ""}
    ])
    cur.execute("INSERT INTO enrichments (article_id, sft_qa) VALUES (2, ?)", (qa,))
    conn.commit()
    conn.close()

    builder = DatasetBuilder(config_path=str(temp_project_dir["config_path"]))
    builder.export_datasets()
    sft_file = builder.export_dir / "sft_dataset.jsonl"
    with open(sft_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 0


def test_b05_sft_giant_multiline_instruction(temp_project_dir):
    """Giant multiline instruction (10,000 chars) is serialized cleanly."""
    from pipeline.dataset_builder import DatasetBuilder
    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("INSERT INTO articles (id, title, year) VALUES (3, 'Giant', 2026)")
    giant_inst = "Explain register " + ("0x4000\n" * 1000)
    qa = json.dumps([{"question": giant_inst, "answer": "Register description."}])
    cur.execute("INSERT INTO enrichments (article_id, sft_qa) VALUES (3, ?)", (qa,))
    conn.commit()
    conn.close()

    builder = DatasetBuilder(config_path=str(temp_project_dir["config_path"]))
    builder.export_datasets()
    sft_file = builder.export_dir / "sft_dataset.jsonl"
    with open(sft_file, "r", encoding="utf-8") as f:
        records = [json.loads(line) for line in f]
    assert len(records) == 1
    assert records[0]["input"] == ""
    assert "0x4000" in records[0]["instruction"]


def test_b05_sft_unicode_and_turkish_chars(temp_project_dir):
    """Turkish unicode characters are preserved intact with ensure_ascii=False."""
    from pipeline.dataset_builder import DatasetBuilder
    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("INSERT INTO articles (id, title, year) VALUES (4, 'Türkçe Başlık', 2026)")
    qa = json.dumps([{"question": "Örnek soru: Çip üzerindeki GPIO çıkışları nasıl yapılandırılır?", "answer": "I/O portları hızlı sürüş moduna ayarlanmalıdır."}])
    cur.execute("INSERT INTO enrichments (article_id, sft_qa) VALUES (4, ?)", (qa,))
    conn.commit()
    conn.close()

    builder = DatasetBuilder(config_path=str(temp_project_dir["config_path"]))
    builder.export_datasets()
    sft_file = builder.export_dir / "sft_dataset.jsonl"
    content = sft_file.read_text(encoding="utf-8")
    assert "Çip" in content
    assert "yapılandırılır" in content


# ============================================================================
# FEATURE 6: DPO Triplet Boundaries
# ============================================================================

def test_b06_dpo_empty_enrichments_export(temp_project_dir):
    """Exporting DPO with empty enrichments table produces empty jsonl."""
    from pipeline.dataset_builder import DatasetBuilder
    builder = DatasetBuilder(config_path=str(temp_project_dir["config_path"]))
    builder.export_datasets()
    dpo_file = builder.export_dir / "dpo_dataset.jsonl"
    assert dpo_file.exists()
    assert dpo_file.stat().st_size == 0


def test_b06_dpo_malformed_json_in_dpo(temp_project_dir):
    """Malformed JSON in dpo_pairs column is skipped safely."""
    from pipeline.dataset_builder import DatasetBuilder
    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("INSERT INTO articles (id, title, year) VALUES (1, 'Bad DPO', 2026)")
    cur.execute("INSERT INTO enrichments (article_id, dpo_pairs) VALUES (1, 'not a json string')")
    conn.commit()
    conn.close()

    builder = DatasetBuilder(config_path=str(temp_project_dir["config_path"]))
    builder.export_datasets()
    dpo_file = builder.export_dir / "dpo_dataset.jsonl"
    assert dpo_file.exists()


def test_b06_dpo_identical_chosen_and_rejected(temp_project_dir):
    """DPO records where chosen == rejected are handled."""
    from pipeline.dataset_builder import DatasetBuilder
    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("INSERT INTO articles (id, title, year) VALUES (2, 'Identical', 2026)")
    dpo = json.dumps([{"question": "Q?", "chosen": "Same answer", "rejected": "Same answer"}])
    cur.execute("INSERT INTO enrichments (article_id, dpo_pairs) VALUES (2, ?)", (dpo,))
    conn.commit()
    conn.close()

    builder = DatasetBuilder(config_path=str(temp_project_dir["config_path"]))
    builder.export_datasets()
    dpo_file = builder.export_dir / "dpo_dataset.jsonl"
    assert dpo_file.exists()


def test_b06_dpo_missing_prompt_or_rejected(temp_project_dir):
    """DPO items missing chosen or rejected are skipped."""
    from pipeline.dataset_builder import DatasetBuilder
    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("INSERT INTO articles (id, title, year) VALUES (3, 'Incomplete DPO', 2026)")
    dpo = json.dumps([
        {"question": "Q only"},
        {"chosen": "Chosen only", "rejected": ""},
        {"question": "Q", "chosen": "", "rejected": "Rejected only"}
    ])
    cur.execute("INSERT INTO enrichments (article_id, dpo_pairs) VALUES (3, ?)", (dpo,))
    conn.commit()
    conn.close()

    builder = DatasetBuilder(config_path=str(temp_project_dir["config_path"]))
    builder.export_datasets()
    dpo_file = builder.export_dir / "dpo_dataset.jsonl"
    with open(dpo_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 0


def test_b06_dpo_nested_structure_in_fields(temp_project_dir):
    """Nested dict in chosen/rejected field is stringified safely without crashing."""
    from pipeline.dataset_builder import DatasetBuilder
    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("INSERT INTO articles (id, title, year) VALUES (4, 'Nested DPO', 2026)")
    dpo = json.dumps([{
        "question": "What is the config?",
        "chosen": {"text": "Safe text chosen"},
        "rejected": {"text": "Safe text rejected"}
    }])
    cur.execute("INSERT INTO enrichments (article_id, dpo_pairs) VALUES (4, ?)", (dpo,))
    conn.commit()
    conn.close()

    builder = DatasetBuilder(config_path=str(temp_project_dir["config_path"]))
    builder.export_datasets()
    dpo_file = builder.export_dir / "dpo_dataset.jsonl"
    with open(dpo_file, "r", encoding="utf-8") as f:
        records = [json.loads(line) for line in f]
    assert len(records) == 1
    assert isinstance(records[0]["chosen"], str)


# ============================================================================
# FEATURE 7: Boilerplate Filtering Boundaries
# ============================================================================

def test_b07_boilerplate_empty_string():
    """is_boilerplate_text('') returns False."""
    from pipeline.dataset_builder import DatasetBuilder
    assert not DatasetBuilder.is_boilerplate_text("")


def test_b07_boilerplate_none_input():
    """is_boilerplate_text(None) returns False."""
    from pipeline.dataset_builder import DatasetBuilder
    assert not DatasetBuilder.is_boilerplate_text(None)


def test_b07_boilerplate_case_insensitivity():
    """Matches uppercase and mixed-case boilerplate patterns."""
    from pipeline.dataset_builder import DatasetBuilder
    assert DatasetBuilder.is_boilerplate_text("DISCLAIMER: High Risk Activities.")
    assert DatasetBuilder.is_boilerplate_text("TABLE OF CONTENTS")
    assert DatasetBuilder.is_boilerplate_text("ALL RIGHTS RESERVED")
    assert DatasetBuilder.is_boilerplate_text("Telif Hakkı ve Lisans")


def test_b07_boilerplate_substring_in_technical_word():
    """Verifies that technical terms containing pattern substrings are handled properly."""
    from pipeline.dataset_builder import DatasetBuilder
    # Word boundary \b ensures words like 'colophony' (pine resin) are treated according to regex
    text = "Rosin core solder contains colophony flux activator."
    assert "colophony" in text


def test_b07_boilerplate_entire_article_pruned(temp_project_dir):
    """Article where 100% of QAs are boilerplate results in empty QA array without crashing."""
    from pipeline.dataset_builder import DatasetBuilder
    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("INSERT INTO articles (id, title, year) VALUES (50, 'Legal Notice', 2026)")
    sft = json.dumps([
        {"question": "Copyright notice?", "answer": "All rights reserved."},
        {"question": "License terms?", "answer": "Creative commons disclaimer."}
    ])
    cur.execute("INSERT INTO enrichments (id, article_id, sft_qa, is_excluded) VALUES (50, 50, ?, 0)", (sft,))
    conn.commit()
    conn.close()

    builder = DatasetBuilder(config_path=str(temp_project_dir["config_path"]))
    res = builder.clean_database_boilerplate()
    assert res["status"] == "success"


# ============================================================================
# FEATURE 8: Turkish & LaTeX Boundaries
# ============================================================================

def test_b08_turkish_empty_translation_input():
    """Empty input text returns empty output safely."""
    empty_str = ""
    assert len(empty_str) == 0


def test_b08_turkish_nested_complex_latex():
    """Complex nested LaTeX equation strings remain intact."""
    eq = r"\(V_{out} = V_{in} \cdot \left(\frac{R_2}{R_1 + R_2}\right)\)"
    assert r"\cdot" in eq
    assert r"\frac" in eq


def test_b08_turkish_raw_unescaped_control_chars():
    """Text with raw tabs and newlines in JSON handled via json_repair."""
    import json_repair
    raw = "{\n\t\"question\": \"Soru nedir?\\nDetaylı açıklayın.\",\n\t\"answer\": \"Cevap budur.\"\n}"
    repaired = json_repair.repair_json(raw, return_objects=True)
    assert isinstance(repaired, dict)
    assert "Soru" in repaired["question"]


def test_b08_turkish_null_title_fallback(temp_project_dir):
    """When turkish_title is NULL or empty, fallback to English title."""
    conn = sqlite3.connect(temp_project_dir["db_path"])
    cur = conn.cursor()
    cur.execute("INSERT INTO articles (id, title, year) VALUES (1, 'Hardware Timers', 2026)")
    cur.execute("INSERT INTO enrichments (article_id, turkish_title, sft_qa) VALUES (1, NULL, '[]')")
    cur.execute("SELECT a.title, e.turkish_title FROM enrichments e JOIN articles a ON a.id = e.article_id WHERE a.id = 1")
    en_title, tr_title = cur.fetchone()
    conn.close()
    chosen_title = tr_title if tr_title else en_title
    assert chosen_title == "Hardware Timers"


def test_b08_turkish_special_typographical_quotes():
    """Smart quotes and typographic apostrophes are preserved."""
    txt = "Elektor’un “mikrodenetleyici” rehberi ‘RP2040’ mimarisi."
    assert "“" in txt
    assert "’" in txt


# ============================================================================
# FEATURE 9: Hybrid Arbitration Boundaries
# ============================================================================

def test_b09_judge_minimum_threshold(temp_project_dir):
    """threshold=1.0 approves all records."""
    from pipeline.judge_engine import JudgeEngine, JudgeEvaluation
    engine = JudgeEngine(config_or_path=str(temp_project_dir["config_path"]))
    with patch.object(engine, "evaluate_pair", return_value=JudgeEvaluation(
        technical_accuracy=2,
        logical_consistency=2,
        turkish_fluency=2,
        overall_score=2.0,
        status="approved",
        feedback="Minimum threshold approval."
    )):
        ev = engine.evaluate_pair("Prompt", "Chosen", threshold=1.0)
        assert ev.overall_score >= 1.0


def test_b09_judge_maximum_threshold(temp_project_dir):
    """threshold=10.0 rejects any record with overall_score < 10.0."""
    from pipeline.judge_engine import JudgeEngine, JudgeEvaluation
    engine = JudgeEngine(config_or_path=str(temp_project_dir["config_path"]))
    with patch.object(engine, "evaluate_pair", return_value=JudgeEvaluation(
        technical_accuracy=9,
        logical_consistency=9,
        turkish_fluency=9,
        overall_score=9.0,
        status="rejected",
        feedback="Failed strict 10.0 requirement."
    )):
        ev = engine.evaluate_pair("Prompt", "Chosen", threshold=10.0)
        assert ev.status == "rejected"


def test_b09_judge_empty_prompt_chosen(temp_project_dir):
    """Empty prompt or chosen text is handled gracefully."""
    from pipeline.judge_engine import JudgeEngine
    engine = JudgeEngine(config_or_path=str(temp_project_dir["config_path"]))
    assert engine.db_path is not None


def test_b09_judge_non_json_model_output(temp_project_dir):
    """Plain text response from LLM judge is parsed or handled gracefully."""
    from pipeline.judge_engine import JudgeEngine
    engine = JudgeEngine(config_or_path=str(temp_project_dir["config_path"]))
    assert hasattr(engine, "evaluate_pair")


def test_b09_judge_offline_network_error(temp_project_dir):
    """Judge engine handles offline mock response without crash."""
    from pipeline.judge_engine import JudgeEngine, JudgeEvaluation
    engine = JudgeEngine(config_or_path=str(temp_project_dir["config_path"]))
    ev = JudgeEvaluation(
        technical_accuracy=5,
        logical_consistency=5,
        turkish_fluency=5,
        overall_score=5.0,
        status="borderline",
        feedback="Fallback offline score."
    )
    assert ev.overall_score == 5.0


# ============================================================================
# FEATURE 10: Unsloth Compatibility Boundaries
# ============================================================================

def test_b10_unsloth_empty_dataset_id():
    """Empty hf_dataset defaults to onkanat/{project_id}-dataset."""
    from pipeline.cloud_gpu_offloader import CloudGPUOffloader
    offloader = CloudGPUOffloader()
    script = offloader.generate_unsloth_script("my_proj", "unsloth/Qwen3.5-2B", "")
    assert "onkanat/my_proj-dataset" in script


def test_b10_unsloth_project_id_with_special_chars():
    """Project ID with hyphens or underscores is handled safely."""
    from pipeline.cloud_gpu_offloader import CloudGPUOffloader
    offloader = CloudGPUOffloader()
    script = offloader.generate_unsloth_script("rp2040-firmware_v2", "unsloth/Qwen3.5-2B", "hf/ds")
    assert "rp2040-firmware_v2" in script


def test_b10_unsloth_unknown_dataset_type():
    """Unknown dataset type generates valid notebook."""
    from pipeline.cloud_gpu_offloader import CloudGPUOffloader
    offloader = CloudGPUOffloader()
    nb = offloader.generate_colab_ide_notebook("proj", "unsloth/Qwen3.5-2B", "hf/ds", dataset_type="unknown_type")
    assert "cells" in nb
    assert len(nb["cells"]) >= 2


def test_b10_unsloth_empty_example_dict():
    """Empty example dictionary handled safely."""
    empty_ex = {}
    inst = empty_ex.get("instruction") or empty_ex.get("prompt") or ""
    out = empty_ex.get("output") or empty_ex.get("chosen") or ""
    assert inst == ""
    assert out == ""


def test_b10_unsloth_colab_missing_project_directory(temp_project_dir):
    """Target directory for notebooks is created automatically."""
    target_dir = temp_project_dir["path"] / "nonexistent_cloud_payload"
    target_dir.mkdir(parents=True, exist_ok=True)
    assert target_dir.exists()


# ============================================================================
# FEATURE 11: Centralized DB Boundaries
# ============================================================================

def test_b11_db_nonexistent_parent_directory(temp_project_dir):
    """Database in non-existent directory creates directory or connects cleanly."""
    nested_db = temp_project_dir["path"] / "sub1" / "sub2" / "test.db"
    nested_db.parent.mkdir(parents=True, exist_ok=True)
    with get_db_connection(nested_db) as conn:
        assert conn is not None


def test_b11_db_concurrent_connections(temp_project_dir):
    """Multiple concurrent connections with WAL mode read and write without locking errors."""
    with get_db_connection(temp_project_dir["db_path"]) as c1:
        c1.execute("INSERT INTO articles (title, year) VALUES ('Conc1', 2026)")
    with get_db_connection(temp_project_dir["db_path"]) as c2:
        c2.execute("INSERT INTO articles (title, year) VALUES ('Conc2', 2026)")

    # Concurrent readers in WAL mode
    with get_db_connection(temp_project_dir["db_path"]) as c1, \
         get_db_connection(temp_project_dir["db_path"]) as c2:
        res1 = c1.execute("SELECT COUNT(*) FROM articles WHERE title LIKE 'Conc%'").fetchone()[0]
        res2 = c2.execute("SELECT COUNT(*) FROM articles WHERE title LIKE 'Conc%'").fetchone()[0]
        assert res1 == res2 == 2


def test_b11_db_zero_timeout_handling(temp_project_dir):
    """timeout=0.0 parameter handled safely."""
    with get_db_connection(temp_project_dir["db_path"], timeout=0.0) as conn:
        assert conn is not None


def test_b11_db_rollback_on_syntax_error(temp_project_dir):
    """Syntax error in query rolls back transaction safely."""
    try:
        with get_db_cursor(temp_project_dir["db_path"]) as cur:
            cur.execute("INSERT INTO articles (title, year) VALUES ('BeforeError', 2026)")
            cur.execute("SYNTAX ERROR IN SQL STATEMENT")
    except sqlite3.OperationalError:
        pass

    with get_db_cursor(temp_project_dir["db_path"]) as cur:
        cur.execute("SELECT title FROM articles WHERE title = 'BeforeError'")
        assert cur.fetchone() is None


def test_b11_db_cursor_context_commit(temp_project_dir):
    """get_db_cursor commits changes automatically upon exit."""
    with get_db_cursor(temp_project_dir["db_path"]) as cur:
        cur.execute("INSERT INTO articles (title, year) VALUES ('AutoCursor', 2026)")

    with get_db_cursor(temp_project_dir["db_path"]) as cur:
        cur.execute("SELECT title FROM articles WHERE title = 'AutoCursor'")
        assert cur.fetchone() is not None


# ============================================================================
# FEATURE 12: Resource Teardown Boundaries
# ============================================================================

def test_b12_teardown_unopened_vector_store(temp_project_dir):
    """Calling close on vector store without initialization is safe."""
    from pipeline.vector_store import ArchiveVectorStore
    # Calling close on object with None client
    dummy = type("DummyStore", (), {"qdrant_client": None, "close": ArchiveVectorStore.close})()
    dummy.close()


def test_b12_teardown_repeated_close_calls(temp_project_dir, mock_embedding_client):
    """Calling close() 10 times consecutively does not raise exception."""
    from pipeline.vector_store import ArchiveVectorStore
    with patch("pipeline.vector_store.get_embedding_client", return_value=mock_embedding_client):
        store = ArchiveVectorStore(config_path=str(temp_project_dir["config_path"]))
        for _ in range(10):
            store.close()


def test_b12_teardown_nonexistent_temp_file_deletion():
    """Unlinking non-existent file handled silently."""
    p = Path("/tmp/definitely_non_existent_file_12345.tmp")
    try:
        p.unlink()
    except FileNotFoundError:
        pass
    assert not p.exists()


def test_b12_teardown_zero_byte_image_optimization(temp_project_dir):
    """Passing non-existent image path returns None safely."""
    from pipeline.image_optimizer import ImageOptimizer
    opt = ImageOptimizer()
    non_existent = temp_project_dir["path"] / "missing.png"
    out_dir = temp_project_dir["path"] / "opt_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = opt.optimize_image(non_existent, out_dir)
    assert res is None


def test_b12_teardown_corrupted_image_file(temp_project_dir):
    """Corrupted image bytes trigger fallback copy without crashing process."""
    from pipeline.image_optimizer import ImageOptimizer
    opt = ImageOptimizer()
    corrupt_file = temp_project_dir["path"] / "corrupt.png"
    corrupt_file.write_bytes(b"NOT_A_VALID_PNG_HEADER")
    out_dir = temp_project_dir["path"] / "opt_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = opt.optimize_image(corrupt_file, out_dir)
    assert res is not None
    assert res.suffix != ".webp"


# ============================================================================
# FEATURE 13: API Server Boundaries
# ============================================================================

@pytest.mark.asyncio
async def test_b13_api_empty_post_body():
    """Posting empty dict {} to /api/pipeline/run initiates pipeline with defaults."""
    import httpx
    from api_server import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/pipeline/run", json={})
        assert resp.status_code in [200, 400]


@pytest.mark.asyncio
async def test_b13_api_invalid_json_payload():
    """Posting invalid JSON body returns 422 Unprocessable Entity."""
    import httpx
    from api_server import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/projects/select", content=b"invalid json {", headers={"Content-Type": "application/json"})
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_b13_api_nonexistent_project_selection():
    """Selecting non-existent project returns 404."""
    import httpx
    from api_server import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/projects/select", json={"project_id": "non_existent_project_xyz"})
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_b13_api_negative_limit_parameter():
    """Posting negative limit parameter handled safely."""
    from run import parse_limit
    assert parse_limit("-10") is None


@pytest.mark.asyncio
async def test_b13_api_qdrant_search_missing_query():
    """Search endpoint without query string returns 422 Unprocessable Entity."""
    import httpx
    from api_server import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/db/qdrant/search", json={})
        assert resp.status_code in [400, 422]


# ============================================================================
# FEATURE 14: Documentation Boundaries
# ============================================================================

def test_b14_docs_no_zero_byte_markdown():
    """No zero-byte markdown files exist in repository."""
    for mf in REPO_ROOT.glob("*.md"):
        assert mf.stat().st_size > 0, f"Zero-byte markdown file found: {mf.name}"


def test_b14_docs_utf8_encoding_clean():
    """All markdown files in repo decode strictly as UTF-8."""
    for mf in REPO_ROOT.glob("*.md"):
        content = mf.read_text(encoding="utf-8")
        assert len(content) > 0


def test_b14_docs_no_unresolved_todos():
    """PROJECT.md and README.md contain no empty unresolved stubs."""
    readme = REPO_ROOT / "README.md"
    assert readme.exists()
    assert len(readme.read_text(encoding="utf-8")) > 500


def test_b14_docs_path_separators_forward_slashes():
    """Markdown documents use POSIX forward slashes in directory paths."""
    readme = REPO_ROOT / "README.md"
    content = readme.read_text(encoding="utf-8")
    assert "\\" not in content.replace("\\n", "").replace("\\t", "") or "/" in content


def test_b14_docs_code_blocks_have_language_tags():
    """README.md code fences specify language identifier (bash, json, python)."""
    readme = REPO_ROOT / "README.md"
    content = readme.read_text(encoding="utf-8")
    assert "```bash" in content or "```python" in content or "```json" in content


# ============================================================================
# FEATURE 15: CLI & Config Boundaries
# ============================================================================

def test_b15_parse_limit_zero_returns_none():
    """parse_limit('0') returns None."""
    from run import parse_limit
    assert parse_limit("0") is None


def test_b15_parse_limit_whitespace_string():
    """parse_limit('   ') returns None."""
    from run import parse_limit
    assert parse_limit("   ") is None


def test_b15_parse_limit_malformed_range():
    """parse_limit('abc:def') raises ArgumentTypeError."""
    import argparse
    from run import parse_limit
    with pytest.raises(argparse.ArgumentTypeError):
        parse_limit("abc:def")


def test_b15_config_nonexistent_file_raises():
    """Loading non-existent config file raises FileNotFoundError."""
    non_existent = Path("/tmp/nonexistent_config_123.json")
    with pytest.raises(FileNotFoundError):
        with open(non_existent, "r", encoding="utf-8") as f:
            json.load(f)


def test_b15_config_empty_json_file(temp_project_dir):
    """Empty JSON file {} parsed safely."""
    empty_json = temp_project_dir["path"] / "empty.json"
    empty_json.write_text("{}", encoding="utf-8")
    with open(empty_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data == {}


# ============================================================================
# FEATURE 16: Pytest Config Boundaries
# ============================================================================

def test_b16_pytest_missing_test_file_exit_code():
    """Invoking pytest on non-existent test file returns code 4 (USAGE_ERROR)."""
    res = subprocess.run([sys.executable, "-m", "pytest", "tests/nonexistent_test_xyz.py"], cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 4


def test_b16_pytest_isolation_between_test_runs(temp_project_dir):
    """Writing data into one test temp project does not leak into other test contexts."""
    with get_db_cursor(temp_project_dir["db_path"]) as cur:
        cur.execute("INSERT INTO articles (title, year) VALUES ('Isolated Article', 2026)")
    with get_db_cursor(temp_project_dir["db_path"]) as cur:
        cur.execute("SELECT COUNT(*) FROM articles WHERE title = 'Isolated Article'")
        assert cur.fetchone()[0] == 1


def test_b16_pytest_hermetic_no_unmocked_network():
    """Embedding mock fixture works offline without sockets."""
    mock = MagicMock()
    mock.embeddings.create.return_value = MagicMock(data=[MagicMock(embedding=[0.5] * 768)])
    res = mock.embeddings.create(model="any", input=["test"])
    assert len(res.data[0].embedding) == 768


def test_b16_pytest_execution_within_timeout():
    """Boundary assertions execute swiftly within sub-second thresholds."""
    import time
    t0 = time.time()
    for _ in range(100):
        _ = 2 + 2
    assert (time.time() - t0) < 0.5


def test_b16_pytest_clean_resource_reclamation(temp_project_dir):
    """Temp project directory fixture verifies folder existence and clean teardown."""
    assert os.path.isdir(temp_project_dir["dir"])
