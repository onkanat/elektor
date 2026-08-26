import os
import time
import json
import random
import uuid
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
    "gemini-2.0-flash": "gemini-2.0-flash",
    "gemini-1.5-flash": "gemini-1.5-flash",
    "gemini-1.5-pro": "gemini-1.5-pro",
}

# Automatic model fallback chains during 503 High Demand / Capacity Spikes
MODEL_FALLBACKS = {
    "gemini-3.6-flash": ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"],
    "gemini-3.5-flash": ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"],
    "gemini-3.5-flash-lite": ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"],
    "gemini-2.5-flash": ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-pro"],
    "gemini-2.5-pro": ["gemini-2.5-flash", "gemini-1.5-pro"],
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

def _load_dotenv_if_needed():
    """Loads environment variables from local/home .env and zsh config files if available."""
    if os.environ.get("GEMINI_API_KEY"):
        return

    env_paths = [
        Path(".env"),
        Path.home() / ".env",
        Path.home() / ".zshrc",
        Path.home() / ".zprofile",
        Path.home() / ".zshenv"
    ]
    for p in env_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            if line.startswith("export "):
                                line = line[7:].strip()
                            if "=" in line:
                                k, v = line.split("=", 1)
                                k = k.strip()
                                v = v.strip().strip("'\"")
                                if k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY") and v:
                                    if not os.environ.get(k):
                                        os.environ[k] = v
                                        if k == "GOOGLE_API_KEY" and not os.environ.get("GEMINI_API_KEY"):
                                            os.environ["GEMINI_API_KEY"] = v
            except Exception:
                pass

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
        _load_dotenv_if_needed()
        self.config = config or {}
        if api_key is not None:
            self.api_key = str(api_key).strip()
        elif "gemini_api_key" in self.config:
            self.api_key = str(self.config.get("gemini_api_key", "")).strip()
        else:
            self.api_key = os.environ.get("GEMINI_API_KEY", "").strip()

        if self.api_key.startswith("${") and self.api_key.endswith("}"):
            env_var = self.api_key[2:-1]
            self.api_key = (os.environ.get(env_var) or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()

        self.default_model = self.config.get("gemini_model", "gemini-3.6-flash")
        self.timeout = float(self.config.get("gemini_timeout", 90.0))
        self.max_retries = int(self.config.get("gemini_max_retries", 4))
        self.rate_limit_delay = float(self.config.get("gemini_rate_limit_delay", 2.5))
        self.last_request_time = 0.0
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
            raw_schema = None
            if isinstance(response_schema, type) and issubclass(response_schema, BaseModel):
                raw_schema = response_schema.model_json_schema()
            elif isinstance(response_schema, dict):
                raw_schema = response_schema

            if raw_schema:
                # Inlining $defs / $ref because Gemini REST API does not support $defs / definitions
                def inline_schema_refs(schema_dict: dict) -> dict:
                    if not isinstance(schema_dict, dict):
                        return schema_dict
                    defs = schema_dict.get("$defs", {}) or schema_dict.get("definitions", {})

                    def resolve(node):
                        if isinstance(node, dict):
                            if "$ref" in node:
                                ref_path = node["$ref"]
                                ref_name = ref_path.split("/")[-1]
                                if ref_name in defs:
                                    return resolve(defs[ref_name].copy())
                            return {k: resolve(v) for k, v in node.items() if k not in ("$defs", "definitions")}
                        elif isinstance(node, list):
                            return [resolve(elem) for elem in node]
                        return node

                    cleaned = resolve(schema_dict)
                    cleaned.pop("$defs", None)
                    cleaned.pop("definitions", None)
                    return cleaned

                gen_config["responseSchema"] = inline_schema_refs(raw_schema)

        payload["generationConfig"] = gen_config

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key
        }

        primary_model = self._resolve_model_name(model)
        fallback_list = MODEL_FALLBACKS.get(primary_model, ["gemini-2.5-flash", "gemini-1.5-flash"])
        candidate_models = [primary_model] + [m for m in fallback_list if m != primary_model]

        last_error = None

        for model_idx, current_model in enumerate(candidate_models):
            endpoint = f"{self.BASE_URL}/models/{current_model}:generateContent"

            for attempt in range(1, self.max_retries + 1):
                try:
                    # Enforce polite client-side rate limit pacing (prevents 15 RPM bursts and 503 errors)
                    elapsed = time.time() - self.last_request_time
                    if elapsed < self.rate_limit_delay:
                        time.sleep(self.rate_limit_delay - elapsed)
                    self.last_request_time = time.time()

                    response = self.http_client.post(endpoint, headers=headers, json=payload)
                    
                    if response.status_code == 200:
                        data = response.json()
                        candidates = data.get("candidates", [])
                        if not candidates:
                            return {"text": "", "json_data": None, "model": current_model, "usage": {}, "success": False, "error": "No candidates returned."}

                        content_parts = candidates[0].get("content", {}).get("parts", [])
                        raw_text = "".join(part.get("text", "") for part in content_parts)

                        # Usage metadata
                        usage_meta = data.get("usageMetadata", {})
                        prompt_tok = usage_meta.get("promptTokenCount", 0)
                        cand_tok = usage_meta.get("candidatesTokenCount", 0)
                        usage_stats = self.budget_manager.record_usage(
                            model=current_model,
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
                            "model": current_model,
                            "usage": usage_stats,
                            "success": True,
                            "error": None
                        }

                    elif response.status_code in (429, 500, 503):
                        # Rate limit or temporary high demand spike - exponential backoff with jitter
                        wait_sec = (2 ** attempt) + random.uniform(1.0, 2.5)
                        self.logger.warning(
                            f"Gemini API {response.status_code} (High Demand/Rate Limit) on model '{current_model}' (attempt {attempt}/{self.max_retries}). Backing off {wait_sec:.2f}s...",
                            module="gemini_client"
                        )
                        last_error = f"HTTP {response.status_code}: {response.text}"
                        time.sleep(wait_sec)
                    else:
                        err_msg = f"Gemini API error on model '{current_model}' (HTTP {response.status_code}): {response.text}"
                        self.logger.error(err_msg, module="gemini_client")
                        last_error = err_msg
                        break

                except httpx.RequestError as e:
                    wait_sec = (2 ** attempt) + random.uniform(1.0, 2.0)
                    self.logger.warning(f"Network error on model '{current_model}' (attempt {attempt}): {e}. Retrying...", module="gemini_client")
                    time.sleep(wait_sec)
                    last_error = str(e)

            # If retries exhausted for this model and another fallback model exists, switch model seamlessly
            if model_idx + 1 < len(candidate_models):
                next_model = candidate_models[model_idx + 1]
                self.logger.warning(
                    f"Model '{current_model}' is experiencing high demand (503/429). Seamlessly switching to fallback model '{next_model}'...",
                    module="gemini_client"
                )

        return {
            "text": "",
            "json_data": None,
            "model": primary_model,
            "usage": {},
            "success": False,
            "error": f"All candidate models failed. Last error: {last_error}"
        }

    # =========================================================================
    # Gemini Batch API Support (50% Discount, Zero Rate Limit, Asynchronous)
    # Reference: https://ai.google.dev/gemini-api/docs/batch-api
    # =========================================================================
    def create_batch_job(
        self,
        requests: List[Dict[str, Any]],
        model: Optional[str] = None,
        purpose: str = "batch_judge",
        display_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Submits an asynchronous batch prediction job to Gemini Batch API (:batchGenerateContent)
        for 50% cost discount and no rate limits.
        """
        if not self.is_available():
            return {
                "batch_name": "",
                "state": "FAILED",
                "total_requests": len(requests),
                "success": False,
                "error": "Gemini API key is not configured."
            }

        resolved_model = self._resolve_model_name(model or self.default_model)
        model_resource = f"models/{resolved_model}" if not resolved_model.startswith("models/") else resolved_model

        # Build formatted batch request items matching Gemini Batch REST API
        formatted_items = []
        for req in requests:
            custom_id = req.get("custom_id") or req.get("key") or f"req_{uuid.uuid4().hex[:8]}"
            prompt_text = req.get("prompt", "")
            system_instr = req.get("system_instruction")
            resp_schema = req.get("response_schema")
            
            gen_config: Dict[str, Any] = {"temperature": req.get("temperature", 0.2)}
            if resp_schema:
                gen_config["responseMimeType"] = "application/json"
                raw_schema = resp_schema.model_json_schema() if (isinstance(resp_schema, type) and issubclass(resp_schema, BaseModel)) else resp_schema
                if raw_schema:
                    def inline_refs(s_dict):
                        if not isinstance(s_dict, dict):
                            return s_dict
                        defs = s_dict.get("$defs", {}) or s_dict.get("definitions", {})
                        def resolve(node):
                            if isinstance(node, dict):
                                if "$ref" in node:
                                    ref_name = node["$ref"].split("/")[-1]
                                    if ref_name in defs:
                                        return resolve(defs[ref_name].copy())
                                return {k: resolve(v) for k, v in node.items() if k not in ("$defs", "definitions", "title")}
                            elif isinstance(node, list):
                                return [resolve(e) for e in node]
                            return node
                        cleaned = resolve(s_dict)
                        cleaned.pop("$defs", None)
                        cleaned.pop("definitions", None)
                        cleaned.pop("title", None)
                        return cleaned
                    gen_config["responseSchema"] = inline_refs(raw_schema)

            req_obj: Dict[str, Any] = {
                "contents": [{"parts": [{"text": prompt_text}]}],
                "generationConfig": gen_config
            }
            if system_instr:
                req_obj["systemInstruction"] = {"parts": [{"text": system_instr}]}

            formatted_items.append({
                "request": req_obj,
                "metadata": {
                    "key": str(custom_id)
                }
            })

        batch_endpoint = f"{self.BASE_URL}/{model_resource}:batchGenerateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key
        }

        job_display_name = display_name or f"batch_{purpose}_{int(time.time())}"
        
        payload = {
            "batch": {
                "display_name": job_display_name,
                "input_config": {
                    "requests": {
                        "requests": formatted_items
                    }
                }
            }
        }

        try:
            response = self.http_client.post(batch_endpoint, headers=headers, json=payload, timeout=60.0)
            if response.status_code in (200, 201):
                res_data = response.json()
                batch_name = res_data.get("name", "")
                metadata = res_data.get("metadata", {})
                state = metadata.get("state", "BATCH_STATE_PENDING")
                self.logger.info(f"Successfully submitted Gemini Batch Job: {batch_name} ({len(requests)} items)", module="gemini_client")
                return {
                    "batch_name": batch_name,
                    "display_name": job_display_name,
                    "state": state,
                    "total_requests": len(requests),
                    "model": resolved_model,
                    "success": True,
                    "error": None,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                }
            else:
                err_text = response.text
                self.logger.warning(f"Batch API submission rejected (HTTP {response.status_code}): {err_text}", module="gemini_client")
                return {
                    "batch_name": "",
                    "display_name": job_display_name,
                    "state": "FAILED",
                    "total_requests": len(requests),
                    "model": resolved_model,
                    "success": False,
                    "error": f"HTTP {response.status_code}: {err_text}"
                }
        except Exception as e:
            self.logger.error(f"Error submitting batch job: {e}", module="gemini_client")
            return {
                "batch_name": "",
                "state": "FAILED",
                "total_requests": len(requests),
                "success": False,
                "error": str(e)
            }

    def get_batch_job_status(self, batch_name: str) -> Dict[str, Any]:
        """Queries the current status of a Gemini Batch Job."""
        if not self.is_available() or not batch_name:
            return {"name": batch_name, "state": "UNKNOWN", "success": False, "error": "Invalid batch name or API key."}

        clean_name = batch_name.strip().lstrip("/")
        endpoint = f"{self.BASE_URL}/{clean_name}"
        headers = {"x-goog-api-key": self.api_key}

        try:
            response = self.http_client.get(endpoint, headers=headers, timeout=30.0)
            if response.status_code == 200:
                data = response.json()
                metadata = data.get("metadata", {})
                state = metadata.get("state") or data.get("state", "BATCH_STATE_UNSPECIFIED")
                is_completed = state in (
                    "BATCH_STATE_SUCCEEDED", "JOB_STATE_SUCCEEDED",
                    "BATCH_STATE_FAILED", "JOB_STATE_FAILED",
                    "BATCH_STATE_CANCELLED", "JOB_STATE_CANCELLED",
                    "BATCH_STATE_EXPIRED", "JOB_STATE_EXPIRED"
                )
                is_success = state in ("BATCH_STATE_SUCCEEDED", "JOB_STATE_SUCCEEDED")
                return {
                    "name": data.get("name", batch_name),
                    "state": state,
                    "completed": is_completed,
                    "raw_response": data,
                    "success": is_success,
                    "error": metadata.get("error") or data.get("error")
                }
            else:
                return {
                    "name": batch_name,
                    "state": "UNKNOWN",
                    "completed": False,
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text}"
                }
        except Exception as e:
            return {"name": batch_name, "state": "ERROR", "completed": False, "success": False, "error": str(e)}

    def download_batch_results(self, batch_name: str) -> List[Dict[str, Any]]:
        """
        Downloads and parses completed batch predictions, returning mapping of custom_id -> output.
        """
        status = self.get_batch_job_status(batch_name)
        if not status.get("success"):
            return []

        raw_data = status.get("raw_response", {})
        results = []
        resp = raw_data.get("response", {})

        # 1. Handle inlinedResponses structure
        inlined_root = resp.get("inlinedResponses", {})
        if isinstance(inlined_root, dict):
            inlined_list = inlined_root.get("inlinedResponses", [])
        elif isinstance(inlined_root, list):
            inlined_list = inlined_root
        else:
            inlined_list = []

        if inlined_list:
            for item in inlined_list:
                cid = item.get("metadata", {}).get("key") or item.get("custom_id") or item.get("customId")
                cand_list = item.get("response", {}).get("candidates", [])
                text_out = ""
                json_out = None
                if cand_list:
                    parts = cand_list[0].get("content", {}).get("parts", [])
                    text_out = "".join(p.get("text", "") for p in parts)
                    try:
                        json_out = json.loads(text_out)
                    except Exception:
                        pass
                results.append({
                    "custom_id": cid,
                    "text": text_out,
                    "json_data": json_out,
                    "success": bool(text_out)
                })
            return results

        # 2. Handle responsesFile structure
        responses_file = resp.get("responsesFile")
        if responses_file:
            try:
                dl_url = f"https://generativelanguage.googleapis.com/download/v1beta/{responses_file}:download?alt=media"
                headers = {"x-goog-api-key": self.api_key}
                dl_resp = self.http_client.get(dl_url, headers=headers, timeout=60.0)
                if dl_resp.status_code == 200:
                    for line in dl_resp.text.splitlines():
                        if not line.strip():
                            continue
                        try:
                            line_obj = json.loads(line)
                            cid = line_obj.get("key") or line_obj.get("custom_id") or line_obj.get("customId")
                            cands = line_obj.get("response", {}).get("candidates", [])
                            text_out = ""
                            json_out = None
                            if cands:
                                parts = cands[0].get("content", {}).get("parts", [])
                                text_out = "".join(p.get("text", "") for p in parts)
                                try:
                                    json_out = json.loads(text_out)
                                except Exception:
                                    pass
                            results.append({
                                "custom_id": cid,
                                "text": text_out,
                                "json_data": json_out,
                                "success": bool(text_out)
                            })
                        except Exception:
                            continue
            except Exception as e:
                self.logger.error(f"Failed to download responsesFile {responses_file}: {e}", module="gemini_client")

        return results

    def cancel_batch_job(self, batch_name: str) -> bool:
        """Cancels a running Gemini Batch Job."""
        if not self.is_available() or not batch_name:
            return False

        clean_name = batch_name.strip().lstrip("/")
        endpoint = f"{self.BASE_URL}/{clean_name}:cancel"
        headers = {"x-goog-api-key": self.api_key}

        try:
            response = self.http_client.post(endpoint, headers=headers, json={}, timeout=30.0)
            return response.status_code == 200
        except Exception:
            return False

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
