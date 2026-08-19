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

if __name__ == "__main__":
    unittest.main()
