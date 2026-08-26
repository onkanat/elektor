import os
import httpx
from openai import OpenAI, AsyncOpenAI

_clients_pool = {}
_async_clients_pool = {}
_client_config_hash = None

from pathlib import Path

def _load_dotenv_if_needed():
    """Loads environment variables from local/home .env and zsh config files if available."""
    if os.environ.get("OLLAMA_API_KEY") and os.environ.get("GEMINI_API_KEY"):
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
                                if k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY") and v:
                                    if not os.environ.get(k):
                                        os.environ[k] = v
            except Exception:
                pass

def _resolve_endpoint_and_key(config: dict):
    _load_dotenv_if_needed()
    base_url = config.get("openai_base_url") or os.environ.get("OPENAI_BASE_URL") or config.get("ollama_url", "http://localhost:11434")
    if isinstance(base_url, str) and base_url.startswith("${") and base_url.endswith("}"):
        env_var = base_url[2:-1]
        base_url = os.environ.get(env_var, "http://localhost:11434")
        
    if not base_url.endswith("/v1") and not base_url.endswith("/v1/"):
        base_url = f"{base_url.rstrip('/')}/v1"
    
    # Auto-upgrade http://ollama.com to https://ollama.com to avoid 301 Moved Permanently redirects
    if base_url.startswith("http://ollama.com"):
        base_url = "https://" + base_url[len("http://"):]
    
    raw_api_key = (
        config.get("openai_api_key") 
        or config.get("ollama_api_key") 
        or os.environ.get("OPENAI_API_KEY") 
        or os.environ.get("OLLAMA_API_KEY") 
        or "ollama"
    )
    if isinstance(raw_api_key, str) and raw_api_key.startswith("${") and raw_api_key.endswith("}"):
        env_var = raw_api_key[2:-1]
        api_key = os.environ.get(env_var) or os.environ.get("OLLAMA_API_KEY") or os.environ.get("OPENAI_API_KEY") or "ollama"
    else:
        api_key = raw_api_key

    timeout = float(config.get("openai_timeout", 600.0))
    return base_url, api_key, timeout

def _get_config_hash(config: dict) -> str:
    """Creates a unique hash key for current client configuration to detect config changes."""
    base_url, api_key, timeout = _resolve_endpoint_and_key(config)
    return f"{base_url}|{api_key}|{timeout}"

def get_openai_client(config: dict) -> OpenAI:
    """Returns a connection-pooled OpenAI client instance cached by config hash."""
    global _clients_pool
    current_hash = _get_config_hash(config)
    
    if current_hash not in _clients_pool:
        base_url, api_key, timeout = _resolve_endpoint_and_key(config)
        
        # Configure robust connection pooling limits and enable follow_redirects
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=60.0)
        http_client = httpx.Client(limits=limits, timeout=timeout, follow_redirects=True)
        
        _clients_pool[current_hash] = OpenAI(
            base_url=base_url,
            api_key=api_key,
            http_client=http_client
        )
        
    return _clients_pool[current_hash]

def get_async_openai_client(config: dict) -> AsyncOpenAI:
    """Returns an AsyncOpenAI client instance configured with target endpoint and key."""
    base_url, api_key, timeout = _resolve_endpoint_and_key(config)
    
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=60.0)
    http_client = httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=True)
    
    return AsyncOpenAI(
        base_url=base_url,
        api_key=api_key,
        http_client=http_client
    )

def get_embedding_client(config: dict) -> OpenAI:
    """Returns an OpenAI client instance specifically configured for vector embeddings.
    If 'embedding_url' is set in config, uses it.
    If 'ollama_url' points to cloud proxy (e.g. ollama.com), automatically falls back to local localhost:11434.
    """
    emb_cfg = dict(config)
    if config.get("embedding_url"):
        emb_cfg["ollama_url"] = config["embedding_url"]
        emb_cfg["openai_base_url"] = config["embedding_url"]
    else:
        base_url = str(config.get("openai_base_url") or config.get("ollama_url", ""))
        if "ollama.com" in base_url.lower():
            # Ollama Cloud proxy does not support /v1/embeddings; route embeddings to local Ollama instance
            emb_cfg["ollama_url"] = "http://localhost:11434/v1"
            emb_cfg["openai_base_url"] = "http://localhost:11434/v1"
            emb_cfg["openai_api_key"] = "ollama"
    return get_openai_client(emb_cfg)

def unload_ollama_model(config: dict, model_name: str):
    """Sends a native Ollama API request to unload the specified model from VRAM immediately."""
    import urllib.request
    import json
    if not model_name:
        return
    ollama_url = config.get("ollama_url", "http://localhost:11434")
    # Clean the URL to get the base Ollama endpoint (remove /v1 if present)
    base_url = ollama_url.split("/v1")[0].rstrip("/")
    for endpoint in ["/api/generate", "/api/chat"]:
        try:
            url = f"{base_url}{endpoint}"
            data = json.dumps({"model": model_name, "keep_alive": 0}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    print(f"  [Ollama] Successfully unloaded model '{model_name}' from VRAM.")
                    return
        except Exception:
            pass
    print(f"  [Ollama Note] Unload model signal sent for '{model_name}'.")

def call_llm(config: dict, system_instruction: str, user_prompt: str, temperature: float = 0.1, model_override: str = None) -> str:
    """Helper function to execute synchronous LLM completion using configured model."""
    client = get_openai_client(config)
    model_name = model_override or config.get("model_analyzer", "qwen3.5:4b")
    
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_prompt}
        ],
        temperature=temperature
    )
    return response.choices[0].message.content or ""
