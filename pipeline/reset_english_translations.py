import sqlite3
import json
import re
from pathlib import Path

def is_turkish(text):
    if not text:
        return False
    # match whole Turkish words
    words = ['nedir', 'nelerdir', 'nasıl', 'veya', 'ile', 'bir', 'için', 'bu', 'ne', 've', 'de', 'da']
    text_lower = text.lower()
    for w in words:
        if re.search(r'\b' + w + r'\b', text_lower):
            return True
    return False

def main():
    config_path = Path("config.json")
    if not config_path.exists():
        print("config.json not found.")
        return
        
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
        
    db_path = config.get("db_path", "database/rapberry_pi_pico_all.db")
    db_path_obj = Path(db_path)
    if len(db_path_obj.parts) == 1:
        db_path = str(Path("database") / db_path)
        
    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    cur.execute("SELECT article_id, sft_qa, tr_sft_qa FROM enrichments")
    rows = cur.fetchall()
    
    reset_count = 0
    for r in rows:
        article_id, sft_qa, tr_sft_qa = r
        if not tr_sft_qa:
            continue
            
        has_english_fallback = False
        try:
            sft_list = json.loads(sft_qa)
            tr_list = json.loads(tr_sft_qa)
            
            if len(sft_list) != len(tr_list):
                has_english_fallback = True
            else:
                for i in range(len(sft_list)):
                    eng_q = sft_list[i].get("question", "").strip()
                    tr_q = tr_list[i].get("question", "").strip()
                    
                    # If it is identical to English, or doesn't look like Turkish
                    if eng_q == tr_q or not is_turkish(tr_q):
                        has_english_fallback = True
                        break
        except Exception:
            has_english_fallback = True
            
        if has_english_fallback:
            cur.execute("""
                UPDATE enrichments 
                SET tr_sft_qa = '', tr_dpo_pairs = '', turkish_summary = ''
                WHERE article_id = ?
            """, (article_id,))
            reset_count += 1
            
    conn.commit()
    print(f"Successfully reset {reset_count} partially or fully English-fallback entries in the database.")
    print("You can now run 'python3.11 run.py enrich' to re-translate them into Turkish.")
    conn.close()

if __name__ == "__main__":
    main()
