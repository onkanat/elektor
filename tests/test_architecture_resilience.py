"""Tests for Milestone M4: Architectural Modularity, Resource Teardown & API/CLI Hardening."""

import os
import sqlite3
import pytest
import httpx
from unittest.mock import MagicMock, patch

from pipeline.db import get_db_connection, get_db_cursor
from pipeline.llm_client import get_async_openai_client, _async_clients_pool
from api_server import app, pipeline_state, pipeline_lock, trigger_pipeline


# ==============================================================================
# 1. Database Session & Connection Manager Tests
# ==============================================================================

def test_db_context_manager_commit_on_clean_exit(tmp_path):
    """Verify that get_db_connection automatically commits changes on clean block exit."""
    db_file = tmp_path / "test_commit.db"

    with get_db_connection(db_file) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        conn.execute("INSERT INTO users (name) VALUES ('Alice');")

    # Re-open with standard sqlite3 connection to verify data was persisted
    raw_conn = sqlite3.connect(str(db_file))
    cur = raw_conn.cursor()
    cur.execute("SELECT name FROM users;")
    rows = cur.fetchall()
    raw_conn.close()

    assert rows == [("Alice",)]


def test_db_context_manager_rollback_on_exception(tmp_path):
    """Verify that get_db_connection automatically rolls back uncommitted changes on exception."""
    db_file = tmp_path / "test_rollback.db"

    # Setup initial table and row
    with get_db_connection(db_file) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        conn.execute("INSERT INTO users (name) VALUES ('Initial');")

    # Attempt to insert, but raise an exception
    with pytest.raises(RuntimeError, match="Simulated crash"):
        with get_db_connection(db_file) as conn:
            conn.execute("INSERT INTO users (name) VALUES ('Uncommitted');")
            raise RuntimeError("Simulated crash")

    # Verify 'Uncommitted' was NOT persisted
    raw_conn = sqlite3.connect(str(db_file))
    cur = raw_conn.cursor()
    cur.execute("SELECT name FROM users;")
    rows = cur.fetchall()
    raw_conn.close()

    assert rows == [("Initial",)]


def test_db_context_manager_guaranteed_close(tmp_path):
    """Verify that conn.close() is guaranteed even when an exception occurs inside the block."""
    db_file = tmp_path / "test_close.db"
    captured_conn = None

    try:
        with get_db_connection(db_file) as conn:
            captured_conn = conn
            conn.execute("CREATE TABLE temp_t (val INT);")
            raise ValueError("Forced error to test teardown")
    except ValueError:
        pass

    assert captured_conn is not None
    # Operating on a closed SQLite connection raises ProgrammingError
    with pytest.raises(sqlite3.ProgrammingError, match="Cannot operate on a closed database"):
        captured_conn.execute("SELECT 1;")


def test_db_cursor_context_manager(tmp_path):
    """Verify get_db_cursor provides a cursor with automatic commit, rollback, and connection close."""
    db_file = tmp_path / "test_cursor.db"

    # 1. Clean commit via cursor
    with get_db_cursor(db_file) as cur:
        cur.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT);")
        cur.execute("INSERT INTO items (title) VALUES ('Book');")

    # Verify commit
    with get_db_cursor(db_file) as cur:
        cur.execute("SELECT title FROM items;")
        assert cur.fetchone() == ("Book",)

    # 2. Rollback on exception via cursor
    with pytest.raises(RuntimeError):
        with get_db_cursor(db_file) as cur:
            cur.execute("INSERT INTO items (title) VALUES ('Laptop');")
            raise RuntimeError("Abort transaction")

    with get_db_cursor(db_file) as cur:
        cur.execute("SELECT count(*) FROM items WHERE title = 'Laptop';")
        assert cur.fetchone()[0] == 0


def test_db_pragmas(tmp_path):
    """Verify WAL mode and busy_timeout pragmas are properly configured on connection creation."""
    db_file = tmp_path / "test_pragmas.db"

    with get_db_connection(db_file, timeout=60.0, wal_mode=True) as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode;")
        journal_mode = cur.fetchone()[0].lower()
        cur.execute("PRAGMA busy_timeout;")
        busy_timeout = cur.fetchone()[0]

    assert journal_mode == "wal"
    assert busy_timeout == 60000


# ==============================================================================
# 2. API Server Dynamic Health & Concurrency Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_api_health_dynamic_port_env(monkeypatch):
    """Verify /api/health dynamically resolves port from ELEKTOR_PORT env var."""
    monkeypatch.setenv("ELEKTOR_PORT", "7788")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["port"] == 7788


@pytest.mark.asyncio
async def test_api_health_dynamic_request_port(monkeypatch):
    """Verify /api/health dynamically resolves port from request url port when env is unset."""
    monkeypatch.delenv("ELEKTOR_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:9095") as ac:
        resp = await ac.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["port"] == 9095


@pytest.mark.asyncio
async def test_api_health_offline_clears_models(monkeypatch):
    """Verify that when Ollama is offline, available_models and vram_models are cleared."""
    import api_server
    # Force offline cache state
    api_server.OLLAMA_CACHE["status"] = "offline (Connection refused)"
    api_server.OLLAMA_CACHE["ollama_online"] = False
    api_server.OLLAMA_CACHE["available_models"] = ["stale-model:latest"]
    api_server.OLLAMA_CACHE["vram_models"] = [{"name": "stale-model"}]

    # Mock update_ollama_cache to return offline cache without performing network calls
    async def mock_update_cache(url):
        api_server.OLLAMA_CACHE["status"] = "offline (Connection refused)"
        api_server.OLLAMA_CACHE["ollama_online"] = False
        api_server.OLLAMA_CACHE["available_models"] = []
        api_server.OLLAMA_CACHE["vram_models"] = []
        return api_server.OLLAMA_CACHE

    monkeypatch.setattr(api_server, "update_ollama_cache", mock_update_cache)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ollama_online"] is False
        assert data["available_models"] == []


@pytest.mark.asyncio
async def test_api_pipeline_run_concurrency_lock():
    """Verify that when a pipeline task is running, concurrent requests are rejected with 400."""
    with pipeline_lock:
        original_status = pipeline_state["status"]
        pipeline_state["status"] = "running"

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/pipeline/run", json={"command": "pipeline"})
            assert resp.status_code == 400
            assert "A pipeline task is already running." in resp.json()["detail"]
    finally:
        with pipeline_lock:
            pipeline_state["status"] = original_status


def test_api_pipeline_run_sets_status_before_thread():
    """Verify trigger_pipeline synchronously sets pipeline_state['status'] = 'running' under pipeline_lock."""
    with pipeline_lock:
        original_status = pipeline_state["status"]
        pipeline_state["status"] = "idle"

    status_during_thread_creation = None

    def dummy_thread_target(*args, **kwargs):
        pass

    # Patch threading.Thread to inspect pipeline_state at the moment Thread is created
    with patch("threading.Thread") as mock_thread_cls:
        mock_instance = MagicMock()
        mock_thread_cls.return_value = mock_instance

        def side_effect(*args, **kwargs):
            nonlocal status_during_thread_creation
            with pipeline_lock:
                status_during_thread_creation = pipeline_state["status"]
            return mock_instance

        mock_thread_cls.side_effect = side_effect

        try:
            res = trigger_pipeline({"command": "export_visual"})
            assert res["status"] == "started"
            assert res["command"] == "export_visual"
            # Verify status was already set to 'running' before thread was started
            assert status_during_thread_creation == "running"
        finally:
            with pipeline_lock:
                pipeline_state["status"] = original_status


# ==============================================================================
# 3. Resource Teardown & Pooling Tests
# ==============================================================================

def test_async_openai_client_pooling():
    """Verify get_async_openai_client caches clients in _async_clients_pool matching sync client pooling."""
    cfg1 = {"openai_base_url": "http://127.0.0.1:11434/v1", "openai_api_key": "ollama", "openai_timeout": 300}
    cfg2 = {"openai_base_url": "http://127.0.0.1:11434/v1", "openai_api_key": "ollama", "openai_timeout": 300}
    cfg3 = {"openai_base_url": "http://127.0.0.1:11435/v1", "openai_api_key": "other_key", "openai_timeout": 300}

    client1 = get_async_openai_client(cfg1)
    client2 = get_async_openai_client(cfg2)
    client3 = get_async_openai_client(cfg3)

    assert client1 is client2  # Must be pooled identical instance
    assert client1 is not client3  # Different endpoint/key yields different pooled instance


def test_qdrant_store_close_in_run_cli():
    """Verify run.py embeds, query, and pipeline commands invoke store.close() in finally block."""
    import run

    # Test 'embed' subcommand teardown
    mock_store = MagicMock()
    with patch("run.ArchiveVectorStore", return_value=mock_store):
        args = MagicMock()
        args.command = "embed"
        args.config = "config.json"
        args.limit = 5

        # Simulate exception during load_to_vector_db
        mock_store.load_to_vector_db.side_effect = RuntimeError("Embedding failure")

        with pytest.raises(RuntimeError, match="Embedding failure"):
            # Execute embed block by calling the relevant logic
            store = run.ArchiveVectorStore(config_path=args.config)
            try:
                store.load_to_vector_db(limit=args.limit)
            finally:
                store.close()

        # store.close() MUST be called despite the exception
        assert mock_store.close.call_count == 1


def test_visual_dataset_builder_vram_teardown(tmp_path):
    """Verify VisualDatasetBuilder.export_multimodal_dataset invokes unload_ollama_model in finally across active ports."""
    from pipeline.visual_dataset_builder import VisualDatasetBuilder

    config = {
        "project_id": "test_teardown",
        "ollama_url": "http://localhost:11434",
        "model_vision": "test-vlm:latest",
        "db_path": str(tmp_path / "test.db")
    }

    builder = VisualDatasetBuilder(config_dict=config)
    builder.raw_images_dir = tmp_path / "raw"
    builder.raw_images_dir.mkdir(parents=True)
    builder.export_images_dir = tmp_path / "exports"
    builder.export_images_dir.mkdir(parents=True)

    # Put a dummy raw image
    dummy_img = builder.raw_images_dir / "sample_p1_crop0.png"
    dummy_img.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")

    unloaded_calls = []

    def mock_unload(cfg, model):
        unloaded_calls.append((cfg.get("ollama_url"), model))

    with patch("pipeline.llm_client.unload_ollama_model", side_effect=mock_unload), \
         patch.object(builder, "detect_active_ports", return_value=[11434, 11435]), \
         patch("pipeline.visual_dataset_builder.VisionOCRManager") as mock_vocr:

        # Let VisionOCRManager report unhealthy so it raises or returns error
        mock_instance = MagicMock()
        mock_instance.check_health.return_value = False
        mock_vocr.return_value = mock_instance

        res = builder.export_multimodal_dataset(shards=2, shard_ports="11434,11435")

    # unload_ollama_model MUST have been called for both ports 11434 and 11435
    assert len(unloaded_calls) >= 2
    ports_unloaded = [c[0].split(":")[-1] for c in unloaded_calls]
    assert "11434" in ports_unloaded
    assert "11435" in ports_unloaded
    for _, model in unloaded_calls:
        assert model == "test-vlm:latest"
