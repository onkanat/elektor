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

    def call_ollama_json(self, system_prompt, user_prompt):
        """Helper to call Ollama model and expect a JSON output, optimized with token limit and temp"""
        try:
            response = self.client.chat(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                format="json",
                think=False,
                options={
                    "temperature": 0.2,
                    "num_predict": 2048  # Prevent infinite loops / excessively long generation
                }
            )
            content = response['message']['content']
            return json.loads(content)
        except Exception as e:
            print(f"  Ollama combined JSON call error: {e}")
            return None

    def analyze_article(self, article_id, title, text):
        """Performs combined analysis in a single LLM call for maximum performance on limited hardware"""
        print(f"Analyzing article [{article_id}]: {title}...")
        
        # Limit text size to 4000 characters to reduce prompt ingestion time and RAM usage
        truncated_text = text[:4000] if len(text) > 4000 else text
        
        system_prompt = (
            "You are an expert embedded systems engineer, technical writer, and translator. "
            "Analyze the technical article text and output a single JSON object. Follow the requested structure strictly. "
            "CRITICAL: Keep your internal thinking process extremely short (under 50 words) to save tokens and generation time."
        )
        
        user_prompt = (
            f"Article Title: {title}\n"
            f"Article Text:\n{truncated_text}\n\n"
            "Generate a JSON object with the following keys:\n"
            "{\n"
            "  \"summary\": \"English summary of the project/article (2-3 sentences)\",\n"
            "  \"topics\": [\"Topic 1\", \"Topic 2\", \"Topic 3\"],\n"
            "  \"turkish_title\": \"Turkish translation of the title\",\n"
            "  \"turkish_summary\": \"Turkish translation of the summary (2-3 sentences)\",\n"
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
            "2. Keep technical terms (e.g. ESP32, SPI, ADC, microcontroller) intact in Turkish translation.\n"
            "3. Return ONLY the JSON object. Do not include markdown code block formatting."
        )
        
        result = self.call_ollama_json(system_prompt, user_prompt)
        
        if not result:
            print(f"  Warning: Failed to parse or receive result for article {article_id}. Using default/fallback.")
            result = {
                "summary": "Summary unavailable.",
                "topics": [],
                "turkish_title": title,
                "turkish_summary": "",
                "sft_qa": [],
                "dpo_pair": {"question": "", "chosen": "", "rejected": ""}
            }
            
        # Format output to match table columns
        sft_qa = result.get("sft_qa", [])
        dpo_pair = result.get("dpo_pair", {})
        dpo_pairs_list = [dpo_pair] if dpo_pair and dpo_pair.get("question") else []
        
        return {
            "summary": result.get("summary", ""),
            "topics": json.dumps(result.get("topics", [])),
            "turkish_title": result.get("turkish_title", title),
            "turkish_summary": result.get("turkish_summary", ""),
            "sft_qa": json.dumps(sft_qa),
            "dpo_pairs": json.dumps(dpo_pairs_list)
        }

    def enrich_all(self, limit=None):
        """Enriches extracted articles in the SQLite DB using local Ollama model"""
        cursor = self.conn.cursor()
        
        # Select articles that don't have enrichments yet
        cursor.execute("""
            SELECT a.id, a.title, a.extracted_text 
            FROM articles a
            LEFT JOIN enrichments e ON a.id = e.article_id
            WHERE e.id IS NULL AND a.extracted_text IS NOT NULL AND a.extracted_text != ''
        """)
        rows = cursor.fetchall()
        
        print(f"Found {len(rows)} articles awaiting enrichment.")
        
        count = 0
        for row in rows:
            if limit and count >= limit:
                print(f"Reached enrichment limit of {limit} articles.")
                break
                
            article_id, title, text = row
            try:
                enriched_data = self.analyze_article(article_id, title, text)
                
                processed_at = datetime.now().isoformat()
                cursor.execute("""
                    INSERT INTO enrichments (
                        article_id, summary, topics, turkish_title, turkish_summary, sft_qa, dpo_pairs, processed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    article_id,
                    enriched_data["summary"],
                    enriched_data["topics"],
                    enriched_data["turkish_title"],
                    enriched_data["turkish_summary"],
                    enriched_data["sft_qa"],
                    enriched_data["dpo_pairs"],
                    processed_at
                ))
                self.conn.commit()
                count += 1
            except Exception as e:
                print(f"Error enriching article {article_id}: {e}")
                self.conn.rollback()
                
        print(f"Enrichment step completed. Enriched {count} articles.")

    def close(self):
        self.conn.close()

if __name__ == "__main__":
    analyzer = ArchiveAnalyzer()
    analyzer.enrich_all(limit=2)
    analyzer.close()
