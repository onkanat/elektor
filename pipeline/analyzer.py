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
        
        # Connect to Ollama
        self.client = ollama.Client(host=self.ollama_url)
        
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
                processed_at TEXT,
                FOREIGN KEY (article_id) REFERENCES articles(id)
            )
        """)
        self.conn.commit()

    def call_ollama_json(self, system_prompt, user_prompt, model=None, keep_alive=None):
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
                    "num_predict": 2048  # Prevent infinite loops / excessively long generation
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
        """Performs English technical analysis (summary, topics, Q&A, DPO) using self.model_name"""
        print(f"Analyzing article [{article_id}] (English): {title}...")
        
        # Limit text size to 4000 characters to reduce prompt ingestion time and RAM usage
        truncated_text = text[:4000] if len(text) > 4000 else text
        
        system_prompt = (
            "You are an expert embedded systems engineer, technical writer, and AI trainer. "
            "Analyze the technical article text and output a single JSON object. Follow the requested structure strictly."
        )
        
        user_prompt = (
            f"Article Title: {title}\n"
            f"Article Text:\n{truncated_text}\n\n"
            "Generate a JSON object with the following keys:\n"
            "{\n"
            "  \"summary\": \"English summary of the project/article (2-3 sentences)\",\n"
            "  \"topics\": [\"Topic 1\", \"Topic 2\", \"Topic 3\"],\n"
            "  \"sft_qa\": [\n"
            "    {\"question\": \"Detailed technical question 1 in English\", \"answer\": \"Detailed correct answer 1 in English\"},\n"
            "    {\"question\": \"Detailed technical question 2 in English\", \"answer\": \"Detailed correct answer 2 in English\"},\n"
            "    {\"question\": \"Detailed technical question 3 in English\", \"answer\": \"Detailed correct answer 3 in English\"}\n"
            "  ],\n"
            "  \"dpo_pair\": {\n"
            "    \"question\": \"Detailed technical question in English\",\n"
            "    \"chosen\": \"Correct, detailed engineering explanation/solution in English\",\n"
            "    \"rejected\": \"Misleading response containing a common hardware design error, bad layout practice, or incorrect calculation in English\"\n"
            "  }\n"
            "}\n\n"
            "Guidelines:\n"
            "1. In the DPO pair, the rejected answer must contain a realistic engineering mistake (e.g. swapping TX/RX, omitting pullups, missing decoupling capacitors, wrong pin definitions) related to the article.\n"
            "2. Return ONLY the JSON object. Do not include markdown code block formatting."
        )
        
        result = self.call_ollama_json(system_prompt, user_prompt, model=self.model_name)
        
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

    def translate_to_turkish(self, title, summary):
        """Translates the title and summary into Turkish using translategemma model"""
        system_prompt = (
            "You are a professional English-to-Turkish technical translator. "
            "Translate the provided title and summary into Turkish. Keep technical terms "
            "(e.g. ESP32, SPI, ADC, microcontroller) intact in Turkish translation. Output a single JSON object."
        )
        user_prompt = (
            f"Title: {title}\n"
            f"Summary: {summary}\n\n"
            "Return a JSON object with these keys:\n"
            "{\n"
            "  \"turkish_title\": \"Turkish translation of the title\",\n"
            "  \"turkish_summary\": \"Turkish translation of the summary (2-3 sentences)\"\n"
            "}\n\n"
            "Guidelines:\n"
            "1. Keep technical terms intact (do not translate ESP32, SPI, I2C, microcontroller, etc.).\n"
            "2. Return ONLY the JSON object. Do not include markdown code block formatting."
        )
        result = self.call_ollama_json(system_prompt, user_prompt, model=self.translator_model)
        if not result:
            print(f"  Warning: Translation failed. Using fallbacks.")
            return title, ""
        return result.get("turkish_title", title), result.get("turkish_summary", "")

    def analyze_article(self, article_id, title, text):
        """Compatibility wrapper for direct analyzer calls in tests/other modules"""
        eng_data = self.analyze_article_english(article_id, title, text)
        tr_title, tr_summary = self.translate_to_turkish(title, eng_data["summary"])
        return {
            "summary": eng_data["summary"],
            "topics": eng_data["topics"],
            "turkish_title": tr_title,
            "turkish_summary": tr_summary,
            "sft_qa": eng_data["sft_qa"],
            "dpo_pairs": eng_data["dpo_pairs"]
        }

    def enrich_all(self, limit=None):
        """Enriches extracted articles in SQLite DB using a two-pass batch optimization"""
        cursor = self.conn.cursor()
        
        # --- PASS 1: English Technical Analysis (Qwen Model) ---
        cursor.execute("""
            SELECT a.id, a.title, a.extracted_text 
            FROM articles a
            LEFT JOIN enrichments e ON a.id = e.article_id
            WHERE e.id IS NULL AND a.extracted_text IS NOT NULL AND a.extracted_text != ''
        """)
        pass1_rows = cursor.fetchall()
        
        if pass1_rows:
            print(f"Pass 1: Found {len(pass1_rows)} articles awaiting English enrichment.")
            count1 = 0
            for row in pass1_rows:
                if limit and count1 >= limit:
                    print(f"Reached English enrichment limit of {limit} articles.")
                    break
                    
                article_id, title, text = row
                try:
                    eng_data = self.analyze_article_english(article_id, title, text)
                    processed_at = datetime.now().isoformat()
                    
                    cursor.execute("""
                        INSERT INTO enrichments (
                            article_id, summary, topics, turkish_title, turkish_summary, sft_qa, dpo_pairs, processed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        article_id,
                        eng_data["summary"],
                        eng_data["topics"],
                        title,       # Placeholder title, will be translated in Pass 2
                        "",          # Placeholder summary, will be translated in Pass 2
                        eng_data["sft_qa"],
                        eng_data["dpo_pairs"],
                        processed_at
                    ))
                    self.conn.commit()
                    count1 += 1
                except Exception as e:
                    print(f"Error in Pass 1 for article {article_id}: {e}")
                    self.conn.rollback()
            
            print(f"Pass 1 complete. Enriched {count1} articles in English.")
            
            # Unload main model from VRAM/RAM
            print("Unloading main analyzer model (Qwen) from server memory...")
            try:
                self.client.generate(model=self.model_name, prompt="", keep_alive=0)
            except Exception as e:
                print(f"Warning: Failed to unload main model: {e}")
        else:
            print("Pass 1: No articles require English enrichment.")
            
        # --- PASS 2: Turkish Translation (TranslateGemma Model) ---
        cursor.execute("""
            SELECT e.article_id, a.title, e.summary 
            FROM enrichments e
            JOIN articles a ON e.article_id = a.id
            WHERE e.turkish_summary IS NULL OR e.turkish_summary = ''
        """)
        pass2_rows = cursor.fetchall()
        
        if pass2_rows:
            print(f"\nPass 2: Found {len(pass2_rows)} articles awaiting Turkish translation.")
            count2 = 0
            for row in pass2_rows:
                if limit and count2 >= limit:
                    print(f"Reached Turkish translation limit of {limit} articles.")
                    break
                    
                article_id, title, summary = row
                if not summary or summary == "Summary unavailable.":
                    continue
                    
                try:
                    tr_title, tr_summary = self.translate_to_turkish(title, summary)
                    
                    cursor.execute("""
                        UPDATE enrichments
                        SET turkish_title = ?, turkish_summary = ?
                        WHERE article_id = ?
                    """, (tr_title, tr_summary, article_id))
                    self.conn.commit()
                    count2 += 1
                except Exception as e:
                    print(f"Error in Pass 2 for article {article_id}: {e}")
                    self.conn.rollback()
                    
            print(f"Pass 2 complete. Translated {count2} articles into Turkish.")
            
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
