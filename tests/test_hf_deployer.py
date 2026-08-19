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
        self.assertIn("sft_dataset.jsonl", card)
        self.assertIn("username/test_proj", card)

if __name__ == "__main__":
    unittest.main()
