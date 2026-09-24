import unittest
import tempfile
import os
from pathlib import Path
from pipeline.hf_deployer import HFDeployer

class TestHFDeployer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.deployer = HFDeployer(exports_dir=self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_generate_dataset_card(self):
        proj_dir = Path(self.temp_dir.name) / "test_proj"
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "sft_dataset.jsonl").write_text("{}", encoding="utf-8")
        (proj_dir / "multimodal_visual_dataset.jsonl").write_text("{}", encoding="utf-8")

        card = self.deployer.generate_dataset_card(
            project_id="test_proj",
            dataset_name="Test Project Dataset",
            repo_id="username/test_proj",
            stats={"sft_samples": 100, "visual_samples": 20}
        )

        self.assertIn("Test Project Dataset", card)
        self.assertIn("multimodal_visual_dataset.jsonl", card)
    def test_audit_upload_generates_readme_and_modern_command(self):
        proj_dir = Path(self.temp_dir.name) / "test_proj"
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "sft_dataset.jsonl").write_text('{"instruction":"hi","output":"hello"}\n', encoding="utf-8")

        audit_res = self.deployer.audit_upload(
            project_id="test_proj",
            repo_id="onkanat/amateur-radio-qa-dataset"
        )

        self.assertEqual(audit_res["status"], "passed")
        self.assertTrue(audit_res["can_proceed"])
        # Check modern CLI command
        self.assertTrue(audit_res["cli_command"].startswith("hf upload onkanat/amateur-radio-qa-dataset"))
        self.assertNotIn("huggingface-cli", audit_res["cli_command"])
        
        # Check README.md file is created on disk
        readme_file = proj_dir / "README.md"
        self.assertTrue(readme_file.exists())
        readme_text = readme_file.read_text(encoding="utf-8")
        self.assertIn("Amateur Radio & Electronics QA Dataset", readme_text)
        self.assertIn("license: cc-by-sa-4.0", readme_text)
        self.assertIn("onkanat/amateur-radio-qa-dataset", readme_text)

if __name__ == "__main__":
    unittest.main()

