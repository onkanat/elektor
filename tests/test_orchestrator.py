import unittest
import tempfile
import json
import sqlite3
from pathlib import Path
from tools.orchestrator import UniversalDatasetOrchestrator

class TestUniversalDatasetOrchestrator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.orch = UniversalDatasetOrchestrator(base_dir=self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_isolated_config(self):
        cfg_path = self.orch.create_isolated_config(
            input_source="downloads/sample.pdf",
            input_mode="book",
            project_name="sample_test"
        )
        self.assertTrue(cfg_path.exists())
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data["project_id"], "sample_test")
            self.assertEqual(data["input_mode"], "book")
            self.assertEqual(data["db_path"], "database/sample_test.db")
            self.assertTrue(data["sqlite_wal_mode"])

        # Verify DB file was created with WAL mode
        db_path = self.base_dir / "database/sample_test.db"
        self.assertTrue(db_path.exists())

    def test_compile_dpo_and_golden_sft(self):
        # Create a mock database with enrichments
        db_path = self.base_dir / "database/orch_test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE enrichments (
                id INTEGER PRIMARY KEY,
                article_id INTEGER,
                prompt_sft TEXT,
                response_sft TEXT,
                prompt_dpo TEXT,
                chosen_dpo TEXT,
                rejected_dpo TEXT,
                judge_score REAL,
                judge_feedback TEXT
            );
        """)

        # Insert 1 high score record, 1 low score record
        conn.execute("""
            INSERT INTO enrichments (article_id, prompt_sft, response_sft, prompt_dpo, chosen_dpo, rejected_dpo, judge_score)
            VALUES 
            (1, 'Soru 1', 'Mükemmel Yanıt 1', 'DPO Soru 1', 'İyi Yanıt 1', 'Kötü Yanıt 1', 8.5),
            (2, 'Soru 2', 'Zayıf Yanıt 2', 'DPO Soru 2', 'İyi Yanıt 2', 'Kötü Yanıt 2', 5.0);
        """)
        conn.commit()
        conn.close()

        res = self.orch.compile_dpo_and_golden_sft(
            project_name="orch_test",
            min_score_diff=2.0,
            min_golden_score=7.5
        )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["dpo_records_compiled"], 2)
        self.assertEqual(res["golden_sft_records_compiled"], 1) # only score 8.5 >= 7.5

        dpo_file = Path(res["dpo_file"])
        sft_file = Path(res["golden_sft_file"])
        self.assertTrue(dpo_file.exists())
        self.assertTrue(sft_file.exists())

        # Verify JSONL lines
        with open(sft_file, "r", encoding="utf-8") as f:
            lines = [json.loads(l) for l in f]
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["output"], "Mükemmel Yanıt 1")

    def test_get_status(self):
        self.orch.create_isolated_config(
            input_source="downloads/test.pdf",
            input_mode="book",
            project_name="status_check"
        )
        st = self.orch.get_status()
        self.assertIn("gpu_endpoints", st)
        self.assertIn("active_projects", st)
        self.assertEqual(st["total_projects"], 1)
        self.assertEqual(st["active_projects"][0]["project_id"], "status_check")

if __name__ == "__main__":
    unittest.main()
