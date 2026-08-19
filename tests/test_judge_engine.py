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

        self.assertEqual(stats["rewritten"], 1)
        self.assertEqual(stats["borderline"], 1)

if __name__ == "__main__":
    unittest.main()
