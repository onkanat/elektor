#!/usr/bin/env python3
"""Makine basina cikarilmis Hermes oturum korpuslarini tek sete birlestirir.

`hermes_sessions_to_dataset.py` her makinede ayri kosar (state.db o makinede).
Bu betik ciktilari okur, `meta.source` etiketi ekler, icerik sha256'si bazinda
tekillestirir ve train/val'i sha'dan yeniden turetir. Ag yok, LLM yok.

    .venv/bin/python hermes-agent/scripts/hermes_korpus_birlestir.py \
        --kaynak exports/hermes_sessions=delinux01 \
        --kaynak exports/hermes_sessions_macair=macair \
        --out exports/hermes_korpus --split
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def sha_of(rec: dict, keys: tuple[str, ...]) -> str:
    return hashlib.sha256("\x00".join(str(rec.get(k, "")) for k in keys).encode("utf-8")).hexdigest()


def split_of(key: str) -> str:
    return "val" if int(key[:8], 16) % 100 < 10 else "train"


KIND_KEYS = {"sft": ("instruction", "output"), "dpo": ("prompt", "chosen", "rejected")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kaynak", action="append", required=True, metavar="YOL=ETIKET")
    ap.add_argument("--out", required=True)
    ap.add_argument("--split", action="store_true")
    args = ap.parse_args()

    out = Path(args.out).expanduser()
    rows: dict[str, list[dict]] = {"sft": [], "dpo": [], "chat": []}
    per_source: dict[str, Counter] = defaultdict(Counter)
    input_files = 0

    for spec in args.kaynak:
        path_s, _, label = spec.partition("=")
        base = Path(path_s).expanduser()
        label = label or base.name
        for kind in ("sft", "dpo", "chat"):
            for sub in ("", "train", "val"):
                f = base / sub / f"{kind}_dataset.jsonl"
                if not f.is_file():
                    continue
                input_files += 1
                with f.open(encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        rec = json.loads(line)
                        meta = dict(rec.get("meta") or {})
                        meta["source"] = label
                        keys = KIND_KEYS.get(kind)
                        if keys:
                            meta["sha256"] = sha_of(rec, keys)
                        meta["split"] = split_of(meta["sha256"]) if meta.get("sha256") else meta.get("split", "train")
                        rec["meta"] = meta
                        rows[kind].append(rec)
                        per_source[label][kind] += 1

    stats: dict[str, dict] = {}
    for kind, recs in rows.items():
        seen: set[str] = set()
        kept: list[dict] = []
        for r in recs:
            key = r["meta"].get("sha256") or sha_of(r, tuple(sorted(r)))
            if key in seen:
                continue
            seen.add(key)
            kept.append(r)
        rows[kind] = kept
        stats[kind] = {"in": len(recs), "kept": len(kept), "duplicate_removed": len(recs) - len(kept)}

    written: dict[str, int] = Counter()
    for kind, recs in rows.items():
        targets = ("train", "val") if args.split else ("",)
        for part in targets:
            sel = [r for r in recs if not args.split or r["meta"]["split"] == part]
            d = out / part if part else out
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"{kind}_dataset.jsonl"
            with p.open("w", encoding="utf-8") as fh:
                for r in sel:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            written[f"{part or 'all'}/{kind}"] = len(sel)

    sft_chars = sum(len(r["instruction"]) + len(r["output"]) for r in rows["sft"])
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "policy": {"llm": "none", "network": "none", "api_keys": "none"},
        "inputs": {"files": input_files, "sources": list(per_source)},
        "per_source": {k: dict(v) for k, v in per_source.items()},
        "merge": stats,
        "written": dict(written),
        "sft_chars": sft_chars,
        "sft_chars_est_tokens": sft_chars // 4,
        "split_rule": "val = ilk 8 hex %100 < 10 (sha256'dan turetilir, makine bagimsiz)",
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
