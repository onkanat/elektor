#!/usr/bin/env python3
"""Skill-local wrapper for elektor_hermes_cli.py supporting ${HERMES_SKILL_DIR}/scripts/elektor_hermes_cli.py."""

import os
import re
import runpy
import sys
from pathlib import Path


def _read_hermes_repo_path() -> str:
    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()
    cfg_yaml = hermes_home / "config.yaml"
    if not cfg_yaml.is_file():
        return ""
    try:
        text = cfg_yaml.read_text(encoding="utf-8", errors="replace")
        try:
            import yaml  # type: ignore

            loaded = yaml.safe_load(text)
            if isinstance(loaded, dict):
                elektor_node = (
                    loaded.get("skills", {}).get("config", {}).get("elektor")
                    if isinstance(loaded.get("skills"), dict)
                    and isinstance(loaded.get("skills", {}).get("config"), dict)
                    else None
                ) or (loaded.get("elektor") if isinstance(loaded.get("elektor"), dict) else None)
                if isinstance(elektor_node, dict) and elektor_node.get("repo_path"):
                    return str(elektor_node["repo_path"]).strip()
        except Exception:
            pass

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
                return m_repo.group(1).strip()
    except Exception:
        pass
    return ""


def _find_master_cli() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / "hermes-agent" / "scripts" / "elektor_hermes_cli.py"
        if candidate.exists() and candidate != here:
            return candidate
        candidate2 = parent / "scripts" / "elektor_hermes_cli.py"
        if candidate2.exists() and candidate2 != here:
            return candidate2
    env_repo = os.environ.get("ELEKTOR_REPO_PATH") or _read_hermes_repo_path() or "/home/hakan/Git/elektor"
    return Path(env_repo).expanduser().resolve() / "hermes-agent" / "scripts" / "elektor_hermes_cli.py"


if __name__ == "__main__":
    master = _find_master_cli()
    sys.path.insert(0, str(master.parent))
    runpy.run_path(str(master), run_name="__main__")
