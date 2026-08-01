import subprocess
import time
import sys
import json
import sqlite3
import os

STATUS_FILE = "production_status.json"

def get_db_stats():
    db_path = "elektor_archive.db"
    if not os.path.exists(db_path):
        return {"total_articles": 0, "enriched_english": 0, "translated_turkish": 0}
        
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM articles")
        total = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM enrichments")
        enriched = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM enrichments WHERE tr_sft_qa IS NOT NULL AND tr_sft_qa != ''")
        translated = cur.fetchone()[0]
        
        conn.close()
        return {
            "total_articles": total,
            "enriched_english": enriched,
            "translated_turkish": translated
        }
    except Exception as e:
        print(f"Error reading stats: {e}")
        return {"total_articles": 0, "enriched_english": 0, "translated_turkish": 0}

def save_status(batch_start, batch_end, stats):
    status = {
        "last_batch_start": batch_start,
        "last_batch_end": batch_end,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stats": stats
    }
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)

def run_command(cmd_args):
    print(f"Executing: {' '.join(cmd_args)}")
    process = subprocess.Popen(
        cmd_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    # Print stdout in real-time
    for line in process.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        
    process.wait()
    return process.returncode

def main():
    total_articles = 11773
    batch_size = 50
    
    # Load status if exists to resume
    start_index = 0
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                status = json.load(f)
                start_index = status.get("last_batch_end", 0)
                print(f"Resuming production from index {start_index} based on status file.")
        except Exception as e:
            print(f"Error loading status file: {e}. Starting from 0.")
            
    if start_index >= total_articles:
        print("All articles already processed according to status file. Resetting to 0 to verify.")
        start_index = 0

    print("=== STARTING ELEKTOR PRODUCTION RUN ===")
    print(f"Total archive size: {total_articles} articles")
    print(f"Batch size: {batch_size} articles")
    
    for start in range(start_index, total_articles, batch_size):
        end = min(start + batch_size, total_articles)
        print(f"\n==========================================")
        print(f"PROCESSING BATCH: {start} to {end}")
        print(f"==========================================")
        
        # 1. Run enrichment/translation for batch
        cmd = [sys.executable, "run.py", "pipeline", "--limit", f"{start}:{end}"]
        ret_code = run_command(cmd)
        
        if ret_code != 0:
            print(f"Warning: Batch {start}:{end} returned non-zero code {ret_code}. Continuing to next batch.")
            
        # 2. Get stats and save status
        stats = get_db_stats()
        save_status(start, end, stats)
        print(f"Batch completed. Current database stats:")
        print(f"  - Total extracted articles: {stats['total_articles']}")
        print(f"  - Enriched in English: {stats['enriched_english']}")
        print(f"  - Translated to Turkish SFT: {stats['translated_turkish']}")
        
        # 3. Export datasets
        print("Exporting updated datasets...")
        run_command([sys.executable, "run.py", "export"])
        
        # Small cooldown
        time.sleep(2)

    print("\nRunning final translation sweep for any failed/skipped articles...")
    run_command([sys.executable, "run.py", "enrich"])
    
    print("Exporting final datasets...")
    run_command([sys.executable, "run.py", "export"])

    print("\nProduction run complete!")

if __name__ == "__main__":
    main()
