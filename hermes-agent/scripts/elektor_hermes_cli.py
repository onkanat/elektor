#!/usr/bin/env python3
"""Elektor Unified CLI & Tool Bridge for Hermes Agents (Nous Research Hermes Agent).

Strictly bound to the production Elektor host contracts:
- Flat config.json schema (db_path, qdrant_db_path, ollama_url, qdrant_collection_name, project_id, model_vision, etc.)
- Exact FastAPI payload contracts (/api/projects/select -> project_id, /api/projects/create -> project_id + project_name)
- Exact run.py CLI flags (--limit, --shards, --shard-ports, --pass, --mode, --threshold, --batch, --project, --type, etc.)
- Project-isolated export paths (exports/<db_stem>/sft_dataset.jsonl, dpo_dataset.jsonl, multimodal_visual_dataset.jsonl, multimodal_catalog.md)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import struct
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _extract_scoped_elektor_yaml(text: str) -> Dict[str, str]:
    """Extract repo_path and api_url strictly from skills.config.elektor (or top-level elektor:) block."""
    out: Dict[str, str] = {}
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text)
        if isinstance(loaded, dict):
            skills_node = loaded.get("skills")
            elektor_node = None
            if isinstance(skills_node, dict):
                cfg_node = skills_node.get("config")
                if isinstance(cfg_node, dict) and isinstance(cfg_node.get("elektor"), dict):
                    elektor_node = cfg_node["elektor"]
            if elektor_node is None and isinstance(loaded.get("elektor"), dict):
                elektor_node = loaded["elektor"]
            if isinstance(elektor_node, dict):
                if elektor_node.get("repo_path"):
                    out["repo_path"] = str(elektor_node["repo_path"]).strip()
                if elektor_node.get("api_url"):
                    out["api_url"] = str(elektor_node["api_url"]).strip()
                return out
    except Exception:
        pass

    # Stdlib indentation-aware fallback scoped strictly to the `elektor:` mapping block
    in_elektor = False
    elektor_indent = -1
    for raw_line in text.splitlines():
        stripped = raw_line.split("#", 1)[0].rstrip()
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        key_part = stripped.strip()
        if not in_elektor:
            if key_part == "elektor:" or key_part.startswith("elektor: "):
                in_elektor = True
                elektor_indent = indent
            continue
        if indent <= elektor_indent:
            in_elektor = False
            if key_part == "elektor:" or key_part.startswith("elektor: "):
                in_elektor = True
                elektor_indent = indent
            continue
        m_repo = re.match(r"^repo_path:\s*[\"']?([^\"'\n#]+)[\"']?$", key_part)
        if m_repo:
            out["repo_path"] = m_repo.group(1).strip()
        m_api = re.match(r"^api_url:\s*[\"']?([^\"'\n#]+)[\"']?$", key_part)
        if m_api:
            out["api_url"] = m_api.group(1).strip()
    return out


def _read_hermes_config_elektor() -> Dict[str, str]:
    """Read optional skills.config.elektor.repo_path / api_url from ~/.hermes/config.yaml."""
    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()
    cfg_yaml = hermes_home / "config.yaml"
    if not cfg_yaml.is_file():
        return {}
    try:
        text = cfg_yaml.read_text(encoding="utf-8", errors="replace")
        return _extract_scoped_elektor_yaml(text)
    except Exception:
        return {}



def resolve_repo_root() -> Path:
    """Resolve the Elektor repository root from env, ~/.hermes/config.yaml, or relative file location."""
    env_root = os.environ.get("ELEKTOR_REPO_PATH")
    if env_root:
        candidate = Path(env_root).expanduser().resolve()
        if (candidate / "run.py").exists():
            return candidate

    hermes_cfg = _read_hermes_config_elektor()
    if "repo_path" in hermes_cfg:
        candidate = Path(hermes_cfg["repo_path"]).expanduser().resolve()
        if (candidate / "run.py").exists():
            return candidate

    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "run.py").exists() and (parent / "pipeline").is_dir():
            return parent

    default_path = Path("/home/hakan/Git/elektor")
    if (default_path / "run.py").exists():
        return default_path
    return Path.cwd()


REPO_ROOT = resolve_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def resolve_api_url(explicit_url: Optional[str] = None) -> str:
    """Resolve FastAPI server URL from explicit arg, env var, ~/.hermes/config.yaml, or default."""
    if explicit_url:
        return explicit_url.rstrip("/")
    env_url = os.environ.get("ELEKTOR_API_URL")
    if env_url:
        return env_url.rstrip("/")
    hermes_cfg = _read_hermes_config_elektor()
    if "api_url" in hermes_cfg:
        return hermes_cfg["api_url"].rstrip("/")
    return "http://127.0.0.1:3456"


def load_config(repo_root: Path = REPO_ROOT) -> Dict[str, Any]:
    """Load flat config.json from the repository root without mutating it."""
    cfg_path = repo_root / "config.json"
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"_error": f"Failed to parse {cfg_path}: {exc}"}
    return {}


def load_projects_index(repo_root: Path = REPO_ROOT) -> Dict[str, Any]:
    """Load projects_index.json if present."""
    idx_path = repo_root / "projects_index.json"
    if idx_path.exists():
        try:
            return json.loads(idx_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def resolve_active_project_id(cfg: Dict[str, Any], repo_root: Path = REPO_ROOT) -> str:
    """Determine active project_id matching run.py and api_server.py."""
    if cfg.get("project_id"):
        return str(cfg["project_id"])
    idx = load_projects_index(repo_root)
    if idx.get("active_project_id"):
        return str(idx["active_project_id"])
    db_raw = cfg.get("db_path") or cfg.get("paths", {}).get("sqlite_db")
    if db_raw:
        return Path(db_raw).stem
    return "rp01"


def resolve_sqlite_path(cfg: Dict[str, Any], repo_root: Path = REPO_ROOT) -> Path:
    """Resolve SQLite database path matching run.py (`db_path` flat key)."""
    db_rel = cfg.get("db_path") or cfg.get("paths", {}).get("sqlite_db") or "database/rp01.db"
    p = Path(db_rel)
    if not p.is_absolute() and len(p.parts) == 1:
        p = Path("database") / p
    return p if p.is_absolute() else (repo_root / p)


def resolve_qdrant_path(cfg: Dict[str, Any], repo_root: Path = REPO_ROOT) -> Path:
    """Resolve local Qdrant directory path matching run.py (`qdrant_db_path` flat key)."""
    proj_id = resolve_active_project_id(cfg, repo_root)
    q_rel = cfg.get("qdrant_db_path") or cfg.get("paths", {}).get("qdrant_path") or f"qdrant_{proj_id}"
    p = Path(q_rel)
    return p if p.is_absolute() else (repo_root / p)


def resolve_qdrant_collection(cfg: Dict[str, Any], repo_root: Path = REPO_ROOT) -> str:
    """Resolve Qdrant collection name matching ArchiveVectorStore (`qdrant_collection_name` flat key)."""
    proj_id = resolve_active_project_id(cfg, repo_root)
    return str(
        cfg.get("qdrant_collection_name")
        or cfg.get("rag", {}).get("collection_name")
        or f"{proj_id}_articles"
    )


def resolve_exports_dir(cfg: Dict[str, Any], repo_root: Path = REPO_ROOT) -> Path:
    """Resolve project-isolated exports directory matching DatasetBuilder & VisualDatasetBuilder (`exports/<db_stem>`)."""
    if cfg.get("paths", {}).get("exports_dir"):
        p = Path(cfg["paths"]["exports_dir"])
        return p if p.is_absolute() else (repo_root / p)
    db_stem = resolve_sqlite_path(cfg, repo_root).stem
    return repo_root / "exports" / db_stem


def resolve_python_bin(repo_root: Path = REPO_ROOT) -> str:
    """Prefer the repository virtualenv Python interpreter when available."""
    venv_py = repo_root / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def http_json(
    url: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = 5.0,
) -> Tuple[int, Any]:
    """Perform a lightweight HTTP JSON request using stdlib urllib."""
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, {"raw": raw}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, {"error": raw}
    except Exception as exc:
        return 0, {"error": str(exc)}


def _read_png_dimensions(path: Path) -> Optional[Tuple[int, int]]:
    """Read PNG (width, height) from IHDR header using stdlib struct."""
    try:
        with path.open("rb") as f:
            header = f.read(24)
        if len(header) >= 24 and header[:8] == b"\x89PNG\r\n\x1a\n" and header[12:16] == b"IHDR":
            width, height = struct.unpack(">II", header[16:24])
            return int(width), int(height)
    except Exception:
        pass
    return None


def cmd_health(args: argparse.Namespace) -> int:
    """Check health of Elektor API server, Ollama endpoints, SQLite DB, and Qdrant storage."""
    cfg = load_config()
    api_url = resolve_api_url(args.api_url)

    status_code, api_health = http_json(f"{api_url}/api/health", timeout=3.0)
    active_project = resolve_active_project_id(cfg)
    sqlite_path = resolve_sqlite_path(cfg)
    qdrant_path = resolve_qdrant_path(cfg)
    qdrant_collection = resolve_qdrant_collection(cfg)
    exports_dir = resolve_exports_dir(cfg)

    sqlite_info: Dict[str, Any] = {
        "path": str(sqlite_path),
        "exists": sqlite_path.exists(),
        "size_bytes": sqlite_path.stat().st_size if sqlite_path.exists() else 0,
        "articles": 0,
        "enrichments": 0,
    }
    if sqlite_path.exists():
        try:
            conn = sqlite3.connect(str(sqlite_path))
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r[0] for r in cur.fetchall()}
            if "articles" in tables:
                cur.execute("SELECT COUNT(*) FROM articles")
                sqlite_info["articles"] = cur.fetchone()[0]
            if "enrichments" in tables:
                cur.execute("SELECT COUNT(*) FROM enrichments")
                sqlite_info["enrichments"] = cur.fetchone()[0]
            sqlite_info["tables"] = sorted(tables)
            conn.close()
        except Exception as exc:
            sqlite_info["error"] = str(exc)

    ollama_cfg_url = str(
        cfg.get("ollama_url")
        or cfg.get("llm", {}).get("ollama_base_url")
        or "http://127.0.0.1:11434"
    ).rstrip("/")
    local_fallback_url = "http://127.0.0.1:11434"

    ollama_endpoints: Dict[str, Any] = {}
    for label, endpoint in [("configured", ollama_cfg_url), ("local_fallback", local_fallback_url)]:
        code, body = http_json(f"{endpoint}/api/tags", timeout=2.0)
        models = [m.get("name") for m in body.get("models", [])] if isinstance(body, dict) else []
        ollama_endpoints[label] = {
            "url": endpoint,
            "online": code == 200,
            "model_count": len(models),
            "models": models[:15],
        }

    report = {
        "status": "ok" if (status_code == 200 or sqlite_info["exists"]) else "degraded",
        "repo_root": str(REPO_ROOT),
        "active_project": active_project,
        "dataset_name": cfg.get("dataset_name", active_project),
        "exports_dir": str(exports_dir),
        "models": {
            "analyzer": cfg.get("model_analyzer", "ornith-1.5:9b"),
            "translator": cfg.get("model_translator", "ornith-1.5:9b"),
            "vision": cfg.get("model_vision", "deepseek-ocr:3b-bf16"),
            "embedding": cfg.get("model_embedding", "nomic-embed-text:latest"),
            "judge": cfg.get("judge_model", "gemini-2.5-flash"),
        },
        "api_server": {
            "url": api_url,
            "online": status_code == 200,
            "http_status": status_code,
            "response": api_health if status_code == 200 else None,
        },
        "sqlite": sqlite_info,
        "qdrant": {
            "path": str(qdrant_path),
            "exists": qdrant_path.exists(),
            "collection": qdrant_collection,
        },
        "ollama": ollama_endpoints,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def cmd_projects(args: argparse.Namespace) -> int:
    """List, inspect, select, or create Elektor projects matching api_server.py contracts."""
    api_url = resolve_api_url(args.api_url)
    cfg = load_config()

    if args.action == "list":
        code, body = http_json(f"{api_url}/api/projects", timeout=3.0)
        if code == 200 and isinstance(body, dict):
            print(json.dumps(body, indent=2, ensure_ascii=False))
            return 0

        idx = load_projects_index()
        db_dir = REPO_ROOT / "database"
        dbs = sorted(p.stem for p in db_dir.glob("*.db")) if db_dir.exists() else []
        fallback = {
            "active_project_id": resolve_active_project_id(cfg),
            "projects": list(idx.get("projects", {}).values()),
            "discovered_databases": dbs,
            "db_path": cfg.get("db_path"),
            "qdrant_db_path": cfg.get("qdrant_db_path"),
            "source": "filesystem_fallback",
        }
        print(json.dumps(fallback, indent=2, ensure_ascii=False))
        return 0

    if args.action == "status":
        code, body = http_json(f"{api_url}/api/status", timeout=3.0)
        if code == 200:
            print(json.dumps(body, indent=2, ensure_ascii=False))
            return 0
        print(
            json.dumps(
                {
                    "active_project_id": resolve_active_project_id(cfg),
                    "config": cfg,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    if args.action == "select":
        project_id = (args.project_id or args.name or "").strip()
        if not project_id:
            print(json.dumps({"error": "--project-id (or --name) is required for projects select"}, ensure_ascii=False))
            return 1
        code, body = http_json(
            f"{api_url}/api/projects/select",
            method="POST",
            payload={"project_id": project_id},
            timeout=5.0,
        )
        print(json.dumps({"http_status": code, "result": body}, indent=2, ensure_ascii=False))
        return 0 if code in (200, 201) else 1

    if args.action == "create":
        raw_id = (args.project_id or args.name or "").strip()
        if not raw_id:
            print(json.dumps({"error": "--project-id (or --name) is required for projects create"}, ensure_ascii=False))
            return 1
        project_id = raw_id.lower().replace(" ", "_")
        project_name = (args.project_name or args.name or raw_id).strip()
        payload = {
            "project_id": project_id,
            "project_name": project_name,
            "input_mode": args.input_mode or "folder",
            "input_path": args.pdf_source or "",
        }
        code, body = http_json(
            f"{api_url}/api/projects/create",
            method="POST",
            payload=payload,
            timeout=5.0,
        )
        print(json.dumps({"http_status": code, "result": body}, indent=2, ensure_ascii=False))
        return 0 if code in (200, 201) else 1

    return 0


def cmd_rag_search(args: argparse.Namespace) -> int:
    """Query Qdrant vector memory via pipeline.mcp_tools."""
    from pipeline.mcp_tools import search_vector_rag

    res = search_vector_rag(query=args.query, top_k=args.limit)
    print(json.dumps(res, indent=2, ensure_ascii=False) if not isinstance(res, str) else res)
    return 0


def cmd_sqlite_search(args: argparse.Namespace) -> int:
    """Query SQLite articles and SFT/DPO enrichments via pipeline.mcp_tools."""
    from pipeline.mcp_tools import query_sqlite_knowledge

    res = query_sqlite_knowledge(query=args.keyword, limit=args.limit)
    if isinstance(res, dict) and args.table in ("articles", "enrichments"):
        filtered = {
            "status": res.get("status"),
            "tool": res.get("tool"),
            "keyword": args.keyword,
            "table": args.table,
            "results": res.get(args.table, []),
        }
        print(json.dumps(filtered, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(res, indent=2, ensure_ascii=False) if not isinstance(res, str) else res)
    return 0


def cmd_dataset_context(args: argparse.Namespace) -> int:
    """Retrieve SFT/DPO dataset context or evaluate knowledge gap for a topic."""
    from pipeline.mcp_tools import evaluate_knowledge_gap, inject_sft_dpo_context

    ctx_res = inject_sft_dpo_context(query=args.topic, limit=args.max_samples)
    if args.evaluate_gap:
        enriched_text = json.dumps(ctx_res.get("samples", []), ensure_ascii=False) if isinstance(ctx_res, dict) else str(ctx_res)
        out = evaluate_knowledge_gap(
            base_response=args.test_question or args.topic,
            enriched_response=enriched_text or args.topic,
            context_text=enriched_text,
        )
    else:
        out = ctx_res

    print(json.dumps(out, indent=2, ensure_ascii=False) if not isinstance(out, str) else out)
    return 0


def cmd_inspect_crops(args: argparse.Namespace) -> int:
    """Inspect extracted visual figure crops and project-specific multimodal_catalog.md."""
    cfg = load_config()
    exports_dir = resolve_exports_dir(cfg)
    images_dir = REPO_ROOT / "downloads" / "extracted_images"
    if args.images_dir:
        images_dir = Path(args.images_dir).expanduser().resolve()

    catalog_path = exports_dir / "multimodal_catalog.md"
    visual_jsonl_path = exports_dir / "multimodal_visual_dataset.jsonl"
    webp_dir = exports_dir / "images"

    png_files = sorted(images_dir.glob("*.png")) if images_dir.exists() else []
    webp_files = sorted(webp_dir.glob("*.webp")) if webp_dir.exists() else []

    samples = []
    for p in png_files[: args.limit]:
        stat = p.stat()
        dims = _read_png_dimensions(p)
        entry: Dict[str, Any] = {
            "filename": p.name,
            "path": str(p),
            "size_bytes": stat.st_size,
        }
        if dims:
            entry["width"] = dims[0]
            entry["height"] = dims[1]
        samples.append(entry)

    result: Dict[str, Any] = {
        "active_project": resolve_active_project_id(cfg),
        "images_dir": str(images_dir),
        "total_crops": len(png_files),
        "optimized_webp_dir": str(webp_dir),
        "total_webp_images": len(webp_files),
        "catalog_path": str(catalog_path),
        "catalog_exists": catalog_path.exists(),
        "catalog_size_bytes": catalog_path.stat().st_size if catalog_path.exists() else 0,
        "visual_dataset_path": str(visual_jsonl_path),
        "visual_dataset_exists": visual_jsonl_path.exists(),
        "samples": samples,
    }
    if args.as_document:
        result["hermes_gateway_directive"] = "[[as_document]]"

    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.as_document:
        print("\n[[as_document]]")
    return 0


def cmd_run_stage(args: argparse.Namespace) -> int:
    """Invoke a run.py pipeline stage using the exact CLI flags accepted by run.py."""
    py_bin = resolve_python_bin()
    run_py = REPO_ROOT / "run.py"
    cmd: List[str] = [py_bin, str(run_py)]
    if args.config:
        cmd.extend(["--config", str(args.config)])
    cmd.append(args.stage)

    # Stages supporting --limit in run.py: extract, enrich, embed, pipeline, judge, langextract, kiwix, trigger
    if args.stage in ("extract", "enrich", "embed", "pipeline", "judge", "langextract", "kiwix", "trigger"):
        if args.limit is not None:
            cmd.extend(["--limit", str(args.limit)])

    # Stages supporting --reset in run.py
    if args.stage in ("extract", "enrich", "embed", "export", "pipeline", "langextract", "kiwix") and args.reset:
        cmd.append("--reset")

    # Sharding flags in run.py: enrich, export_visual, pipeline
    if args.stage in ("enrich", "export_visual", "pipeline"):
        if args.shards is not None:
            cmd.extend(["--shards", str(args.shards)])
        if args.shard_ports:
            cmd.extend(["--shard-ports", str(args.shard_ports)])

    if args.stage in ("enrich", "pipeline") and args.enrich_pass:
        cmd.extend(["--pass", str(args.enrich_pass)])

    if args.stage == "export_visual" and args.clear:
        cmd.append("--clear")

    if args.stage == "clean_boilerplate" and args.db:
        cmd.extend(["--db", str(args.db)])

    if args.stage == "query":
        if not args.search:
            print(json.dumps({"error": "--search is required for stage 'query'"}, ensure_ascii=False))
            return 1
        cmd.append(str(args.search))
        if args.top_k is not None:
            cmd.extend(["--top_k", str(args.top_k)])

    if args.stage in ("judge", "trigger"):
        if args.mode:
            cmd.extend(["--mode", str(args.mode)])
        if args.threshold is not None:
            cmd.extend(["--threshold", str(args.threshold)])
        if args.batch:
            cmd.append("--batch")
    if args.stage == "judge" and args.sync_batch:
        cmd.append("--sync-batch")
    if args.stage == "trigger":
        if args.daemon:
            cmd.append("--daemon")
        if args.interval is not None:
            cmd.extend(["--interval", str(args.interval)])

    if args.stage == "langextract":
        if args.provider:
            cmd.extend(["--provider", str(args.provider)])
        if args.preset:
            cmd.extend(["--preset", str(args.preset)])
        if args.visualize:
            cmd.append("--visualize")

    if args.stage == "kiwix":
        if args.zim:
            cmd.extend(["--zim", str(args.zim)])
        if args.url:
            cmd.extend(["--url", str(args.url)])
        if args.mode:
            cmd.extend(["--mode", str(args.mode)])
        if args.batch_size is not None:
            cmd.extend(["--batch-size", str(args.batch_size)])

    if args.stage == "hooks" and args.check:
        cmd.append("--check")

    if args.stage == "colab":
        if args.project:
            cmd.extend(["--project", str(args.project)])
        if args.model:
            cmd.extend(["--model", str(args.model)])
        if args.colab_type:
            cmd.extend(["--type", str(args.colab_type)])
        if args.hf_dataset:
            cmd.extend(["--hf-dataset", str(args.hf_dataset)])

    if args.stage == "hf_upload":
        if not args.repo_id:
            print(json.dumps({"error": "--repo-id is required for stage 'hf_upload'"}, ensure_ascii=False))
            return 1
        cmd.extend(["--repo_id", str(args.repo_id)])
        if args.project:
            cmd.extend(["--project_id", str(args.project)])
        if args.private:
            cmd.append("--private")

    if args.extra_args:
        cmd.extend(args.extra_args)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "cwd": str(REPO_ROOT),
                    "command": cmd,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, capture_output=True)
    output = {
        "stage": args.stage,
        "returncode": proc.returncode,
        "command": cmd,
        "stdout": proc.stdout[-4000:] if proc.stdout else "",
        "stderr": proc.stderr[-4000:] if proc.stderr else "",
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return proc.returncode


REQUIRED_SECTIONS = [
    "## When to Use",
    "## Prerequisites",
    "## How to Run",
    "## Quick Reference",
    "## Procedure",
    "## Pitfalls",
    "## Verification",
]

BANNED_MARKETING_WORDS = {"comprehensive", "powerful", "seamless", "robust", "cutting-edge", "world-class"}


def validate_skill_file(skill_md_path: Path) -> Dict[str, Any]:
    """Validate a single SKILL.md against Nous Research Hermes Agent standards."""
    errors: List[str] = []
    warnings: List[str] = []

    raw_bytes = skill_md_path.read_bytes()
    if not raw_bytes.startswith(b"---\n"):
        errors.append("File must start at byte 0 with '---\\n'.")

    text = raw_bytes.decode("utf-8", errors="replace")
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        errors.append("Missing closing '\\n---\\n' frontmatter delimiter.")
        return {"path": str(skill_md_path), "valid": False, "errors": errors, "warnings": warnings}

    frontmatter_raw = parts[0][4:]  # strip leading ---\n
    body = parts[1]

    name_match = re.search(r"^name:\s*(.+)$", frontmatter_raw, re.MULTILINE)
    desc_match = re.search(r"^description:\s*(.+)$", frontmatter_raw, re.MULTILINE)
    version_match = re.search(r"^version:\s*(.+)$", frontmatter_raw, re.MULTILINE)
    platforms_match = re.search(r"^platforms:\s*\[(.+)\]", frontmatter_raw, re.MULTILINE)
    hermes_meta_match = re.search(r"^\s+hermes:\s*$", frontmatter_raw, re.MULTILINE)

    skill_name = name_match.group(1).strip().strip("\"'") if name_match else ""
    desc = desc_match.group(1).strip().strip("\"'") if desc_match else ""

    if not skill_name:
        errors.append("Missing 'name' in frontmatter.")
    else:
        if skill_name != skill_md_path.parent.name:
            errors.append(f"Skill name '{skill_name}' does not match directory '{skill_md_path.parent.name}'.")
        if len(skill_name) > 64 or not re.match(r"^[a-z0-9-]+$", skill_name):
            errors.append(f"Skill name '{skill_name}' must be lowercase alphanumeric + hyphens, <= 64 chars.")

    if not desc:
        errors.append("Missing 'description' in frontmatter.")
    else:
        if len(desc) > 60:
            errors.append(f"Description length ({len(desc)}) exceeds 60-character limit: '{desc}'")
        if not desc.endswith("."):
            errors.append(f"Description must end with a period: '{desc}'")
        lower_words = set(re.findall(r"[a-z]+", desc.lower()))
        banned_hit = lower_words.intersection(BANNED_MARKETING_WORDS)
        if banned_hit:
            errors.append(f"Description contains banned filler words: {sorted(banned_hit)}")

    if not version_match:
        errors.append("Missing 'version' in frontmatter.")
    if not platforms_match:
        errors.append("Missing 'platforms' list in frontmatter.")
    if not hermes_meta_match:
        errors.append("Missing 'metadata.hermes' block in frontmatter.")

    for section in REQUIRED_SECTIONS:
        if section not in body:
            errors.append(f"Missing required section heading: '{section}'")

    skill_dir = skill_md_path.parent
    ref_mentions = re.findall(r"references/[a-zA-Z0-9_.-]+\.(?:md|json|yaml|txt)", body)
    for ref_rel in set(ref_mentions):
        if not (skill_dir / ref_rel).exists():
            errors.append(f"Referenced file '{ref_rel}' does not exist in {skill_dir}")

    tmpl_mentions = re.findall(r"templates/[a-zA-Z0-9_.-]+\.(?:md|json|yaml|txt)", body)
    for tmpl_rel in set(tmpl_mentions):
        if not (skill_dir / tmpl_rel).exists():
            errors.append(f"Referenced template '{tmpl_rel}' does not exist in {skill_dir}")

    line_count = len(text.splitlines())
    if line_count > 500:
        warnings.append(f"SKILL.md is {line_count} lines (recommended <= 500 lines for progressive disclosure).")

    return {
        "skill": skill_name or skill_md_path.parent.name,
        "path": str(skill_md_path),
        "description": desc,
        "description_length": len(desc),
        "line_count": line_count,
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def cmd_validate_skills(args: argparse.Namespace) -> int:
    """Validate all SKILL.md files under hermes-agent/skills/."""
    skills_root = Path(args.skills_dir).expanduser().resolve() if args.skills_dir else (REPO_ROOT / "hermes-agent" / "skills")
    skill_files = sorted(skills_root.rglob("SKILL.md"))

    if not skill_files:
        print(json.dumps({"valid": False, "error": f"No SKILL.md files found under {skills_root}"}, indent=2))
        return 1

    results = [validate_skill_file(p) for p in skill_files]
    all_valid = all(r["valid"] for r in results)

    summary = {
        "skills_root": str(skills_root),
        "total_skills": len(results),
        "all_valid": all_valid,
        "results": results,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if all_valid else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="elektor_hermes_cli",
        description="Unified Elektor Dataset Pipeline CLI & Tool Bridge for Hermes Agents",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_health = sub.add_parser("health", help="Check API server, Ollama, SQLite, and Qdrant health")
    p_health.add_argument("--api-url", default=None, help="Override Elektor FastAPI URL")
    p_health.set_defaults(func=cmd_health)

    p_proj = sub.add_parser("projects", help="Manage or inspect Elektor projects")
    p_proj.add_argument("action", choices=["list", "status", "select", "create"], default="list", nargs="?")
    p_proj.add_argument("--project-id", default=None, help="Project ID (e.g. rp01) for select/create")
    p_proj.add_argument("--project-name", default=None, help="Human-readable project name for create")
    p_proj.add_argument("--name", default=None, help="Alias for --project-id / --project-name")
    p_proj.add_argument("--input-mode", choices=["folder", "book", "rendergit", "kiwix"], default="folder")
    p_proj.add_argument("--pdf-source", default=None, help="Input directory or file path for create")
    p_proj.add_argument("--api-url", default=None, help="Override Elektor FastAPI URL")
    p_proj.set_defaults(func=cmd_projects)

    p_rag = sub.add_parser("rag-search", help="Semantic search in Qdrant vector memory")
    p_rag.add_argument("--query", "-q", required=True, help="Technical search query")
    p_rag.add_argument("--limit", "-k", type=int, default=5, help="Max chunks to retrieve")
    p_rag.add_argument("--json", action="store_true", help="Emit JSON output")
    p_rag.set_defaults(func=cmd_rag_search)

    p_sql = sub.add_parser("sqlite-search", help="Keyword search in SQLite articles or enrichments")
    p_sql.add_argument("--keyword", "-k", required=True, help="Keyword to search")
    p_sql.add_argument("--table", choices=["articles", "enrichments"], default="articles")
    p_sql.add_argument("--limit", type=int, default=5)
    p_sql.add_argument("--json", action="store_true", help="Emit JSON output")
    p_sql.set_defaults(func=cmd_sqlite_search)

    p_ctx = sub.add_parser("dataset-context", help="Fetch SFT/DPO examples or evaluate knowledge gap")
    p_ctx.add_argument("--topic", "-t", required=True, help="Technical topic")
    p_ctx.add_argument("--format-type", choices=["sft", "dpo"], default="sft")
    p_ctx.add_argument("--max-samples", type=int, default=3)
    p_ctx.add_argument("--evaluate-gap", action="store_true", help="Compare pre/post dataset density")
    p_ctx.add_argument("--test-question", default="", help="Optional test question for gap evaluation")
    p_ctx.add_argument("--json", action="store_true", help="Emit JSON output")
    p_ctx.set_defaults(func=cmd_dataset_context)

    p_crops = sub.add_parser("inspect-crops", help="Inspect visual crops and multimodal_catalog.md")
    p_crops.add_argument("--images-dir", default=None, help="Override extracted images directory")
    p_crops.add_argument("--limit", type=int, default=10, help="Max sample files to list")
    p_crops.add_argument("--as-document", action="store_true", help="Append [[as_document]] for Hermes gateway")
    p_crops.set_defaults(func=cmd_inspect_crops)

    p_stage = sub.add_parser("run-stage", help="Execute an Elektor run.py pipeline stage")
    p_stage.add_argument(
        "stage",
        choices=[
            "extract",
            "enrich",
            "embed",
            "query",
            "export",
            "export_visual",
            "clean_boilerplate",
            "hf_upload",
            "judge",
            "langextract",
            "kiwix",
            "pipeline",
            "self_test",
            "trigger",
            "hooks",
            "colab",
        ],
    )
    p_stage.add_argument("--config", default=None, help="Custom config JSON path for run.py")
    p_stage.add_argument("--limit", default=None, help="Sample limit or slice 'start:end'")
    p_stage.add_argument("--reset", action="store_true", help="Reset databases/exports before running")
    p_stage.add_argument("--shards", "--workers", dest="shards", type=int, default=None, help="Number of parallel GPU shards (--workers alias supported)")
    p_stage.add_argument("--shard-ports", default=None, help="Comma-separated Ollama ports (e.g. 11434,11435)")
    p_stage.add_argument("--pass", dest="enrich_pass", choices=["all", "english", "turkish"], default=None)
    p_stage.add_argument("--clear", action="store_true", help="Delete raw PNG crops after WebP optimization (export_visual)")
    p_stage.add_argument("--db", default=None, help="Database path override for clean_boilerplate")
    p_stage.add_argument("--search", default=None, help="Query string for 'query' stage")
    p_stage.add_argument("--top-k", "--top_k", dest="top_k", type=int, default=3, help="Top-K results for 'query' stage")
    p_stage.add_argument("--mode", default=None, help="Mode for judge/trigger (strict|hybrid_editor) or kiwix (auto|stackexchange|wiki)")
    p_stage.add_argument("--threshold", type=float, default=None, help="Score threshold (1.0-10.0) for judge/trigger")
    p_stage.add_argument("--batch", action="store_true", help="Use Gemini Batch API for judge/trigger")
    p_stage.add_argument("--sync-batch", action="store_true", help="Sync Gemini Batch jobs for judge")
    p_stage.add_argument("--daemon", action="store_true", help="Run trigger in continuous daemon mode")
    p_stage.add_argument("--interval", type=int, default=None, help="Daemon interval in seconds for trigger")
    p_stage.add_argument("--provider", choices=["ollama", "openai", "gemini"], default=None, help="Provider for langextract")
    p_stage.add_argument("--preset", default=None, help="Schema preset for langextract")
    p_stage.add_argument("--visualize", action="store_true", help="Generate HTML visualizer for langextract")
    p_stage.add_argument("--zim", default=None, help="Local .zim path for kiwix")
    p_stage.add_argument("--url", default=None, help="Download URL for kiwix")
    p_stage.add_argument("--batch-size", type=int, default=None, help="SQLite batch size for kiwix")
    p_stage.add_argument("--check", action="store_true", help="Run self-check for hooks stage")
    p_stage.add_argument("--project", default=None, help="Target project ID for colab or hf_upload")
    p_stage.add_argument("--model", default=None, help="Base model for colab (e.g. unsloth/Qwen3.5-2B)")
    p_stage.add_argument("--type", dest="colab_type", choices=["all", "sft", "dpo", "chat", "langextract"], default=None)
    p_stage.add_argument("--hf-dataset", default=None, help="HF dataset repo ID for colab")
    p_stage.add_argument("--repo-id", default=None, help="Target HF repo ID for hf_upload")
    p_stage.add_argument("--private", action="store_true", help="Private HF repo flag for hf_upload")
    p_stage.add_argument("--dry-run", action="store_true", help="Print resolved command without executing")
    p_stage.add_argument("extra_args", nargs="*", help="Additional arguments passed to run.py")
    p_stage.set_defaults(func=cmd_run_stage)

    p_val = sub.add_parser("validate-skills", help="Validate SKILL.md files against Hermes Agent spec")
    p_val.add_argument("--skills-dir", default=None, help="Directory containing SKILL.md files")
    p_val.set_defaults(func=cmd_validate_skills)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
