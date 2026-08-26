import unittest
import os
import json
import sqlite3
import tempfile
from pathlib import Path

from pipeline.kiwix_extractor import KiwixZimExtractor, clean_html_fragment
from pipeline.dataset_builder import DatasetBuilder


class TestKiwixExtractor(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_db_path = Path(self.temp_dir.name) / "test_kiwix.db"
        self.config_path = Path(self.temp_dir.name) / "config.json"
        self.config = {
            "project_id": "test_kiwix_proj",
            "db_path": str(self.temp_db_path),
            "kiwix_zim_path": "downloads/ham.stackexchange.com_en_all_2026-02.zim",
            "kiwix_extract_mode": "auto",
            "kiwix_min_chars": 50,
            "kiwix_batch_size": 10,
            "generation_language": "bilingual",
            "enable_langextract": False
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_clean_html_fragment_code_and_math(self):
        """Test clean_html_fragment converts code blocks, inline code, and math properly."""
        raw_html = """
        <p>Here is an explanation of <code>RF Mixer</code> circuits:</p>
        <pre><code class="lang-python">
        def calculate_impedance(r, x):
            return complex(r, x)
        </code></pre>
        <p>The formula for resonance is <span class="math-container">f = \\frac{1}{2\\pi\\sqrt{LC}}</span>.</p>
        <ul>
            <li>First point &amp; detail</li>
            <li>Second point &lt; 50 Ohm</li>
        </ul>
        <blockquote>High frequency signal warning</blockquote>
        """
        cleaned = clean_html_fragment(raw_html)
        self.assertIn("```python", cleaned)
        self.assertIn("def calculate_impedance", cleaned)
        self.assertIn("`RF Mixer`", cleaned)
        self.assertIn("$f = \\frac{1}{2\\pi\\sqrt{LC}}$", cleaned)
        self.assertIn("* First point & detail", cleaned)
        self.assertIn("> High frequency signal warning", cleaned)

    def test_02_parse_stackexchange_html(self):
        """Test parse_stackexchange_html extracts question tags, votes, accepted answer, and DPO pairs."""
        extractor = KiwixZimExtractor(config_path=str(self.config_path))

        mock_se_html = """
        <h1 id="question-header">How to design a 20m Dipole Antenna?</h1>
        <div id="question" class="question" data-questionid="101" data-score="14">
            <div class="post-taglist">
                <a href="/tags/antennas" class="post-tag">antennas</a>
                <a href="/tags/hf" class="post-tag">hf</a>
                <a href="/tags/dipole" class="post-tag">dipole</a>
            </div>
            <div class="post-text">
                <p>I want to construct a half-wave dipole for 14.150 MHz. What is the formula?</p>
            </div>
        </div>
        <div id="answer-201" class="answer accepted-answer" data-answerid="201" data-score="25">
            <div class="post-text">
                <p>For a half-wave wire dipole, length in feet is <code>468 / f(MHz)</code>. For 14.15 MHz, length is 33.07 feet.</p>
            </div>
        </div>
        <div id="answer-202" class="answer" data-answerid="202" data-score="1">
            <div class="post-text">
                <p>Just cut a random wire and attach a tuner.</p>
            </div>
        </div>
        """

        parsed = extractor.parse_stackexchange_html(mock_se_html, title="How to design a 20m Dipole Antenna?")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["title"], "How to design a 20m Dipole Antenna?")
        self.assertEqual(parsed["tags"], ["antennas", "hf", "dipole"])
        self.assertEqual(parsed["vote_score"], 14)
        self.assertEqual(parsed["is_accepted"], 1)
        self.assertEqual(len(parsed["answers"]), 2)

        # SFT QA
        sft = parsed["sft_qa"]
        self.assertIsNotNone(sft)
        self.assertIn("468 / f(MHz)", sft["answer"])

        # DPO pair
        dpo = parsed["dpo_pairs"]
        self.assertEqual(len(dpo), 1)
        self.assertIn("468 / f(MHz)", dpo[0]["chosen"])
        self.assertIn("random wire", dpo[0]["rejected"])
        self.assertEqual(dpo[0]["chosen_score"], 25)
        self.assertEqual(dpo[0]["rejected_score"], 1)

        extractor.close()

    def test_03_real_zim_batch_extraction_and_dataset_export(self):
        """Integration test on real downloads/ham.stackexchange.com_en_all_2026-02.zim archive."""
        zim_file = Path("downloads/ham.stackexchange.com_en_all_2026-02.zim")
        if not zim_file.exists():
            self.skipTest("Real ZIM archive not found in downloads/")

        extractor = KiwixZimExtractor(config_path=str(self.config_path))
        try:
            count = extractor.extract_from_zim(zim_path=str(zim_file), limit=5)
        finally:
            extractor.close()

        self.assertGreater(count, 0, "Should extract at least 1 article from ZIM")

        # Verify SQLite DB contents
        conn = sqlite3.connect(str(self.temp_db_path))
        cur = conn.cursor()
        cur.execute("SELECT count(*), source_type, tags, metadata_json FROM articles WHERE source_type='stackexchange'")
        res = cur.fetchone()
        self.assertIsNotNone(res)
        se_count, stype, tags, meta = res
        self.assertGreater(se_count, 0)
        self.assertEqual(stype, "stackexchange")
        conn.close()

        # Test DatasetBuilder export from the Kiwix data
        builder = DatasetBuilder(config_path=str(self.config_path))
        builder.export_datasets()

        export_dir = Path("exports") / "test_kiwix.db" if (Path("exports") / "test_kiwix.db").exists() else Path("exports") / "test_kiwix_proj"
        # Check if sft_dataset.jsonl exists in the export dir
        sft_file = Path("exports") / "test_kiwix" / "sft_dataset.jsonl"
        # Find any generated export
        generated_files = list(Path("exports").glob("**/sft_dataset.jsonl"))
        self.assertTrue(len(generated_files) > 0, "At least one sft_dataset.jsonl should be exported")
        print(f"\n[Kiwix & DatasetBuilder Test Passed] Extracted {count} articles and exported datasets successfully.")


if __name__ == "__main__":
    unittest.main()
