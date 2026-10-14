import sys
import os
import json
import sqlite3
import tempfile
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import Generator
from contextlib import contextmanager
import pytest
from unittest.mock import MagicMock, patch

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Safe adapters for modules under milestone development
try:
    from pipeline.chunking import SmartTextChunker, TextChunk
    HAS_NATIVE_CHUNKING = True
except ImportError:
    HAS_NATIVE_CHUNKING = False

    @dataclass
    class TextChunk:
        text: str
        chunk_index: int
        total_chunks: int
        start_char: int
        end_char: int
        token_estimate: int

    class SmartTextChunker:
        def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 150):
            self.chunk_size = chunk_size
            self.chunk_overlap = chunk_overlap

        def chunk_text(self, text: str, max_chunks: int = 500) -> list[TextChunk]:
            if not text or not text.strip():
                return []
            words = text.split()
            if not words:
                return []
            chunks_str = []
            curr_words = []
            curr_len = 0
            for w in words:
                w_len = len(w) + 1
                if curr_len + w_len > self.chunk_size and curr_words:
                    chunks_str.append(" ".join(curr_words))
                    overlap_w = []
                    overlap_l = 0
                    for ow in reversed(curr_words):
                        if overlap_l + len(ow) + 1 > self.chunk_overlap:
                            break
                        overlap_w.insert(0, ow)
                        overlap_l += len(ow) + 1
                    curr_words = overlap_w
                    curr_len = overlap_l
                curr_words.append(w)
                curr_len += w_len
            if curr_words:
                chunks_str.append(" ".join(curr_words))

            chunks_str = chunks_str[:max_chunks]
            total = len(chunks_str)
            result = []
            char_cursor = 0
            for idx, c_text in enumerate(chunks_str):
                start_c = text.find(c_text[:30], char_cursor) if len(c_text) >= 30 else text.find(c_text, char_cursor)
                if start_c == -1:
                    start_c = char_cursor
                end_c = start_c + len(c_text)
                char_cursor = start_c
                result.append(TextChunk(
                    text=c_text,
                    chunk_index=idx,
                    total_chunks=total,
                    start_char=start_c,
                    end_char=end_c,
                    token_estimate=len(c_text) // 4
                ))
            return result

try:
    from pipeline.db import get_db_connection, get_db_cursor
    HAS_NATIVE_DB = True
except ImportError:
    HAS_NATIVE_DB = False

    @contextmanager
    def get_db_connection(db_path: str | Path, timeout: float = 60.0, wal_mode: bool = True) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(db_path), timeout=timeout)
        try:
            if wal_mode:
                conn.execute("PRAGMA busy_timeout=60000;")
                try:
                    conn.execute("PRAGMA journal_mode=WAL;")
                except sqlite3.OperationalError:
                    pass
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def get_db_cursor(db_path: str | Path, timeout: float = 60.0) -> Generator[sqlite3.Cursor, None, None]:
        with get_db_connection(db_path, timeout=timeout) as conn:
            cursor = conn.cursor()
            yield cursor


@pytest.fixture
def mock_embedding_vector():
    """Returns a deterministic 768-dimensional unit vector."""
    vec = [0.0] * 768
    vec[0] = 1.0
    return vec


@pytest.fixture
def mock_embedding_client(mock_embedding_vector):
    """Provides a mocked embedding client returning deterministic embeddings."""
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_data = MagicMock()
    mock_data.embedding = mock_embedding_vector
    mock_resp.data = [mock_data]
    mock_client.embeddings.create.return_value = mock_resp
    return mock_client


@pytest.fixture
def temp_project_dir():
    """Provides a temporary, self-contained project workspace with config and SQLite database."""
    temp_dir = tempfile.mkdtemp(prefix="elektor_e2e_")
    base_path = Path(temp_dir)
    db_path = base_path / "test_project.db"
    qdrant_dir = base_path / "qdrant_data"
    export_dir = base_path / "exports" / "test_project"
    export_dir.mkdir(parents=True, exist_ok=True)
    qdrant_dir.mkdir(parents=True, exist_ok=True)

    config_path = base_path / "config.json"
    config_data = {
        "project_id": "test_project",
        "dataset_name": "Test Technical Archive",
        "dataset_name_tr": "Test Teknik Arşivi",
        "db_path": str(db_path),
        "qdrant_db_path": str(qdrant_dir),
        "qdrant_collection_name": "test_collection",
        "ollama_url": "http://localhost:11434",
        "model_embedding": "nomic-embed-text",
        "model_analyzer": "qwen3.6:27b-mtp-q4_K_M",
        "model_translator": "translategemma:12b-it-q4_K_M",
        "chunk_size": 500,
        "chunk_overlap": 100,
        "clean_alpaca_input": True,
        "filter_boilerplate": True,
        "generation_language": "bilingual"
    }
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)

    # Initialize standard schema in SQLite
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT,
            filename TEXT,
            title TEXT,
            year INTEGER,
            zoom_snippet TEXT,
            extracted_text TEXT,
            is_ocr INTEGER DEFAULT 0,
            is_embedded INTEGER DEFAULT 0,
            processed_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS enrichments (
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
            judge_score REAL,
            judge_status TEXT,
            judge_feedback TEXT,
            judged_at TEXT,
            is_excluded INTEGER DEFAULT 0,
            processed_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS synthetic_code_pairs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instruction TEXT,
            input_code TEXT,
            output_response TEXT,
            tr_instruction TEXT,
            tr_output_response TEXT,
            category TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

    yield {
        "dir": temp_dir,
        "path": base_path,
        "db_path": db_path,
        "qdrant_dir": qdrant_dir,
        "export_dir": export_dir,
        "config_path": config_path,
        "config": config_data
    }

    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass
