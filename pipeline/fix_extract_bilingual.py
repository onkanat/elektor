import sqlite3
import sys
import json
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

from pipeline.analyzer import ArchiveAnalyzer
from pipeline.dataset_builder import DatasetBuilder

def main():
    config_file = "projects_extract.json"
    if not Path(config_file).exists():
        print(f"Error: {config_file} not found.")
        return

    with open(config_file, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    db_path = cfg.get("db_path", "database/extract.db")
    print(f"Connecting to {db_path}...")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Ensure tr_multi_turn_chat column exists
    cursor.execute("PRAGMA table_info(enrichments)")
    cols = [col[1] for col in cursor.fetchall()]
    if "tr_multi_turn_chat" not in cols:
        print("Adding column tr_multi_turn_chat to enrichments...")
        cursor.execute("ALTER TABLE enrichments ADD COLUMN tr_multi_turn_chat TEXT")
        conn.commit()

    # If tr_multi_turn_chat is empty and multi_turn_chat has Turkish chat, copy it over
    cursor.execute("""
        UPDATE enrichments 
        SET tr_multi_turn_chat = multi_turn_chat 
        WHERE (tr_multi_turn_chat IS NULL OR tr_multi_turn_chat = '') 
          AND multi_turn_chat IS NOT NULL 
          AND multi_turn_chat != ''
    """)
    conn.commit()

    # Clear English fields where Turkish content was duplicated into them so English pass re-generates true English content
    cursor.execute("""
        UPDATE enrichments
        SET summary = NULL,
            sft_qa = NULL,
            dpo_pairs = NULL,
            multi_turn_chat = NULL
        WHERE sft_qa = tr_sft_qa OR summary = turkish_summary
    """)
    conn.commit()
    print(f"Prepared database records for bilingual enrichment. Modified {cursor.rowcount} rows.")
    conn.close()

    # Run English enrichment pass
    print("\n=== Running English Enrichment Pass for test_extract ===")
    analyzer = ArchiveAnalyzer(config_path=config_file)
    try:
        analyzer.enrich_all(enrich_pass="english")
    finally:
        analyzer.close()

    # Re-export datasets
    print("\n=== Re-exporting Datasets for test_extract ===")
    builder = DatasetBuilder(config_path=config_file)
    builder.export_datasets()
    print("\n=== Bilingual Repair & Dataset Export Complete ===")

if __name__ == "__main__":
    main()
