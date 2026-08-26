import unittest
import tempfile
import os
import json
from pathlib import Path
from pipeline.cloud_gpu_offloader import CloudGPUOffloader

class TestCloudGPUOffloader(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.offloader = CloudGPUOffloader(exports_dir=self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_generate_payload_includes_vertex_and_unsloth(self):
        res = self.offloader.generate_payload(
            project_id="test_proj",
            base_model="Qwen/Qwen2.5-Coder-7B-Instruct",
            hf_dataset="username/test_proj"
        )
        self.assertEqual(res["status"], "success")
        self.assertIn("vertex_ai_tuning.json", res["generated_files"])
        self.assertIn("unsloth_finetune.py", res["generated_files"])

        payload_dir = Path(res["payload_dir"])
        vertex_file = payload_dir / "vertex_ai_tuning.json"
        self.assertTrue(vertex_file.exists())
        
        with open(vertex_file, "r", encoding="utf-8") as f:
            v_data = json.load(f)
            self.assertEqual(v_data["tuning_job_name"], "test_proj-gemini-sft")

    def test_generate_colab_ide_notebook_types(self):
        for dtype, expected_str in [
            ("sft", "SFTTrainer"),
            ("dpo", "DPOTrainer"),
            ("chat", "Chat"),
            ("langextract", "LangExtract")
        ]:
            nb = self.offloader.generate_colab_ide_notebook(
                project_id="test_colab",
                base_model="unsloth/Qwen3.5-2B",
                hf_dataset="onkanat/test_colab-dataset",
                dataset_type=dtype
            )
            self.assertEqual(nb["nbformat"], 4)
            self.assertEqual(len(nb["cells"]), 7)
            # Verify Open in Colab badge in header cell
            header_text = "".join(nb["cells"][0]["source"])
            self.assertIn("Open In Colab", header_text)
            self.assertIn("Antigravity-IDE", header_text)
            self.assertIn("unsloth/Qwen3.5-2B", header_text)

    def test_generate_all_colab_notebooks(self):
        res = self.offloader.generate_all_colab_notebooks(
            project_id="test_all_types",
            base_model="unsloth/Qwen3.5-2B",
            hf_dataset="onkanat/test_all_types"
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(len(res["generated_notebooks"]), 4)
        for dtype, filename in res["generated_notebooks"].items():
            filepath = Path(res["payload_dir"]) / filename
            self.assertTrue(filepath.exists(), f"Notebook {filename} should exist on disk")
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.assertEqual(data["nbformat"], 4)

if __name__ == "__main__":
    unittest.main()
