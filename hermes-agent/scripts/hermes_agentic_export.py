#!/usr/bin/env python3
"""Hermes state.db -> AJAN IZI (agentic) korpusu: arac cagrisi + sonuc zincirleri.

Neden ayri dosya: `hermes_sessions_to_dataset.py` turun NIHAI YANITINI cikarir
(raporlama davranisi). Arac SECMEYI ogretmek icin cagri zinciri gerekir:
asistan -> tool_calls, tool -> sonuc, ... -> nihai metin.

Arac semalari state.db'de YOK. Semalar gozlenen cagrilardan deterministik
turetilir (ad + gorulen arguman anahtarlari + tip) ve `meta.schema_source =
"observed"` diye isaretlenir; uydurma sema yok.

Cikti: <out>/agentic_dataset.jsonl  (satir basina bir yorunge)
    {"messages":[...], "tools":[...], "meta":{...}}

    .venv/bin/python hermes-agent/scripts/hermes_agentic_export.py --out exports/hermes_agentic
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REDACT = [
    (re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_\-]{16,}"), "[REDACTED:api_key]"),
    (re.compile(r"\b(?:ghp|gho|github_pat)_[A-Za-z0-9_]{20,}"), "[REDACTED:github]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED:aws]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED:key]"),
    (re.compile(r"(?i)\b(password|parola|şifre|sifre|secret|api[_\-]?key|access[_\-]?token)\b\s*[:=]\s*([^\s\"',;}]{6,})"), r"\1=[REDACTED:secret]"),
]

# Bilinen Hermes araclari icin kisa aciklama; bilinmeyenler "observed" kalir.
TOOL_DESC = {
    "terminal": "Yerel kabukta komut calistirir (stdout/stderr/exit_code doner).",
    "read_file": "Bir metin dosyasini satir araligiyla okur.",
    "write_file": "Bir dosyayi tamamen yazar (uzerine yazar).",
    "patch": "Bir dosyada hedefli metin degistirir (bul/degistir).",
    "search_files": "Dosya adi veya icerik arar (ripgrep).",
    "execute_code": "Python kodunu kalici cekirdekte calistirir; Hermes araclarini cagirabilir.",
    "skill_view": "Bir becerinin (skill) icerigini/dosyalarini okur.",
    "skill_manage": "Beceri olusturur/gunceller/siler.",
    "memory": "Kalici belleğe not ekler/gunceller.",
    "tool_describe": "Ertelenmis bir aracin semasini yukler.",
    "tool_call": "Ertelenmis bir araci cagirir.",
    "tool_search": "Ertelenmis arac katalogunda arama yapar.",
    "session_search": "Gecmis Hermes oturumlarinda arama yapar.",
    "web_search": "Web'de arama yapar.",
    "web_extract": "Bir web sayfasini/PDF'i metne cevirir.",
    "browser_exec": "Gerçek tarayiciyi surer.",
    "todo_list": "Cok adimli is icin yapilacak listesi tutar.",
    "delegate_task": "Alt ajana is verir.",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def redact(text: str) -> tuple[str, Counter]:
    hits: Counter = Counter()
    for pat, rep in REDACT:
        text, n = pat.subn(rep, text)
        if n:
            hits[pat.pattern[:18]] += n
    return text, hits


def tip_of(v) -> dict:
    if isinstance(v, bool):
        return {"type": "boolean"}
    if isinstance(v, int):
        return {"type": "integer"}
    if isinstance(v, float):
        return {"type": "number"}
    if isinstance(v, list):
        return {"type": "array"}
    if isinstance(v, dict):
        return {"type": "object"}
    return {"type": "string"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(Path.home() / ".hermes" / "state.db"))
    ap.add_argument("--out", default="exports/hermes_agentic")
    ap.add_argument("--min-tool-calls", type=int, default=1)
    ap.add_argument("--max-tool-result", type=int, default=1200)
    ap.add_argument("--max-args", type=int, default=2000)
    ap.add_argument("--min-session-messages", type=int, default=4)
    args = ap.parse_args()

    db = Path(args.db).expanduser()
    if not db.exists():
        print(f"HATA: {db} yok", file=sys.stderr)
        return 2
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    db_sha = hashlib.sha256(db.read_bytes()[: 8 << 20]).hexdigest()

    sessions = conn.execute(
        "SELECT id, title, model, started_at FROM sessions WHERE COALESCE(hidden,0)=0"
    ).fetchall()

    # 1. gecis: gozlenen arac semalarini topla
    arg_keys: dict[str, set[str]] = defaultdict(set)
    arg_types: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    tool_uses: Counter = Counter()
    for s in sessions:
        for m in conn.execute(
            "SELECT tool_calls FROM messages WHERE session_id=? AND tool_calls IS NOT NULL AND tool_calls!=''",
            (s["id"],),
        ):
            try:
                calls = json.loads(m["tool_calls"])
            except Exception:
                continue
            for c in calls if isinstance(calls, list) else [calls]:
                fn = (c.get("function") or {})
                name = fn.get("name")
                if not name:
                    continue
                tool_uses[name] += 1
                raw = fn.get("arguments")
                try:
                    a = json.loads(raw) if isinstance(raw, str) else (raw or {})
                except Exception:
                    continue
                if isinstance(a, dict):
                    for k, v in a.items():
                        arg_keys[name].add(k)
                        arg_types[name][k][tip_of(v)["type"]] += 1

    tools = []
    for name in sorted(tool_uses):
        props = {}
        for k in sorted(arg_keys.get(name, ())):
            t = arg_types[name][k].most_common(1)[0][0]
            props[k] = {"type": t}
        tools.append({"type": "function", "function": {
            "name": name,
            "description": TOOL_DESC.get(name, f"{name} (sema gozlemden turetildi)"),
            "parameters": {"type": "object", "properties": props, "required": []},
        }})

    # 2. gecis: yorungeler
    rows: list[dict] = []
    stats = Counter()
    redactions: Counter = Counter()
    skipped = Counter()

    for s in sessions:
        msgs = conn.execute(
            "SELECT id, role, content, tool_calls, tool_name FROM messages WHERE session_id=? ORDER BY id",
            (s["id"],),
        ).fetchall()
        if len(msgs) < args.min_session_messages:
            skipped["session_too_short"] += 1
            continue
        cur: dict | None = None
        traj: list[dict] = []

        def flush(c: dict | None) -> None:
            if not c:
                return
            if c["calls"] < args.min_tool_calls:
                skipped["no_tool_call"] += 1
                return
            if not c["final"]:
                skipped["no_final_answer"] += 1
                return
            rows.append(c["row"])

        for m in msgs:
            role = (m["role"] or "").lower()
            if role == "user":
                flush(cur)
                text, hits = redact((m["content"] or "").strip())
                redactions.update(hits)
                cur = {"calls": 0, "final": "", "row": {
                    "messages": ([{"role": "user", "content": text}] if text else []),
                    "meta": {"session_id": s["id"], "title": (s["title"] or "")[:120]},
                }}
                continue
            if cur is None:
                continue
            if role == "assistant":
                if m["tool_calls"]:
                    try:
                        calls = json.loads(m["tool_calls"])
                    except Exception:
                        continue
                    norm = []
                    for c in calls if isinstance(calls, list) else [calls]:
                        fn = c.get("function") or {}
                        name = fn.get("name")
                        if not name:
                            continue
                        raw = fn.get("arguments")
                        try:
                            a = json.loads(raw) if isinstance(raw, str) else (raw or {})
                        except Exception:
                            a = {"_raw": str(raw)[: args.max_args]}
                        a_txt, hits = redact(json.dumps(a, ensure_ascii=False))
                        redactions.update(hits)
                        norm.append({"type": "function", "function": {"name": name, "arguments": a_txt[: args.max_args]}})
                        cur["calls"] += 1
                    if m["content"]:
                        txt, hits = redact(m["content"])
                        redactions.update(hits)
                        cur["row"]["messages"].append({"role": "assistant", "content": txt[: args.max_args], "tool_calls": norm})
                    else:
                        cur["row"]["messages"].append({"role": "assistant", "content": "", "tool_calls": norm})
                elif m["content"]:
                    txt, hits = redact(m["content"])
                    redactions.update(hits)
                    cur["final"] = txt[: args.max_args]
            elif role == "tool":
                txt, hits = redact(m["content"] or "")
                redactions.update(hits)
                cur["row"]["messages"].append({
                    "role": "tool",
                    "name": m["tool_name"] or "unknown",
                    "content": txt[: args.max_tool_result],
                })
        flush(cur)

    # tekillestirme + split (icerik sha)
    seen: set[str] = set()
    kept: list[dict] = []
    for r in rows:
        key = hashlib.sha256(json.dumps(r["messages"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if key in seen:
            skipped["duplicate"] += 1
            continue
        seen.add(key)
        r["meta"]["sha256"] = key
        r["meta"]["split"] = "val" if int(key[:8], 16) % 100 < 10 else "train"
        r["meta"]["tool_calls"] = sum(len(m.get("tool_calls") or []) for m in r["messages"] if m["role"] == "assistant")
        r["meta"]["schema_source"] = "observed"
        r["tools"] = tools
        kept.append(r)

    files = {}
    for part in ("train", "val"):
        sel = [r for r in kept if r["meta"]["split"] == part]
        p = out / part / "agentic_dataset.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as fh:
            for r in sel:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        files[part] = len(sel)
    allp = out / "agentic_dataset.jsonl"
    with allp.open("w", encoding="utf-8") as fh:
        for r in kept:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    files["all"] = len(kept)

    chars = sum(len(m.get("content") or "") + len(json.dumps(m.get("tool_calls") or []))
                for r in kept for m in r["messages"])
    manifest = {
        "generated_at": now(),
        "source": {"db": str(db), "size_bytes": db.stat().st_size, "prefix_sha256_8mb": db_sha},
        "policy": {"llm": "none", "network": "none", "api_keys": "none",
                   "schema": "observed (gorulen cagrilardan turetildi, uydurma yok)"},
        "stats": {"sessions": len(sessions), "trajectories": len(kept),
                  "tool_calls_total": sum(tool_uses.values()), "distinct_tools": len(tool_uses),
                  "avg_calls_per_traj": round(sum(r["meta"]["tool_calls"] for r in kept) / max(len(kept), 1), 2)},
        "top_tools": tool_uses.most_common(12),
        "skipped": dict(skipped),
        "redactions": dict(redactions),
        "chars": chars, "est_tokens": chars // 4,
        "files": files,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
