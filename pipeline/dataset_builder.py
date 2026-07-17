import sqlite3
import json
import os
from pathlib import Path

class DatasetBuilder:
    def __init__(self, config_path="config.json"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
            
        self.db_path = self.config["db_path"]
        self.export_dir = Path("exports")
        self.export_dir.mkdir(exist_ok=True)
        
    def export_datasets(self):
        """Compiles enriched SQLite data and exports SFT, DPO, and Chat datasets"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Select all articles and enrichments
        cursor.execute("""
            SELECT a.title, a.year, e.summary, e.turkish_title, e.turkish_summary, e.sft_qa, e.dpo_pairs
            FROM enrichments e
            JOIN articles a ON a.id = e.article_id
        """)
        rows = cursor.fetchall()
        
        sft_records = []
        dpo_records = []
        chat_records = []
        
        # Turkish dataset records
        tr_sft_records = []
        
        print(f"Compiling datasets from {len(rows)} enriched articles...")
        
        for row in rows:
            title, year, summary, tr_title, tr_summary, sft_qa_json, dpo_pairs_json = row
            
            # SFT and Chat data
            if sft_qa_json:
                try:
                    sft_qa = json.loads(sft_qa_json)
                    if isinstance(sft_qa, dict):
                        sft_qa = [sft_qa]
                    if isinstance(sft_qa, list):
                        for item in sft_qa:
                            if not isinstance(item, dict):
                                continue
                            q = item.get("question", "").strip()
                            a = item.get("answer", "").strip()
                            if q and a:
                                sft_records.append({
                                    "instruction": q,
                                    "input": f"Context: Elektor Magazine ({year}) article '{title}'",
                                    "output": a
                                })
                                chat_records.append({
                                    "messages": [
                                        {"role": "user", "content": q},
                                        {"role": "assistant", "content": a}
                                    ]
                                })
                except Exception as e:
                    print(f"Error parsing SFT QA for article '{title}': {e}")
                    
            # DPO data
            if dpo_pairs_json:
                try:
                    dpo_pairs = json.loads(dpo_pairs_json)
                    if isinstance(dpo_pairs, dict):
                        dpo_pairs = [dpo_pairs]
                    if isinstance(dpo_pairs, list):
                        for item in dpo_pairs:
                            if not isinstance(item, dict):
                                continue
                            q = item.get("question", "").strip()
                            chosen = item.get("chosen", "").strip()
                            rej = item.get("rejected", "").strip()
                            if q and chosen and rej:
                                dpo_records.append({
                                    "prompt": q,
                                    "chosen": chosen,
                                    "rejected": rej
                                })
                except Exception as e:
                    print(f"Error parsing DPO pairs for article '{title}': {e}")
                    
            # Turkish SFT dataset (Summary and Title QA)
            if tr_title and tr_summary:
                tr_sft_records.append({
                    "instruction": f"Elektor dergisinde {year} yılında yayınlanan '{tr_title}' makalesi ne hakkındadır? Kısaca özetler misiniz?",
                    "input": "",
                    "output": tr_summary.strip()
                })
                
        # Write SFT
        sft_file = self.export_dir / "sft_dataset.jsonl"
        with open(sft_file, "w", encoding="utf-8") as f:
            for rec in sft_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                
        # Write DPO
        dpo_file = self.export_dir / "dpo_dataset.jsonl"
        with open(dpo_file, "w", encoding="utf-8") as f:
            for rec in dpo_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                
        # Write Chat
        chat_file = self.export_dir / "chat_dataset.jsonl"
        with open(chat_file, "w", encoding="utf-8") as f:
            for rec in chat_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                
        # Write Turkish SFT
        tr_sft_file = self.export_dir / "tr_sft_dataset.jsonl"
        with open(tr_sft_file, "w", encoding="utf-8") as f:
            for rec in tr_sft_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                
        print("\nDatasets exported successfully:")
        print(f"  English SFT  : {len(sft_records)} samples -> {sft_file}")
        print(f"  English DPO  : {len(dpo_records)} samples -> {dpo_file}")
        print(f"  English Chat : {len(chat_records)} samples -> {chat_file}")
        print(f"  Turkish SFT  : {len(tr_sft_records)} samples -> {tr_sft_file}")
        
        conn.close()

if __name__ == "__main__":
    builder = DatasetBuilder()
    builder.export_datasets()
