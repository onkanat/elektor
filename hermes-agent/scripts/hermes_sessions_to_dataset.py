#!/usr/bin/env python3
"""Hermes oturum deposu (state.db) -> Elektor uyumlu SFT / DPO / chat JSONL.

Yerel ve deterministik: **hicbir ag cagrisi yapmaz, LLM kullanmaz, API anahtari
istemez.** Tek girdi salt-okunur `state.db`, tek cikti JSONL dosyalari.

Neden ayri bir betik: Elektor boru hatti PDF -> metin -> LLM zenginlestirme
uzerine kurulu. Hermes oturumlari zaten (soru, yanit) cifti olarak uretildigi
icin zenginlestirme gerekmez; egri altinda kalan is *temizlik*: arac ciktisi
gurultusunu, sirlari ve islevsiz turlari ayiklamak. Bu betik onu yapar.

Kullanim:
    .venv/bin/python hermes-agent/scripts/hermes_sessions_to_dataset.py \
        --out exports/hermes_sessions --split

Cikti dosyalari (Elektor `exports/<proje>/` semasiyla ayni):
    chat_dataset.jsonl   {"messages": [{"role","content"}, ...]}
    sft_dataset.jsonl    {"instruction","input","output"}
    dpo_dataset.jsonl    {"prompt","chosen","rejected"}
    _atlanan.jsonl       atilan her tur icin gerekce (sessiz veri kaybi yok)
    manifest.json        sayimlar + kaynak sha256 + kirmizi cizgi raporu
    KAYNAK.md            insan okunur kaynak/olcum tablosu
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

# --- sizinti temizleyici -----------------------------------------------------
# Kural: desenleri ANAHTAR BAGLAMINA bagla. Ciplak 64-hex redaksiyonu korpusu
# bosaltir (ozetlerde/sha'larda her yerde gecer) - bkz. skill egitim-verisi-hazirlama.
REDACTIONS: list[tuple[str, re.Pattern[str], str]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED:private_key]"),
    ("openai_like", re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_\-]{16,}"), "[REDACTED:api_key]"),
    ("github", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"), "[REDACTED:github_token]"),
    ("slack", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"), "[REDACTED:slack_token]"),
    ("aws", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED:aws_key]"),
    ("google", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), "[REDACTED:google_key]"),
    ("huggingface", re.compile(r"\bhf_[A-Za-z0-9]{30,}"), "[REDACTED:hf_token]"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"), "[REDACTED:jwt]"),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{12,}"), "Bearer [REDACTED:token]"),
    # anahtar sozcuk + deger: yalniz anahtar baglaminda
    ("kv_secret", re.compile(r"(?i)\b(password|passwd|parola|sifre|şifre|secret|api[_\-]?key|apikey|access[_\-]?token|auth[_\-]?token|client[_\-]?secret)\b\s*[:=]\s*(?!\[REDACTED)([^\s\"',;}]{6,})"), None),
    ("url_creds", re.compile(r"\b([a-z][a-z0-9+.\-]*://)[^/\s:@]{2,}:[^/\s@]{2,}@"), None),
]


def redact(text: str) -> tuple[str, Counter]:
    hits: Counter = Counter()
    for kind, pattern, replacement in REDACTIONS:
        if kind == "kv_secret":
            def _kv(m: re.Match[str]) -> str:
                hits[kind] += 1
                return f"{m.group(1)}=[REDACTED:{kind}]"
            text = pattern.sub(_kv, text)
        elif kind == "url_creds":
            def _url(m: re.Match[str]) -> str:
                hits[kind] += 1
                return f"{m.group(1)}[REDACTED:userinfo]@"
            text = pattern.sub(_url, text)
        else:
            text, n = pattern.subn(replacement, text)
            if n:
                hits[kind] += n
    return text, hits


LEAK_PROBES = [
    ("sk-", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
    ("github", re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}")),
    ("aws", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}")),
]

# Islevsiz / gurultu turlari: kullanici mesaji bunlardan biriyse tur atilir.
NOISE_USER = re.compile(
    r"^\s*(?:/(?:new|reload-mcp|reload-skills|status|help)\b|devam|continue|tamam|ok|evet|hayır|peki|\[SYSTEM)",
    re.I,
)
# Asistanin arac cagrisi arasinda kalan dolgu metinleri (son yanit degilse elenir)
FILLER_ASSISTANT = re.compile(
    r"^\s*(?:I(?:'| a)m going to|Let me|Now let me|I will|Kontrol ediyorum|Bakıyorum|Şimdi|Önce|Araştırıyorum)",
    re.I,
)
CORRECTION = re.compile(
    r"\b(?:hayır|yanlış|hatalı|olmadı|olmuyor|düzelt|tekrar|çalışmadı|çalışmıyor|değil|wrong|incorrect|failed|doesn't work|not working)\b",
    re.I,
)
# Harness tarafindan kullanici mesajina eklenen zarflar (kullanici yazmadi):
#   [IMPORTANT: The user has invoked the "<skill>" skill ...] + skill govdesi
#   [OUT-OF-BAND USER MESSAGE ...] ... [/OUT-OF-BAND USER MESSAGE]
SKILL_INJECT = re.compile(r'^\s*\[IMPORTANT: The user has invoked the "([^"]+)" skill', re.I)
SKILL_DESC = re.compile(r"^description:\s*(.+)$", re.M)
OOB_OPEN = re.compile(r"^\s*\[OUT-OF-BAND USER MESSAGE[^\]]*\]\s*", re.I | re.M)
OOB_CLOSE = re.compile(r"^\s*\[/OUT-OF-BAND USER MESSAGE\]\s*", re.I | re.M)


def clean_user_text(text: str) -> tuple[str, str | None, str]:
    """Harness zarflarini temizler.

    Donus: (temiz metin, enjekte edilen skill adi ya da None, skill aciklamasi).
    """
    text = OOB_CLOSE.sub("", OOB_OPEN.sub("", text)).strip()
    # "standing goal" dongusu: kullanici metni degil, cron/hedef kosucusu yazdi.
    if text.startswith("[Continuing toward your standing goal]"):
        g = re.search(r"^Goal:\s*(.+)$", text, re.M)
        text = f"Hedef: {g.group(1).strip()}" if g else "Hedefi sürdür."
    m = SKILL_INJECT.match(text)
    if not m:
        return text, None, ""
    d = SKILL_DESC.search(text[:4000])
    return text, m.group(1), (d.group(1).strip() if d else "")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def truncate(text: str, limit: int) -> str:
    """Sinirda kes; cumle/paragraf sonuna yakin kesmeye calis."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in ("\n\n", "\n", ". ", "? ", "! "):
        pos = cut.rfind(sep)
        if pos > limit * 0.6:
            return cut[: pos + len(sep)].rstrip() + " [...]"
    return cut.rstrip() + " [...]"


def connect_ro(db_path: Path) -> sqlite3.Connection:
    # WAL iceren canli depo: salt-okunur + immutable DEGIL, aksi halde son
    # islemler gorunmez. mode=ro yeterli (yazma yok, kilit almaz).
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_sessions(conn: sqlite3.Connection, include_hidden: bool) -> list[sqlite3.Row]:
    q = "SELECT * FROM sessions"
    if not include_hidden:
        q += " WHERE COALESCE(hidden,0)=0"
    return conn.execute(q + " ORDER BY COALESCE(started_at,'')").fetchall()


def build_turns(messages: list[sqlite3.Row], min_assistant: int, max_chars: int,
                include_tool: bool, drop_skill_turns: bool = False) -> tuple[list[dict], list[dict]]:
    """Bir oturumun mesajlarini (user -> asistan son metni) turlarina cevirir."""
    turns: list[dict] = []
    skipped: list[dict] = []
    cur: dict | None = None
    tool_msgs: list[str] = []

    for m in messages:
        role = (m["role"] or "").lower()
        content = (m["content"] or "").strip()
        if role == "user":
            if cur:
                turns.append(cur)
            cur = {"user": content, "assistant_texts": [], "tool_count": 0, "tool_texts": []}
        elif role == "assistant":
            if cur is None:
                continue
            if m["tool_calls"]:
                cur["tool_count"] += 1
            if content:
                cur["assistant_texts"].append(content)
        elif role == "tool":
            if cur is None:
                continue
            cur["tool_count"] += 1
            if include_tool and content:
                cur["tool_texts"].append(content)
    if cur:
        turns.append(cur)

    kept: list[dict] = []
    for idx, t in enumerate(turns):
        user, skill_name, skill_desc = clean_user_text(t["user"])
        texts = t["assistant_texts"]
        # son anlamli asistan metni = turun nihai yaniti
        final = ""
        for txt in reversed(texts):
            if len(txt) >= min_assistant and not FILLER_ASSISTANT.match(txt):
                final = txt
                break
        reason = None
        if skill_name:
            if drop_skill_turns:
                reason = "skill_injection"
            else:
                # Skill cagrisi gercek kullanici talimati degil: enjeksiyonu at,
                # talimati skill adi + aciklamasindan deterministik kur.
                user = (f"{skill_name} yeteneğini kullan: {skill_desc}"
                        if skill_desc else f'"{skill_name}" yeteneğini çalıştır.')
        if reason is None and not user:
            reason = "empty_user"
        elif reason is None and NOISE_USER.match(user) and len(user) < 40:
            reason = "noise_user"
        elif reason is None and len(user) < 12:
            reason = "user_too_short"
        elif reason is None and not final:
            reason = "no_substantive_answer"
        if reason:
            skipped.append({"turn": idx, "reason": reason, "user_head": user[:120],
                            "assistant_texts": len(texts), "tool_count": t["tool_count"]})
            continue
        u, u_hits = redact(truncate(user, max_chars))
        a, a_hits = redact(truncate(final, max_chars))
        kept.append({
            "user": u, "assistant": a,
            "tool_count": t["tool_count"],
            "redactions": dict(u_hits + a_hits),
        })
    return kept, skipped


def split_of(key: str) -> str:
    """Split icerik sha'sindan turetilir (yol/ad bazli split sizinti uretir)."""
    return "val" if int(key[:8], 16) % 100 < 10 else "train"


def main() -> int:
    ap = argparse.ArgumentParser(description="Hermes state.db -> Elektor uyumlu SFT/DPO/chat JSONL (yerel, API'siz)")
    ap.add_argument("--db", default=str(Path.home() / ".hermes" / "state.db"))
    ap.add_argument("--out", default="/home/hakan/Git/elektor/exports/hermes_sessions")
    ap.add_argument("--min-assistant", type=int, default=80)
    ap.add_argument("--min-session-messages", type=int, default=4)
    ap.add_argument("--max-chars", type=int, default=6000)
    ap.add_argument("--split", action="store_true", help="train/val alt dizinlerine ayir")
    ap.add_argument("--include-tool", action="store_true", help="arac ciktisini de sakla (agentic varyant)")
    ap.add_argument("--drop-skill-turns", action="store_true",
                    help="skill enjeksiyonlu turlari at (varsayilan: talimati skill adi+aciklamasindan kur)")
    ap.add_argument("--include-hidden", action="store_true")
    args = ap.parse_args()

    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        print(f"HATA: depo bulunamadi: {db_path}", file=sys.stderr)
        return 2
    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    db_sha = sha256(db_path.read_bytes()[: 8 * 1024 * 1024])  # ilk 8 MB: hizli parmak izi
    conn = connect_ro(db_path)
    sessions = load_sessions(conn, args.include_hidden)

    chat_rows: list[dict] = []
    sft_rows: list[dict] = []
    dpo_rows: list[dict] = []
    skipped_all: list[dict] = []
    redaction_counts: Counter = Counter()
    stats = {"sessions_total": len(sessions), "sessions_used": 0, "sessions_skipped": 0,
             "turns_kept": 0, "turns_skipped": 0, "tool_messages_seen": 0}
    skip_reasons: Counter = Counter()

    for s in sessions:
        sid = s["id"]
        msgs = conn.execute(
            "SELECT id, role, content, tool_calls, tool_name, active FROM messages "
            "WHERE session_id=? ORDER BY id", (sid,)
        ).fetchall()
        if len(msgs) < args.min_session_messages:
            stats["sessions_skipped"] += 1
            skip_reasons["session_too_short"] += 1
            continue
        stats["tool_messages_seen"] += sum(1 for m in msgs if (m["role"] or "") == "tool")
        turns, skipped = build_turns(msgs, args.min_assistant, args.max_chars,
                                     args.include_tool, args.drop_skill_turns)
        for sk in skipped:
            sk["session_id"] = sid
            skip_reasons[sk["reason"]] += 1
        skipped_all.extend(skipped)
        if not turns:
            stats["sessions_skipped"] += 1
            skip_reasons["no_usable_turn"] += 1
            continue
        stats["sessions_used"] += 1
        stats["turns_kept"] += len(turns)
        stats["turns_skipped"] += len(skipped)
        for t in turns:
            redaction_counts.update(t["redactions"])

        title = s["title"] or sid
        chat_key = sha256(json.dumps([t["user"] + t["assistant"] for t in turns], ensure_ascii=False))
        chat_rows.append({
            "messages": [x for t in turns for x in (
                {"role": "user", "content": t["user"]},
                {"role": "assistant", "content": t["assistant"]},
            )],
            "meta": {"session_id": sid, "title": title[:120], "turns": len(turns),
                     "split": split_of(chat_key), "sha256": chat_key},
        })
        for t in turns:
            key = sha256(t["user"] + "\x00" + t["assistant"])
            sft_rows.append({
                "instruction": t["user"],
                "input": "",
                "output": t["assistant"],
                "meta": {"session_id": sid, "tool_count": t["tool_count"],
                         "split": split_of(key), "sha256": key},
            })
        # Gercek duzeltmelerden DPO: kullanici bir onceki yaniti reddedip yeniden
        # sorduysa, reddedilen=onceki yanit, secilen=sonraki yanit.
        for prev, nxt in zip(turns, turns[1:]):
            u = nxt["user"]
            if len(u) < 12 or not CORRECTION.search(u):
                continue
            if prev["assistant"] == nxt["assistant"] or len(nxt["assistant"]) < args.min_assistant:
                continue
            key = sha256(prev["assistant"] + "\x00" + nxt["assistant"])
            dpo_rows.append({
                "prompt": u,
                "chosen": nxt["assistant"],
                "rejected": prev["assistant"],
                "meta": {"session_id": sid, "split": split_of(key), "sha256": key},
            })

    # Icerik bazinda tekilleştirme (ayni tur birden cok oturumda tekrar edebilir)
    def dedupe(rows: list[dict]) -> tuple[list[dict], int]:
        seen: set[str] = set()
        out: list[dict] = []
        for r in rows:
            k = r["meta"]["sha256"]
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
        return out, len(rows) - len(out)

    chat_rows, dup_chat = dedupe(chat_rows)
    sft_rows, dup_sft = dedupe(sft_rows)
    dpo_rows, dup_dpo = dedupe(dpo_rows)

    # Sizinti kapisi: temizlikten SONRA korpusu yeniden tara, kalan 0 olmali.
    leak_counts: Counter = Counter()
    for r in sft_rows:
        for name, pat in LEAK_PROBES:
            if pat.search(r["instruction"]) or pat.search(r["output"]):
                leak_counts[name] += 1

    def write_jsonl(path: Path, rows: list[dict], split: bool) -> dict:
        n = 0
        if split:
            for part in ("train", "val"):
                sel = [r for r in rows if r["meta"]["split"] == part]
                p = path.parent / part / path.name
                p.parent.mkdir(parents=True, exist_ok=True)
                with p.open("w", encoding="utf-8") as f:
                    for r in sel:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
                        n += 1
            return {"rows": len(rows), "written": n}
        with path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                n += 1
        return {"rows": len(rows), "written": n}

    r1 = write_jsonl(out_dir / "chat_dataset.jsonl", chat_rows, args.split)
    r2 = write_jsonl(out_dir / "sft_dataset.jsonl", sft_rows, args.split)
    r3 = write_jsonl(out_dir / "dpo_dataset.jsonl", dpo_rows, args.split)
    with (out_dir / "_atlanan.jsonl").open("w", encoding="utf-8") as f:
        for sk in skipped_all:
            f.write(json.dumps(sk, ensure_ascii=False) + "\n")

    chars = sum(len(r["instruction"]) + len(r["output"]) for r in sft_rows)
    manifest = {
        "generated_at": now_iso(),
        "source": {"db": str(db_path), "db_size_bytes": db_path.stat().st_size,
                   "db_prefix_sha256_8mb": db_sha},
        "policy": {"llm": "none", "network": "none", "api_keys": "none",
                   "min_assistant": args.min_assistant, "max_chars": args.max_chars,
                   "include_tool": args.include_tool, "split": args.split},
        "stats": stats,
        "skip_reasons": dict(skip_reasons),
        "dedupe_removed": {"chat": dup_chat, "sft": dup_sft, "dpo": dup_dpo},
        "redactions": dict(redaction_counts),
        "leak_probe_after_redaction": dict(leak_counts),
        "outputs": {"chat": r1, "sft": r2, "dpo": r3},
        "sft_chars": chars, "sft_chars_est_tokens": chars // 4,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "KAYNAK.md").write_text(render_kaynak(manifest), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def render_kaynak(m: dict) -> str:
    s, st = m["stats"], m["stats"]
    lines = [
        "# KAYNAK — Hermes oturum korpusu (delinux01)",
        "",
        f"- Üretim: {m['generated_at']}",
        f"- Kaynak depo: `{m['source']['db']}` ({m['source']['db_size_bytes']/1e6:.1f} MB, ilk 8 MB sha256 `{m['source']['db_prefix_sha256_8mb'][:16]}`)",
        "- Politika: **LLM yok, ağ çağrısı yok, API anahtarı yok** (deterministik dönüşüm)",
        "",
        "## Sayımlar",
        "",
        "| Ölçüm | Değer |",
        "| :--- | ---: |",
        f"| Oturum (depoda) | {s['sessions_total']} |",
        f"| Oturum (kullanılan) | {s['sessions_used']} |",
        f"| Oturum (atlanan) | {s['sessions_skipped']} |",
        f"| Tur (korunan) | {s['turns_kept']} |",
        f"| Tur (atlanan) | {s['turns_skipped']} |",
        f"| Araç mesajı (görülen) | {s['tool_messages_seen']} |",
        f"| SFT satırı | {m['outputs']['sft']['rows']} |",
        f"| chat satırı | {m['outputs']['chat']['rows']} |",
        f"| DPO satırı | {m['outputs']['dpo']['rows']} |",
        f"| SFT karakter | {m['sft_chars']:,} |",
        f"| SFT ~token (char/4) | {m['sft_chars_est_tokens']:,} |",
        "",
        "## Atlama gerekçeleri",
        "",
        "| Gerekçe | Adet |",
        "| :--- | ---: |",
    ]
    for k, v in sorted(m["skip_reasons"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{k}` | {v} |")
    lines += ["", "## Redaksiyon (sır temizliği)", "", "| Desen | Adet |", "| :--- | ---: |"]
    if m["redactions"]:
        for k, v in sorted(m["redactions"].items(), key=lambda kv: -kv[1]):
            lines.append(f"| `{k}` | {v} |")
    else:
        lines.append("| (temizlik gerekmedi) | 0 |")
    lines += ["", "## Sızıntı kapısı (temizlik SONRASI yeniden tarama)", ""]
    if m["leak_probe_after_redaction"]:
        lines += ["**KALAN VAR — korpus kullanılmamalı:**", ""]
        for k, v in m["leak_probe_after_redaction"].items():
            lines.append(f"- `{k}`: {v}")
    else:
        lines.append("Kalan sır kalıbı: **0** (kapı geçildi).")
    lines += ["", "## Tekilleştirme", "",
              f"- chat: {m['dedupe_removed']['chat']} · sft: {m['dedupe_removed']['sft']} · dpo: {m['dedupe_removed']['dpo']} satır (içerik sha256 bazında)",
              "", "## Dürüst sınırlar", "",
              "- `meta` anahtarı korpus satırında duruyor; alıcı şeması `{\"messages\":[…]}` / "
              "`{\"instruction\",\"input\",\"output\"}` / `{\"prompt\",\"chosen\",\"rejected\"}` ise "
              "**`meta` çıkarılarak** birleştirilmeli (provenance ayrı tutulur).",
              "- DPO çiftleri gerçek düzeltmelerden türetildi (LLM üretmedi); sayı bu yüzden küçüktür.",
              "- Araç çıktıları varsayılan olarak korpusa girmez (`--include-tool` ile agentic varyant).",
              "- Bu korpus Hermes ajan davranışını yansıtır (Türkçe ağırlıklı, araç kullanımı yoğun), "
              "teknik datasheet bilgisi değil.",
              ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
