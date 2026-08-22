#!/usr/bin/env python3
"""
Diagnostic test tool for Google LangExtract Grounded Extraction.
Tests entity extraction, verbatim character offset location, and fallback behavior
across Gemini, Ollama, OpenAI, and Heuristic Fallback engines.
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

from pipeline.langextract_engine import LangExtractEngine

SAMPLE_DOC = (
    "The STM32F401 microcontroller operates at 84 MHz with 512 kB Flash memory and 96 kB SRAM. "
    "It features an integrated 12-bit ADC with 2.4 MSPS conversion speed, powered by a 3.3V VDD supply "
    "and drawing 140 µA/MHz in run mode. Communication peripherals include SPI at 42 Mbit/s, I2C at 1 MHz, "
    "and USART up to 10.5 Mbit/s. An external 32.768 kHz crystal oscillator provides precise RTC timing."
)

def test_langextract(config_path: str = "config.json", provider: str = None, preset: str = "technical_components"):
    print("=" * 80)
    print("  GOOGLE LANGEXTRACT GROUNDED EXTRACTION DIAGNOSTIC TEST")
    print("=" * 80)

    cfg = {}
    if Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

    if provider:
        cfg["langextract_provider"] = provider
    if preset:
        cfg["langextract_schema_preset"] = preset

    engine = LangExtractEngine(cfg)
    active_prov = provider or cfg.get("langextract_provider", "gemini")
    active_preset = preset or cfg.get("langextract_schema_preset", "technical_components")

    print(f"📍 Target Provider : {active_prov}")
    print(f"🏷️  Schema Preset   : {active_preset}")
    print(f"📄 Sample Document : \"{SAMPLE_DOC[:90]}...\" ({len(SAMPLE_DOC)} chars)")
    print("-" * 80)

    start_t = time.time()
    res = engine.extract_grounded_entities(SAMPLE_DOC, schema_preset=active_preset, provider_override=active_prov)
    elapsed = time.time() - start_t

    entities = res.get("entities", [])
    resolved_provider = res.get("provider", "unknown")
    is_fallback = "fallback" in resolved_provider

    print(f"\n📊 Extraction Result:")
    print(f"  • Resolved Provider : {'⚠️ ' if is_fallback else '✅ '}{resolved_provider}")
    print(f"  • Total Entities    : {len(entities)}")
    print(f"  • Latency           : {elapsed:.2f}s")
    
    if is_fallback:
        print(f"  💡 Note: Primary provider '{active_prov}' transitioned smoothly to '{resolved_provider}' heuristic recovery.")

    print(f"\n📋 Extracted Grounded Entities Sample:")
    print(f"| {'Text Span':<22} | {'Class':<22} | {'Span Range':<12} | {'Attributes':<25} |")
    print(f"|{'-'*24}|{'-'*24}|{'-'*14}|{'-'*27}|")
    for ent in entities[:15]:
        span_str = f"[{ent.get('start_char', 0)}:{ent.get('end_char', 0)}]"
        attr_str = json.dumps(ent.get("attributes", {}), ensure_ascii=False)
        if len(attr_str) > 25:
            attr_str = attr_str[:22] + "..."
        print(f"| {ent.get('text_span', '')[:22]:<22} | {ent.get('extraction_class', '')[:22]:<22} | {span_str:<12} | {attr_str:<25} |")

    # Generate HTML visualization
    vis_path = Path("exports") / "diagnostics" / "langextract_test.html"
    vis_file = engine.generate_visualization_html(SAMPLE_DOC, res, str(vis_path))
    print(f"\n🌐 Generated Visual Report: {vis_path}")
    print("=" * 80)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test LangExtract grounded entity extraction and fallback mechanisms.")
    parser.add_argument("--config", type=str, default="config.json", help="Path to config file")
    parser.add_argument("--provider", type=str, default=None, choices=["gemini", "ollama", "openai", "fallback"], help="Force provider (gemini, ollama, openai, fallback)")
    parser.add_argument("--preset", type=str, default="technical_components", help="Schema preset")
    args = parser.parse_args()
    test_langextract(args.config, args.provider, args.preset)
