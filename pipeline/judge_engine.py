import os
import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from pipeline.gemini_client import get_gemini_client
from pipeline.project_logger import get_project_logger

class JudgeEvaluation(BaseModel):
    technical_accuracy: int = Field(description="Score 1-10 for factual and mathematical correctness", ge=1, le=10)
    logical_consistency: int = Field(description="Score 1-10 for logical flow, reasoning, and safety", ge=1, le=10)
    turkish_fluency: int = Field(description="Score 1-10 for Turkish terminology and syntax (or 10 if English only)", ge=1, le=10)
    overall_score: float = Field(description="Weighted overall score from 1.0 to 10.0", ge=1.0, le=10.0)
    status: str = Field(description="'approved', 'borderline', or 'rejected'")
    feedback: str = Field(description="Detailed reason for the evaluation")
    rewritten_chosen: Optional[str] = Field(default=None, description="Surgically rewritten high-quality Chosen answer if in editor mode")

class JudgeEngine:
    """
    Independent LLM-as-a-Judge Engine.
    Evaluates, scores, filters, and refines SFT/DPO pairs in SQLite database.
    Supports 'strict' (fast scoring) and 'hybrid_editor' (targeted rewrite) modes.
    """
    def __init__(self, config_or_path: Any = "config.json"):
        if isinstance(config_or_path, dict):
            self.config = config_or_path
        else:
            cpath = Path(config_or_path)
            if cpath.exists():
                with open(cpath, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
            else:
                self.config = {}

        self.db_path = self.config.get("db_path", "database/elektor_archive.db")
        db_path_obj = Path(self.db_path)
        if len(db_path_obj.parts) == 1:
            self.db_path = str(Path("database") / self.db_path)

        self.logger = get_project_logger()
        self.gemini_client = get_gemini_client(self.config)
        self.judge_model = self.config.get("judge_model", "gemini-3.6-flash")
        self.default_threshold = float(self.config.get("judge_threshold", 7.0))
        self.editor_threshold = float(self.config.get("editor_threshold", 5.5))
        self._ensure_tables()

    def _ensure_tables(self):
        try:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(enrichments)")
            cols = [col[1] for col in cursor.fetchall()]
            
            if "judge_score" not in cols:
                cursor.execute("ALTER TABLE enrichments ADD COLUMN judge_score REAL")
            if "judge_status" not in cols:
                cursor.execute("ALTER TABLE enrichments ADD COLUMN judge_status TEXT")
            if "judge_feedback" not in cols:
                cursor.execute("ALTER TABLE enrichments ADD COLUMN judge_feedback TEXT")
            if "judged_at" not in cols:
                cursor.execute("ALTER TABLE enrichments ADD COLUMN judged_at TEXT")
                
            conn.commit()
            conn.close()
        except Exception as e:
            self.logger.warning(f"Could not update enrichments schema for judge: {e}", module="judge_engine")

    def evaluate_pair(
        self,
        prompt_text: str,
        chosen_text: str,
        rejected_text: Optional[str] = None,
        mode: str = "strict",
        threshold: Optional[float] = None
    ) -> JudgeEvaluation:
        """
        Evaluates a single prompt/chosen/rejected record.
        In 'strict' mode: evaluates scores and marks approved/rejected.
        In 'hybrid_editor' mode: rewrites Chosen if borderline.
        """
        target_threshold = threshold or self.default_threshold
        system_instruction = """You are a Principal AI Dataset Auditor and Chief Editor specializing in engineering, mathematics, computer science, and electronics.
Your task is to critically judge the provided (Prompt, Chosen, Rejected) pairs.
Criteria:
1. Technical Accuracy (1-10): Factual soundness, correct formulas, valid code, no hallucinations.
2. Logical Consistency (1-10): Chain-of-thought validity, safety, pedagogical clarity.
3. Turkish Fluency (1-10): Correct engineering terminology, no awkward machine translation syntax.

Rules:
- If overall_score >= {threshold}, status = "approved".
- If {editor_threshold} <= overall_score < {threshold}, status = "borderline".
- If overall_score < {editor_threshold}, status = "rejected".
""".format(threshold=target_threshold, editor_threshold=self.editor_threshold)

        if mode == "hybrid_editor":
            system_instruction += "\nIf status is 'borderline' or 'rejected', provide a surgically corrected, flawless, publication-grade 'rewritten_chosen' text."

        user_content = f"### Prompt / Instruction:\n{prompt_text}\n\n### Candidate Chosen:\n{chosen_text}\n"
        if rejected_text:
            user_content += f"\n### Candidate Rejected:\n{rejected_text}\n"

        res = self.gemini_client.generate_content(
            prompt=user_content,
            system_instruction=system_instruction,
            model=self.judge_model,
            response_schema=JudgeEvaluation,
            purpose=f"judge_{mode}"
        )

        if res["success"] and res["json_data"]:
            try:
                return JudgeEvaluation(**res["json_data"])
            except Exception:
                pass

        # Fallback heuristic evaluation if API call fails
        self.logger.warning("Gemini Judge API unavailable or returned malformed JSON. Using fallback heuristic.", module="judge_engine")
        is_empty_or_short = len(chosen_text.strip()) < 30
        score = 3.0 if is_empty_or_short else 7.5
        status = "rejected" if is_empty_or_short else "approved"
        return JudgeEvaluation(
            technical_accuracy=3 if is_empty_or_short else 8,
            logical_consistency=3 if is_empty_or_short else 8,
            turkish_fluency=5 if is_empty_or_short else 8,
            overall_score=score,
            status=status,
            feedback="Fallback heuristic evaluation (offline/mock mode)."
        )

    def judge_all(
        self,
        limit: Optional[int] = None,
        mode: str = "strict",
        threshold: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Iterates over enrichments table and runs strict or hybrid editor evaluation.
        """
        conn = sqlite3.connect(self.db_path, timeout=60.0)
        cursor = conn.cursor()

        query = "SELECT id, article_id, sft_qa, dpo_pairs, tr_sft_qa, tr_dpo_pairs FROM enrichments"
        if limit:
            query += f" LIMIT {int(limit)}"

        cursor.execute(query)
        rows = cursor.fetchall()
        total = len(rows)

        print(f"\n--- Starting Judge Engine (Mode: {mode.upper()}, Limit: {total}) ---")
        stats = {"total": total, "approved": 0, "borderline": 0, "rejected": 0, "rewritten": 0}

        for idx, (eid, aid, sft_json, dpo_json, tr_sft_json, tr_dpo_json) in enumerate(rows, 1):
            # Parse pairs
            pairs = []
            if tr_dpo_json:
                try:
                    pairs = json.loads(tr_dpo_json)
                except Exception:
                    pass
            elif dpo_json:
                try:
                    pairs = json.loads(dpo_json)
                except Exception:
                    pass

            if not pairs and (tr_sft_json or sft_json):
                try:
                    raw_sft = json.loads(tr_sft_json or sft_json)
                    if isinstance(raw_sft, list) and raw_sft:
                        pairs = [{"prompt": raw_sft[0].get("question", ""), "chosen": raw_sft[0].get("answer", ""), "rejected": ""}]
                except Exception:
                    pass

            if not pairs:
                print(f"[{idx}/{total}] Enrichment #{eid} (Article #{aid}): No SFT/DPO pairs found to judge.")
                continue

            first_pair = pairs[0] if isinstance(pairs, list) else pairs
            prompt = first_pair.get("prompt") or first_pair.get("question") or ""
            chosen = first_pair.get("chosen") or first_pair.get("answer") or ""
            rejected = first_pair.get("rejected", "")

            eval_res = self.evaluate_pair(
                prompt_text=prompt,
                chosen_text=chosen,
                rejected_text=rejected,
                mode=mode,
                threshold=threshold
            )

            stats[eval_res.status] = stats.get(eval_res.status, 0) + 1
            if eval_res.rewritten_chosen:
                stats["rewritten"] += 1
                # If rewritten, update Chosen text in the payload
                first_pair["chosen"] = eval_res.rewritten_chosen
                if tr_dpo_json:
                    tr_dpo_json = json.dumps(pairs, ensure_ascii=False)
                elif dpo_json:
                    dpo_json = json.dumps(pairs, ensure_ascii=False)

            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            feedback_json = json.dumps(eval_res.model_dump(), ensure_ascii=False)

            cursor.execute("""
                UPDATE enrichments
                SET judge_score = ?, judge_status = ?, judge_feedback = ?, judged_at = ?, dpo_pairs = ?, tr_dpo_pairs = ?
                WHERE id = ?
            """, (eval_res.overall_score, eval_res.status, feedback_json, now_iso, dpo_json, tr_dpo_json, eid))
            conn.commit()

            print(f"[{idx}/{total}] Article #{aid} -> Score: {eval_res.overall_score:.1f}/10 [{eval_res.status.upper()}] - {eval_res.feedback[:60]}...")

        conn.close()
        print(f"\n✅ Judge Execution Complete: {stats['approved']} Approved, {stats['borderline']} Borderline, {stats['rejected']} Rejected, {stats['rewritten']} Rewritten.\n")
        return stats
