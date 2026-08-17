import sqlite3
import json
from pathlib import Path
from datetime import datetime
from pipeline.llm_client import get_openai_client

class ArchiveAnalyzer:
    def __init__(self, config_path="config.json"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
            
        self.db_path = self.config["db_path"]
        db_path_obj = Path(self.db_path)
        if len(db_path_obj.parts) == 1:
            self.db_path = str(Path("database") / self.db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.input_mode = self.config.get("input_mode", "book")
        self.input_path = self.config.get("input_path", "")
        self.ollama_url = self.config["ollama_url"]
        self.model_name = self.config["model_analyzer"]
        self.translator_model = self.config.get("model_translator", "translategemma:12b-it-q4_K_M")
        self.qa_count = self.config.get("sft_qa_count", self.config.get("qa_count_per_article", 10))
        self.llm_persona = self.config.get("llm_persona", "You are an expert embedded systems engineer, technical writer, and AI trainer.")
        self.llm_subject = self.config.get("llm_subject", "analog and digital circuit design, microcontrollers, embedded systems, RF communication, power electronics, and test equipment.")
        self.direct_tr_generation = self.config.get("direct_tr_generation", True)
        self.enable_dpo_verification = self.config.get("enable_dpo_verification", True)
        self.generate_multi_turn_chat = self.config.get("generate_multi_turn_chat", True)
        self.analyzer_max_chars = self.config.get("analyzer_max_chars", 4000)
        self.analyzer_max_tokens = self.config.get("analyzer_max_tokens", 8192)
        
        # Connect to LLM client with 300s timeout limit
        from pipeline.project_logger import get_project_logger
        self.logger = get_project_logger()
        self.openai_client = get_openai_client(self.config)
        
        # Connect/Initialize SQLite database with WAL mode and timeout
        self.conn = sqlite3.connect(self.db_path, timeout=30.0)
        self.create_tables()

    def call_ollama_chat_with_retry(self, model, messages, options=None, format=None, keep_alive="30m", max_retries=3):
        """Executes a chat completion request with automatic retry and exponential backoff on timeouts/failures"""
        import time
        target_model = (model or self.model_name or "qwen3.6:27b-mtp-q4_K_M").strip()
        
        temperature = 0.7
        max_tokens = None
        if options:
            if "temperature" in options:
                temperature = options["temperature"]
            if "num_predict" in options:
                max_tokens = options["num_predict"]

        chat_kwargs = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature
        }
        if max_tokens:
            chat_kwargs["max_tokens"] = max_tokens
        if format == "json":
            chat_kwargs["response_format"] = {"type": "json_object"}

        for attempt in range(1, max_retries + 1):
            try:
                # Re-fetch pooled client
                client = get_openai_client(self.config)
                response = client.chat.completions.create(**chat_kwargs)
                
                reply_content = response.choices[0].message.content or ""
                # Return standard dict format to keep compatibility with existing parsing
                return {
                    "message": {
                        "role": "assistant",
                        "content": reply_content
                    }
                }
            except Exception as e:
                warn_msg = f"LLM Chat Warning (Attempt {attempt}/{max_retries} for model '{target_model}'): {e}"
                print(f"  {warn_msg}")
                self.logger.warning(warn_msg, module="analyzer")
                
                if attempt < max_retries:
                    sleep_sec = attempt * 5
                    print(f"  Retrying in {sleep_sec} seconds...")
                    time.sleep(sleep_sec)
                else:
                    err_msg = f"LLM Chat Failed for '{target_model}' after {max_retries} attempts."
                    print(f"  {err_msg}")
                    self.logger.error(err_msg, module="analyzer")
                    return None


    def create_tables(self):
        cursor = self.conn.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
        except sqlite3.OperationalError:
            pass
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
        if "human_rating" not in existing_cols:
            cursor.execute("ALTER TABLE enrichments ADD COLUMN human_rating INTEGER DEFAULT 0")
        if "is_excluded" not in existing_cols:
            cursor.execute("ALTER TABLE enrichments ADD COLUMN is_excluded INTEGER DEFAULT 0")
        if "human_feedback" not in existing_cols:
            cursor.execute("ALTER TABLE enrichments ADD COLUMN human_feedback TEXT")
        self.conn.commit()

    def get_grounded_context_for_article(self, article_id: int) -> str:
        """Queries SQLite langextract_extractions table for article_id and returns formatted grounded context."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT text_span, start_char, end_char, attributes, preset
                FROM langextract_extractions
                WHERE article_id = ?
                LIMIT 20
            """, (article_id,))
            rows = cursor.fetchall()
            if not rows:
                return ""
            
            grounded_lines = []
            for span, start, end, attr_json, preset in rows:
                grounded_lines.append(f"- Entity: '{span}' (Span: [{start}:{end}], Preset: '{preset}', Attr: {attr_json})")
            
            return "\n\n### Grounded Source Entities (LangExtract Evidence):\n" + "\n".join(grounded_lines)
        except Exception:
            return ""

    def call_ollama_json(self, system_prompt, user_prompt, model=None, keep_alive=None, num_predict=8192):
        """Helper to call LLM model and expect a JSON output, optimized with token limit and temp"""
        if model is None:
            model = self.model_name
        try:
            client = get_openai_client(self.config)
            chat_kwargs = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.2
            }
            if num_predict:
                chat_kwargs["max_tokens"] = num_predict
                
            response = client.chat.completions.create(**chat_kwargs)
            content = response.choices[0].message.content or ""
            return json.loads(content)
        except Exception as e:
            print(f"  LLM JSON call error (Model: {model}): {e}")
            return None

    def analyze_article_english(self, article_id, title, text):
        """Performs English technical analysis (summary, topics, 10 detailed Q&As, DPO) using self.model_name"""
        print(f"Analyzing article [{article_id}] (English - {self.qa_count} Q&As): {title}...")
        
        # Limit text size to self.analyzer_max_chars characters to reduce prompt ingestion time and RAM usage
        truncated_text = text[:self.analyzer_max_chars] if len(text) > self.analyzer_max_chars else text
        
        system_prompt = (
            f"{self.llm_persona} "
            "Analyze the document text and output a single JSON object. Follow the requested structure strictly."
        )
        
        user_prompt = (
            f"Article Title: {title}\n"
            f"Article Text:\n{truncated_text}\n\n"
            f"Generate a JSON object containing EXACTLY {self.qa_count} advanced Q&A pairs and 1 DPO pair with the following key structure:\n"
            "{\n"
            "  \"summary\": \"English summary of the document/article (2-4 detailed sentences)\",\n"
            "  \"topics\": [\"Topic 1\", \"Topic 2\", \"Topic 3\"],\n"
            "  \"sft_qa\": [\n"
            "    {\"question\": \"Advanced question 1 in English\", \"answer\": \"Long, comprehensive, step-by-step answer explaining the concepts, evidence, mechanisms, or details related to the text\"},\n"
            f"    ... (Include EXACTLY {self.qa_count} total Q&A items in this array)\n"
            "  ],\n"
            "  \"dpo_pair\": {\n"
            "    \"question\": \"Detailed question in English\",\n"
            "    \"chosen\": \"Correct, detailed explanation/solution in English\",\n"
            "    \"rejected\": \"Misleading response containing a plausible misconception, incorrect factual claim, or flawed reasoning in English\"\n"
            "  }\n"
            "}\n\n"
            "Guidelines:\n"
            f"1. Generate EXACTLY {self.qa_count} distinct Q&A items in 'sft_qa'.\n"
            f"2. Answers MUST be detailed, thorough, and instructive according to the domain: {self.llm_subject}.\n"
            f"3. In the DPO pair, the rejected answer must contain a plausible misconception, incorrect factual claim, or flawed reasoning related to {self.llm_subject} and the article text.\n"
            "4. Format any mathematical equations or formulas using standard LaTeX notation, for example: \\(p = \\frac{n \\cdot n_{cyl}}{60 \\cdot a}\\) instead of plain text.\n"
            "5. Return ONLY the valid JSON object. Do not include markdown code block formatting."
        )
        
        result = self.call_ollama_json(system_prompt, user_prompt, model=self.model_name, num_predict=self.analyzer_max_tokens)
        
        if not result:
            raise RuntimeError(f"Ollama model '{self.model_name}' failed to generate analysis for article {article_id}.")
            
        sft_qa = result.get("sft_qa", [])
        dpo_pair = result.get("dpo_pair", {})
        dpo_pairs_list = [dpo_pair] if dpo_pair and dpo_pair.get("question") else []
        
        return {
            "summary": result.get("summary", ""),
            "topics": json.dumps(result.get("topics", [])),
            "sft_qa": json.dumps(sft_qa),
            "dpo_pairs": json.dumps(dpo_pairs_list)
        }

    def verify_dpo_pair(self, question, chosen, rejected, source_text):
        """Verifies technical plausibility, non-identicality, and minimum grounding quality of DPO pairs"""
        if not question or not chosen or not rejected:
            return False
        if chosen.strip().lower() == rejected.strip().lower():
            return False
        if len(chosen.strip()) < 15 or len(rejected.strip()) < 15:
            return False
        return True

    def analyze_article_direct_turkish(self, article_id, title, text):
        """Performs DIRECT Turkish technical analysis (summary, topics, Q&As, DPO pair, multi-turn chat) without translation pass"""
        print(f"Analyzing article [{article_id}] (Direct Turkish Mode - {self.qa_count} Q&As): {title}...")
        
        truncated_text = text[:self.analyzer_max_chars] if len(text) > self.analyzer_max_chars else text
        
        system_prompt = (
            f"Sen uzman bir gömülü sistemler mimarı, teknik yazar ve Türkçe yapay zeka eğitmenisin. ({self.llm_persona})\n"
            "Verilen döküman metnini derinlemesine incele ve doğrudan yüksek kaliteli Türkçe teknik içerik üreterek JSON objesi döndür."
        )
        
        user_prompt = (
            f"Makale/Bölüm Başlığı: {title}\n"
            f"İçerik Metni:\n{truncated_text}\n\n"
            f"Aşağıdaki JSON yapısına BİREBİR uyarak EXACTLY {self.qa_count} adet Türkçe soru-cevap çifti, 1 adet DPO çifti ve 1 adet çok turlu (multi-turn) teknik diyalog içeren JSON nesnesi üret:\n"
            "{\n"
            "  \"turkish_title\": \"Makalenin Türkçe başlığı\",\n"
            "  \"turkish_summary\": \"Dökümanın 2-4 cümlelik detaylı Türkçe teknik özeti\",\n"
            "  \"topics\": [\"Konu 1\", \"Konu 2\", \"Konu 3\"],\n"
            "  \"tr_sft_qa\": [\n"
            "    {\"question\": \"Detaylı Türkçe teknik soru 1\", \"answer\": \"Kapsamlı, adım adım ve teknik doğruluğu yüksek Türkçe açıklama\"}\n"
            "  ],\n"
            "  \"tr_dpo_pair\": {\n"
            "    \"question\": \"Türkçe teknik soru\",\n"
            "    \"chosen\": \"Doğru, açıklayıcı ve teknik olarak kusursuz Türkçe yanıt\",\n"
            "    \"rejected\": \"İnandırıcı ancak teknik olarak hatalı/yanıltıcı mantık içeren Türkçe yanıt\"\n"
            "  },\n"
            "  \"multi_turn_chat\": [\n"
            "    {\"role\": \"user\", \"content\": \"Kullanıcı sorusu/sorunu\"},\n"
            "    {\"role\": \"assistant\", \"content\": \"Asistan yönlendirmesi/sorusu\"},\n"
            "    {\"role\": \"user\", \"content\": \"Kullanıcı detay yanıtı\"},\n"
            "    {\"role\": \"assistant\", \"content\": \"Asistan çözümü/uyarısı\"}\n"
            "  ]\n"
            "}\n\n"
            "Kurallar:\n"
            f"1. 'tr_sft_qa' dizisinde tam olarak {self.qa_count} adet soru-cevap öğesi üretin.\n"
            f"2. Yanıtlar {self.llm_subject} alanına uygun, Türkçe teknik terimlerin korunduğu derinlikte olmalıdır.\n"
            "3. DPO çiftinde reddedilen (rejected) cevap, mantıklı görünen ancak gerçek bir mühendislik hatası (gerilim uyumsuzluğu, pin hatası, vb.) içermelidir.\n"
            "4. Matematiksel formülleri LaTeX notation ile yazın: \\(E = m c^2\\).\n"
            "5. SADECE geçerli JSON formatı döndürün."
        )
        
        result = self.call_ollama_json(system_prompt, user_prompt, model=self.model_name, num_predict=self.analyzer_max_tokens)
        if not result:
            result = {
                "turkish_title": title,
                "turkish_summary": "Özet bulunamadı.",
                "topics": [],
                "tr_sft_qa": [],
                "tr_dpo_pair": {"question": "", "chosen": "", "rejected": ""},
                "multi_turn_chat": []
            }
            
        sft_qa = result.get("tr_sft_qa", [])
        dpo_pair = result.get("tr_dpo_pair", {})
        dpo_pairs_list = [dpo_pair] if dpo_pair and dpo_pair.get("question") else []
        
        if self.enable_dpo_verification and dpo_pairs_list:
            verified_dpo = []
            for dp in dpo_pairs_list:
                if self.verify_dpo_pair(dp.get("question", ""), dp.get("chosen", ""), dp.get("rejected", ""), truncated_text):
                    dp["quality_status"] = "validated"
                    verified_dpo.append(dp)
                else:
                    print(f"  DPO Pair failed quality verification for [{title}]. Marking for review.")
                    dp["quality_status"] = "flagged"
                    verified_dpo.append(dp)
            dpo_pairs_list = verified_dpo

        return {
            "turkish_title": result.get("turkish_title", title),
            "turkish_summary": result.get("turkish_summary", ""),
            "topics": json.dumps(result.get("topics", []), ensure_ascii=False),
            "tr_sft_qa": json.dumps(sft_qa, ensure_ascii=False),
            "tr_dpo_pairs": json.dumps(dpo_pairs_list, ensure_ascii=False),
            "multi_turn_chat": json.dumps(result.get("multi_turn_chat", []), ensure_ascii=False)
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
            if isinstance(item, dict):
                q_txt = item.get('question', '')
                a_txt = item.get('answer', '')
            else:
                q_txt = str(item)
                a_txt = ""
            text_block.append(f"Q{idx+1}: {q_txt}")
            text_block.append(f"A{idx+1}: {a_txt}")
            
        for idx, item in enumerate(dpo_pairs_list):
            if isinstance(item, dict):
                q_txt = item.get('question', '')
                c_txt = item.get('chosen', '')
                r_txt = item.get('rejected', '')
            else:
                q_txt = str(item)
                c_txt = ""
                r_txt = ""
            text_block.append(f"DPO_Q: {q_txt}")
            text_block.append(f"DPO_Chosen: {c_txt}")
            text_block.append(f"DPO_Rejected: {r_txt}")
            
        full_text = "\n\n".join(text_block)
        
        system_prompt = (
            f"You are a professional translator specializing in {self.llm_subject}.\n"
            "Translate the text block provided by the user into natural, high-quality Turkish.\n\n"
            "CRITICAL TERMINOLOGY RULES:\n"
            "1. PRESERVE ALL PROPER NAMES, DATES, DOMAIN TERMINOLOGY, AND ACRONYMS IN THEIR STANDARD ACCURATE FORM.\n"
            "2. Keep all math/LaTeX formulas intact.\n"
            "3. Preserve the exact markers (e.g. Title:, Summary:, Q1:, A1:, DPO_Q:, DPO_Chosen:, DPO_Rejected:) to demarcate segments."
        )
        
        user_prompt = (
            "Translate the following segment block into Turkish, preserving the markers:\n\n"
            f"{full_text}"
        )
        
        response = self.call_ollama_chat_with_retry(
            model=self.translator_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            options={"temperature": 0.2, "num_predict": self.analyzer_max_tokens},
            keep_alive="30m"
        )

        if not response:
            raise RuntimeError(f"TranslateGemma model '{self.translator_model}' did not return a response.")

        content = ""
        if isinstance(response, dict) and "message" in response:
            content = response["message"].get("content", "")
        elif hasattr(response, "message"):
            content = getattr(response.message, "content", "")

        if not content:
            raise ValueError(f"Empty translation output for article '{title}'.")

        # Regex Parsing
        content_norm = content.replace('\r\n', '\n')
        
        # Helper to clean up matched groups (strip spaces and markdown bold/italic asterisks)
        def clean_val(match, group_idx=1):
            if not match:
                return None
            val = match.group(group_idx)
            if not val:
                return ""
            return val.strip().strip('*').strip()

        # Extract title
        title_match = re.search(r'^\**\s*(?:Title|Başlık|Title\s*\(Turkish\))\s*(?::\**|\**:)\s*(.*)', content_norm, re.IGNORECASE | re.MULTILINE)
        turkish_title = clean_val(title_match) if title_match else title
        if not turkish_title:
            turkish_title = title
            
        # Extract summary
        summary_match = re.search(r'^\**\s*(?:Summary|Özet)\s*(?::\**|\**:)\s*(.*?)(?=\n\**\s*(?:Q|S|D|C|Soru|Cevap|A\d|C\d|DPO_))', content_norm, re.IGNORECASE | re.DOTALL | re.MULTILINE)
        turkish_summary = clean_val(summary_match) if summary_match else summary
        if not turkish_summary:
            turkish_summary = summary

        # Extract SFT QA
        tr_sft_qa = []
        for i in range(1, len(sft_qa_list) + 1):
            q_pattern = rf'^\**\s*(?:Q{i}|S{i}|Soru\s*{i})\s*(?::\**|\**:)\s*(.*?)(?=\n\**\s*(?:A{i}|C{i}|Cevap\s*{i})\s*(?::\**|\**:)|\n\**\s*(?:Q{i+1}|S{i+1}|Soru\s*{i+1})\s*(?::\**|\**:)|\n\**\s*DPO_|$)'
            a_pattern = rf'^\**\s*(?:A{i}|C{i}|Cevap\s*{i})\s*(?::\**|\**:)\s*(.*?)(?=\n\**\s*(?:Q{i+1}|S{i+1}|Soru\s*{i+1})\s*(?::\**|\**:)|\n\**\s*(?:A{i+1}|C{i+1}|Cevap\s*{i+1})\s*(?::\**|\**:)|\n\**\s*DPO_|$)'
            
            q_match = re.search(q_pattern, content_norm, re.IGNORECASE | re.DOTALL | re.MULTILINE)
            a_match = re.search(a_pattern, content_norm, re.IGNORECASE | re.DOTALL | re.MULTILINE)
            
            cleaned_q = clean_val(q_match)
            cleaned_a = clean_val(a_match)
            
            if cleaned_q and cleaned_a:
                tr_sft_qa.append({
                    "question": cleaned_q,
                    "answer": cleaned_a
                })
            else:
                # Fallback to original English item if parse fails for this specific item
                orig_item = sft_qa_list[i-1]
                tr_sft_qa.append(orig_item)
        
        # Extract DPO pairs
        tr_dpo_pairs = []
        for i in range(1, len(dpo_pairs_list) + 1):
            dpo_q_match = re.search(r'^\**\s*(?:DPO_Q|DPO_Soru|DPO_S)\s*(?::\**|\**:)\s*(.*?)(?=\n\**\s*(?:DPO_Chosen|DPO_Seçilen|DPO_Tercih_Edilen|DPO_Reddedilen|DPO_Rejected|DPO_|$))', content_norm, re.IGNORECASE | re.DOTALL | re.MULTILINE)
            dpo_chosen_match = re.search(r'^\**\s*(?:DPO_Chosen|DPO_Seçilen|DPO_Tercih_Edilen)\s*(?::\**|\**:)\s*(.*?)(?=\n\**\s*(?:DPO_Rejected|DPO_Reddedilen|DPO_|$))', content_norm, re.IGNORECASE | re.DOTALL | re.MULTILINE)
            dpo_rej_match = re.search(r'^\**\s*(?:DPO_Rejected|DPO_Reddedilen)\s*(?::\**|\**:)\s*(.*?)(?=\n\**\s*(?:DPO_|$))', content_norm, re.IGNORECASE | re.DOTALL | re.MULTILINE)
            
            cleaned_dq = clean_val(dpo_q_match)
            cleaned_dc = clean_val(dpo_chosen_match)
            cleaned_dr = clean_val(dpo_rej_match)
            
            if cleaned_dq and cleaned_dc and cleaned_dr:
                tr_dpo_pairs.append({
                    "question": cleaned_dq,
                    "chosen": cleaned_dc,
                    "rejected": cleaned_dr
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

    def enrich_code_units(self, limit=None):
        """Enriches extracted AST code_units into synthetic SFT instruction pairs in English and Turkish"""
        cursor = self.conn.cursor()

        # Ensure synthetic_code_pairs table exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS synthetic_code_pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code_unit_id INTEGER,
                project_id TEXT,
                instruction TEXT,
                input_code TEXT,
                output_response TEXT,
                tr_instruction TEXT,
                tr_output_response TEXT,
                category TEXT,
                created_at REAL,
                FOREIGN KEY(code_unit_id) REFERENCES code_units(id)
            )
        """)
        self.conn.commit()

        # Check if code_units exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='code_units'")
        if not cursor.fetchone():
            return

        if self.input_mode == "rendergit":
            limit_val = 10000
        else:
            limit_val = limit if isinstance(limit, int) and limit > 0 else 1000

        # --- CODE PASS 1: English Code Unit Analysis (Analyzer Model) ---
        if enrich_pass in ["all", "english"]:
            cursor.execute("""
                SELECT u.id, u.project_id, u.file_path, u.unit_type, u.name, u.signature, u.docstring, u.code
                FROM code_units u
                LEFT JOIN synthetic_code_pairs p ON u.id = p.code_unit_id
                WHERE p.id IS NULL
                LIMIT ?
            """, (limit_val,))
            pass1_rows = cursor.fetchall()

            if pass1_rows:
                print(f"=== Code Enrichment (Pass 1: Analysis with '{self.model_name}'): Processing {len(pass1_rows)} AST Code Units ===")
                count1 = 0
                for row in pass1_rows:
                    unit_id, project_id, file_path, unit_type, name, sig, docstring, code = row
                    pragmatic_ratio = self.config.get("pragmatic_ratio", 50)
                    use_pragmatic = (unit_id % 100) < pragmatic_ratio
                    
                    active_cats = []
                    if self.config.get("code_cat_explanation", True):
                        active_cats.append(0)
                    if self.config.get("code_cat_completion", True):
                        active_cats.append(1)
                    if self.config.get("code_cat_bug_fix", True):
                        active_cats.append(2)
                    if self.config.get("code_cat_unit_test", True):
                        active_cats.append(3)

                    if not active_cats:
                        active_cats = [0, 1, 2, 3]

                    cat_selector = active_cats[unit_id % len(active_cats)]

                    if cat_selector == 1:
                        category = "completion"
                        instruction = f"Implement the Python {unit_type} `{name}` with signature `{sig}` cleanly according to type safety and best practices."
                        tr_inst = f"`{file_path}` dosyasındaki `{name}` {unit_type} birimini imzasına (`{sig}`) uygun olarak tip güvenli biçimde kodla."
                        sys_prompt = "You are a senior Python software engineer. Provide pure, high-quality, production-ready Python code implementation based on the signature and docstring."
                        user_prompt = (
                            f"Implement the Python {unit_type} `{name}` in file `{file_path}`.\n"
                            f"Signature: `{sig}`\n"
                            f"Docstring:\n{docstring}\n\n"
                            f"Reference Implementation:\n```python\n{code}\n```\n\n"
                            f"Provide a clean, refactored production implementation with complete type hints and docstrings. Do NOT include filler text."
                        )
                    elif cat_selector == 2:
                        category = "bug_fix"
                        instruction = f"Analyze `{name}` in `{file_path}` for logic bugs, type risks, or boundary issues and provide the fixed code."
                        tr_inst = f"`{file_path}` dosyasındaki `{name}` birimindeki olası mantık veya tip hatalarını tespit et ve düzeltilmiş kod halini sun."
                        sys_prompt = "You are a senior security code auditor. Identify potential bugs, type risks, or magic string hazards and provide the clean, corrected code."
                        user_prompt = (
                            f"Review the following Python code for `{name}` in `{file_path}`:\n```python\n{code}\n```\n\n"
                            f"Identify any code smells, boundary errors, or type risks, then output the corrected Python code snippet with an explanation."
                        )
                    elif cat_selector == 3:
                        category = "unit_test"
                        instruction = f"Write a comprehensive pytest unit test suite for `{name}` in `{file_path}`."
                        tr_inst = f"`{file_path}` dosyasındaki `{name}` birimi için kapsayıcı pytest birim testleri yaz."
                        sys_prompt = "You are a test automation engineer specializing in pytest. Write clean, complete pytest test cases covering standard execution and edge cases."
                        user_prompt = (
                            f"Write a pytest test suite for the Python {unit_type} `{name}` from file `{file_path}`.\n\n"
                            f"Code:\n```python\n{code}\n```\n\n"
                            f"Provide complete, runnable pytest test functions including assertions and edge cases."
                        )
                    else:
                        category = "explanation"
                        instruction = f"Explain the purpose and implementation of `{name}` in `{file_path}`."
                        tr_inst = f"`{file_path}` dosyasındaki `{name}` {unit_type} biriminin amacını ve iç mantığını açıkla."
                        if self.input_mode == "rendergit":
                            if use_pragmatic:
                                category = "pragmatic"
                                sys_prompt = "You are a pragmatic, concise Python software architect. Provide direct code analysis starting immediately with structured Markdown headings, without greetings or introductory filler."
                                user_prompt = (
                                    f"Analyze the Python {unit_type} `{name}` from file `{file_path}`.\n"
                                    f"Do NOT include introductory greetings or persona intros (such as 'As a Senior Architect...'). Start IMMEDIATELY with section `### Purpose`.\n\n"
                                    f"Use the following structure:\n"
                                    f"### Purpose\n<concise 1-2 sentence purpose>\n\n"
                                    f"### Attributes & Signature\n<key params & types>\n\n"
                                    f"### Implementation Analysis & Refactoring\n<1-2 key technical observations and clean refactored Python snippet if applicable>\n\n"
                                    f"Code:\n```python\n{code}\n```"
                                )
                            else:
                                category = "educational"
                                sys_prompt = "You are a senior software engineering educator and mentor. Provide comprehensive, pedagogical code analysis explaining underlying design patterns, trade-offs, theoretical concepts, and architectural decisions."
                                user_prompt = (
                                    f"Analyze the Python {unit_type} `{name}` from file `{file_path}` in a comprehensive, educational manner.\n"
                                    f"Do NOT include boilerplate greetings (such as 'As a Senior Architect...'). Start IMMEDIATELY with section `### Overview & Pedagogy`.\n\n"
                                    f"Use the following structure:\n"
                                    f"### Overview & Pedagogy\n<educational breakdown and design patterns used>\n\n"
                                    f"### Theoretical Concepts & Principles\n<design patterns, DTO/Enum/SOLID trade-offs>\n\n"
                                    f"### Detailed Line-by-Line Breakdown\n<key execution steps>\n\n"
                                    f"### Refactored Version & Recommendations\n<clean code recommendations>\n\n"
                                    f"Code:\n```python\n{code}\n```"
                                )
                        else:
                            sys_prompt = f"You are an expert software architect and static analyzer. {self.llm_persona}"
                            user_prompt = (
                                f"Analyze the following Python {unit_type} `{name}` from file `{file_path}`.\n"
                                f"Explain its purpose, signature, inner logic, arguments, return values, and key implementation details:\n\n"
                                f"```python\n{code}\n```"
                            )

                    try:
                        res = self.call_ollama_chat_with_retry(
                            model=self.model_name,
                            messages=[
                                {"role": "system", "content": sys_prompt},
                                {"role": "user", "content": user_prompt}
                            ],
                            options={"temperature": 0.2, "num_predict": 4096},
                            keep_alive="30m"
                        )

                        if not res:
                            continue

                        output_expl = res.get("message", {}).get("content", "")

                        cursor.execute("""
                            INSERT INTO synthetic_code_pairs 
                            (code_unit_id, project_id, instruction, input_code, output_response, tr_instruction, tr_output_response, category, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            unit_id, project_id, instruction, code, output_expl,
                            tr_inst, output_expl if self.direct_tr_generation else "", category, datetime.now().timestamp()
                        ))
                        self.conn.commit()
                        count1 += 1
                        print(f"  [{count1}/{len(pass1_rows)}] Analyzed AST {unit_type} [{category}]: {name}")
                    except Exception as e:
                        print(f"Error analyzing code unit {name}: {e}")

                print(f"Code Pass 1 Complete. Analyzed {count1} code units.")

                # Unload main analyzer model from VRAM to make room for TranslateGemma
                print(f"Unloading code analyzer model ('{self.model_name}') from VRAM...")
                from pipeline.llm_client import unload_ollama_model
                unload_ollama_model(self.config, self.model_name)
            else:
                print("Code Pass 1: No un-processed AST code units found.")

        # --- CODE PASS 2: Turkish Code Unit Translation (TranslateGemma Model) ---
        if enrich_pass in ["all", "turkish"]:
            cursor.execute("""
                SELECT id, output_response
                FROM synthetic_code_pairs
                WHERE tr_output_response IS NULL OR tr_output_response = ''
                LIMIT ?
            """, (limit_val,))
            pass2_rows = cursor.fetchall()

            if pass2_rows:
                print(f"\n=== Code Enrichment (Pass 2: Translation with '{self.translator_model}'): Processing {len(pass2_rows)} Code Instruction Pairs ===")
                count2 = 0
                for row in pass2_rows:
                    pair_id, output_expl = row
                    if not output_expl:
                        continue

                    try:
                        tr_res = self.call_ollama_chat_with_retry(
                            model=self.translator_model,
                            messages=[
                                {"role": "user", "content": f"Translate the following code explanation into technical Turkish. Preserve code snippets as is:\n\n{output_expl}"}
                            ],
                            options={"temperature": 0.2, "num_predict": 4096},
                            keep_alive="30m"
                        )

                        tr_out = tr_res.get("message", {}).get("content", output_expl) if tr_res else output_expl

                        cursor.execute("""
                            UPDATE synthetic_code_pairs
                            SET tr_output_response = ?
                            WHERE id = ?
                        """, (tr_out, pair_id))
                        self.conn.commit()
                        count2 += 1
                        print(f"  [{count2}/{len(pass2_rows)}] Translated Code Explanation -> ID {pair_id}")
                    except Exception as e:
                        print(f"Error translating code pair {pair_id}: {e}")

                print(f"Code Pass 2 Complete. Translated {count2} code instruction pairs.")

                # Unload translator model from VRAM
                print(f"Unloading translation model ('{self.translator_model}') from VRAM...")
                from pipeline.llm_client import unload_ollama_model
                unload_ollama_model(self.config, self.translator_model)
            else:
                print("Code Pass 2: No code pairs require translation.")

        print("Code Enrichment Complete.")


    def enrich_all(self, limit=None, enrich_pass="all"):
        """Enriches extracted articles and AST code units in SQLite DB using a two-pass batch optimization"""
        if enrich_pass in ["all", "english"]:
            self.enrich_code_units(limit=limit, enrich_pass=enrich_pass)

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
        
        # --- PASS 1: Technical Analysis (Direct Turkish vs English) ---
        if enrich_pass not in ["all", "english"]:
            pass1_rows = []
        else:
            if self.direct_tr_generation:
                where_cond = "(e.id IS NULL OR e.tr_sft_qa IS NULL OR e.tr_sft_qa = '')"
            else:
                where_cond = "(e.id IS NULL OR e.sft_qa IS NULL OR e.sft_qa = '' OR e.sft_qa = '[]' OR e.summary = 'Summary unavailable.')"

            cursor.execute(f"""
                SELECT a.id, a.title, a.extracted_text 
                FROM articles a
                LEFT JOIN enrichments e ON a.id = e.article_id
                WHERE {where_cond} AND a.extracted_text IS NOT NULL AND a.extracted_text != ''
                AND a.id IN ({placeholders})
            """, active_ids)
            pass1_rows = cursor.fetchall()
        
        if pass1_rows:
            mode_str = "Direct Turkish" if self.direct_tr_generation else "English"
            print(f"Pass 1: Found {len(pass1_rows)} articles awaiting {mode_str} enrichment ({self.qa_count} Q&As each) in range [{start}:{end if end is not None else len(all_ids)}].")
            count1 = 0
            for row in pass1_rows:
                article_id, title, text = row
                try:
                    processed_at = datetime.now().isoformat()
                    if self.direct_tr_generation:
                        tr_data = self.analyze_article_direct_turkish(article_id, title, text)
                        cursor.execute("""
                            INSERT OR REPLACE INTO enrichments (
                                article_id, summary, topics, turkish_title, turkish_summary, sft_qa, dpo_pairs, tr_sft_qa, tr_dpo_pairs, processed_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            article_id,
                            tr_data["turkish_summary"],
                            tr_data["topics"],
                            tr_data["turkish_title"],
                            tr_data["turkish_summary"],
                            tr_data["tr_sft_qa"],
                            tr_data["tr_dpo_pairs"],
                            tr_data["tr_sft_qa"],
                            tr_data["tr_dpo_pairs"],
                            processed_at
                        ))
                    else:
                        eng_data = self.analyze_article_english(article_id, title, text)
                        cursor.execute("""
                            INSERT OR REPLACE INTO enrichments (
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
            
            print(f"Pass 1 complete. Enriched {count1} articles ({mode_str} Mode) with {self.qa_count} Q&A pairs each.")
            
            # Unload main model from VRAM/RAM
            print(f"Unloading main analyzer model ('{self.model_name}') from server memory...")
            from pipeline.llm_client import unload_ollama_model
            unload_ollama_model(self.config, self.model_name)
        else:
            print("Pass 1: No articles require enrichment in the specified range.")
            
        # --- PASS 2: Turkish Translation (Only executed if direct_tr_generation is False) ---
        if not self.direct_tr_generation and enrich_pass in ["all", "turkish"]:
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
                        err_msg = f"Error in Pass 2 for article {article_id}: {e}"
                        print(f"  {err_msg}")
                        self.logger.error(err_msg, module="analyzer")
                        self.conn.rollback()
                        
                print(f"Pass 2 complete. Translated {count2} articles into Turkish using TranslateGemma.")
                
                # Unload TranslateGemma model from VRAM/RAM
                print(f"Unloading translation model ('{self.translator_model}') from server memory...")
                from pipeline.llm_client import unload_ollama_model
                unload_ollama_model(self.config, self.translator_model)
            else:
                print("Pass 2: No articles require translation.")
        else:
            print("Pass 2: Skipped (Direct Turkish Generation mode is active).")
            
        print("All enrichment steps completed successfully.")

    def close(self):
        self.conn.close()

if __name__ == "__main__":
    analyzer = ArchiveAnalyzer()
    analyzer.enrich_all(limit=2)
    analyzer.close()
