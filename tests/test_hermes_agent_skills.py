"""Automated contract & integration tests for Nous Research Hermes Agent skills, CLI bridge, and MCP server in hermes-agent/."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HERMES_DIR = REPO_ROOT / "hermes-agent"
CLI_SCRIPT = HERMES_DIR / "scripts" / "elektor_hermes_cli.py"
MCP_SCRIPT = HERMES_DIR / "scripts" / "elektor_mcp_server.py"
INSTALL_SCRIPT = HERMES_DIR / "scripts" / "install_skills.sh"
INDEX_JSON = HERMES_DIR / ".well-known" / "skills" / "index.json"

EXPECTED_SKILLS = {
    "elektor-dataset-pipeline",
    "elektor-ocr-layout",
    "elektor-rag-memory",
    "elektor-dataset-curation",
}

STALE_TOKENS = [
    "sft_alpaca.jsonl",
    "dpo_pairs.jsonl",
    "multimodal_sft.jsonl",
    "Elektor_Unsloth_Finetune.ipynb",
    "judge --max-samples",
    "trigger --max-samples",
    "--auto-clean",
    "pipeline/judge.py",
    "extraction.min_image_size",
    "elektor_docs",
]


def test_hermes_directory_structure_and_well_known_manifest():
    """Verify all required documentation, manifest (name/description/skill-relative files), category description, and scripts exist."""
    assert (HERMES_DIR / "README.md").is_file()
    assert (HERMES_DIR / "INSTALLATION.md").is_file()
    assert (HERMES_DIR / "ARCHITECTURE.md").is_file()
    assert (HERMES_DIR / "skills" / "data" / "DESCRIPTION.md").is_file()
    assert CLI_SCRIPT.is_file()
    assert MCP_SCRIPT.is_file()
    assert INSTALL_SCRIPT.is_file()
    assert INDEX_JSON.is_file()

    manifest = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
    manifest_names = {entry["name"] for entry in manifest.get("skills", [])}
    assert manifest_names == EXPECTED_SKILLS
    for entry in manifest["skills"]:
        skill_name = entry["name"]
        skill_dir = HERMES_DIR / "skills" / "data" / skill_name
        assert len(entry["description"]) <= 60
        assert entry["description"].endswith(".")
        assert isinstance(entry.get("files"), list) and len(entry["files"]) >= 2
        assert "SKILL.md" in entry["files"]
        for rel_file in entry["files"]:
            assert not rel_file.startswith("skills/"), f"Manifest file path must be skill-relative, got: {rel_file}"
            assert not rel_file.startswith("/"), f"Manifest file path must be relative, got: {rel_file}"
            assert (skill_dir / rel_file).is_file(), f"Missing skill-relative file: {skill_dir / rel_file}"


def test_no_stale_artifact_or_flag_names_in_hermes_agent_docs():
    """Ensure none of the deprecated artifact names or invalid CLI flags appear anywhere in hermes-agent/."""
    for md_or_yaml in HERMES_DIR.rglob("*"):
        if md_or_yaml.is_file() and md_or_yaml.suffix in {".md", ".yaml", ".json"}:
            text = md_or_yaml.read_text(encoding="utf-8")
            for stale in STALE_TOKENS:
                assert stale not in text, f"Found stale token '{stale}' in {md_or_yaml}"


def test_validate_skills_cli_passes_all_hermes_invariants():
    """Verify elektor_hermes_cli.py validate-skills enforces Hermes Agent SKILL.md frontmatter and section rules."""
    proc = subprocess.run(
        [sys.executable, str(CLI_SCRIPT), "validate-skills"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["all_valid"] is True
    assert payload["total_skills"] == 4
    found_skills = {item["skill"] for item in payload["results"]}
    assert found_skills == EXPECTED_SKILLS

    for item in payload["results"]:
        assert item["valid"] is True, f"Skill validation failed: {item['errors']}"
        assert item["description_length"] <= 60
        assert item["line_count"] <= 500


def test_health_and_inspect_crops_match_real_host_config_contract():
    """Verify health and inspect-crops resolve the exact SQLite, Qdrant, Ollama, and catalog paths from flat config.json."""
    cfg = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
    expected_db = (REPO_ROOT / cfg["db_path"]).resolve()
    expected_qdrant = (REPO_ROOT / cfg["qdrant_db_path"]).resolve()
    expected_collection = cfg["qdrant_collection_name"]
    expected_project = cfg["project_id"]
    expected_ollama_url = cfg["ollama_url"].rstrip("/")
    expected_catalog = (REPO_ROOT / "exports" / expected_db.stem / "multimodal_catalog.md").resolve()

    proc_health = subprocess.run(
        [sys.executable, str(CLI_SCRIPT), "health"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    health_data = json.loads(proc_health.stdout)

    assert health_data["active_project"] == expected_project
    assert Path(health_data["sqlite"]["path"]).resolve() == expected_db
    assert health_data["sqlite"]["exists"] == expected_db.exists()
    assert Path(health_data["qdrant"]["path"]).resolve() == expected_qdrant
    assert health_data["qdrant"]["exists"] == expected_qdrant.exists()
    assert health_data["qdrant"]["collection"] == expected_collection
    assert health_data["ollama"]["configured"]["url"] == expected_ollama_url
    assert health_data["ollama"]["local_fallback"]["url"] == "http://127.0.0.1:11434"
    assert health_data["models"]["vision"] == cfg.get("model_vision", "deepseek-ocr:3b-bf16")

    proc_crops = subprocess.run(
        [sys.executable, str(CLI_SCRIPT), "inspect-crops", "--limit", "3", "--as-document"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "[[as_document]]" in proc_crops.stdout
    json_part = proc_crops.stdout.split("\n[[as_document]]")[0]
    crops_data = json.loads(json_part)
    assert Path(crops_data["catalog_path"]).resolve() == expected_catalog
    assert crops_data["catalog_exists"] == expected_catalog.exists()
    assert crops_data["hermes_gateway_directive"] == "[[as_document]]"
    if crops_data["samples"]:
        sample = crops_data["samples"][0]
        assert "width" in sample and "height" in sample
        assert sample["width"] > 0 and sample["height"] > 0


def test_projects_select_and_create_send_exact_fastapi_payloads():
    """Verify projects select and create send project_id and project_name matching api_server.py."""
    captured: List[Dict[str, Any]] = []

    class MockHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            captured.append({"path": self.path, "body": body})
            if self.path == "/api/projects/select":
                if not body.get("project_id"):
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'{"detail":"project_id required"}')
                    return
            elif self.path == "/api/projects/create":
                if not body.get("project_id") or not body.get("project_name"):
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'{"detail":"project_id and project_name are required"}')
                    return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "received": body}).encode("utf-8"))

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), MockHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        api_url = f"http://127.0.0.1:{port}"
        proc_sel = subprocess.run(
            [sys.executable, str(CLI_SCRIPT), "projects", "select", "--project-id", "rp01", "--api-url", api_url],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        sel_out = json.loads(proc_sel.stdout)
        assert sel_out["http_status"] == 200
        assert captured[0] == {"path": "/api/projects/select", "body": {"project_id": "rp01"}}

        proc_create = subprocess.run(
            [
                sys.executable,
                str(CLI_SCRIPT),
                "projects",
                "create",
                "--project-id",
                "test_proj",
                "--project-name",
                "Test Project",
                "--pdf-source",
                "/tmp/pdfs",
                "--api-url",
                api_url,
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        create_out = json.loads(proc_create.stdout)
        assert create_out["http_status"] == 200
        assert captured[1]["path"] == "/api/projects/create"
        assert captured[1]["body"]["project_id"] == "test_proj"
        assert captured[1]["body"]["project_name"] == "Test Project"
    finally:
        server.shutdown()


def test_run_stage_commands_accepted_by_run_py_argparser():
    """Verify every stage command constructed by elektor_hermes_cli.py is accepted by run.py's actual ArgumentParser."""
    stage_invocations = [
        ["run-stage", "extract", "--limit", "5", "--reset", "--dry-run"],
        ["run-stage", "enrich", "--limit", "10", "--shards", "2", "--shard-ports", "11434,11435", "--pass", "turkish", "--dry-run"],
        ["run-stage", "enrich", "--limit", "10", "--workers", "2", "--dry-run"],
        ["run-stage", "embed", "--limit", "15", "--dry-run"],
        ["run-stage", "query", "--search", "RP2040 PIO", "--top-k", "4", "--dry-run"],
        ["run-stage", "export", "--reset", "--dry-run"],
        ["run-stage", "export_visual", "--shards", "2", "--shard-ports", "11434,11435", "--clear", "--dry-run"],
        ["run-stage", "clean_boilerplate", "--db", "database/rp01.db", "--dry-run"],
        ["run-stage", "judge", "--mode", "strict", "--threshold", "7.5", "--limit", "30", "--batch", "--dry-run"],
        ["run-stage", "trigger", "--mode", "hybrid_editor", "--threshold", "7.0", "--limit", "25", "--dry-run"],
        ["run-stage", "langextract", "--limit", "5", "--provider", "ollama", "--preset", "technical_components", "--visualize", "--dry-run"],
        ["run-stage", "kiwix", "--zim", "downloads/test.zim", "--mode", "stackexchange", "--batch-size", "250", "--limit", "50", "--dry-run"],
        ["run-stage", "colab", "--project", "rp01", "--model", "unsloth/Qwen3.5-2B", "--type", "dpo", "--dry-run"],
        ["run-stage", "hooks", "--check", "--dry-run"],
    ]

    for cli_args in stage_invocations:
        proc = subprocess.run(
            [sys.executable, str(CLI_SCRIPT), *cli_args],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(proc.stdout)
        cmd = data["command"]
        stage = cli_args[1]

        if "--limit" in cli_args:
            assert "--limit" in cmd, f"--limit was dropped for stage '{stage}': {cmd}"
        if "--workers" in cli_args:
            assert "--shards" in cmd, f"--workers alias did not map to --shards for '{stage}': {cmd}"

        # Verify run.py "<stage> ... --help" exits 0 with those exact generated flags!
        help_cmd = [*cmd, "--help"]
        help_proc = subprocess.run(
            help_cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert help_proc.returncode == 0, f"run.py rejected flags for {stage}: {help_proc.stderr}"


def test_mcp_server_jsonrpc_handshake_and_tools_list():
    """Verify elektor_mcp_server.py responds to JSON-RPC 2.0 initialize, ping, and tools/list."""
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
    ]
    stdin_payload = "\n".join(json.dumps(r) for r in requests) + "\n"
    proc = subprocess.run(
        [sys.executable, str(MCP_SCRIPT)],
        cwd=str(REPO_ROOT),
        input=stdin_payload,
        capture_output=True,
        text=True,
        check=True,
    )
    lines = [line for line in proc.stdout.strip().splitlines() if line.strip()]
    assert len(lines) == 3

    init_resp = json.loads(lines[0])
    assert init_resp["id"] == 1
    assert init_resp["result"]["serverInfo"]["name"] == "elektor-dataset-mcp"

    ping_resp = json.loads(lines[1])
    assert ping_resp["id"] == 2

    tools_resp = json.loads(lines[2])
    tool_names = {t["name"] for t in tools_resp["result"]["tools"]}
    assert tool_names == {
        "search_vector_rag",
        "query_sqlite_knowledge",
        "inject_sft_dpo_context",
        "evaluate_knowledge_gap",
    }


def test_install_skills_script_link_copy_and_config_yaml_resolution(tmp_path: Path):
    """Verify install_skills.sh --link, --copy (standalone CLI), and scoped ~/.hermes/config.yaml resolution."""
    cfg_yaml = tmp_path / "config.yaml"
    # Intentionally include unrelated gateway.api_url and other.repo_path BEFORE skills.config.elektor
    cfg_yaml.write_text(
        "gateway:\n"
        '  api_url: "http://127.0.0.1:8642"\n'
        '  repo_path: "/tmp/unrelated_gateway_repo"\n'
        "skills:\n"
        "  config:\n"
        "    other_skill:\n"
        '      api_url: "http://127.0.0.1:9999"\n'
        "    elektor:\n"
        f'      repo_path: "{REPO_ROOT}"\n'
        '      api_url: "http://127.0.0.1:3456"\n',
        encoding="utf-8",
    )
    env = {"HERMES_HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}

    # 1. Test --copy installs standalone elektor_hermes_cli.py that runs outside the repo tree
    subprocess.run(
        ["bash", str(INSTALL_SCRIPT), "--copy"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    for skill_name in EXPECTED_SKILLS:
        copied_dir = tmp_path / "skills" / "data" / skill_name
        assert copied_dir.is_dir() and not copied_dir.is_symlink()
        copied_cli = copied_dir / "scripts" / "elektor_hermes_cli.py"
        assert copied_cli.is_file()
        proc = subprocess.run(
            [sys.executable, str(copied_cli), "health"],
            cwd=str(tmp_path),
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        health = json.loads(proc.stdout)
        assert Path(health["repo_root"]).resolve() == REPO_ROOT.resolve()
        assert health["api_server"]["url"] == "http://127.0.0.1:3456"
        assert health["active_project"] == "rp01"

    # 2. Verify re-running --copy without --force fails safely instead of unconditionally wiping
    proc_no_force = subprocess.run(
        ["bash", str(INSTALL_SCRIPT), "--copy"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc_no_force.returncode != 0

    # 3. Test --link --force replaces with symlinks, then --uninstall cleans up
    subprocess.run(
        ["bash", str(INSTALL_SCRIPT), "--link", "--force"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    for skill_name in EXPECTED_SKILLS:
        linked = tmp_path / "skills" / "data" / skill_name
        assert linked.is_symlink()

    subprocess.run(
        ["bash", str(INSTALL_SCRIPT), "--uninstall"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    for skill_name in EXPECTED_SKILLS:
        assert not (tmp_path / "skills" / "data" / skill_name).exists()
