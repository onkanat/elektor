import sqlite3
import json
import os
from pathlib import Path

class DatasetBuilder:
    def __init__(self, config_path="config.json"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
            
        self.db_path = self.config["db_path"]
        db_path_obj = Path(self.db_path)
        if len(db_path_obj.parts) == 1:
            self.db_path = str(Path("database") / self.db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        db_name = Path(self.db_path).stem
        self.export_dir = Path("exports") / db_name
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.dataset_name = self.config.get("dataset_name", "Document")
        self.dataset_name_tr = self.config.get("dataset_name_tr", "Döküman")

    def _save_jsonl_and_parquet(self, file_path: Path, records: list):
        with open(file_path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if records:
            try:
                import pandas as pd
                parquet_path = file_path.with_suffix(".parquet")
                df = pd.DataFrame(records)
                df.to_parquet(parquet_path, engine="pyarrow", index=False)
            except Exception as e:
                print(f"Warning: Parquet conversion error for {file_path.name}: {e}")

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
                                    "input": f"Context: {self.dataset_name} ({year}) article '{title}'",
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
                                    "input": f"Context: {self.dataset_name} ({year}) article '{title}'",
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
                                    "input": f"Bağlam: {self.dataset_name_tr} ({year}) '{display_tr_title}' makalesi",
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
                                    "input": f"Bağlam: {self.dataset_name_tr} ({year}) '{display_tr_title}' makalesi",
                                    "chosen": chosen,
                                    "rejected": rej
                                })
                except Exception as e:
                    print(f"Error parsing Turkish DPO pairs for article '{display_tr_title}': {e}")
                    
            # Turkish SFT dataset (Summary and Title QA)
            if display_tr_title and tr_summary:
                import random
                tr_templates = [
                    "{dataset} bünyesinde {year} yılında yayınlanan '{title}' makalesi ne hakkındadır? Kısaca özetler misiniz?",
                    "Lütfen {year} yılına ait '{title}' başlıklı {dataset} makalesinin özetini Türkçe olarak yazın.",
                    "{dataset} içeriğindeki '{title}' ({year}) çalışmasının ana konusunu ve teknik içeriğini özetleyebilir misiniz?",
                    "{year} basımı {dataset} içeriğindeki '{title}' yazısı hangi teknik konuları ele alıyor ve neyi özetliyor?",
                    "'{title}' ({year}) isimli {dataset} makalesinin Türkçe özetini ve hedeflenen konuları paylaşır mısınız?",
                    "{dataset} bünyesinde {year} yılında çıkan '{title}' makalesi hakkında bilgi verip kısaca özetler misiniz?",
                    "'{title}' ({year}) başlıklı teknik {dataset} makalesinin içeriğini Türkçe olarak özetleyiniz."
                ]
                tr_prompt = random.choice(tr_templates).format(dataset=self.dataset_name_tr, year=year, title=display_tr_title)
                tr_sft_records.append({
                    "instruction": tr_prompt,
                    "input": "",
                    "output": tr_summary.strip()
                })
                
        # Check and export synthetic_code_pairs table

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='synthetic_code_pairs'")
        if cursor.fetchone():
            cursor.execute("""
                SELECT instruction, input_code, output_response, tr_instruction, tr_output_response 
                FROM synthetic_code_pairs
            """)
            code_rows = cursor.fetchall()
            if code_rows:
                code_sft_records = []
                tr_code_sft_records = []
                for inst, inp, out, tr_inst, tr_out in code_rows:
                    code_sft_records.append({
                        "instruction": inst,
                        "input": inp,
                        "output": out
                    })
                    tr_code_sft_records.append({
                        "instruction": tr_inst if tr_inst else inst,
                        "input": inp,
                        "output": tr_out if tr_out else out
                    })
                    sft_records.append({
                        "instruction": inst,
                        "input": inp,
                        "output": out
                    })
                    tr_sft_records.append({
                        "instruction": tr_inst if tr_inst else inst,
                        "input": inp,
                        "output": tr_out if tr_out else out
                    })

                    # Convert code pair to Chat format (messages)
                    user_msg_en = f"{inst}\n\n```python\n{inp}\n```" if inp else inst
                    chat_records.append({
                        "messages": [
                            {"role": "user", "content": user_msg_en},
                            {"role": "assistant", "content": out}
                        ]
                    })

                    tr_inst_val = tr_inst if tr_inst else inst
                    user_msg_tr = f"{tr_inst_val}\n\n```python\n{inp}\n```" if inp else tr_inst_val
                    tr_out_val = tr_out if tr_out else out
                    tr_chat_records.append({
                        "messages": [
                            {"role": "user", "content": user_msg_tr},
                            {"role": "assistant", "content": tr_out_val}
                        ]
                    })

                code_sft_file = self.export_dir / "code_sft_dataset.jsonl"
                self._save_jsonl_and_parquet(code_sft_file, code_sft_records)

                tr_code_sft_file = self.export_dir / "tr_code_sft_dataset.jsonl"
                self._save_jsonl_and_parquet(tr_code_sft_file, tr_code_sft_records)

                print(f"  Code SFT      : {len(code_sft_records)} samples -> {code_sft_file} & .parquet")
                print(f"  Turkish Code SFT: {len(tr_code_sft_records)} samples -> {tr_code_sft_file} & .parquet")

        # Write English SFT
        sft_file = self.export_dir / "sft_dataset.jsonl"
        self._save_jsonl_and_parquet(sft_file, sft_records)
                
        # Write English DPO
        dpo_file = self.export_dir / "dpo_dataset.jsonl"
        self._save_jsonl_and_parquet(dpo_file, dpo_records)
                
        # Write English Chat
        chat_file = self.export_dir / "chat_dataset.jsonl"
        self._save_jsonl_and_parquet(chat_file, chat_records)
                
        # Write Turkish SFT
        tr_sft_file = self.export_dir / "tr_sft_dataset.jsonl"
        self._save_jsonl_and_parquet(tr_sft_file, tr_sft_records)

        # Write Turkish Chat
        tr_chat_file = self.export_dir / "tr_chat_dataset.jsonl"
        self._save_jsonl_and_parquet(tr_chat_file, tr_chat_records)

        # Write Turkish DPO
        tr_dpo_file = self.export_dir / "tr_dpo_dataset.jsonl"
        self._save_jsonl_and_parquet(tr_dpo_file, tr_dpo_records)
                
        print("\nDatasets exported successfully (JSONL & Parquet):")
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
