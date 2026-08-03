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
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import pydantic
import ollama
import psutil
import httpx

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
PROJECTS_REGISTRY_PATH = Path("projects_index.json")

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

def get_projects_registry() -> Dict[str, Any]:
    if not PROJECTS_REGISTRY_PATH.exists():
        default_registry = {
            "active_project_id": "sdr_engineers",
            "projects": {
                "sdr_engineers": {
                    "project_id": "sdr_engineers",
                    "project_name": "Software-Defined Radio for Engineers",
                    "config_file": "config.json",
                    "created_at": time.time(),
                    "last_accessed": time.time()
                }
            }
        }
        with open(PROJECTS_REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(default_registry, f, indent=2, ensure_ascii=False)
        return default_registry
    try:
        with open(PROJECTS_REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"active_project_id": "sdr_engineers", "projects": {}}

def save_projects_registry(registry: Dict[str, Any]):
    with open(PROJECTS_REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)

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

@app.get("/api/projects")
def list_projects():
    registry = get_projects_registry()
    active_id = registry.get("active_project_id", "sdr_engineers")
    projects_list = list(registry.get("projects", {}).values())
    
    # Sort projects by last_accessed descending
    projects_list.sort(key=lambda x: x.get("last_accessed", 0), reverse=True)

    return {
        "active_project_id": active_id,
        "projects": projects_list
    }

@app.post("/api/projects/select")
def select_project(payload: Dict[str, Any] = Body(...)):
    project_id = payload.get("project_id")
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id required")
        
    registry = get_projects_registry()
    projects = registry.get("projects", {})
    if project_id not in projects:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    # Update active project and timestamp
    registry["active_project_id"] = project_id
    projects[project_id]["last_accessed"] = time.time()
    save_projects_registry(registry)

    # Load project's specific config if saved under projects_<project_id>.json
    proj_config_path = Path(f"projects_{project_id}.json")
    proj_config = {}
    if proj_config_path.exists():
        try:
            with open(proj_config_path, "r", encoding="utf-8") as f:
                proj_config = json.load(f)
        except Exception:
            pass

    current_config = get_config()
    target_config = dict(current_config)
    target_config.update(proj_config)

    # Force sync project_id, database path, and qdrant paths for selected project
    target_config["project_id"] = project_id
    target_config["dataset_name"] = projects[project_id].get("project_name", target_config.get("dataset_name", project_id))
    
    expected_db = f"database/{project_id}.db"
    if not target_config.get("db_path") or not target_config["db_path"].endswith(f"{project_id}.db"):
        target_config["db_path"] = expected_db
        
    if not target_config.get("qdrant_db_path") or project_id not in target_config["qdrant_db_path"]:
        target_config["qdrant_db_path"] = f"qdrant_{project_id}"

    if not target_config.get("qdrant_collection_name") or project_id not in target_config["qdrant_collection_name"]:
        target_config["qdrant_collection_name"] = f"{project_id}_articles"

    # Save to config.json AND projects_<project_id>.json
    save_config(target_config)
    with open(proj_config_path, "w", encoding="utf-8") as f:
        json.dump(target_config, f, indent=2, ensure_ascii=False)

    return {"status": "success", "active_project_id": project_id, "config": target_config}

@app.post("/api/projects/create")
def create_project(payload: Dict[str, Any] = Body(...)):
    project_id = payload.get("project_id", "").strip().lower().replace(" ", "_")
    project_name = payload.get("project_name", "").strip()
    
    if not project_id or not project_name:
        raise HTTPException(status_code=400, detail="project_id and project_name are required")

    registry = get_projects_registry()
    projects = registry.setdefault("projects", {})

    if project_id in projects:
        raise HTTPException(status_code=400, detail=f"Project ID '{project_id}' already exists")

    # Create new project config from existing config or defaults
    current_config = get_config()
    new_config = dict(current_config)
    new_config["project_id"] = project_id
    new_config["dataset_name"] = project_name
    new_config["dataset_name_tr"] = payload.get("project_name_tr", project_name)
    new_config["input_mode"] = payload.get("input_mode", "book")
    new_config["input_path"] = payload.get("input_path", "")
    new_config["db_path"] = f"database/{project_id}.db"
    new_config["qdrant_db_path"] = f"qdrant_{project_id}"
    new_config["qdrant_collection_name"] = f"{project_id}_articles"
    if "llm_persona" in payload:
        new_config["llm_persona"] = payload["llm_persona"]
    if "llm_subject" in payload:
        new_config["llm_subject"] = payload["llm_subject"]

    # Save project specific config file
    proj_config_path = Path(f"projects_{project_id}.json")
    with open(proj_config_path, "w", encoding="utf-8") as f:
        json.dump(new_config, f, indent=2, ensure_ascii=False)

    # Register in projects_index.json
    projects[project_id] = {
        "project_id": project_id,
        "project_name": project_name,
        "config_file": str(proj_config_path),
        "created_at": time.time(),
        "last_accessed": time.time()
    }
    registry["active_project_id"] = project_id
    save_projects_registry(registry)
    
    # Set as active config
    save_config(new_config)

    return {"status": "created", "project_id": project_id, "config": new_config}

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

@app.get("/api/system/metrics")
def get_system_metrics():
    config = get_config()
    ollama_url = config.get("ollama_url", "http://localhost:11434")
    
    # System RAM & CPU
    cpu_percent = psutil.cpu_percent(interval=None)
    vm = psutil.virtual_memory()
    mem_info = {
        "total_mb": round(vm.total / (1024 * 1024), 1),
        "used_mb": round(vm.used / (1024 * 1024), 1),
        "available_mb": round(vm.available / (1024 * 1024), 1),
        "percent": vm.percent
    }
    
    # Ollama Loaded Models & VRAM Usage
    vram_models = []
    ollama_online = False
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{ollama_url}/api/ps")
            if resp.status_code == 200:
                ollama_online = True
                data = resp.json()
                for m in data.get("models", []):
                    vram_bytes = m.get("size_vram", 0) or m.get("size", 0)
                    vram_models.append({
                        "name": m.get("name") or m.get("model"),
                        "param_size": m.get("details", {}).get("parameter_size", "-"),
                        "quant": m.get("details", {}).get("quantization_level", "-"),
                        "vram_mb": round(vram_bytes / (1024 * 1024), 1),
                        "vram_gb": round(vram_bytes / (1024 * 1024 * 1024), 2),
                        "expires_at": m.get("expires_at")
                    })
    except Exception:
        ollama_online = False

    return {
        "cpu_percent": cpu_percent,
        "memory": mem_info,
        "ollama_online": ollama_online,
        "vram_models": vram_models
    }

@app.get("/api/config")
def read_config():
    return get_config()

@app.post("/api/config")
def update_config(data: Dict[str, Any] = Body(...)):
    current = get_config()
    current.update(data)
    save_config(current)

    # Sync to active project's JSON file if project_id exists
    project_id = current.get("project_id")
    if project_id:
        proj_config_path = Path(f"projects_{project_id}.json")
        try:
            with open(proj_config_path, "w", encoding="utf-8") as f:
                json.dump(current, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Could not update {proj_config_path}: {e}")

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

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
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
    valid_commands = ["pipeline", "extract", "enrich", "embed", "export"]
    if cmd not in valid_commands:
        raise HTTPException(status_code=400, detail=f"Geçersiz komut: '{cmd}'. Geçerli komutlar: {valid_commands}")

    limit = payload.get("limit")
    reset = payload.get("reset", False)
    confirm_reset = payload.get("confirm_reset", False)

    if reset and not confirm_reset:
        raise HTTPException(
            status_code=400,
            detail="GÜVENLİK UYARISI: Veritabanı ve veri setlerinin sıfırlanması için confirm_reset=True onayı zorunludur."
        )

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
def resolve_db_path(raw_path: str) -> str:
    if not raw_path:
        return "database/sdr_engineers.db"
    db_obj = Path(raw_path)
    if len(db_obj.parts) == 1:
        return str(Path("database") / raw_path)
    return str(db_obj)

# SQLite Lite Query Viewer
@app.get("/api/db/sqlite/tables")
def get_sqlite_tables():
    config = get_config()
    raw_path = config.get("db_path", "database/sdr_engineers.db")
    db_path = resolve_db_path(raw_path)
    if not os.path.exists(db_path):
        return {"tables": [], "db_path": db_path, "exists": False}

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")]
        
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
    raw_path = config.get("db_path", "database/sdr_engineers.db")
    db_path = resolve_db_path(raw_path)
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="Database file not found")

    offset = (page - 1) * limit
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get column info dynamically
        cursor.execute(f"PRAGMA table_info(`{table}`);")
        cols_info = cursor.fetchall()
        text_cols = [c[1] for c in cols_info if c[2].upper() in ['TEXT', 'VARCHAR', 'CHAR', 'CLOB'] or c[1] in ['title', 'filename', 'extracted_text', 'summary', 'turkish_title', 'turkish_summary', 'sft_qa', 'dpo_pairs', 'tr_sft_qa', 'tr_dpo_pairs']]

        where_clause = ""
        params = []
        if search and text_cols:
            clauses = [f"`{col}` LIKE ?" for col in text_cols]
            where_clause = "WHERE (" + " OR ".join(clauses) + ")"
            params = [f"%{search}%"] * len(text_cols)

        count_sql = f"SELECT COUNT(*) FROM `{table}` {where_clause}"
        cursor.execute(count_sql, params)
        total_records = cursor.fetchone()[0]

        query_sql = f"SELECT * FROM `{table}` {where_clause} LIMIT ? OFFSET ?"
        cursor.execute(query_sql, params + [limit, offset])
        rows = [dict(row) for row in cursor.fetchall()]
        
        for r in rows:
            for k, val in list(r.items()):
                if isinstance(val, str) and len(val) > 400:
                    r[f"{k}_preview"] = val[:400] + "..."

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

    client = None
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
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

@app.post("/api/db/qdrant/search")
def search_qdrant(payload: Dict[str, Any] = Body(...)):
    config = get_config()
    query_text = payload.get("query", "")
    top_k = payload.get("top_k", 5)
    
    if not query_text.strip():
        raise HTTPException(status_code=400, detail="Query string cannot be empty")

    store = None
    try:
        from pipeline.vector_store import ArchiveVectorStore
        store = ArchiveVectorStore()
        results = store.search(query_text, top_k=top_k)
        return {"query": query_text, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Qdrant search error: {str(e)}")
    finally:
        if store is not None:
            store.close()

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

# Mount React frontend static build
FRONTEND_DIST = Path("frontend/dist")
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="static_assets")

    @app.get("/")
    def serve_spa():
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}")
    def serve_spa_paths(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        file_path = FRONTEND_DIST / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIST / "index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=3456, reload=True)
