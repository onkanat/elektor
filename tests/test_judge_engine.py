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

if __name__ == "__main__":
    unittest.main()
