#!/usr/bin/env python3
"""
Diagnostic test tool for Google Gemini API configuration.
Verifies API authentication, GeminiClient connection pooling,
structured JSON schema extraction, Turkish translation, and Multimodal Vision OCR.
"""

import sys
import os
import json
import time
import base64
import argparse
from pathlib import Path
from io import BytesIO

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.gemini_client import GeminiClient
from pipeline.vision_ocr import VisionOCRManager

def _create_mock_circuit_image_base64() -> str:
    """Generates a small test circuit diagram image in memory as a base64 PNG string."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (300, 150), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        # Draw a simple schematic line and box
        draw.rectangle([20, 40, 100, 110], outline=(0, 0, 0), width=2)
        draw.text((30, 70), "LM7805", fill=(0, 0, 0))
        draw.line([0, 75, 20, 75], fill=(0, 0, 255), width=2)
        draw.line([100, 75, 180, 75], fill=(255, 0, 0), width=2)
        draw.text((5, 55), "VIN: 12V", fill=(0, 0, 0))
        draw.text((110, 55), "VOUT: 5V", fill=(0, 0, 0))
        
        buf = BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        # Fallback to 1x1 transparent PNG if PIL is missing
        return "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

def test_gemini_config(config_path: str):
    print("=" * 80)
    print("  GOOGLE GEMINI PIPELINE DIAGNOSTIC TEST")
    print("=" * 80)

    cfg_path = Path(config_path)
    if not cfg_path.exists():
        print(f"❌ Error: Config file '{config_path}' not found.")
        sys.exit(1)

    with open(cfg_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    client = GeminiClient(config=config)
    
    if not client.is_available():
        print("❌ Error: GEMINI_API_KEY is not configured in config.json or environment.")
        print("Set it via: export GEMINI_API_KEY='your_api_key'")
        sys.exit(1)

    masked_key = f"{client.api_key[:4]}...{client.api_key[-4:]}" if len(client.api_key) > 8 else "***"
    print(f"📍 Gemini Endpoint : {client.BASE_URL}")
    print(f"🔑 API Key         : {masked_key} (len={len(client.api_key)})")
    print(f"🧠 Default Model   : {client.default_model}")
    print(f"🌐 Translator Model: {config.get('model_translator', 'gemini-3.6-flash')}")
    print(f"👁️  Vision Model    : {config.get('model_vision', 'gemini-3.6-flash')}")
    print(f"⏱️  Timeout         : {client.timeout}s")
    print("-" * 80)

    results = []

    # 1. Test Basic API Connectivity
    print("\n[Step 1/4] Testing API authentication and basic text generation...")
    try:
        start_t = time.time()
        res = client.generate_content(
            prompt="Respond in exactly 3 words: 'Gemini is operational'.",
            temperature=0.1,
            max_output_tokens=30,
            purpose="diagnostic_ping"
        )
        elapsed = time.time() - start_t
        if res.get("success"):
            print(f"  ✅ Handshake successful in {elapsed:.2f}s!")
            print(f"  💬 Response: \"{res.get('text', '').strip()}\"")
            print(f"  📊 Model: {res.get('model')}")
            results.append({"step": "API Connectivity", "status": "PASS", "details": f"Response in {elapsed:.2f}s"})
        else:
            print(f"  ❌ Generation failed: {res.get('error')}")
            results.append({"step": "API Connectivity", "status": "FAIL", "details": res.get("error", "")})
            return results
    except Exception as e:
        print(f"  ❌ API call exception: {e}")
        results.append({"step": "API Connectivity", "status": "FAIL", "details": str(e)})
        return results

    # 2. Test Structured JSON Schema Output (Analyzer Test)
    print(f"\n[Step 2/4] Testing Structured JSON Schema output with '{client.default_model}'...")
    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "topics": {"type": "array", "items": {"type": "string"}},
            "sft_qa": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "answer": {"type": "string"}
                    },
                    "required": ["question", "answer"]
                }
            }
        },
        "required": ["summary", "topics", "sft_qa"]
    }
    test_doc = (
        "The ESP32-S3 is a dual-core XTensa LX7 MCU with 2.4 GHz Wi-Fi and Bluetooth 5 (LE). "
        "It features 45 programmable GPIOs and supports vector instructions for neural network computing."
    )
    try:
        start_t = time.time()
        res = client.generate_content(
            prompt=f"Analyze the technical text:\n{test_doc}",
            system_instruction="You are an expert embedded systems engineer. Extract structured technical metadata.",
            model=client.default_model,
            response_schema=schema,
            temperature=0.1,
            max_output_tokens=1024,
            purpose="analyzer_test"
        )
        elapsed = time.time() - start_t
        if res.get("success") and res.get("json_data"):
            data = res.get("json_data")
            print(f"  ✅ Structured JSON Schema extracted successfully in {elapsed:.2f}s!")
            print(f"  📊 Summary Preview : {data.get('summary', '')[:100]}...")
            print(f"  🏷️  Topics          : {data.get('topics', [])}")
            print(f"  ❓ QA Count        : {len(data.get('sft_qa', []))} pairs")
            results.append({"step": f"Structured JSON ({client.default_model})", "status": "PASS", "details": f"{elapsed:.2f}s ({res.get('usage', {}).get('total_tokens', 0)} tokens)"})
        else:
            print(f"  ❌ Structured JSON failed: {res.get('error')}")
            results.append({"step": f"Structured JSON ({client.default_model})", "status": "FAIL", "details": res.get("error", "Invalid JSON")})
    except Exception as e:
        print(f"  ❌ Structured JSON exception: {e}")
        results.append({"step": f"Structured JSON ({client.default_model})", "status": "FAIL", "details": str(e)})

    # 3. Test Turkish Translation Quality
    print(f"\n[Step 3/4] Testing Technical English-to-Turkish Translation...")
    tr_prompt = (
        "Translate this sentence to professional Turkish engineering documentation:\n"
        "'The phase-locked loop (PLL) synthesizer provides low phase noise and fast lock times across the 2.4 GHz ISM band.'"
    )
    try:
        start_t = time.time()
        res = client.generate_content(
            prompt=tr_prompt,
            system_instruction="You are a professional technical translator specializing in RF engineering.",
            temperature=0.1,
            max_output_tokens=256,
            purpose="translation_test"
        )
        elapsed = time.time() - start_t
        if res.get("success"):
            print(f"  ✅ Translation Output in {elapsed:.2f}s:\n     \"{res.get('text', '').strip()}\"")
            results.append({"step": "Technical Translation (TR)", "status": "PASS", "details": f"{elapsed:.2f}s"})
        else:
            print(f"  ❌ Translation failed: {res.get('error')}")
            results.append({"step": "Technical Translation (TR)", "status": "FAIL", "details": res.get("error", "")})
    except Exception as e:
        print(f"  ❌ Translation exception: {e}")
        results.append({"step": "Technical Translation (TR)", "status": "FAIL", "details": str(e)})

    # 4. Test Multimodal Vision OCR
    print(f"\n[Step 4/4] Testing Multimodal Vision OCR with mock schematic...")
    try:
        mock_b64 = _create_mock_circuit_image_base64()
        start_t = time.time()
        vision_prompt = "Identify the IC part number and voltage ratings in this circuit diagram snippet."
        
        # Direct multimodal call with Gemini REST API
        endpoint = f"{client.BASE_URL}/models/{client._resolve_model_name(config.get('model_vision', 'gemini-3.6-flash'))}:generateContent"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": vision_prompt},
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": mock_b64
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 512
            }
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": client.api_key
        }
        response = client.http_client.post(endpoint, headers=headers, json=payload)
        elapsed = time.time() - start_t
        if response.status_code == 200:
            data = response.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            vision_text = "".join(p.get("text", "") for p in parts).strip()
            print(f"  ✅ Multimodal Vision OCR verified in {elapsed:.2f}s!")
            print(f"  👁️ Vision Description: {vision_text[:140]}...")
            results.append({"step": "Multimodal Vision OCR", "status": "PASS", "details": f"{elapsed:.2f}s"})
        else:
            print(f"  ❌ Multimodal Vision failed (HTTP {response.status_code}): {response.text}")
            results.append({"step": "Multimodal Vision OCR", "status": "FAIL", "details": f"HTTP {response.status_code}"})
    except Exception as e:
        print(f"  ❌ Multimodal Vision exception: {e}")
        results.append({"step": "Multimodal Vision OCR", "status": "FAIL", "details": str(e)})

    # Print Consumption and Summary
    monthly = client.budget_manager.get_monthly_consumption()
    print("\n" + "=" * 80)
    print("  GEMINI API USAGE & BUDGET SUMMARY")
    print("=" * 80)
    print(f"  📅 Month               : {monthly.get('month')}")
    print(f"  🔢 Total Tokens Used   : {monthly.get('total_tokens'):,}")
    print(f"  💰 Estimated Cost (TL) : ₺{monthly.get('estimated_cost_tl'):.4f}")
    print(f"  📊 Budget Cap Used     : {monthly.get('budget_percent')}%")
    print("-" * 80)

    print("\n" + "=" * 80)
    print("  GEMINI DIAGNOSTIC SUMMARY")
    print("=" * 80)
    print(f"| {'Diagnostic Step':<35} | {'Status':<8} | {'Metrics / Details':<30} |")
    print(f"|{'-'*37}|{'-'*10}|{'-'*32}|")
    for r in results:
        icon = "✅" if r["status"] == "PASS" else "❌"
        print(f"| {r['step']:<35} | {icon} {r['status']:<5} | {r['details']:<30} |")
    print("=" * 80)
    
    client.close()
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Google Gemini configuration and endpoint.")
    parser.add_argument("--config", type=str, default="templates/gemini.json", help="Path to config JSON file")
    args = parser.parse_args()
    test_gemini_config(args.config)
