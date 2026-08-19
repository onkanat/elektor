import unittest
from unittest.mock import patch, MagicMock
import tempfile
import os
import json
from pydantic import BaseModel, Field

from pipeline.gemini_client import GeminiClient, TokenBudgetManager, MODEL_ALIASES, get_gemini_client

class DummySchema(BaseModel):
    summary: str = Field(description="Summary of text")
    score: int = Field(description="Score between 1 and 10")

class TestGeminiClient(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.config = {
            "gemini_api_key": "AIzaSy_fake_test_key",
            "gemini_model": "gemini-3.6-flash",
            "db_path": self.temp_db.name
        }

    def tearDown(self):
        if os.path.exists(self.temp_db.name):
            os.unlink(self.temp_db.name)

    def test_model_aliases(self):
        client = GeminiClient(self.config)
        self.assertEqual(client._resolve_model_name("gemini-flash"), "gemini-3.6-flash")
        self.assertEqual(client._resolve_model_name("gemini-flash-lite"), "gemini-3.5-flash-lite")
        self.assertEqual(client._resolve_model_name("gemini-pro"), "gemini-2.5-pro")

    def test_budget_manager(self):
        manager = TokenBudgetManager(db_path=self.temp_db.name, max_monthly_budget_tokens=10000)
        res = manager.record_usage(model="gemini-3.6-flash", prompt_tokens=500, candidate_tokens=200, purpose="test_judge")
        self.assertEqual(res["total_tokens"], 700)
        self.assertGreater(res["cost_estimate_tl"], 0)

        consumption = manager.get_monthly_consumption()
        self.assertEqual(consumption["total_tokens"], 700)
        self.assertEqual(consumption["request_count"], 1)

    @patch("httpx.Client.post")
    def test_generate_content_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": '{"summary": "Test circuit", "score": 9}'}]
                    }
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 100,
                "candidatesTokenCount": 50
            }
        }
        mock_post.return_value = mock_resp

        client = GeminiClient(self.config)
        result = client.generate_content(
            prompt="Analyze this text",
            response_schema=DummySchema,
            purpose="test_eval"
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["json_data"]["score"], 9)
        self.assertEqual(result["usage"]["total_tokens"], 150)

    def test_no_api_key_handling(self):
        client = GeminiClient({"gemini_api_key": ""})
        self.assertFalse(client.is_available())
        res = client.generate_content("test")
        self.assertFalse(res["success"])
        self.assertIn("Gemini API key is not configured", res["error"])

if __name__ == "__main__":
    unittest.main()
