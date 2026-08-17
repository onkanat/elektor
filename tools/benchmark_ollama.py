import time
import sys
import os
import argparse
from openai import OpenAI

# Cloud model hints
CLOUD_MODEL_HINTS = (
    "gpt-oss",
    "deepseek",
    "kimi",
    "qwen3",
    "gemini",
    "glm",
    "minimax",
    "cogito",
    "mistral",
    "ministral",
    "devstral",
    "gemma",
    "rnj",
)

# Names that signal a non-chat / embedding model
EMBED_HINTS = ("nomic", "embed", "bge", "mxbai", "all-minilm", "snowflake")

def is_chat_model(name: str) -> bool:
    n = name.lower()
    if any(h in n for h in EMBED_HINTS):
        return False
    return True

def benchmark_models(host: str, prompt: str, is_cloud: bool, api_key: str | None, models_override: str | None = None, vram_only: bool = False):
    # Build base_url
    if is_cloud:
        if not api_key:
            print("=" * 70)
            print("ERROR: --cloud requires an API key.")
            print("Set it with one of these methods:")
            print("  1. export OLLAMA_API_KEY=your_key (Linux/macOS)")
            print("     $env:OLLAMA_API_KEY='your_key' (PowerShell)")
            print("     set OLLAMA_API_KEY=your_key (Windows CMD)")
            print("  2. python bench.py --cloud --api-key your_key")
            print("Get a key at: https://ollama.com/settings/keys")
            print("=" * 70)
            sys.exit(1)
        base_url = "https://ollama.com/v1"
    else:
        # Correct single-slash typos (e.g. http:/ -> http://)
        normalized_host = host.strip()
        if normalized_host.startswith("http:/") and not normalized_host.startswith("http://"):
            normalized_host = "http://" + normalized_host[6:]
        elif normalized_host.startswith("https:/") and not normalized_host.startswith("https://"):
            normalized_host = "https://" + normalized_host[7:]
        elif not normalized_host.startswith("http://") and not normalized_host.startswith("https://"):
            normalized_host = "http://" + normalized_host  # Default to http for local
        base_url = normalized_host
        
        if not base_url.endswith("/v1") and not base_url.endswith("/v1/"):
            base_url = f"{base_url.rstrip('/')}/v1"

    print(f"Connecting to OpenAI-compatible server at: {base_url}")
    print(f"Mode: {'Ollama Cloud' if is_cloud else 'Local Ollama'}")
    
    if is_cloud:
        masked = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "***"
        print(f"API key: {masked} (len={len(api_key)})")

    try:
        client = OpenAI(base_url=base_url, api_key=api_key or "ollama")
        import re
        if models_override:
            chat_models = [m.strip() for m in models_override.split(",") if m.strip()]
            print(f"Skipping auto-detection. Benchmarking manually specified models: {chat_models}")
        elif vram_only:
            import httpx
            # Convert base_url to api/ps endpoint (e.g., http://host:port/api/ps)
            api_url = base_url
            if "/v1" in api_url:
                api_url = api_url.replace("/v1", "/api/ps")
            else:
                api_url = f"{api_url.rstrip('/')}/api/ps"
                
            print(f"Fetching running/VRAM-loaded models from: {api_url}")
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            try:
                res = httpx.get(api_url, headers=headers, timeout=5.0)
                if res.status_code == 200:
                    running_models = [m.get("name") for m in res.json().get("models", [])]
                    chat_models = [m for m in running_models if is_chat_model(m)]
                    print(f"Found running VRAM models: {chat_models}")
                else:
                    print(f"Failed to fetch running models. Status code: {res.status_code}")
                    chat_models = []
            except Exception as ex:
                print(f"Error fetching running models from VRAM: {ex}")
                chat_models = []
        elif is_cloud and os.path.exists("cloud.txt"):
            with open("cloud.txt", "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                if "|" in content:
                    raw_models = re.findall(r'`([^`]+)`', content)
                    chat_models = [m.strip() for m in raw_models if m.strip().lower() not in ("model", "status", "n/a", "success", "failed")]
                else:
                    chat_models = [m.strip() for m in re.split(r'[\n,]+', content) if m.strip()]
                print(f"Loaded cloud models from cloud.txt: {chat_models}")
            else:
                print("cloud.txt is empty. Falling back to server model list.")
                models_data = client.models.list().data
                if not models_data:
                    print("No models found on the server.")
                    return
                print(f"Found {len(models_data)} models on the server.")
                chat_models = [m.id for m in models_data if is_chat_model(m.id)]
        else:
            models_data = client.models.list().data
            if not models_data:
                print("No models found on the server.")
                return
            print(f"Found {len(models_data)} models on the server.")
            
            # Filter chat-capable models
            chat_models = []
            for m in models_data:
                name = m.id
                if not is_chat_model(name):
                    print(f" Skipping embedding/non-chat model: {name}")
                    continue
                chat_models.append(name)
    except Exception as e:
        print(f"Error connecting to server or listing models: {e}")
        sys.exit(1)

    if not chat_models:
        print("No chat models to benchmark.")
        return

    print(f"Starting benchmark for {len(chat_models)} generation models...\n")
    results = []

    for idx, name in enumerate(chat_models):
        print(f"[{idx + 1}/{len(chat_models)}] Benchmarking: {name}")
        time.sleep(2)
        try:
            start_wall = time.time()
            response = client.chat.completions.create(
                model=name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=150,
            )
            wall_time = time.time() - start_wall
            usage = getattr(response, "usage", None)
            prompt_tokens = usage.prompt_tokens if usage else 0
            completion_tokens = usage.completion_tokens if usage else 0
            eval_tps = completion_tokens / wall_time if wall_time > 0 else 0
            content = response.choices[0].message.content or ""
            print(f"  Response    : {content.strip()}")
            print(f"  Prompt Toks : {prompt_tokens}")
            print(f"  Gen Toks    : {completion_tokens}")
            print(f"  Eval Speed  : {eval_tps:.2f} tok/s")
            print(f"  Wall Time   : {wall_time:.3f} s\n")
            results.append({
                "model": name,
                "prompt_tokens": prompt_tokens,
                "gen_tokens": completion_tokens,
                "generation_tps": eval_tps,
                "wall_time_sec": wall_time,
                "status": "Success",
            })
        except Exception as e:
            err_str = str(e)
            if "401" in err_str or "Unauthorized" in err_str or "unauthorized" in err_str.lower():
                print(" ✖ Authentication failed. Check your OLLAMA_API_KEY.")
                print(" Get a new key: https://ollama.com/settings/keys")
                sys.exit(1)
                
            # Fallback to legacy text completions if chat completions fails with 405
            is_405 = "405" in err_str or "Method Not Allowed" in err_str or "not allowed" in err_str.lower()
            if is_405:
                print(f"  Chat completions not allowed (405). Trying text completions fallback...")
                try:
                    start_wall = time.time()
                    response = client.completions.create(
                        model=name,
                        prompt=prompt,
                        temperature=0.3,
                        max_tokens=150
                    )
                    wall_time = time.time() - start_wall
                    usage = getattr(response, "usage", None)
                    prompt_tokens = usage.prompt_tokens if usage else 0
                    completion_tokens = usage.completion_tokens if usage else 0
                    eval_tps = completion_tokens / wall_time if wall_time > 0 else 0
                    content = response.choices[0].text or ""
                    print(f"  Response    : {content.strip()}")
                    print(f"  Prompt Toks : {prompt_tokens}")
                    print(f"  Gen Toks    : {completion_tokens}")
                    print(f"  Eval Speed  : {eval_tps:.2f} tok/s")
                    print(f"  Wall Time   : {wall_time:.3f} s\n")
                    results.append({
                        "model": name,
                        "prompt_tokens": prompt_tokens,
                        "gen_tokens": completion_tokens,
                        "generation_tps": eval_tps,
                        "wall_time_sec": wall_time,
                        "status": "Success",
                    })
                    time.sleep(2)
                    continue
                except Exception as fallback_err:
                    e = fallback_err
            
            print(f"  Error benchmarking {name}: {e}\n")
            results.append({
                "model": name,
                "prompt_tokens": 0,
                "gen_tokens": 0,
                "generation_tps": 0,
                "wall_time_sec": 0,
                "status": f"Failed: {e}",
            })
        time.sleep(2)

    # ---- Report ----
    print("=" * 80)
    print("BENCHMARK REPORT SUMMARY")
    print("=" * 80)
    successful = [r for r in results if r["status"] == "Success"]
    failed = [r for r in results if r["status"] != "Success"]
    sorted_results = sorted(successful, key=lambda x: x["generation_tps"], reverse=True) + failed
    print("\n| Model | Prompt Toks | Gen Toks | Eval (t/s) | Wall (s) | Status |")
    print("|---|---|---|---|---|---|")
    for r in sorted_results:
        if r["status"] == "Success":
            print(f"| `{r['model']}` | {r['prompt_tokens']} | {r['gen_tokens']} "
                  f"| {r['generation_tps']:.2f} | {r['wall_time_sec']:.2f} | ✅ |")
        else:
            print(f"| `{r['model']}` | N/A | N/A | N/A | N/A | ❌ {r['status']} |")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ollama / Ollama Cloud Model Benchmarker")
    parser.add_argument(
        "--host",
        type=str,
        default="http://localhost:11434",
        help="Local Ollama server URL (ignored when --cloud is set)",
    )
    parser.add_argument(
        "--cloud",
        action="store_true",
        help="Benchmark against Ollama Cloud (https://ollama.com/v1)",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="API key (defaults to OLLAMA_API_KEY env var when --cloud is used)",
    )
    parser.add_argument(
        "--models",
        type=str,
        default=None,
        help="Comma-separated list of specific models to benchmark (bypasses auto-detection)",
    )
    parser.add_argument(
        "--vram-only",
        action="store_true",
        help="Only benchmark models currently loaded in memory/VRAM (queried via /api/ps)",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default="Explain what a resistor does in exactly one sentence.",
        help="Benchmark prompt",
    )
    args = parser.parse_args()
    api_key = args.api_key or os.environ.get("OLLAMA_API_KEY")
    benchmark_models(args.host, args.prompt, args.cloud, api_key, args.models, args.vram_only)
