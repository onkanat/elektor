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
                
            # Ensure batch_jobs tracking table exists for Gemini Batch API
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS batch_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT UNIQUE,
                    job_type TEXT DEFAULT 'judge',
                    model TEXT,
                    state TEXT,
                    total_requests INTEGER DEFAULT 0,
                    processed_requests INTEGER DEFAULT 0,
                    mode TEXT DEFAULT 'strict',
                    threshold REAL DEFAULT 7.0,
                    manifest_json TEXT DEFAULT '{}',
                    created_at TEXT,
                    completed_at TEXT
                )
            """)

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
            
            # Polite pacing between judged articles
            if idx < total:
                time.sleep(1.0)

        conn.close()
        print(f"\n✅ Judge Execution Complete: {stats['approved']} Approved, {stats['borderline']} Borderline, {stats['rejected']} Rejected, {stats['rewritten']} Rewritten.\n")
        return stats

    # =========================================================================
    # Gemini Batch API Support (50% Cost Discount, Zero 15-RPM Rate Limit)
    # =========================================================================

    def judge_batch_submit(
        self,
        limit: Optional[int] = None,
        mode: str = "strict",
        threshold: Optional[float] = None,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Gathers unreviewed SFT/DPO pairs from SQLite, constructs Gemini Batch API requests,
        and submits an asynchronous batch prediction job for 50% discount and zero rate limits.
        """
        conn = sqlite3.connect(self.db_path, timeout=60.0)
        cursor = conn.cursor()

        # Check if an active/pending batch job already exists to prevent duplicate submissions
        cursor.execute("""
            SELECT job_id, state, created_at FROM batch_jobs 
            WHERE state IN ('PENDING', 'JOB_STATE_PENDING', 'JOB_STATE_RUNNING', 'LOCAL_QUEUED')
            ORDER BY id DESC LIMIT 1
        """)
        active_job = cursor.fetchone()
        if active_job and not force:
            conn.close()
            return {
                "status": "active_job_exists",
                "job_id": active_job[0],
                "state": active_job[1],
                "total_requests": 0,
                "message": f"Devam eden aktif bir Batch işi bulunuyor (İş ID: '{active_job[0]}', Durum: {active_job[1]}). Mükerrer gönderim engellendi. Mevcut işi tablodan silebilir/iptal edebilir veya tamamlanmasını bekleyebilirsiniz."
            }

        query = "SELECT id, article_id, sft_qa, dpo_pairs, tr_sft_qa, tr_dpo_pairs FROM enrichments WHERE judge_status IS NULL OR judge_status = ''"
        if limit:
            query += f" LIMIT {int(limit)}"

        cursor.execute(query)
        rows = cursor.fetchall()
        total = len(rows)

        if total == 0:
            conn.close()
            return {"status": "up_to_date", "message": "No unreviewed enrichments to submit.", "total": 0}

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

        batch_requests = []
        item_manifest = []

        for (eid, aid, sft_json, dpo_json, tr_sft_json, tr_dpo_json) in rows:
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
                continue

            first_pair = pairs[0] if isinstance(pairs, list) else pairs
            prompt = first_pair.get("prompt") or first_pair.get("question") or ""
            chosen = first_pair.get("chosen") or first_pair.get("answer") or ""
            rejected = first_pair.get("rejected", "")

            user_content = f"### Prompt / Instruction:\n{prompt}\n\n### Candidate Chosen:\n{chosen}\n"
            if rejected:
                user_content += f"\n### Candidate Rejected:\n{rejected}\n"

            custom_id = f"enrichment_{eid}"
            batch_requests.append({
                "custom_id": custom_id,
                "prompt": user_content,
                "system_instruction": system_instruction,
                "response_schema": JudgeEvaluation
            })
            item_manifest.append({"eid": eid, "aid": aid, "custom_id": custom_id})

        if not batch_requests:
            conn.close()
            return {"status": "no_valid_pairs", "message": "No valid pairs found to construct batch requests.", "total": 0}

        # Submit to GeminiClient
        batch_res = self.gemini_client.create_batch_job(
            requests=batch_requests,
            model=self.judge_model,
            purpose=f"judge_batch_{mode}",
            display_name=f"judge_batch_{mode}_{len(batch_requests)}items"
        )

        job_id = batch_res.get("batch_name") or f"batch_{int(time.time())}"
        state = batch_res.get("state", "PENDING")
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        manifest_str = json.dumps(item_manifest, ensure_ascii=False)

        cursor.execute("""
            INSERT OR REPLACE INTO batch_jobs (
                job_id, job_type, model, state, total_requests, processed_requests, mode, threshold, manifest_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (job_id, "judge", self.judge_model, state, len(batch_requests), 0, mode, target_threshold, manifest_str, now_iso))
        conn.commit()
        conn.close()

        self.logger.info(f"Gemini Batch Judge Job Created: {job_id} ({len(batch_requests)} requests, Mode: {mode})", module="judge_engine")
        return {
            "status": "submitted",
            "job_id": job_id,
            "state": state,
            "total_requests": len(batch_requests),
            "model": self.judge_model,
            "mode": mode,
            "message": f"Successfully submitted batch job with {len(batch_requests)} items (%50 discount applied)."
        }

    def judge_batch_sync(self, job_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Polls Gemini Batch API for completed batch jobs, downloads results,
        and applies judge scores / surgical rewrites to SQLite enrichments table.
        """
        conn = sqlite3.connect(self.db_path, timeout=60.0)
        cursor = conn.cursor()

        if job_id:
            cursor.execute("SELECT id, job_id, state, manifest_json, mode FROM batch_jobs WHERE job_id = ?", (job_id,))
        else:
            cursor.execute("SELECT id, job_id, state, manifest_json, mode FROM batch_jobs WHERE state NOT IN ('COMPLETED', 'JOB_STATE_SUCCEEDED', 'JOB_STATE_FAILED', 'JOB_STATE_CANCELLED')")

        jobs = cursor.fetchall()
        if not jobs:
            conn.close()
            return {"status": "no_pending_jobs", "synced_count": 0, "message": "No pending batch jobs to sync."}

        synced_total = 0
        job_summaries = []

        for (bj_id, jid, old_state, manifest_json, mode) in jobs:
            status_res = self.gemini_client.get_batch_job_status(jid)
            new_state = status_res.get("state", old_state)

            if new_state == "JOB_STATE_SUCCEEDED" or (status_res.get("completed") and status_res.get("success")):
                # Download and parse results
                results = self.gemini_client.download_batch_results(jid)
                now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

                for r in results:
                    cid = r.get("custom_id", "")
                    if not cid.startswith("enrichment_"):
                        continue
                    try:
                        eid = int(cid.replace("enrichment_", ""))
                    except Exception:
                        continue

                    json_data = r.get("json_data")
                    if not json_data:
                        continue

                    try:
                        eval_obj = JudgeEvaluation(**json_data)
                    except Exception:
                        continue

                    feedback_json = json.dumps(eval_obj.model_dump(), ensure_ascii=False)
                    
                    # Update enrichment
                    cursor.execute("SELECT dpo_pairs, tr_dpo_pairs FROM enrichments WHERE id = ?", (eid,))
                    row = cursor.fetchone()
                    dpo_p = row[0] if row else None
                    tr_dpo_p = row[1] if row else None

                    if eval_obj.rewritten_chosen:
                        if tr_dpo_p:
                            try:
                                p_list = json.loads(tr_dpo_p)
                                if p_list and isinstance(p_list, list):
                                    p_list[0]["chosen"] = eval_obj.rewritten_chosen
                                    tr_dpo_p = json.dumps(p_list, ensure_ascii=False)
                            except Exception:
                                pass
                        elif dpo_p:
                            try:
                                p_list = json.loads(dpo_p)
                                if p_list and isinstance(p_list, list):
                                    p_list[0]["chosen"] = eval_obj.rewritten_chosen
                                    dpo_p = json.dumps(p_list, ensure_ascii=False)
                            except Exception:
                                pass

                    cursor.execute("""
                        UPDATE enrichments
                        SET judge_score = ?, judge_status = ?, judge_feedback = ?, judged_at = ?, dpo_pairs = ?, tr_dpo_pairs = ?
                        WHERE id = ?
                    """, (eval_obj.overall_score, eval_obj.status, feedback_json, now_iso, dpo_p, tr_dpo_p, eid))
                    synced_total += 1

                # Mark batch job completed
                cursor.execute("""
                    UPDATE batch_jobs
                    SET state = 'COMPLETED', processed_requests = ?, completed_at = ?
                    WHERE id = ?
                """, (len(results), now_iso, bj_id))
                conn.commit()

                job_summaries.append({"job_id": jid, "state": "COMPLETED", "processed": len(results)})
                self.logger.info(f"Successfully synced Gemini Batch Job {jid}: Processed {len(results)} items into SQLite.", module="judge_engine")
            else:
                # Update current state
                cursor.execute("UPDATE batch_jobs SET state = ? WHERE id = ?", (new_state, bj_id))
                conn.commit()
                job_summaries.append({"job_id": jid, "state": new_state})

        conn.close()
        return {
            "status": "success",
            "synced_count": synced_total,
            "jobs": job_summaries,
            "message": f"Synced {synced_total} evaluation records from Gemini Batch API."
        }

    def list_batch_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Lists recent Gemini Batch Jobs and their live states."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='batch_jobs'")
        if not cursor.fetchone():
            conn.close()
            return []

        cursor.execute("""
            SELECT id, job_id, job_type, model, state, total_requests, processed_requests, mode, threshold, created_at, completed_at
            FROM batch_jobs
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        conn.close()

        jobs = []
        for r in rows:
            jobs.append({
                "id": r[0],
                "job_id": r[1],
                "job_type": r[2],
                "model": r[3],
                "state": r[4],
                "total_requests": r[5],
                "processed_requests": r[6],
                "mode": r[7],
                "threshold": r[8],
                "created_at": r[9],
                "completed_at": r[10]
            })
        return jobs

    def delete_batch_job(self, job_id: str) -> Dict[str, Any]:
        """Cancels a remote Gemini Batch Job if applicable and deletes it from SQLite tracking table."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        cursor = conn.cursor()
        cursor.execute("SELECT id, job_id, state FROM batch_jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return {"status": "not_found", "message": f"Batch işi bulunamadı: {job_id}"}

        # Cancel on remote Gemini if not local
        if not job_id.startswith("local_batch_"):
            try:
                self.gemini_client.cancel_batch_job(job_id)
            except Exception:
                pass

        cursor.execute("DELETE FROM batch_jobs WHERE job_id = ?", (job_id,))
        conn.commit()
        conn.close()
        self.logger.info(f"Deleted / cancelled Batch Job: {job_id}", module="judge_engine")
        return {"status": "success", "message": f"Batch işi ({job_id}) başarıyla silindi ve iptal edildi."}
