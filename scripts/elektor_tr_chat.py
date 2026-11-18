#!/usr/bin/env python3
"""Generate real Turkish multi-turn chat rows for Elektor enrichments.

Usage: python scripts/elektor_tr_chat.py --config CONFIG --start 0 --end 25
Only updates enrichments.tr_multi_turn_chat; other fields are untouched.
"""
import argparse
import json
import sys

from pipeline.analyzer import ArchiveAnalyzer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="projects_macair-teknik-nightly.json")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=None)
    args = ap.parse_args()

    analyzer = ArchiveAnalyzer(config_path=args.config)
    ok = failed = missing_text = 0
    try:
        end = args.end if args.end is not None else 10**9
        rows = analyzer.conn.execute(
            "SELECT a.id, a.title, a.extracted_text, e.tr_sft_qa "
            "FROM articles a JOIN enrichments e ON e.article_id = a.id "
            "WHERE (e.tr_multi_turn_chat IS NULL OR trim(e.tr_multi_turn_chat) IN ('', '[]', 'null')) "
            "AND a.id >= ? AND a.id < ? ORDER BY a.id",
            (args.start, end),
        ).fetchall()
        print(f"chat candidates [{args.start}:{end}] = {len(rows)}")
        for aid, title, text, tr_sft in rows:
            if not text or not str(text).strip():
                missing_text += 1
                continue
            try:
                chat_raw = analyzer.generate_turkish_multi_turn_chat(aid, title, text, tr_sft)
                if not chat_raw:
                    failed += 1
                    print(f"  [{aid}] no valid chat")
                    continue
                chat = json.loads(chat_raw)
                if len(chat) != 4 or [x.get("role") for x in chat] != ["user", "assistant", "user", "assistant"]:
                    failed += 1
                    print(f"  [{aid}] invalid turn structure")
                    continue
                analyzer.conn.execute(
                    "UPDATE enrichments SET tr_multi_turn_chat=? WHERE article_id=?",
                    (chat_raw, aid),
                )
                analyzer.conn.commit()
                ok += 1
                print(f"  [{aid}] OK {len(chat_raw)} chars")
            except Exception as e:
                analyzer.conn.rollback()
                failed += 1
                print(f"  [{aid}] ERROR {e}")
    finally:
        analyzer.close()
    print(json.dumps({"ok": ok, "failed": failed, "missing_text": missing_text}, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
