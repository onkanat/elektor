import sqlite3
import json
import ollama
from pathlib import Path
from datetime import datetime

class ArchiveAnalyzer:
    def __init__(self, config_path="config.json"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
            
        self.db_path = self.config["db_path"]
        db_path_obj = Path(self.db_path)
        if len(db_path_obj.parts) == 1:
            self.db_path = str(Path("database") / self.db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.ollama_url = self.config["ollama_url"]
        self.model_name = self.config["model_analyzer"]
        self.translator_model = self.config.get("model_translator", "translategemma:12b-it-q4_K_M")
        self.qa_count = self.config.get("sft_qa_count", self.config.get("qa_count_per_article", 10))
        self.llm_persona = self.config.get("llm_persona", "You are an expert embedded systems engineer, technical writer, and AI trainer.")
        self.llm_subject = self.config.get("llm_subject", "analog and digital circuit design, microcontrollers, embedded systems, RF communication, power electronics, and test equipment.")
        
        # Connect to Ollama with 300s timeout for 35B models
        self.client = ollama.Client(host=self.ollama_url, timeout=300.0)
        
        # Connect/Initialize SQLite database with WAL mode and timeout
        self.conn = sqlite3.connect(self.db_path, timeout=30.0)
        self.create_tables()

    def call_ollama_chat_with_retry(self, model, messages, options=None, format=None, keep_alive="30m", max_retries=3):
        """Executes an Ollama chat request with automatic retry and exponential backoff on timeouts/failures"""
        import time
        chat_kwargs = {
            "model": model,
            "messages": messages,
            "keep_alive": keep_alive
        }
        if options:
            chat_kwargs["options"] = options
        if format:
            chat_kwargs["format"] = format

        for attempt in range(1, max_retries + 1):
            try:
                response = self.client.chat(**chat_kwargs)
                return response
            except Exception as e:
                print(f"  Ollama Chat Warning (Attempt {attempt}/{max_retries} for model '{model}'): {e}")
                if attempt < max_retries:
                    sleep_sec = attempt * 5
                    print(f"  Retrying in {sleep_sec} seconds...")
                    time.sleep(sleep_sec)
                else:
                    print(f"  Ollama Chat Failed for '{model}' after {max_retries} attempts.")
                    return None


    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
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

        limit_val = limit if isinstance(limit, int) and limit > 0 else 50

        # --- CODE PASS 1: English Code Unit Analysis (Analyzer Model) ---
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
                    category = "explanation"
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
                    tr_inst = f"`{file_path}` dosyasındaki `{name}` {unit_type} biriminin amacını ve iç mantığını açıkla."
                    instruction = f"Explain the purpose and implementation of `{name}` in `{file_path}`."

                    cursor.execute("""
                        INSERT INTO synthetic_code_pairs 
                        (code_unit_id, project_id, instruction, input_code, output_response, tr_instruction, tr_output_response, category, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        unit_id, project_id, instruction, code, output_expl,
                        tr_inst, "", category, datetime.now().timestamp()
                    ))
                    self.conn.commit()
                    count1 += 1
                    print(f"  [{count1}/{len(pass1_rows)}] Analyzed AST {unit_type}: {name}")
                except Exception as e:
                    print(f"Error analyzing code unit {name}: {e}")

            print(f"Code Pass 1 Complete. Analyzed {count1} code units.")

            # Unload main analyzer model from VRAM to make room for TranslateGemma
            print(f"Unloading code analyzer model ('{self.model_name}') from VRAM...")
            try:
                self.client.generate(model=self.model_name, prompt="", keep_alive=0)
            except Exception as e:
                print(f"Warning: Failed to unload code analyzer model: {e}")
        else:
            print("Code Pass 1: No un-processed AST code units found.")

        # --- CODE PASS 2: Turkish Code Unit Translation (TranslateGemma Model) ---
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
            try:
                self.client.generate(model=self.translator_model, prompt="", keep_alive=0)
            except Exception as e:
                print(f"Warning: Failed to unload code translator model: {e}")
        else:
            print("Code Pass 2: No code pairs require translation.")

        print("Code Enrichment Complete.")


    def enrich_all(self, limit=None):
        """Enriches extracted articles and AST code units in SQLite DB using a two-pass batch optimization"""
        self.enrich_code_units(limit=limit)

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
