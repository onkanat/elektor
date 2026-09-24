import unittest
import json
import sqlite3
import tempfile
from pathlib import Path
from pipeline.dataset_builder import DatasetBuilder

class TestBoilerplateCleaner(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.config_path = Path(self.temp_dir.name) / "config.json"
        
        cfg = {
            "db_path": str(self.db_path),
            "dataset_name": "test_mcu",
            "dataset_name_tr": "test_mcu",
            "generation_language": "bilingual",
            "clean_alpaca_input": True,
            "filter_boilerplate": True
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
            
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT,
                filename TEXT,
                title TEXT,
                year INTEGER,
                zoom_snippet TEXT,
                extracted_text TEXT,
                is_ocr INTEGER,
                processed_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE enrichments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER UNIQUE,
                summary TEXT,
                topics TEXT,
                turkish_title TEXT,
                turkish_summary TEXT,
                sft_qa TEXT,
                dpo_pairs TEXT,
                tr_sft_qa TEXT,
                tr_dpo_pairs TEXT,
                multi_turn_chat TEXT,
                tr_multi_turn_chat TEXT,
                is_excluded INTEGER DEFAULT 0,
                processed_at TEXT
            )
        """)
        
        # Article 1: Colophon / Legal boilerplate
        c.execute("""
            INSERT INTO articles (id, file_path, filename, title, year, extracted_text)
            VALUES (1, 'doc1.pdf', 'doc1.pdf', 'RP2040 Datasheet: Colophon', 2026, 'Colophon © 2025 Raspberry Pi Ltd. This documentation is licensed under Creative Commons CC BY-ND 4.0.')
        """, )
        sft_colophon = json.dumps([
            {"question": "What license is used for the RP2040 datasheet?", "answer": "It is licensed under CC BY-ND 4.0."},
            {"question": "Who owns Synopsys copyright?", "answer": "Portions are copyright Synopsys Inc."}
        ])
        dpo_colophon = json.dumps([{
            "question": "Is the RP2040 suitable for high risk activities?",
            "chosen": "No, disclaimer excludes high risk activities.",
            "rejected": "Yes, it is guaranteed for everything."
        }])
        c.execute("""
            INSERT INTO enrichments (id, article_id, summary, sft_qa, dpo_pairs, is_excluded)
            VALUES (1, 1, 'Colophon and legal summary', ?, ?, 0)
        """, (sft_colophon, dpo_colophon))
        
        # Article 2: Technical architecture
        c.execute("""
            INSERT INTO articles (id, file_path, filename, title, year, extracted_text)
            VALUES (2, 'doc2.pdf', 'doc2.pdf', 'Chapter 1: System Architecture', 2026, 'The RP2040 features dual Cortex-M0+ cores and 264kB of SRAM in 6 banks.')
        """, )
        sft_tech = json.dumps([
            {"question": "How many cores does the RP2040 have?", "answer": "It has dual ARM Cortex-M0+ cores."},
            {"question": "What is the memory size?", "answer": "It has 264kB SRAM organized into 6 banks."}
        ])
        dpo_tech = json.dumps([{
            "question": "Can the cores run at 133MHz?",
            "chosen": "Yes, both cores can run at 133MHz.",
            "rejected": "No, they only run at 12MHz."
        }])
        c.execute("""
            INSERT INTO enrichments (id, article_id, summary, sft_qa, dpo_pairs, is_excluded)
            VALUES (2, 2, 'Technical architecture of RP2040', ?, ?, 0)
        """, (sft_tech, dpo_tech))
        
        conn.commit()
        conn.close()
        
    def tearDown(self):
        self.temp_dir.cleanup()
        
    def test_clean_database_boilerplate_and_export(self):
        builder = DatasetBuilder(config_path=str(self.config_path))
        
        # Test cleaning database
        res = builder.clean_database_boilerplate()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["excluded_articles"], 1)
        
        # Verify Article 1 is marked as is_excluded = 1
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT is_excluded FROM enrichments WHERE article_id = 1")
        self.assertEqual(c.fetchone()[0], 1)
        c.execute("SELECT is_excluded FROM enrichments WHERE article_id = 2")
        self.assertEqual(c.fetchone()[0], 0)
        conn.close()
        
        # Test export datasets
        builder.export_datasets()
        
        sft_file = builder.export_dir / "sft_dataset.jsonl"
        dpo_file = builder.export_dir / "dpo_dataset.jsonl"
        
        self.assertTrue(sft_file.exists())
        self.assertTrue(dpo_file.exists())
        
        with open(sft_file, "r", encoding="utf-8") as f:
            sft_lines = [json.loads(line) for line in f]
            
        with open(dpo_file, "r", encoding="utf-8") as f:
            dpo_lines = [json.loads(line) for line in f]
            
        # Verify SFT records do not contain boilerplate, and have clean empty input
        for rec in sft_lines:
            self.assertEqual(rec["input"], "")
            self.assertNotIn("license", rec["instruction"].lower())
            self.assertNotIn("synopsys", rec["instruction"].lower())
            
        # Verify DPO records do not have 'input' field and do not contain boilerplate
        for rec in dpo_lines:
            self.assertNotIn("input", rec)
            self.assertNotIn("high risk activities", rec["prompt"].lower())
            self.assertIn("133mhz", rec["prompt"].lower())

if __name__ == "__main__":
    unittest.main()
