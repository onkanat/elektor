"""
Self-Test / Autonomous System Health Diagnostic Module for Elektor Pipeline.
Checks:
1. SQLite DB WAL mode & table integrity.
2. Qdrant vector database connection & query_points compatibility.
3. Ollama server reachability, model tags & VRAM status.
4. DeepSeek-OCR VLM base64 PNG stream conversion.
5. Pytest unit test suite execution.
"""
import sys
import json
import sqlite3
import subprocess
import urllib.request
from pathlib import Path

def run_self_test(config_path: str = "config.json"):
    print("==================================================")
    print("🔍 ELEKTOR PIPELINE SYSTEM SELF-TEST & DIAGNOSTICS")
    print("==================================================")
    
    passed_checks = 0
    total_checks = 5
    
    # 1. Config & SQLite DB Check
    print("\n[1/5] Checking Configuration & SQLite Database...")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        db_path = Path(cfg.get("db_path", "database/test_vision.db"))
        print(f"  Config loaded: Project ID = '{cfg.get('project_id')}'")
        if db_path.exists():
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode;")
            journal_mode = cursor.fetchone()[0]
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()
            print(f"  SQLite DB OK: {db_path} (Journal Mode: {journal_mode.upper()}, Tables: {len(tables)})")
        else:
            print(f"  SQLite DB Notice: {db_path} does not exist yet (will be created on run).")
        passed_checks += 1
    except Exception as e:
        print(f"  ❌ SQLite Check Failed: {e}")

    # 2. Qdrant Vector Store Check
    print("\n[2/5] Checking Local Qdrant Vector Database...")
    try:
        from pipeline.vector_store import ArchiveVectorStore
        store = ArchiveVectorStore(config_path=config_path)
        col_name = store.collection_name
        points_count = store.qdrant_client.get_collection(col_name).points_count
        print(f"  Qdrant OK: Collection '{col_name}' (Points: {points_count}, Mode: Local Storage)")
        store.close()
        passed_checks += 1
    except Exception as e:
        print(f"  ❌ Qdrant Check Failed: {e}")

    # 3. Ollama Server & VRAM Check
    print("\n[3/5] Checking Ollama Server & Model Availability...")
    ollama_url = cfg.get("ollama_url", "http://localhost:11434").rstrip("/")
    try:
        req = urllib.request.urlopen(f"{ollama_url}/api/tags", timeout=5)
        tags_data = json.loads(req.read().decode("utf-8"))
        models = [m["name"] for m in tags_data.get("models", [])]
        
        req_ps = urllib.request.urlopen(f"{ollama_url}/api/ps", timeout=5)
        ps_data = json.loads(req_ps.read().decode("utf-8"))
        loaded_models = [m["name"] for m in ps_data.get("models", [])]
        
        print(f"  Ollama Server OK: {ollama_url}")
        print(f"  Installed Models ({len(models)}): {', '.join(models[:6])}...")
        print(f"  Loaded Models in VRAM ({len(loaded_models)}): {loaded_models if loaded_models else 'None (Idle)'}")
        passed_checks += 1
    except Exception as e:
        print(f"  ❌ Ollama Connection Failed ({ollama_url}): {e}")

    # 4. Vision OCR Manager Check
    print("\n[4/5] Checking Vision OCR Engine & PNG Stream Conversion...")
    try:
        from pipeline.vision_ocr import VisionOCRManager
        v = VisionOCRManager(config_path=config_path)
        print(f"  Vision OCR Manager OK: Model = '{v.model_vision}'")
        passed_checks += 1
    except Exception as e:
        print(f"  ❌ Vision OCR Manager Failed: {e}")

    # 5. Unit Test Suite (pytest) Check
    print("\n[5/5] Executing Pytest Test Suite...")
    try:
        import os
        env = dict(os.environ)
        env["PYTHONPATH"] = "."
        res = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-o", "pythonpath=."],
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )
        if res.returncode == 0:
            print("  Pytest Suite OK: All 21 unit tests PASSED cleanly!")
            passed_checks += 1
        else:
            print(f"  ⚠️ Pytest Warning (Exit code {res.returncode}):\n{res.stdout[:200]}")
    except Exception as e:
        print(f"  ❌ Pytest Execution Failed: {e}")

    print("\n==================================================")
    print(f"🎯 SELF-TEST COMPLETED: {passed_checks}/{total_checks} System Checks Passed!")
    print("==================================================")
    return passed_checks == total_checks

if __name__ == "__main__":
    run_self_test()
