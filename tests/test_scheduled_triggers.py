import unittest
from unittest.mock import patch, MagicMock
import tempfile
import os
import sqlite3

from pipeline.scheduled_triggers import ScheduledTriggersManager

class TestScheduledTriggers(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        
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
                tr_dpo_pairs TEXT,
                judge_status TEXT
            )
        """)
        cur.execute("INSERT INTO articles (id, title) VALUES (1, 'DSP Filter')")
        cur.execute("""
            INSERT INTO enrichments (id, article_id, sft_qa, dpo_pairs, judge_status)
            VALUES (1, 1, '[{"question": "What is FIR?", "answer": "Finite Impulse Response filter."}]', NULL, NULL)
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
    def test_trigger_audit_pass(self, mock_generate):
        mock_generate.return_value = {
            "success": True,
            "json_data": {
                "technical_accuracy": 9,
                "logical_consistency": 9,
                "turkish_fluency": 9,
                "overall_score": 9.0,
                "status": "approved",
                "feedback": "Clear DSP explanation",
                "rewritten_chosen": None
            }
        }

        manager = ScheduledTriggersManager(self.config)
        res = manager.run_trigger_audit_pass(limit=10, mode="strict")

        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["stats"]["approved"], 1)

    def test_trigger_when_all_judged(self):
        # Mark record as already judged
        conn = sqlite3.connect(self.temp_db.name)
        conn.execute("UPDATE enrichments SET judge_status = 'approved' WHERE id = 1")
        conn.commit()
        conn.close()

        manager = ScheduledTriggersManager(self.config)
        res = manager.run_trigger_audit_pass(limit=10, mode="strict")
        self.assertEqual(res["status"], "up_to_date")

    @patch("pipeline.judge_engine.JudgeEngine.judge_batch_submit")
    def test_trigger_batch_mode(self, mock_batch_submit):
        mock_batch_submit.return_value = {
            "status": "submitted",
            "job_id": "batches/trigger_batch_001",
            "total_requests": 1
        }

        manager = ScheduledTriggersManager(self.config)
        res = manager.run_trigger_audit_pass(limit=10, mode="strict", use_batch_api=True)
        self.assertEqual(res["status"], "batch_submitted")
        self.assertEqual(res["batch_job"]["job_id"], "batches/trigger_batch_001")

if __name__ == "__main__":
    unittest.main()
