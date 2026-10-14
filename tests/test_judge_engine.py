import unittest
from unittest.mock import patch, MagicMock
import tempfile
import os
import sqlite3
import json

from pipeline.judge_engine import JudgeEngine, JudgeEvaluation

class TestJudgeEngine(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        
        # Create mock sqlite database with articles and enrichments
        conn = sqlite3.connect(self.temp_db.name)
        cur = conn.cursor()
        cur.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT)")
        cur.execute("""
            CREATE TABLE enrichments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER,
                sft_qa TEXT,
                dpo_pairs TEXT,
                tr_sft_qa TEXT,
                tr_dpo_pairs TEXT
            )
        """)
        cur.execute("INSERT INTO articles (id, title) VALUES (1, 'Op-Amp Filter')")
        cur.execute("""
            INSERT INTO enrichments (id, article_id, sft_qa, dpo_pairs, tr_sft_qa, tr_dpo_pairs)
            VALUES (1, 1, NULL, '[{"prompt": "Calculate cutoff freq", "chosen": "fc = 1 / (2*pi*R*C)", "rejected": "fc = R * C"}]', NULL, NULL)
        """)
        conn.commit()
        conn.close()

        self.config = {
            "db_path": self.temp_db.name,
            "judge_model": "gemini-3.6-flash",
            "judge_threshold": 7.0
        }

    def tearDown(self):
        if os.path.exists(self.temp_db.name):
            os.unlink(self.temp_db.name)

    @patch("pipeline.gemini_client.GeminiClient.generate_content")
    def test_judge_all_strict_mode(self, mock_generate):
        mock_generate.return_value = {
            "success": True,
            "json_data": {
                "technical_accuracy": 9,
                "logical_consistency": 9,
                "turkish_fluency": 9,
                "overall_score": 9.0,
                "status": "approved",
                "feedback": "Perfect mathematical formulation",
                "rewritten_chosen": None
            }
        }

        engine = JudgeEngine(self.config)
        stats = engine.judge_all(limit=10, mode="strict")

        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["approved"], 1)

        # Check SQLite record
        conn = sqlite3.connect(self.temp_db.name)
        cur = conn.cursor()
        cur.execute("SELECT judge_score, judge_status FROM enrichments WHERE id = 1")
        row = cur.fetchone()
        conn.close()

        self.assertEqual(row[0], 9.0)
        self.assertEqual(row[1], "approved")

    @patch("pipeline.gemini_client.GeminiClient.generate_content")
    def test_judge_all_hybrid_editor_rewrites(self, mock_generate):
        mock_generate.return_value = {
            "success": True,
            "json_data": {
                "technical_accuracy": 5,
                "logical_consistency": 6,
                "turkish_fluency": 5,
                "overall_score": 5.5,
                "status": "borderline",
                "feedback": "Missing component units, rewrote answer.",
                "rewritten_chosen": "fc = 1 / (2*pi*R*C) where R is in Ohms and C is in Farads."
            }
        }

        engine = JudgeEngine(self.config)
        stats = engine.judge_all(limit=10, mode="hybrid_editor")

        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["rewritten"], 1)
        self.assertEqual(stats["borderline"], 1)

        # Check SQLite record was atomically updated with rewritten chosen answer
        conn = sqlite3.connect(self.temp_db.name)
        cur = conn.cursor()
        cur.execute("SELECT judge_score, judge_status, dpo_pairs, judge_feedback, judged_at FROM enrichments WHERE id = 1")
        row = cur.fetchone()
        conn.close()

        self.assertEqual(row[0], 5.5)
        self.assertEqual(row[1], "borderline")
        updated_pairs = json.loads(row[2])
        self.assertEqual(updated_pairs[0]["chosen"], "fc = 1 / (2*pi*R*C) where R is in Ohms and C is in Farads.")
        self.assertIsNotNone(row[4])

    @patch("pipeline.gemini_client.GeminiClient.create_batch_job")
    def test_judge_batch_submit(self, mock_create_batch):
        mock_create_batch.return_value = {
            "batch_name": "batches/test_batch_123",
            "state": "JOB_STATE_PENDING",
            "total_requests": 1,
            "success": True,
            "error": None
        }

        engine = JudgeEngine(self.config)
        res = engine.judge_batch_submit(limit=10, mode="strict")

        self.assertEqual(res["status"], "submitted")
        self.assertEqual(res["job_id"], "batches/test_batch_123")
        self.assertEqual(res["total_requests"], 1)

        # Check batch_jobs table
        jobs = engine.list_batch_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["job_id"], "batches/test_batch_123")

    @patch("pipeline.gemini_client.GeminiClient.download_batch_results")
    @patch("pipeline.gemini_client.GeminiClient.get_batch_job_status")
    def test_judge_batch_sync(self, mock_status, mock_download):
        engine = JudgeEngine(self.config)
        
        # Insert a pending batch job
        conn = sqlite3.connect(self.temp_db.name)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO batch_jobs (job_id, job_type, model, state, total_requests, processed_requests, mode, threshold, created_at)
            VALUES ('batches/test_batch_456', 'judge', 'gemini-3.6-flash', 'JOB_STATE_RUNNING', 1, 0, 'strict', 7.0, '2026-08-24T00:00:00Z')
        """)
        conn.commit()
        conn.close()

        mock_status.return_value = {
            "name": "batches/test_batch_456",
            "state": "JOB_STATE_SUCCEEDED",
            "completed": True,
            "success": True
        }
        mock_download.return_value = [
            {
                "custom_id": "enrichment_1",
                "text": "{}",
                "json_data": {
                    "technical_accuracy": 10,
                    "logical_consistency": 10,
                    "turkish_fluency": 10,
                    "overall_score": 10.0,
                    "status": "approved",
                    "feedback": "Batch evaluation verified flawless.",
                    "rewritten_chosen": None
                },
                "success": True
            }
        ]

        engine = JudgeEngine(self.config)
        sync_res = engine.judge_batch_sync(job_id="batches/test_batch_456")

        self.assertEqual(sync_res["status"], "success")
        self.assertEqual(sync_res["synced_count"], 1)

        # Verify enrichment was updated
        conn = sqlite3.connect(self.temp_db.name)
        cur = conn.cursor()
        cur.execute("SELECT judge_score, judge_status FROM enrichments WHERE id = 1")
        row = cur.fetchone()
        conn.close()

        self.assertEqual(row[0], 10.0)
        self.assertEqual(row[1], "approved")

    @patch("pipeline.gemini_client.GeminiClient.create_batch_job")
    def test_judge_batch_active_job_deduplication(self, mock_create_batch):
        engine = JudgeEngine(self.config)
        
        # Insert an active batch job
        conn = sqlite3.connect(self.temp_db.name)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO batch_jobs (job_id, job_type, model, state, total_requests, processed_requests, mode, threshold, created_at)
            VALUES ('batches/active_job_999', 'judge', 'gemini-3.6-flash', 'JOB_STATE_RUNNING', 5, 0, 'strict', 7.0, '2026-08-24T00:00:00Z')
        """)
        conn.commit()
        conn.close()

        # Attempt to submit another batch without force
        res = engine.judge_batch_submit(limit=10, mode="strict")
        self.assertEqual(res["status"], "active_job_exists")
        self.assertEqual(res["job_id"], "batches/active_job_999")

    def test_delete_batch_job(self):
        engine = JudgeEngine(self.config)
        
        # Insert a job
        conn = sqlite3.connect(self.temp_db.name)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO batch_jobs (job_id, job_type, model, state, total_requests, processed_requests, mode, threshold, created_at)
            VALUES ('local_batch_to_delete', 'judge', 'gemini-3.6-flash', 'FAILED', 1, 0, 'strict', 7.0, '2026-08-24T00:00:00Z')
        """)
        conn.commit()
        conn.close()

        del_res = engine.delete_batch_job("local_batch_to_delete")
        self.assertEqual(del_res["status"], "success")

        # Verify deletion
        jobs = engine.list_batch_jobs()
        job_ids = [j["job_id"] for j in jobs]
        self.assertNotIn("local_batch_to_delete", job_ids)

    def test_evaluate_pair_offline_fallback(self):
        """Verifies deterministic heuristic offline fallback when Gemini API key is missing or calls fail."""
        engine = JudgeEngine(self.config)
        with patch.object(engine.gemini_client, "generate_content", return_value={"success": False, "error": "No API key"}):
            # 1. Sufficiently long candidate text (>= 15 chars) should be approved
            eval_good = engine.evaluate_pair(
                prompt_text="What is SPI?",
                chosen_text="Serial Peripheral Interface is a synchronous serial communication interface.",
                rejected_text="Wrong answer.",
                mode="strict"
            )
            self.assertEqual(eval_good.status, "approved")
            self.assertEqual(eval_good.overall_score, 7.5)
            self.assertIn("Fallback heuristic evaluation", eval_good.feedback)

            # 2. Too short candidate text (< 15 chars) should be rejected
            eval_short = engine.evaluate_pair(
                prompt_text="What is SPI?",
                chosen_text="Short",
                rejected_text="Another wrong",
                mode="strict"
            )
            self.assertEqual(eval_short.status, "rejected")
            self.assertEqual(eval_short.overall_score, 3.0)

            # 3. Identical chosen and rejected should be rejected
            eval_ident = engine.evaluate_pair(
                prompt_text="What is SPI?",
                chosen_text="Identical text description.",
                rejected_text="Identical text description.",
                mode="strict"
            )
            self.assertEqual(eval_ident.status, "rejected")

            # 4. In hybrid_editor mode on rejected candidate, rewritten_chosen is generated
            eval_edit = engine.evaluate_pair(
                prompt_text="What is SPI?",
                chosen_text="Too short",
                rejected_text="Too short",
                mode="hybrid_editor"
            )
            self.assertEqual(eval_edit.status, "rejected")
            self.assertIsNotNone(eval_edit.rewritten_chosen)

    @patch("pipeline.gemini_client.GeminiClient.generate_content")
    def test_judge_all_hybrid_editor_rewrites_tr_dpo(self, mock_generate):
        """Verifies hybrid_editor mode surgically rewrites tr_dpo_pairs in SQLite."""
        conn = sqlite3.connect(self.temp_db.name)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO enrichments (id, article_id, sft_qa, dpo_pairs, tr_sft_qa, tr_dpo_pairs)
            VALUES (2, 1, NULL, NULL, NULL, '[{"prompt": "Kesim frekansı nedir?", "chosen": "fc = 1/(2*pi*R*C)", "rejected": "fc = R*C"}]')
        """)
        conn.commit()
        conn.close()

        mock_generate.return_value = {
            "success": True,
            "json_data": {
                "technical_accuracy": 6,
                "logical_consistency": 6,
                "turkish_fluency": 6,
                "overall_score": 6.0,
                "status": "borderline",
                "feedback": "Birim eksik, cerrahi düzeltme yapıldı.",
                "rewritten_chosen": "fc = 1 / (2*pi*R*C) [Birim: Hz]"
            }
        }

        engine = JudgeEngine(self.config)
        stats = engine.judge_all(limit=10, mode="hybrid_editor")

        self.assertGreaterEqual(stats["rewritten"], 1)

        conn = sqlite3.connect(self.temp_db.name)
        cur = conn.cursor()
        cur.execute("SELECT judge_score, judge_status, tr_dpo_pairs FROM enrichments WHERE id = 2")
        row = cur.fetchone()
        conn.close()

        self.assertEqual(row[0], 6.0)
        self.assertEqual(row[1], "borderline")
        updated_tr_dpo = json.loads(row[2])
        self.assertEqual(updated_tr_dpo[0]["chosen"], "fc = 1 / (2*pi*R*C) [Birim: Hz]")

    @patch("pipeline.gemini_client.GeminiClient.generate_content")
    def test_judge_all_hybrid_editor_sft_fallback(self, mock_generate):
        """Verifies hybrid_editor mode updates tr_sft_qa and creates tr_dpo_pairs when no DPO was present."""
        conn = sqlite3.connect(self.temp_db.name)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO enrichments (id, article_id, sft_qa, dpo_pairs, tr_sft_qa, tr_dpo_pairs)
            VALUES (3, 1, NULL, NULL, '[{"question": "I2C saat hızı?", "answer": "100 kHz veya 400 kHz."}]', NULL)
        """)
        conn.commit()
        conn.close()

        mock_generate.return_value = {
            "success": True,
            "json_data": {
                "technical_accuracy": 6,
                "logical_consistency": 6,
                "turkish_fluency": 6,
                "overall_score": 6.0,
                "status": "borderline",
                "feedback": "Fast mode eklendi.",
                "rewritten_chosen": "Standart modda 100 kHz, Hızlı modda (Fast-mode) 400 kHz ve Fast-mode Plus'ta 1 MHz."
            }
        }

        engine = JudgeEngine(self.config)
        stats = engine.judge_all(limit=10, mode="hybrid_editor")

        self.assertGreaterEqual(stats["rewritten"], 1)

        conn = sqlite3.connect(self.temp_db.name)
        cur = conn.cursor()
        cur.execute("SELECT judge_score, judge_status, tr_sft_qa, tr_dpo_pairs FROM enrichments WHERE id = 3")
        row = cur.fetchone()
        conn.close()

        self.assertEqual(row[0], 6.0)
        self.assertEqual(row[1], "borderline")
        updated_sft = json.loads(row[2])
        self.assertIn("Fast-mode Plus", updated_sft[0]["answer"])
        updated_tr_dpo = json.loads(row[3])
        self.assertIn("Fast-mode Plus", updated_tr_dpo[0]["chosen"])

    @patch("httpx.Client.post")
    def test_gemini_client_model_fallback_and_retry_on_503(self, mock_post):
        """Verifies GeminiClient cascades to fallback models and retries on 503 high demand spikes."""
        from pipeline.gemini_client import GeminiClient
        client = GeminiClient(api_key="mock_key", config={"gemini_rate_limit_delay": 0.01, "gemini_max_retries": 2})

        resp_503 = MagicMock()
        resp_503.status_code = 503
        resp_503.text = "High demand spike"

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "candidates": [{
                "content": {"parts": [{"text": '{"technical_accuracy": 9, "logical_consistency": 9, "turkish_fluency": 9, "overall_score": 9.0, "status": "approved", "feedback": "Fallback model succeeded", "rewritten_chosen": null}'}]}
            }],
            "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 20}
        }

        # First model fails twice with 503, fallback model succeeds with 200
        mock_post.side_effect = [resp_503, resp_503, resp_200]

        res = client.generate_content(
            prompt="Test prompt",
            model="gemini-3.6-flash",
            purpose="test_fallback"
        )

        self.assertTrue(res["success"])
        self.assertEqual(res["model"], "gemini-2.5-flash")

if __name__ == "__main__":
    unittest.main()
