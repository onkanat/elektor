import sqlite3
import json
import ollama
from datetime import datetime

class ArchiveAnalyzer:
    def __init__(self, config_path="config.json"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
            
        self.db_path = self.config["db_path"]
        self.ollama_url = self.config["ollama_url"]
        self.model_name = self.config["model_analyzer"]
        self.translator_model = self.config.get("model_translator", "translategemma:12b-it-q4_K_M")
        self.qa_count = self.config.get("qa_count_per_article", 10)
        
        # Connect to Ollama
        self.client = ollama.Client(host=self.ollama_url, timeout=180.0)
        
        # Connect/Initialize SQLite database
        self.conn = sqlite3.connect(self.db_path)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS enrichments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER UNIQUE,
                summary TEXT,
                topics TEXT,
                turkish_title TEXT,
                turkish_summary TEXT,
                sft_qa TEXT,
                dpo_pairs TEXT,
                tr_sft_qa TEXT,
                tr_dpo_pairs TEXT,
                processed_at TEXT,
                FOREIGN KEY (article_id) REFERENCES articles(id)
            )
        """)
        self.conn.commit()

        # Dynamic migration check for existing tables
        cursor.execute("PRAGMA table_info(enrichments)")
        existing_cols = [col[1] for col in cursor.fetchall()]
        if "tr_sft_qa" not in existing_cols:
            cursor.execute("ALTER TABLE enrichments ADD COLUMN tr_sft_qa TEXT")
        if "tr_dpo_pairs" not in existing_cols:
            cursor.execute("ALTER TABLE enrichments ADD COLUMN tr_dpo_pairs TEXT")
        self.conn.commit()

    def call_ollama_json(self, system_prompt, user_prompt, model=None, keep_alive=None, num_predict=8192):
        """Helper to call Ollama model and expect a JSON output, optimized with token limit and temp"""
        if model is None:
            model = self.model_name
        try:
            chat_kwargs = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "format": "json",
                "think": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": num_predict
                }
            }
            if keep_alive is not None:
                chat_kwargs["keep_alive"] = keep_alive
                
            response = self.client.chat(**chat_kwargs)
            content = response['message']['content']
            return json.loads(content)
        except Exception as e:
            print(f"  Ollama JSON call error (Model: {model}): {e}")
            return None

    def analyze_article_english(self, article_id, title, text):
        """Performs English technical analysis (summary, topics, 10 detailed Q&As, DPO) using self.model_name"""
        print(f"Analyzing article [{article_id}] (English - {self.qa_count} Q&As): {title}...")
        
        # Limit text size to 4000 characters to reduce prompt ingestion time and RAM usage
        truncated_text = text[:4000] if len(text) > 4000 else text
        
        system_prompt = (
            "You are an expert embedded systems engineer, technical writer, and AI trainer. "
            "Analyze the technical article text and output a single JSON object. Follow the requested structure strictly."
        )
        
        user_prompt = (
            f"Article Title: {title}\n"
            f"Article Text:\n{truncated_text}\n\n"
            f"Generate a JSON object containing EXACTLY {self.qa_count} advanced technical Q&A pairs and 1 DPO pair with the following key structure:\n"
            "{\n"
            "  \"summary\": \"English summary of the project/article (2-4 detailed sentences)\",\n"
            "  \"topics\": [\"Topic 1\", \"Topic 2\", \"Topic 3\"],\n"
            "  \"sft_qa\": [\n"
            "    {\"question\": \"Advanced technical question 1 in English\", \"answer\": \"Long, comprehensive, step-by-step engineering answer explaining hardware operation, component roles, or circuit design\"},\n"
            f"    ... (Include EXACTLY {self.qa_count} total Q&A items in this array)\n"
            "  ],\n"
            "  \"dpo_pair\": {\n"
            "    \"question\": \"Detailed technical question in English\",\n"
            "    \"chosen\": \"Correct, detailed engineering explanation/solution in English\",\n"
            "    \"rejected\": \"Misleading response containing a common hardware design error, bad layout practice, or incorrect calculation in English\"\n"
            "  }\n"
            "}\n\n"
            "Guidelines:\n"
            f"1. Generate EXACTLY {self.qa_count} distinct advanced technical Q&A items in 'sft_qa'.\n"
            "2. Answers MUST be detailed, thorough, and instructive. Provide full explanations for hardware mechanisms, pinouts, component calculations, or code logic.\n"
            "3. In the DPO pair, the rejected answer must contain a realistic engineering mistake (e.g. swapping TX/RX, omitting pullups, missing decoupling capacitors, wrong pin definitions) related to the article.\n"
            "4. Format any mathematical equations or formulas using standard LaTeX notation, for example: \\(p = \\frac{n \\cdot n_{cyl}}{60 \\cdot a}\\) instead of plain text.\n"
            "5. Return ONLY the valid JSON object. Do not include markdown code block formatting."
        )
        
        result = self.call_ollama_json(system_prompt, user_prompt, model=self.model_name, num_predict=8192)
        
        if not result:
            print(f"  Warning: Failed to parse/receive Qwen response for article {article_id}. Using default/fallback.")
            result = {
                "summary": "Summary unavailable.",
                "topics": [],
                "sft_qa": [],
                "dpo_pair": {"question": "", "chosen": "", "rejected": ""}
            }
            
        sft_qa = result.get("sft_qa", [])
        dpo_pair = result.get("dpo_pair", {})
        dpo_pairs_list = [dpo_pair] if dpo_pair and dpo_pair.get("question") else []
        
        return {
            "summary": result.get("summary", ""),
            "topics": json.dumps(result.get("topics", [])),
            "sft_qa": json.dumps(sft_qa),
            "dpo_pairs": json.dumps(dpo_pairs_list)
        }

    def translate_enrichments_to_turkish(self, title, summary, sft_qa_raw, dpo_pairs_raw):
        """Translates title, summary, 10 Q&A pairs, and DPO pairs into Turkish using TranslateGemma with technical term preservation"""
        import re
        print(f"Translating to Turkish with TranslateGemma: '{title}'...")
        
        sft_qa_list = json.loads(sft_qa_raw) if isinstance(sft_qa_raw, str) and sft_qa_raw else sft_qa_raw or []
        dpo_pairs_list = json.loads(dpo_pairs_raw) if isinstance(dpo_pairs_raw, str) and dpo_pairs_raw else dpo_pairs_raw or []
        
        # Prepare plain text block
        text_block = []
        text_block.append(f"Title: {title}")
        text_block.append(f"Summary: {summary}")
        for idx, item in enumerate(sft_qa_list):
            text_block.append(f"Q{idx+1}: {item.get('question', '')}")
            text_block.append(f"A{idx+1}: {item.get('answer', '')}")
        for idx, item in enumerate(dpo_pairs_list):
            text_block.append(f"DPO_Q: {item.get('question', '')}")
            text_block.append(f"DPO_Chosen: {item.get('chosen', '')}")
            text_block.append(f"DPO_Rejected: {item.get('rejected', '')}")
            
        full_text = "\n\n".join(text_block)
        
        system_prompt = (
            "You are a professional technical translator specializing in electrical engineering, embedded systems, and computer science.\n"
            "Translate the technical text block provided by the user into natural, high-quality Turkish.\n\n"
            "CRITICAL TERMINOLOGY RULES:\n"
            "1. PRESERVE ALL TECHNICAL TERMS IN THEIR ORIGINAL STANDARD FORM (e.g. ESP32, SPI, I2C, MOSFET, ADC, DAC, PWM, microcontroller, op-amp, decoupling capacitor, pull-up, baud rate, duty cycle, flip-flop, PCB, RAM, ROM, GPIO, UART, DMA, breadboard, SMD, transceiver, etc.).\n"
            "2. Keep all math/LaTeX formulas intact.\n"
            "3. Preserve the exact markers (e.g. Title:, Summary:, Q1:, A1:, DPO_Q:, DPO_Chosen:, DPO_Rejected:) to demarcate segments."
        )
        
        user_prompt = (
            "Translate the following segment block into Turkish, preserving the markers:\n\n"
            f"{full_text}"
        )
        
        try:
            chat_kwargs = {
                "model": self.translator_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "options": {
                    "temperature": 0.2,
                    "num_predict": 8192
                }
            }
            response = self.client.chat(**chat_kwargs)
            content = response['message']['content']
            
            # Regex Parsing
            content_norm = content.replace('\r\n', '\n')
            
            # Extract title
            title_match = re.search(r'^Title:\s*(.*)', content_norm, re.IGNORECASE | re.MULTILINE)
            turkish_title = title_match.group(1).strip() if title_match else title
            
            # Extract summary
            summary_match = re.search(r'^Summary:\s*(.*?)(?=\n\n|\n[Q|D])', content_norm, re.IGNORECASE | re.DOTALL | re.MULTILINE)
            turkish_summary = summary_match.group(1).strip() if summary_match else summary
            
            # Extract SFT QA
            tr_sft_qa = []
            for i in range(1, len(sft_qa_list) + 1):
                q_pattern = rf'^Q{i}:\s*(.*?)(?=\nA{i}:|\nQ{i+1}:|\nDPO_|$)'
                a_pattern = rf'^A{i}:\s*(.*?)(?=\nQ{i+1}:|\nA{i+1}:|\nDPO_|$)'
                
                q_match = re.search(q_pattern, content_norm, re.IGNORECASE | re.DOTALL | re.MULTILINE)
                a_match = re.search(a_pattern, content_norm, re.IGNORECASE | re.DOTALL | re.MULTILINE)
                
                if q_match and a_match:
                    tr_sft_qa.append({
                        "question": q_match.group(1).strip(),
                        "answer": a_match.group(1).strip()
                    })
                else:
                    # Fallback to original English item if parse fails for this specific item
                    orig_item = sft_qa_list[i-1]
                    tr_sft_qa.append(orig_item)
            
            # Extract DPO pairs
            tr_dpo_pairs = []
            for i in range(1, len(dpo_pairs_list) + 1):
                dpo_q_match = re.search(r'^DPO_Q:\s*(.*?)(?=\nDPO_|$)', content_norm, re.IGNORECASE | re.DOTALL | re.MULTILINE)
                dpo_chosen_match = re.search(r'^DPO_Chosen:\s*(.*?)(?=\nDPO_|$)', content_norm, re.IGNORECASE | re.DOTALL | re.MULTILINE)
                dpo_rej_match = re.search(r'^DPO_Rejected:\s*(.*?)(?=\nDPO_|$)', content_norm, re.IGNORECASE | re.DOTALL | re.MULTILINE)
                
                if dpo_q_match and dpo_chosen_match and dpo_rej_match:
                    tr_dpo_pairs.append({
                        "question": dpo_q_match.group(1).strip(),
                        "chosen": dpo_chosen_match.group(1).strip(),
                        "rejected": dpo_rej_match.group(1).strip()
                    })
                else:
                    # Fallback
                    tr_dpo_pairs.append(dpo_pairs_list[i-1])
            
            # Check if we parsed anything at all. If empty, trigger fallback
            if not tr_sft_qa:
                tr_sft_qa = sft_qa_list
            if not tr_dpo_pairs:
                tr_dpo_pairs = dpo_pairs_list
                
            return {
                "turkish_title": turkish_title if turkish_title else title,
                "turkish_summary": turkish_summary if turkish_summary else summary,
                "tr_sft_qa": json.dumps(tr_sft_qa, ensure_ascii=False),
                "tr_dpo_pairs": json.dumps(tr_dpo_pairs, ensure_ascii=False)
            }
            
        except Exception as e:
            print(f"  Warning: Translation failed/errored for article '{title}': {e}. Using fallback structure.")
            return {
                "turkish_title": title,
                "turkish_summary": summary,
                "tr_sft_qa": json.dumps(sft_qa_list, ensure_ascii=False),
                "tr_dpo_pairs": json.dumps(dpo_pairs_list, ensure_ascii=False)
            }

    def translate_to_turkish(self, title, summary):
        """Backwards compatible title/summary translator method"""
        tr_res = self.translate_enrichments_to_turkish(title, summary, [], [])
        return tr_res["turkish_title"], tr_res["turkish_summary"]

    def analyze_article(self, article_id, title, text):
        """Compatibility wrapper for direct analyzer calls in tests/other modules"""
        eng_data = self.analyze_article_english(article_id, title, text)
        tr_res = self.translate_enrichments_to_turkish(title, eng_data["summary"], eng_data["sft_qa"], eng_data["dpo_pairs"])
        return {
            "summary": eng_data["summary"],
            "topics": eng_data["topics"],
            "turkish_title": tr_res["turkish_title"],
            "turkish_summary": tr_res["turkish_summary"],
            "sft_qa": eng_data["sft_qa"],
            "dpo_pairs": eng_data["dpo_pairs"],
            "tr_sft_qa": tr_res["tr_sft_qa"],
            "tr_dpo_pairs": tr_res["tr_dpo_pairs"]
        }

    def enrich_all(self, limit=None):
        """Enriches extracted articles in SQLite DB using a two-pass batch optimization"""
        cursor = self.conn.cursor()
        
        # Parse range limit if range format
        start, end = 0, None
        if isinstance(limit, tuple):
            start, end = limit
        elif isinstance(limit, int):
            start, end = 0, limit
            
        # Get active IDs based on entire articles set to align passes deterministically
        cursor.execute("SELECT id FROM articles ORDER BY id")
        all_ids = [r[0] for r in cursor.fetchall()]
        active_ids = all_ids[start:end] if end is not None else all_ids[start:]
        
        if not active_ids:
            print("No active articles in the specified range.")
            return
            
        placeholders = ",".join(["?"] * len(active_ids))
        
        # --- PASS 1: English Technical Analysis (Qwen Model - 10 Detailed Q&A) ---
        cursor.execute(f"""
            SELECT a.id, a.title, a.extracted_text 
            FROM articles a
            LEFT JOIN enrichments e ON a.id = e.article_id
            WHERE e.id IS NULL AND a.extracted_text IS NOT NULL AND a.extracted_text != ''
            AND a.id IN ({placeholders})
        """, active_ids)
        pass1_rows = cursor.fetchall()
        
        if pass1_rows:
            print(f"Pass 1: Found {len(pass1_rows)} articles awaiting English enrichment ({self.qa_count} Q&As each) in range [{start}:{end if end is not None else len(all_ids)}].")
            count1 = 0
            for row in pass1_rows:
                article_id, title, text = row
                try:
                    eng_data = self.analyze_article_english(article_id, title, text)
                    processed_at = datetime.now().isoformat()
                    
                    cursor.execute("""
                        INSERT INTO enrichments (
                            article_id, summary, topics, turkish_title, turkish_summary, sft_qa, dpo_pairs, tr_sft_qa, tr_dpo_pairs, processed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        article_id,
                        eng_data["summary"],
                        eng_data["topics"],
                        title,       # Placeholder title, will be translated in Pass 2
                        "",          # Placeholder summary, will be translated in Pass 2
                        eng_data["sft_qa"],
                        eng_data["dpo_pairs"],
                        "",          # Placeholder tr_sft_qa, translated in Pass 2
                        "",          # Placeholder tr_dpo_pairs, translated in Pass 2
                        processed_at
                    ))
                    self.conn.commit()
                    count1 += 1
                except Exception as e:
                    print(f"Error in Pass 1 for article {article_id}: {e}")
                    self.conn.rollback()
            
            print(f"Pass 1 complete. Enriched {count1} articles in English with {self.qa_count} Q&A pairs each.")
            
            # Unload main model from VRAM/RAM
            print("Unloading main analyzer model (Qwen) from server memory...")
            try:
                self.client.generate(model=self.model_name, prompt="", keep_alive=0)
            except Exception as e:
                print(f"Warning: Failed to unload main model: {e}")
        else:
            print("Pass 1: No articles require English enrichment in the specified range.")
            
        # --- PASS 2: Turkish Translation (TranslateGemma Model - Term Preservation) ---
        cursor.execute(f"""
            SELECT e.article_id, a.title, e.summary, e.sft_qa, e.dpo_pairs, e.turkish_summary
            FROM enrichments e
            JOIN articles a ON e.article_id = a.id
            WHERE (e.tr_sft_qa IS NULL OR e.tr_sft_qa = '' OR e.turkish_summary IS NULL OR e.turkish_summary = '')
            AND e.article_id IN ({placeholders})
        """, active_ids)
        pass2_rows = cursor.fetchall()
        
        if pass2_rows:
            print(f"\nPass 2: Found {len(pass2_rows)} articles awaiting Turkish translation with TranslateGemma in range [{start}:{end if end is not None else len(all_ids)}].")
            count2 = 0
            for row in pass2_rows:
                article_id, title, summary, sft_qa_raw, dpo_pairs_raw, existing_tr_summary = row
                if not summary or summary == "Summary unavailable.":
                    continue
                    
                try:
                    tr_res = self.translate_enrichments_to_turkish(title, summary, sft_qa_raw, dpo_pairs_raw)
                    
                    target_tr_summary = existing_tr_summary if existing_tr_summary else tr_res["turkish_summary"]
                    
                    cursor.execute("""
                        UPDATE enrichments
                        SET turkish_title = ?, turkish_summary = ?, tr_sft_qa = ?, tr_dpo_pairs = ?
                        WHERE article_id = ?
                    """, (
                        tr_res["turkish_title"],
                        target_tr_summary,
                        tr_res["tr_sft_qa"],
                        tr_res["tr_dpo_pairs"],
                        article_id
                    ))
                    self.conn.commit()
                    count2 += 1
                except Exception as e:
                    print(f"Error in Pass 2 for article {article_id}: {e}")
                    self.conn.rollback()
                    
            print(f"Pass 2 complete. Translated {count2} articles (titles, summaries, 10 Q&A pairs, DPO) into Turkish using TranslateGemma.")
            
            # Unload TranslateGemma model from VRAM/RAM
            print("Unloading translation model (TranslateGemma) from server memory...")
            try:
                self.client.generate(model=self.translator_model, prompt="", keep_alive=0)
            except Exception as e:
                print(f"Warning: Failed to unload translation model: {e}")
        else:
            print("Pass 2: No articles require translation.")
            
        print("All enrichment steps completed successfully.")

    def close(self):
        self.conn.close()

if __name__ == "__main__":
    analyzer = ArchiveAnalyzer()
    analyzer.enrich_all(limit=2)
    analyzer.close()
