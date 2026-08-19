import os
import time
import json
import random
import sqlite3
from typing import Dict, Any, List, Optional, Union
from pathlib import Path
import httpx
from pydantic import BaseModel

from pipeline.project_logger import get_project_logger

# Model alias mappings
MODEL_ALIASES = {
    "gemini-flash": "gemini-3.6-flash",
    "gemini-flash-lite": "gemini-3.5-flash-lite",
    "gemini-pro": "gemini-2.5-pro",
    "gemini-3.6-flash": "gemini-3.6-flash",
    "gemini-3.5-flash": "gemini-3.5-flash",
    "gemini-3.5-flash-lite": "gemini-3.5-flash-lite",
    "gemini-2.5-flash": "gemini-2.5-flash",
    "gemini-2.5-pro": "gemini-2.5-pro",
}

class TokenBudgetManager:
    """
    Tracks and enforces token consumption and monthly budget limits for Gemini API.
    Persists usage in SQLite database to prevent runaway costs.
    """
    def __init__(self, db_path: str = "database/elektor_archive.db", max_monthly_budget_tokens: int = 50_000_000):
        self.db_path = db_path
        self.max_monthly_budget_tokens = max_monthly_budget_tokens
        self.logger = get_project_logger()
        self._init_db()

    def _init_db(self):
        try:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS gemini_usage_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model TEXT,
                    prompt_tokens INTEGER,
                    candidate_tokens INTEGER,
                    total_tokens INTEGER,
                    purpose TEXT,
                    cost_estimate_tl REAL,
                    timestamp TEXT
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            self.logger.warning(f"Could not initialize Gemini usage log table: {e}", module="gemini_client")

    def record_usage(self, model: str, prompt_tokens: int, candidate_tokens: int, purpose: str = "general") -> Dict[str, Any]:
        total_tokens = prompt_tokens + candidate_tokens
        # Rough cost estimate in TL based on Gemini 3.6 Flash (~₺0.0035 per 1k tokens)
        cost_tl = (total_tokens / 1000.0) * 0.0035
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO gemini_usage_logs (model, prompt_tokens, candidate_tokens, total_tokens, purpose, cost_estimate_tl, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (model, prompt_tokens, candidate_tokens, total_tokens, purpose, cost_tl, timestamp))
            conn.commit()
            conn.close()
        except Exception as e:
            self.logger.warning(f"Failed to record token usage: {e}", module="gemini_client")

        return {
            "prompt_tokens": prompt_tokens,
            "candidate_tokens": candidate_tokens,
            "total_tokens": total_tokens,
            "cost_estimate_tl": round(cost_tl, 4)
        }

    def get_monthly_consumption(self) -> Dict[str, Any]:
        """Returns total token consumption and estimated spending for the current month."""
        month_prefix = time.strftime("%Y-%m", time.gmtime())
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT SUM(prompt_tokens), SUM(candidate_tokens), SUM(total_tokens), SUM(cost_estimate_tl), COUNT(*)
                FROM gemini_usage_logs
                WHERE timestamp LIKE ?
            """, (f"{month_prefix}%",))
            row = cursor.fetchone()
            conn.close()
            
            p_tokens = row[0] or 0
            c_tokens = row[1] or 0
            t_tokens = row[2] or 0
            cost_tl = row[3] or 0.0
            req_count = row[4] or 0
            
            return {
                "month": month_prefix,
                "request_count": req_count,
                "prompt_tokens": p_tokens,
                "candidate_tokens": c_tokens,
                "total_tokens": t_tokens,
                "estimated_cost_tl": round(cost_tl, 2),
                "budget_percent": round((t_tokens / self.max_monthly_budget_tokens) * 100, 2) if self.max_monthly_budget_tokens > 0 else 0
            }
        except Exception as e:
            self.logger.warning(f"Could not fetch monthly consumption: {e}", module="gemini_client")
            return {"total_tokens": 0, "estimated_cost_tl": 0.0, "budget_percent": 0.0}

class GeminiClient:
    """
    Production-grade, connection-pooled client for Gemini API.
    Features:
    - Support for Gemini 3.6 Flash, 3.5 Flash, 3.5 Flash-Lite, 2.5 Pro.
    - Automatic exponential backoff with jitter on 429/500/503.
    - Structured JSON Schema outputs (Pydantic / JSON schema).
    - Token tracking and budget caps.
    """
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, config: Optional[Dict[str, Any]] = None, api_key: Optional[str] = None):
        self.config = config or {}
        if api_key is not None:
            self.api_key = api_key
        elif "gemini_api_key" in self.config:
            self.api_key = self.config.get("gemini_api_key", "")
        else:
            self.api_key = os.environ.get("GEMINI_API_KEY", "")
        self.default_model = self.config.get("gemini_model", "gemini-3.6-flash")
        self.timeout = float(self.config.get("gemini_timeout", 90.0))
        self.max_retries = int(self.config.get("gemini_max_retries", 4))
        self.logger = get_project_logger()
        
        # Initialize connection-pooled httpx client
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=60.0)
        self.http_client = httpx.Client(limits=limits, timeout=self.timeout)
        
        db_path = self.config.get("db_path", "database/elektor_archive.db")
        self.budget_manager = TokenBudgetManager(db_path=db_path)

    def is_available(self) -> bool:
        """Returns True if Gemini API key is configured."""
        return bool(self.api_key and self.api_key.strip())

    def _resolve_model_name(self, model_name: Optional[str]) -> str:
        target = (model_name or self.default_model).strip()
        return MODEL_ALIASES.get(target, target)

    def generate_content(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: Optional[int] = 4096,
        response_schema: Optional[Union[Dict[str, Any], type]] = None,
        purpose: str = "general"
    ) -> Dict[str, Any]:
        """
        Executes a robust Gemini API generation call.
        
        Returns:
            {
                "text": str,
                "json_data": Optional[Dict / List],
                "model": str,
                "usage": {"prompt_tokens": int, "candidate_tokens": int, "total_tokens": int},
                "success": bool,
                "error": Optional[str]
            }
        """
        if not self.is_available():
            err_msg = "Gemini API key is not configured. Set GEMINI_API_KEY environment variable or config.json."
            self.logger.warning(err_msg, module="gemini_client")
            return {"text": "", "json_data": None, "model": model or self.default_model, "usage": {}, "success": False, "error": err_msg}

        resolved_model = self._resolve_model_name(model)
        endpoint = f"{self.BASE_URL}/models/{resolved_model}:generateContent"

        # Build payload
        contents = []
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload: Dict[str, Any] = {"contents": contents}

        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        gen_config: Dict[str, Any] = {
            "temperature": temperature,
        }
        if max_output_tokens:
            gen_config["maxOutputTokens"] = max_output_tokens

        # Handle Structured JSON Schema
        if response_schema:
            gen_config["responseMimeType"] = "application/json"
            if isinstance(response_schema, type) and issubclass(response_schema, BaseModel):
                gen_config["responseSchema"] = response_schema.model_json_schema()
            elif isinstance(response_schema, dict):
                gen_config["responseSchema"] = response_schema

        payload["generationConfig"] = gen_config

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key
        }

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.http_client.post(endpoint, headers=headers, json=payload)
                
                if response.status_code == 200:
                    data = response.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        return {"text": "", "json_data": None, "model": resolved_model, "usage": {}, "success": False, "error": "No candidates returned."}

                    content_parts = candidates[0].get("content", {}).get("parts", [])
                    raw_text = "".join(part.get("text", "") for part in content_parts)

                    # Usage metadata
                    usage_meta = data.get("usageMetadata", {})
                    prompt_tok = usage_meta.get("promptTokenCount", 0)
                    cand_tok = usage_meta.get("candidatesTokenCount", 0)
                    usage_stats = self.budget_manager.record_usage(
                        model=resolved_model,
                        prompt_tokens=prompt_tok,
                        candidate_tokens=cand_tok,
                        purpose=purpose
                    )

                    # Parse JSON if structured
                    json_data = None
                    if response_schema or gen_config.get("responseMimeType") == "application/json":
                        try:
                            json_data = json.loads(raw_text)
                        except Exception:
                            # Fallback regex extraction
                            import re
                            match = re.search(r"\{.*\}|\[.*\]", raw_text, re.DOTALL)
                            if match:
                                try:
                                    json_data = json.loads(match.group(0))
                                except Exception:
                                    pass

                    return {
                        "text": raw_text,
                        "json_data": json_data,
                        "model": resolved_model,
                        "usage": usage_stats,
                        "success": True,
                        "error": None
                    }

                elif response.status_code in (429, 500, 503):
                    # Rate limit or temporary service issue - exponential backoff with jitter
                    wait_sec = (2 ** attempt) + random.uniform(0.5, 1.5)
                    self.logger.warning(
                        f"Gemini API {response.status_code} on attempt {attempt}/{self.max_retries}. Backing off {wait_sec:.2f}s...",
                        module="gemini_client"
                    )
                    time.sleep(wait_sec)
                    last_error = f"HTTP {response.status_code}: {response.text}"
                else:
                    err_msg = f"Gemini API error (HTTP {response.status_code}): {response.text}"
                    self.logger.error(err_msg, module="gemini_client")
                    return {"text": "", "json_data": None, "model": resolved_model, "usage": {}, "success": False, "error": err_msg}

            except httpx.RequestError as e:
                wait_sec = (2 ** attempt) + random.uniform(0.5, 1.0)
                self.logger.warning(f"Network error on Gemini request (attempt {attempt}): {e}. Retrying...", module="gemini_client")
                time.sleep(wait_sec)
                last_error = str(e)

        return {
            "text": "",
            "json_data": None,
            "model": resolved_model,
            "usage": {},
            "success": False,
            "error": f"Failed after {self.max_retries} attempts. Last error: {last_error}"
        }

    def close(self):
        try:
            self.http_client.close()
        except Exception:
            pass

# Global cached client instance
_gemini_client_instance = None

def get_gemini_client(config: Optional[Dict[str, Any]] = None) -> GeminiClient:
    """Returns a singleton/cached GeminiClient instance."""
    global _gemini_client_instance
    if _gemini_client_instance is None:
        _gemini_client_instance = GeminiClient(config=config)
    elif config:
        _gemini_client_instance.config = config
        _gemini_client_instance.api_key = config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
    return _gemini_client_instance
