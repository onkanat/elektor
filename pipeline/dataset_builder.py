import sqlite3
import json
import os
from pathlib import Path

class DatasetBuilder:
    def __init__(self, config_path="config.json"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
            
        self.db_path = self.config["db_path"]
        db_name = Path(self.db_path).stem
        self.export_dir = Path("exports") / db_name
        self.export_dir.mkdir(parents=True, exist_ok=True)
        
    def export_datasets(self):
        """Compiles enriched SQLite data and exports SFT, DPO, and Chat datasets (English and Turkish)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check column existence in enrichments table
        cursor.execute("PRAGMA table_info(enrichments)")
        cols = [c[1] for c in cursor.fetchall()]
        has_tr_qa = "tr_sft_qa" in cols and "tr_dpo_pairs" in cols

        if has_tr_qa:
            cursor.execute("""
                SELECT a.title, a.year, e.summary, e.turkish_title, e.turkish_summary, 
                       e.sft_qa, e.dpo_pairs, e.tr_sft_qa, e.tr_dpo_pairs
                FROM enrichments e
                JOIN articles a ON a.id = e.article_id
            """)
        else:
            cursor.execute("""
                SELECT a.title, a.year, e.summary, e.turkish_title, e.turkish_summary, 
                       e.sft_qa, e.dpo_pairs, NULL, NULL
                FROM enrichments e
                JOIN articles a ON a.id = e.article_id
            """)
        rows = cursor.fetchall()
        
        sft_records = []
        dpo_records = []
        chat_records = []
        
        # Turkish dataset records
        tr_sft_records = []
        tr_chat_records = []
        tr_dpo_records = []
        
        print(f"Compiling datasets from {len(rows)} enriched articles...")
        
        for row in rows:
            title, year, summary, tr_title, tr_summary, sft_qa_json, dpo_pairs_json, tr_sft_qa_json, tr_dpo_pairs_json = row
            display_tr_title = tr_title if tr_title else title
            
            # --- English SFT and Chat data ---
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
                    
            # --- English DPO data ---
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
                                    "input": f"Context: Elektor Magazine ({year}) article '{title}'",
                                    "chosen": chosen,
                                    "rejected": rej
                                })
                except Exception as e:
                    print(f"Error parsing DPO pairs for article '{title}': {e}")
                    
            # --- Turkish SFT, Chat, and DPO data ---
            if tr_sft_qa_json:
                try:
                    tr_sft_qa = json.loads(tr_sft_qa_json)
                    if isinstance(tr_sft_qa, dict):
                        tr_sft_qa = [tr_sft_qa]
                    if isinstance(tr_sft_qa, list):
                        for item in tr_sft_qa:
                            if not isinstance(item, dict):
                                continue
                            q = item.get("question", "").strip()
                            a = item.get("answer", "").strip()
                            if q and a:
                                tr_sft_records.append({
                                    "instruction": q,
                                    "input": f"Bağlam: Elektor Dergisi ({year}) '{display_tr_title}' makalesi",
                                    "output": a
                                })
                                tr_chat_records.append({
                                    "messages": [
                                        {"role": "user", "content": q},
                                        {"role": "assistant", "content": a}
                                    ]
                                })
                except Exception as e:
                    print(f"Error parsing Turkish SFT QA for article '{display_tr_title}': {e}")

            if tr_dpo_pairs_json:
                try:
                    tr_dpo_pairs = json.loads(tr_dpo_pairs_json)
                    if isinstance(tr_dpo_pairs, dict):
                        tr_dpo_pairs = [tr_dpo_pairs]
                    if isinstance(tr_dpo_pairs, list):
                        for item in tr_dpo_pairs:
                            if not isinstance(item, dict):
                                continue
                            q = item.get("question", "").strip()
                            chosen = item.get("chosen", "").strip()
                            rej = item.get("rejected", "").strip()
                            if q and chosen and rej:
                                tr_dpo_records.append({
                                    "prompt": q,
                                    "input": f"Bağlam: Elektor Dergisi ({year}) '{display_tr_title}' makalesi",
                                    "chosen": chosen,
                                    "rejected": rej
                                })
                except Exception as e:
                    print(f"Error parsing Turkish DPO pairs for article '{display_tr_title}': {e}")
                    
            # Turkish SFT dataset (Summary and Title QA)
            if display_tr_title and tr_summary:
                import random
                tr_templates = [
                    "Elektor dergisinde {year} yılında yayınlanan '{title}' makalesi ne hakkındadır? Kısaca özetler misiniz?",
                    "Lütfen {year} yılına ait '{title}' başlıklı Elektor makalesinin özetini Türkçe olarak yazın.",
                    "Elektor dergisindeki '{title}' ({year}) çalışmasının ana konusunu ve teknik içeriğini özetleyebilir misiniz?",
                    "{year} basımı Elektor dergisi içeriğindeki '{title}' yazısı hangi teknik konuları ele alıyor ve neyi özetliyor?",
                    "'{title}' ({year}) isimli Elektor makalesinin Türkçe özetini ve hedeflenen konuları paylaşır mısınız?",
                    "Elektor bünyesinde {year} yılında çıkan '{title}' makalesi hakkında bilgi verip kısaca özetler misiniz?",
                    "'{title}' ({year}) başlıklı teknik Elektor makalesinin içeriğini Türkçe olarak özetleyiniz."
                ]
                tr_prompt = random.choice(tr_templates).format(year=year, title=display_tr_title)
                tr_sft_records.append({
                    "instruction": tr_prompt,
                    "input": "",
                    "output": tr_summary.strip()
                })
                
        # Write English SFT
        sft_file = self.export_dir / "sft_dataset.jsonl"
        with open(sft_file, "w", encoding="utf-8") as f:
            for rec in sft_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                
        # Write English DPO
        dpo_file = self.export_dir / "dpo_dataset.jsonl"
        with open(dpo_file, "w", encoding="utf-8") as f:
            for rec in dpo_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                
        # Write English Chat
        chat_file = self.export_dir / "chat_dataset.jsonl"
        with open(chat_file, "w", encoding="utf-8") as f:
            for rec in chat_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                
        # Write Turkish SFT
        tr_sft_file = self.export_dir / "tr_sft_dataset.jsonl"
        with open(tr_sft_file, "w", encoding="utf-8") as f:
            for rec in tr_sft_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # Write Turkish Chat
        tr_chat_file = self.export_dir / "tr_chat_dataset.jsonl"
        with open(tr_chat_file, "w", encoding="utf-8") as f:
            for rec in tr_chat_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # Write Turkish DPO
        tr_dpo_file = self.export_dir / "tr_dpo_dataset.jsonl"
        with open(tr_dpo_file, "w", encoding="utf-8") as f:
            for rec in tr_dpo_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                
        print("\nDatasets exported successfully:")
        print(f"  English SFT   : {len(sft_records)} samples -> {sft_file}")
        print(f"  English DPO   : {len(dpo_records)} samples -> {dpo_file}")
        print(f"  English Chat  : {len(chat_records)} samples -> {chat_file}")
        print(f"  Turkish SFT   : {len(tr_sft_records)} samples -> {tr_sft_file}")
        print(f"  Turkish Chat  : {len(tr_chat_records)} samples -> {tr_chat_file}")
        print(f"  Turkish DPO   : {len(tr_dpo_records)} samples -> {tr_dpo_file}")
        
        conn.close()

if __name__ == "__main__":
    builder = DatasetBuilder()
    builder.export_datasets()
