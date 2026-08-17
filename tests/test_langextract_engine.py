import os
import json
import pytest
from pathlib import Path
from pipeline.langextract_engine import LangExtractEngine

def test_langextract_engine_initialization():
    engine = LangExtractEngine()
    status = engine.get_provider_status()
    assert "providers" in status
    assert "ollama" in status["providers"]
    assert "openai" in status["providers"]
    assert "gemini" in status["providers"]
    assert status["providers"]["ollama"]["default"] is True

def test_langextract_grounded_entity_extraction():
    engine = LangExtractEngine()
    sample_text = "The ATmega328P microcontroller operates at 16MHz and interfaces with an MPU6050 accelerometer at 3.3V."
    result = engine.extract_grounded_entities(sample_text, schema_preset="technical_components")
    
    assert "entities" in result
    assert "grounded_spans" in result
    assert result["count"] >= 1
    
    # Verify entity spans match original text exactly
    for ent in result["entities"]:
        start = ent["start_char"]
        end = ent["end_char"]
        span = ent["text_span"]
        assert sample_text[start:end] == span

def test_langextract_visualization_html_generation(tmp_path):
    engine = LangExtractEngine()
    sample_text = "The ESP32 chip operates at 3.3V with Wi-Fi and Bluetooth."
    result = engine.extract_grounded_entities(sample_text, schema_preset="technical_components")
    
    out_html = tmp_path / "test_visualizer.html"
    generated_file = engine.generate_visualization_html(sample_text, result, str(out_html))
    
    assert Path(generated_file).exists()
    content = Path(generated_file).read_text(encoding="utf-8")
    assert "LangExtract Visual Grounding Report" in content
    assert "<mark class=\"lx-entity\"" in content or "ESP32" in content
