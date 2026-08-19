import unittest
import json
import tempfile
import os
from pipeline.agent_hooks import AgentHooksManager

class TestAgentHooks(unittest.TestCase):
    def setUp(self):
        self.hooks_mgr = AgentHooksManager()

    def test_pre_hook_allows_safe_tool(self):
        res = self.hooks_mgr.execute_pre_hooks(
            tool_name="code_execution",
            tool_args={"command": "python3 -c 'print(1+1)'"}
        )
        self.assertEqual(res["decision"], "allow")

    def test_pre_hook_denies_destructive_command(self):
        res = self.hooks_mgr.execute_pre_hooks(
            tool_name="code_execution",
            tool_args={"command": "rm -rf / --no-preserve-root"}
        )
        self.assertEqual(res["decision"], "deny")
        self.assertIn("Prohibited dangerous pattern", res["reason"])

    def test_post_hook_lints_python_syntax(self):
        valid_content = "Here is the code:\n```python\ndef test():\n    return 42\n```"
        res = self.hooks_mgr.execute_post_hooks(
            tool_name="enrich",
            tool_output=valid_content
        )
        self.assertIn(res["status"], ["passed", "warning"])

    def test_post_hook_detects_syntax_error(self):
        invalid_content = "Broken code:\n```python\ndef bad_syntax(\n```"
        res = self.hooks_mgr.execute_post_hooks(
            tool_name="enrich",
            tool_output=invalid_content
        )
        self.assertEqual(res["status"], "failed")

if __name__ == "__main__":
    unittest.main()
