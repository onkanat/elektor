import os
import json
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Body
from starlette.background import BackgroundTask
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import pydantic
import ollama

app = FastAPI(title="Elektor Universal PDF Pipeline Backend API", version="1.0.0")

# Enable CORS for Frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_PATH = Path("config.json")

# Global pipeline execution state
pipeline_state: Dict[str, Any] = {
    "status": "idle",  # idle, running, completed, failed
    "command": None,
    "start_time": None,
    "end_time": None,
    "exit_code": None,
    "logs": []
}
pipeline_lock = threading.Lock()

def get_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="config.json not found")
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading config.json: {str(e)}")

def save_config(data: Dict[str, Any]):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error writing config.json: {str(e)}")

@app.get("/api/health")
def health_check():
    config = get_config()
    ollama_url = config.get("ollama_url", "http://localhost:11434")
    
    # Check Ollama connectivity
    ollama_status = "offline"
    available_models = []
    try:
        client = ollama.Client(host=ollama_url)
        models_resp = client.list()
        if isinstance(models_resp, dict) and "models" in models_resp:
            available_models = [m.get("name") or m.get("model") for m in models_resp["models"]]
        elif hasattr(models_resp, "models"):
            available_models = [getattr(m, "model", getattr(m, "name", str(m))) for m in models_resp.models]
        ollama_status = "online"
    except Exception as e:
        ollama_status = f"offline ({str(e)})"
        
    db_file = Path(config.get("db_path", "database/sdr_engineers.db"))
    qdrant_path = Path(config.get("qdrant_db_path", "qdrant_sdr"))

    return {
        "status": "ok",
        "port": 3456,
        "ollama_status": ollama_status,
        "ollama_url": ollama_url,
        "available_models": available_models,
        "sqlite_exists": db_file.exists(),
        "qdrant_exists": qdrant_path.exists(),
        "config": config
    }

@app.get("/api/config")
def read_config():
    return get_config()

@app.post("/api/config")
def update_config(data: Dict[str, Any] = Body(...)):
    current = get_config()
    current.update(data)
    save_config(current)
    return {"status": "success", "config": current}

# Pipeline Execution Background Task
def run_pipeline_process(cmd: str, limit: Optional[str] = None, reset: bool = False):
    global pipeline_state
    
    with pipeline_lock:
        pipeline_state["status"] = "running"
        pipeline_state["command"] = cmd
        pipeline_state["start_time"] = time.time()
        pipeline_state["end_time"] = None
        pipeline_state["exit_code"] = None
        pipeline_state["logs"] = [f"=== Starting pipeline subcommand: '{cmd}' (Limit: {limit}, Reset: {reset}) ==="]

    args = ["python3.11", "run.py", cmd]
    if limit:
        args.extend(["--limit", str(limit)])
    if reset:
        args.append("--reset")

    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        for line in iter(process.stdout.readline, ''):
            if line:
                clean_line = line.rstrip()
                with pipeline_lock:
                    pipeline_state["logs"].append(clean_line)
                    if len(pipeline_state["logs"]) > 1000:
                        pipeline_state["logs"].pop(0)

        process.wait()
        with pipeline_lock:
            pipeline_state["exit_code"] = process.returncode
            pipeline_state["status"] = "completed" if process.returncode == 0 else "failed"
            pipeline_state["end_time"] = time.time()
            pipeline_state["logs"].append(f"=== Task finished with exit code: {process.returncode} ===")

    except Exception as e:
        with pipeline_lock:
            pipeline_state["status"] = "failed"
            pipeline_state["end_time"] = time.time()
            pipeline_state["logs"].append(f"Execution error: {str(e)}")

@app.post("/api/pipeline/run")
def trigger_pipeline(payload: Dict[str, Any] = Body(...)):
    global pipeline_state
    with pipeline_lock:
        if pipeline_state["status"] == "running":
            raise HTTPException(status_code=400, detail="A pipeline task is already running.")

    cmd = payload.get("command", "pipeline")
    limit = payload.get("limit")
    reset = payload.get("reset", False)

    thread = threading.Thread(target=run_pipeline_process, args=(cmd, limit, reset))
    thread.daemon = True
    thread.start()

    return {"status": "started", "command": cmd, "limit": limit, "reset": reset}

@app.get("/api/pipeline/status")
def get_pipeline_status():
    with pipeline_lock:
        return dict(pipeline_state)

# Section B: Dataset Viewer & Database Inspector Uç Noktaları

@app.get("/api/datasets")
def list_datasets():
    exports_dir = Path("exports")
    if not exports_dir.exists():
        return {"datasets": []}

    results = []
    for filepath in exports_dir.glob("**/*.jsonl"):
        stat = filepath.stat()
        line_count = 0
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                line_count = sum(1 for _ in f)
        except Exception:
            pass

        results.append({
            "filename": filepath.name,
            "relative_path": str(filepath.relative_to(exports_dir)),
            "full_path": str(filepath),
            "size_bytes": stat.st_size,
            "modified_at": stat.st_mtime,
            "sample_count": line_count
        })

    return {"datasets": sorted(results, key=lambda x: x["filename"])}

@app.get("/api/datasets/preview")
def preview_dataset(
    file_path: str = Query(..., description="Relative path in exports folder"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None
):
    exports_dir = Path("exports")
    target_file = (exports_dir / file_path).resolve()
    if not str(target_file).startswith(str(exports_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not target_file.exists():
        raise HTTPException(status_code=404, detail="File not found")

    items = []
    total_matches = 0
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit

    try:
        with open(target_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    text_content = json.dumps(record, ensure_ascii=False)
                    if search and search.lower() not in text_content.lower():
                        continue
                    
                    if start_idx <= total_matches < end_idx:
                        items.append(record)
                    total_matches += 1
                except Exception:
                    continue
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading JSONL: {str(e)}")

    return {
        "file": target_file.name,
        "page": page,
        "limit": limit,
        "total_matches": total_matches,
        "items": items
    }

# SQLite Lite Query Viewer
@app.get("/api/db/sqlite/tables")
def get_sqlite_tables():
    config = get_config()
    db_path = config.get("db_path", "database/sdr_engineers.db")
    if not os.path.exists(db_path):
        return {"tables": [], "db_path": db_path, "exists": False}

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        
        info = []
        for t in tables:
            cursor.execute(f"SELECT COUNT(*) FROM `{t}`")
            count = cursor.fetchone()[0]
            info.append({"name": t, "count": count})
            
        conn.close()
        return {"tables": info, "db_path": db_path, "exists": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SQLite error: {str(e)}")

@app.get("/api/db/sqlite/query")
def query_sqlite_table(
    table: str = Query("articles"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    search: Optional[str] = None
):
    config = get_config()
    db_path = config.get("db_path", "database/sdr_engineers.db")
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="Database file not found")

    offset = (page - 1) * limit
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        where_clause = ""
        params = []
        if search:
            where_clause = "WHERE title LIKE ? OR text_content LIKE ?"
            params = [f"%{search}%", f"%{search}%"]

        count_sql = f"SELECT COUNT(*) FROM `{table}` {where_clause}"
        cursor.execute(count_sql, params)
        total_records = cursor.fetchone()[0]

        query_sql = f"SELECT * FROM `{table}` {where_clause} LIMIT ? OFFSET ?"
        cursor.execute(query_sql, params + [limit, offset])
        rows = [dict(row) for row in cursor.fetchall()]
        
        for r in rows:
            if "text_content" in r and r["text_content"] and len(r["text_content"]) > 500:
                r["text_content_preview"] = r["text_content"][:500] + "..."
            if "raw_ai_response" in r and r["raw_ai_response"] and len(r["raw_ai_response"]) > 300:
                r["raw_ai_response_preview"] = r["raw_ai_response"][:300] + "..."

        conn.close()
        return {
            "table": table,
            "page": page,
            "limit": limit,
            "total_records": total_records,
            "records": rows
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SQLite query error: {str(e)}")

# Qdrant Lite Query Viewer
@app.get("/api/db/qdrant/info")
def get_qdrant_info():
    config = get_config()
    qdrant_path = config.get("qdrant_db_path", "qdrant_sdr")
    collection_name = config.get("qdrant_collection_name", "sdr_articles")
    
    if not os.path.exists(qdrant_path):
        return {"exists": False, "path": qdrant_path, "collection": collection_name, "points_count": 0}

    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(path=qdrant_path)
        collections = client.get_collections()
        coll_list = [c.name for c in collections.collections]
        
        points_count = 0
        if collection_name in coll_list:
            info = client.get_collection(collection_name)
            points_count = info.points_count

        return {
            "exists": True,
            "path": qdrant_path,
            "collection": collection_name,
            "all_collections": coll_list,
            "points_count": points_count
        }
    except Exception as e:
        return {"exists": False, "path": qdrant_path, "error": str(e)}

@app.post("/api/db/qdrant/search")
def search_qdrant(payload: Dict[str, Any] = Body(...)):
    config = get_config()
    query_text = payload.get("query", "")
    top_k = payload.get("top_k", 5)
    
    if not query_text.strip():
        raise HTTPException(status_code=400, detail="Query string cannot be empty")

    try:
        from pipeline.vector_store import ArchiveVectorStore
        store = ArchiveVectorStore()
        results = store.search(query_text, top_k=top_k)
        return {"query": query_text, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Qdrant search error: {str(e)}")

# Section C: Analyzer Model Chat Uç Noktası
@app.post("/api/chat")
def chat_with_analyzer(payload: Dict[str, Any] = Body(...)):
    config = get_config()
    ollama_url = config.get("ollama_url", "http://localhost:11434")
    model = payload.get("model") or config.get("model_analyzer", "qwen3.6:27b-mtp-q4_K_M")
    messages = payload.get("messages", [])
    system_prompt = payload.get("system_prompt") or config.get("llm_persona", "")

    if not messages:
        raise HTTPException(status_code=400, detail="Messages array required")

    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    try:
        client = ollama.Client(host=ollama_url)
        response = client.chat(model=model, messages=full_messages, stream=False)
        
        reply_content = ""
        if isinstance(response, dict) and "message" in response:
            reply_content = response["message"].get("content", "")
        elif hasattr(response, "message"):
            reply_content = getattr(response.message, "content", "")

        return {
            "model": model,
            "message": {"role": "assistant", "content": reply_content}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ollama chat error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=3456, reload=True)
