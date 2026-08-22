#!/usr/bin/env python3
"""
Diagnostic test tool for Ollama Cloud (https://ollama.com/v1).
Verifies authentication, endpoint connectivity, structured JSON analysis,
and technical English-to-Turkish translation with performance metrics.
"""

import sys
import os
import json
import time
import argparse
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.llm_client import get_openai_client, _resolve_endpoint_and_key

def test_ollama_cloud(config_path: str, api_key_override: str = None, host_override: str = None):
    print("=" * 80)
    print("  OLLAMA CLOUD PIPELINE DIAGNOSTIC TEST (https://ollama.com/v1)")
    print("=" * 80)

    cfg_path = Path(config_path)
    if not cfg_path.exists():
        print(f"❌ Error: Config file '{config_path}' not found.")
        sys.exit(1)

    with open(cfg_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    if host_override:
        config["openai_base_url"] = host_override
        config["ollama_url"] = host_override
    if api_key_override:
        config["ollama_api_key"] = api_key_override
        config["openai_api_key"] = api_key_override

    base_url, api_key, timeout = _resolve_endpoint_and_key(config)
    print(f"📍 Target Endpoint : {base_url}")
    masked_key = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "***"
    print(f"🔑 API Key         : {masked_key} (len={len(api_key)})")
    print(f"⏱️  Timeout         : {timeout}s")
    
    analyzer_model = config.get("model_analyzer", "gpt-oss:20b")
    translator_model = config.get("model_translator", "gpt-oss:20b")
    vision_model = config.get("model_vision", "qwen3.5:397b")

    print(f"🧠 Analyzer Model  : {analyzer_model}")
    print(f"🌐 Translator Model: {translator_model}")
    print(f"👁️  Vision Model    : {vision_model}")
    print("-" * 80)

    client = get_openai_client(config)
    results = []

    # 1. Test Server Connectivity & Model Discovery
    print("\n[Step 1/3] Testing endpoint connectivity and model discovery...")
    try:
        start_t = time.time()
        models_data = client.models.list().data
        elapsed = time.time() - start_t
        available_models = [m.id for m in models_data]
        print(f"  ✅ Connected successfully in {elapsed:.2f}s.")
        print(f"  📦 Total models available on server: {len(available_models)}")
        
        for name, role in [(analyzer_model, "Analyzer"), (translator_model, "Translator"), (vision_model, "Vision")]:
            if name in available_models:
                print(f"  ✓ {role} model '{name}' is online and available.")
            else:
                print(f"  ⚠️ {role} model '{name}' was not listed in server models catalog.")
        
        results.append({"step": "Connectivity & Discovery", "status": "PASS", "details": f"{len(available_models)} models found ({elapsed:.2f}s)"})
    except Exception as e:
        print(f"  ❌ Failed to connect to {base_url}: {e}")
        results.append({"step": "Connectivity & Discovery", "status": "FAIL", "details": str(e)})
        return results

    # 2. Test Structured JSON Generation (Technical Analyzer)
    print(f"\n[Step 2/3] Testing Structured JSON generation with Analyzer model ('{analyzer_model}')...")
    test_text = (
        "The AD9850 is a highly integrated device that uses advanced DDS technology coupled with an internal "
        "high speed, high performance D/A converter and comparator to form a complete, digitally programmable "
        "frequency synthesizer and clock generator function."
    )
    system_prompt = (
        "You are an expert electronics engineer. Analyze the technical text and respond ONLY with a JSON object "
        "containing keys 'summary' (string) and 'sft_qa' (list of objects with 'question' and 'answer')."
    )
    user_prompt = f"Text to analyze:\n{test_text}"

    try:
        start_t = time.time()
        response = client.chat.completions.create(
            model=analyzer_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=1024
        )
        wall_time = time.time() - start_t
        content = response.choices[0].message.content or ""
        
        # Clean think tags and code blocks if present
        clean_content = content.strip()
        if "<think>" in clean_content and "</think>" in clean_content:
            clean_content = clean_content.split("</think>", 1)[1].strip()
        if clean_content.startswith("```json"):
            clean_content = clean_content[7:]
        elif clean_content.startswith("```"):
            clean_content = clean_content[3:]
        if clean_content.endswith("```"):
            clean_content = clean_content[:-3]
        clean_content = clean_content.strip()

        parsed_json = json.loads(clean_content)
        usage = getattr(response, "usage", None)
        prompt_tokens = usage.prompt_tokens if usage else 0
        comp_tokens = usage.completion_tokens if usage else 0
        tps = comp_tokens / wall_time if wall_time > 0 else 0

        print(f"  ✅ Structured JSON successfully generated and validated!")
        print(f"  📊 Summary Preview : {parsed_json.get('summary', '')[:120]}...")
        print(f"  ❓ QA Count        : {len(parsed_json.get('sft_qa', []))} pairs")
        print(f"  ⚡ Eval Speed      : {tps:.2f} tok/s | Gen Tokens: {comp_tokens} | Wall: {wall_time:.2f}s")
        results.append({"step": f"Analyzer JSON ({analyzer_model})", "status": "PASS", "details": f"{comp_tokens} tokens @ {tps:.1f} tok/s ({wall_time:.2f}s)"})
    except Exception as e:
        print(f"  ❌ JSON Analysis failed: {e}")
        results.append({"step": f"Analyzer JSON ({analyzer_model})", "status": "FAIL", "details": str(e)})

    # 3. Test Technical Translation (English to Turkish)
    print(f"\n[Step 3/3] Testing Technical Translation with Translator model ('{translator_model}')...")
    trans_prompt = (
        "Translate the following electronics paragraph into professional Turkish technical documentation. "
        "Keep technical terminology precise (e.g. DDS, DAC, clock generator):\n\n"
        "The DDS core utilizes a 32-bit phase accumulator which resolves frequency tuning to 0.029 Hz at a 125 MHz clock rate."
    )
    try:
        start_t = time.time()
        response = client.chat.completions.create(
            model=translator_model,
            messages=[
                {"role": "system", "content": "You are a professional technical translator specializing in electrical engineering."},
                {"role": "user", "content": trans_prompt}
            ],
            temperature=0.1,
            max_tokens=1024
        )
        wall_time = time.time() - start_t
        raw_output = (response.choices[0].message.content or "").strip()
        if "<think>" in raw_output and "</think>" in raw_output:
            trans_output = raw_output.split("</think>", 1)[1].strip()
        elif "<think>" in raw_output and not "</think>" in raw_output:
            trans_output = raw_output.replace("<think>", "").strip()
        else:
            trans_output = raw_output
            
        usage = getattr(response, "usage", None)
        comp_tokens = usage.completion_tokens if usage else 0
        tps = comp_tokens / wall_time if wall_time > 0 else 0

        print(f"  ✅ Translation Output:\n     \"{trans_output}\"")
        print(f"  ⚡ Eval Speed      : {tps:.2f} tok/s | Gen Tokens: {comp_tokens} | Wall: {wall_time:.2f}s")
        results.append({"step": f"Translator TR ({translator_model})", "status": "PASS", "details": f"{comp_tokens} tokens @ {tps:.1f} tok/s ({wall_time:.2f}s)"})
    except Exception as e:
        print(f"  ❌ Translation failed: {e}")
        results.append({"step": f"Translator TR ({translator_model})", "status": "FAIL", "details": str(e)})

    # Report Summary
    print("\n" + "=" * 80)
    print("  OLLAMA CLOUD DIAGNOSTIC SUMMARY")
    print("=" * 80)
    print(f"| {'Diagnostic Step':<35} | {'Status':<8} | {'Metrics / Details':<30} |")
    print(f"|{'-'*37}|{'-'*10}|{'-'*32}|")
    for r in results:
        icon = "✅" if r["status"] == "PASS" else "❌"
        print(f"| {r['step']:<35} | {icon} {r['status']:<5} | {r['details']:<30} |")
    print("=" * 80)
    
    if any(r["status"] == "FAIL" and "401" in r["details"] for r in results):
        print("\n💡 [Troubleshooting 401 Unauthorized]:")
        print("  - Ollama Cloud (https://ollama.com) allows public model listing (/v1/models),")
        print("    but requires an active serverless credit balance / paid inference subscription for text generation.")
        print("  - To test or verify with free tier, you can use Google Gemini:")
        print("      PYTHONPATH=. uv run python tools/test_gemini_config.py --config templates/gemini.json")
        print("  - Or run against a local Ollama server on your Mac:")
        print("      PYTHONPATH=. uv run python tools/test_ollama_cloud.py --host http://127.0.0.1:11434")

    return results

def probe_all_models(config_path: str, api_key_override: str = None, host_override: str = None):
    """Probes all models available on the endpoint to check which ones respond with 200 OK."""
    print("=" * 80)
    print("  PROBING ALL MODELS ON OLLAMA ENDPOINT")
    print("=" * 80)
    
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    if host_override:
        config["openai_base_url"] = host_override
        config["ollama_url"] = host_override
    if api_key_override:
        config["ollama_api_key"] = api_key_override
        config["openai_api_key"] = api_key_override

    base_url, api_key, timeout = _resolve_endpoint_and_key(config)
    print(f"📍 Endpoint: {base_url}")
    print(f"🔑 API Key : {api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else f"🔑 API Key : {api_key}")
    print("-" * 80)

    client = get_openai_client(config)
    try:
        models = [m.id for m in client.models.list().data]
    except Exception as e:
        print(f"❌ Failed to fetch models list: {e}")
        return

    print(f"Found {len(models)} models. Testing each model with a short generation request...\n")
    working = []
    failed = []

    for idx, model_name in enumerate(models, 1):
        print(f"[{idx}/{len(models)}] Testing '{model_name}'...", end=" ", flush=True)
        try:
            start_t = time.time()
            res = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": "Respond with 'OK'"}],
                max_tokens=10,
                timeout=20.0
            )
            wall_t = time.time() - start_t
            content = (res.choices[0].message.content or "").strip()
            print(f"✅ PASS ({wall_t:.2f}s) -> \"{content[:30]}\"")
            working.append(model_name)
        except Exception as e:
            err = str(e)
            if "401" in err:
                short_err = "401 Unauthorized"
            elif "404" in err:
                short_err = "404 Not Found"
            elif "429" in err:
                short_err = "429 Rate Limit"
            else:
                short_err = err[:40]
            print(f"❌ FAIL ({short_err})")
            failed.append((model_name, short_err))

    print("\n" + "=" * 80)
    print("  MODEL PROBING SUMMARY")
    print("=" * 80)
    print(f"  Total Tested : {len(models)}")
    print(f"  Working (200): {len(working)}")
    print(f"  Failed       : {len(failed)}")
    if working:
        print(f"\n  ✅ Working Models: {working}")
    print("=" * 80)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Ollama Cloud configuration and endpoint.")
    parser.add_argument("--config", type=str, default="templates/ollama_cloud.json", help="Path to config JSON file")
    parser.add_argument("--api-key", type=str, default=None, help="Override API key (e.g. from https://ollama.com/settings/keys)")
    parser.add_argument("--host", type=str, default=None, help="Override endpoint URL (e.g. https://ollama.com/v1 or http://localhost:11434)")
    parser.add_argument("--model", type=str, default=None, help="Override model to test")
    parser.add_argument("--probe-models", action="store_true", help="Probe all available models on the server")
    args = parser.parse_args()
    
    if args.probe_models:
        probe_all_models(args.config, api_key_override=args.api_key, host_override=args.host)
    else:
        if args.model:
            # Temporarily set analyzer model in config
            with open(args.config, "r", encoding="utf-8") as f:
                cfg_tmp = json.load(f)
            cfg_tmp["model_analyzer"] = args.model
            cfg_tmp["model_translator"] = args.model
            tmp_cfg_path = "/tmp/ollama_model_override.json"
            with open(tmp_cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg_tmp, f)
            test_ollama_cloud(tmp_cfg_path, api_key_override=args.api_key, host_override=args.host)
        else:
            test_ollama_cloud(args.config, api_key_override=args.api_key, host_override=args.host)
