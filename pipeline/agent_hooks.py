import os
import re
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

from pipeline.project_logger import get_project_logger

class AgentHooksManager:
    """
    Manages and executes pre/post environment hooks defined in .agents/hooks.json.
    Enforces security boundaries, token caps, and automated schema/code linting.
    """
    def __init__(self, hooks_config_path: str = ".agents/hooks.json"):
        self.hooks_path = Path(hooks_config_path)
        self.logger = get_project_logger()
        self.hooks_data = self._load_hooks()

    def _load_hooks(self) -> Dict[str, Any]:
        if not self.hooks_path.exists():
            return {}
        try:
            with open(self.hooks_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.logger.warning(f"Could not parse hooks config at {self.hooks_path}: {e}", module="agent_hooks")
            return {}

    def _matches(self, matcher: str, tool_name: str) -> bool:
        if matcher == "*":
            return True
        try:
            return bool(re.search(matcher, tool_name, re.IGNORECASE))
        except Exception:
            return matcher.lower() in tool_name.lower()

    def execute_pre_hooks(self, tool_name: str, tool_args: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Executes all matching pre_tool_execution hooks.
        Returns: {"decision": "allow" | "deny", "reason": str}
        """
        payload = {
            "tool_name": tool_name,
            "tool_args": tool_args,
            "context": context or {}
        }
        payload_str = json.dumps(payload, ensure_ascii=False)

        for group_name, group_cfg in self.hooks_data.items():
            pre_hooks = group_cfg.get("pre_tool_execution", [])
            for entry in pre_hooks:
                matcher = entry.get("matcher", "*")
                if self._matches(matcher, tool_name):
                    for hook in entry.get("hooks", []):
                        cmd = hook.get("command", "")
                        timeout = float(hook.get("timeout", 10))
                        if not cmd:
                            continue

                        try:
                            proc = subprocess.run(
                                cmd,
                                shell=True,
                                input=payload_str,
                                capture_output=True,
                                text=True,
                                timeout=timeout
                            )
                            output = {}
                            if proc.stdout.strip():
                                try:
                                    output = json.loads(proc.stdout.strip())
                                except Exception:
                                    pass

                            if output.get("decision") == "deny" or proc.returncode != 0:
                                reason = output.get("reason") or proc.stderr.strip() or "Pre-tool execution denied by security hook."
                                self.logger.warning(f"Pre-tool hook '{group_name}' DENIED '{tool_name}': {reason}", module="agent_hooks")
                                return {"decision": "deny", "reason": reason}

                        except subprocess.TimeoutExpired:
                            reason = f"Pre-tool hook timed out after {timeout}s"
                            self.logger.error(reason, module="agent_hooks")
                            return {"decision": "deny", "reason": reason}
                        except Exception as e:
                            self.logger.warning(f"Pre-tool hook execution error: {e}", module="agent_hooks")

        return {"decision": "allow", "reason": "Pre-tool hooks passed."}

    def execute_post_hooks(self, tool_name: str, tool_output: Any, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Executes all matching post_tool_execution hooks.
        Returns: {"status": "passed" | "failed" | "warning", "lint_results": [...]}
        """
        payload = {
            "tool_name": tool_name,
            "tool_output": tool_output,
            "context": context or {}
        }
        payload_str = json.dumps(payload, ensure_ascii=False)
        aggregated_results = []

        for group_name, group_cfg in self.hooks_data.items():
            post_hooks = group_cfg.get("post_tool_execution", [])
            for entry in post_hooks:
                matcher = entry.get("matcher", "*")
                if self._matches(matcher, tool_name):
                    for hook in entry.get("hooks", []):
                        cmd = hook.get("command", "")
                        timeout = float(hook.get("timeout", 15))
                        if not cmd:
                            continue

                        try:
                            proc = subprocess.run(
                                cmd,
                                shell=True,
                                input=payload_str,
                                capture_output=True,
                                text=True,
                                timeout=timeout
                            )
                            if proc.stdout.strip():
                                try:
                                    res_json = json.loads(proc.stdout.strip())
                                    aggregated_results.append(res_json)
                                except Exception:
                                    aggregated_results.append({"raw_output": proc.stdout.strip()})
                        except Exception as e:
                            self.logger.warning(f"Post-tool hook error in '{group_name}': {e}", module="agent_hooks")

        overall_status = "passed"
        for item in aggregated_results:
            if item.get("status") == "failed" or item.get("errors"):
                overall_status = "failed"
                break
            elif item.get("status") == "warning" or item.get("warnings"):
                overall_status = "warning"

        return {
            "status": overall_status,
            "lint_results": aggregated_results
        }

_hooks_manager_instance = None

def get_agent_hooks_manager() -> AgentHooksManager:
    """Returns singleton instance of AgentHooksManager."""
    global _hooks_manager_instance
    if _hooks_manager_instance is None:
        _hooks_manager_instance = AgentHooksManager()
    return _hooks_manager_instance
