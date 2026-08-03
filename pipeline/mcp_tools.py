import json
import sqlite3
import os
from pathlib import Path
import ollama
from pipeline.vector_store import ArchiveVectorStore

def get_active_config():
    config_path = Path("config.json")
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def resolve_db_path(raw_path: str) -> str:
    if not raw_path:
        return "database/sdr_engineers.db"
    db_obj = Path(raw_path)
    if len(db_obj.parts) == 1:
        return str(Path("database") / raw_path)
    return str(db_obj)

def search_vector_rag(query: str, top_k: int = 4):
    """Retrieves top-k relevant semantic vector chunks from Qdrant database"""
    store = None
    try:
        store = ArchiveVectorStore()
        results = store.search(query, top_k=top_k)
        return {
            "status": "success",
            "tool": "search_vector_rag",
            "query": query,
            "count": len(results),
            "results": results
        }
    except Exception as e:
        return {
            "status": "error",
            "tool": "search_vector_rag",
            "error": str(e),
            "results": []
        }
    finally:
        if store is not None:
            store.close()

def query_sqlite_knowledge(query: str, limit: int = 3):
    """Queries SQLite database tables (articles & enrichments) for matching document segments and SFT Q&A pairs"""
    config = get_active_config()
    db_path = resolve_db_path(config.get("db_path", "database/sdr_engineers.db"))
    
    if not os.path.exists(db_path):
        return {"status": "error", "tool": "query_sqlite_knowledge", "error": "Database file not found", "results": []}

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Query articles
        cursor.execute("""
            SELECT id, file_path, title, year, extracted_text
            FROM articles
            WHERE title LIKE ? OR extracted_text LIKE ?
            LIMIT ?
        """, (f"%{query}%", f"%{query}%", limit))
        
        article_rows = [dict(r) for r in cursor.fetchall()]
        for a in article_rows:
            if "extracted_text" in a and a["extracted_text"] and len(a["extracted_text"]) > 600:
                a["extracted_text_snippet"] = a["extracted_text"][:600] + "..."

        # Query enrichments SFT pairs
        cursor.execute("""
            SELECT id, article_id, summary, turkish_title, sft_qa, tr_sft_qa
            FROM enrichments
            WHERE summary LIKE ? OR sft_qa LIKE ? OR tr_sft_qa LIKE ?
            LIMIT ?
        """, (f"%{query}%", f"%{query}%", f"%{query}%", limit))
        
        enrichment_rows = [dict(r) for r in cursor.fetchall()]
        
        conn.close()
        return {
            "status": "success",
            "tool": "query_sqlite_knowledge",
            "articles_found": len(article_rows),
            "articles": article_rows,
            "enrichments_found": len(enrichment_rows),
            "enrichments": enrichment_rows
        }
    except Exception as e:
        return {"status": "error", "tool": "query_sqlite_knowledge", "error": str(e), "articles": [], "enrichments": []}

def inject_sft_dpo_context(query: str, limit: int = 3):
    """Searches generated JSONL datasets in exports/ folder for relevant SFT and DPO training pairs"""
    exports_dir = Path("exports")
    if not exports_dir.exists():
        return {"status": "success", "tool": "inject_sft_dpo_context", "samples": []}

    matched_samples = []
    query_words = [w.lower() for w in query.split() if len(w) > 3]

    try:
        for jsonl_file in exports_dir.glob("**/*.jsonl"):
            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    if any(w in line_str.lower() for w in query_words):
                        try:
                            record = json.loads(line_str)
                            matched_samples.append({
                                "file": jsonl_file.name,
                                "record": record
                            })
                            if len(matched_samples) >= limit:
                                break
                        except Exception:
                            continue
            if len(matched_samples) >= limit:
                break

        return {
            "status": "success",
            "tool": "inject_sft_dpo_context",
            "count": len(matched_samples),
            "samples": matched_samples
        }
    except Exception as e:
        return {"status": "error", "tool": "inject_sft_dpo_context", "error": str(e), "samples": []}

def evaluate_knowledge_gap(base_response: str, enriched_response: str, context_text: str = ""):
    """
    Evaluates the Knowledge Gain (%) and Fine-Tuning Impact.
    Primary: LLM evaluator pass.
    Fallback: Jaccard similarity heuristic.
    """
    config = get_active_config()
    ollama_url = config.get("ollama_url", "http://localhost:11434")
    model_analyzer = config.get("model_analyzer", "qwen3.5:2b")

    eval_prompt = f"""You are an expert AI Fine-Tuning Impact Evaluator.
Compare the following two responses given to a user query:

--- BASE RESPONSE (No Fine-Tuning / No Context) ---
{base_response[:800]}

--- ENRICHED RESPONSE (With Database & SFT Context) ---
{enriched_response[:800]}

--- CONTEXT DATASET ---
{context_text[:800]}

Respond ONLY in valid JSON with this exact structure:
{{
  "knowledge_gain_percent": 85,
  "factuality": "Yüksek (Dökümana Sadık)",
  "verdict": "Fine-Tuning Önerilir",
  "explanation": "Dökümandaki özel alan terminolojisi ham modelde bulunmuyor."
}}
"""

    try:
        client = ollama.Client(host=ollama_url, timeout=30.0)
        res = client.chat(
            model=model_analyzer,
            messages=[{"role": "user", "content": eval_prompt}],
            options={"temperature": 0.1}
        )
        content = res.get("message", {}).get("content", "").strip()
        
        # Extract JSON from response
        if "{" in content and "}" in content:
            json_str = content[content.find("{"):content.rfind("}")+1]
            eval_data = json.loads(json_str)
            eval_data["evaluator"] = "llm"
            return eval_data
    except Exception as e:
        print(f"LLM Evaluator pass failed ({e}). Executing Jaccard similarity fallback...")

    # Jaccard Similarity Fallback
    words_base = set(base_response.lower().split())
    words_enriched = set(enriched_response.lower().split())
    
    intersection = words_base.intersection(words_enriched)
    union = words_base.union(words_enriched)
    
    similarity = len(intersection) / len(union) if union else 1.0
    gain_percent = max(10, min(95, int((1.0 - similarity) * 100)))

    verdict = "Fine-Tuning Önerilir" if gain_percent >= 40 else "İsteğe Bağlı / Yeterli Bilgi Var"
    factuality = "Yüksek (Döküman Destekli)" if len(context_text) > 50 else "Genel Yanıt"

    return {
        "knowledge_gain_percent": gain_percent,
        "factuality": factuality,
        "verdict": verdict,
        "explanation": f"Jaccard küme farkı analizi ile %{gain_percent} yeni alan bilgisi ve terminoloji kazancı hesaplandı.",
        "evaluator": "jaccard_fallback"
    }
