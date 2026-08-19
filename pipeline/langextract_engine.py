import os
import json
import re
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field

try:
    import langextract as lx
    LANGEXTRACT_AVAILABLE = True
except ImportError:
    LANGEXTRACT_AVAILABLE = False

from pipeline.project_logger import get_project_logger
from pipeline.gemini_client import get_gemini_client

# Structured Pydantic models for Grounded Extraction
class ExtractedEntityItem(BaseModel):
    extraction_class: str = Field(description="Class or type of entity (e.g., 'component', 'parameter', 'formula', 'pinout', 'task', 'concept')")
    extraction_text: str = Field(description="Exact verbatim substring found inside the text")
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Key-value properties (e.g. {'value': '50 Ohm', 'unit': 'Ohm'})")

class ExtractionPayload(BaseModel):
    extractions: List[ExtractedEntityItem] = Field(default_factory=list, description="List of extracted grounded entities")

class DynamicFewShotPackage(BaseModel):
    prompt_description: str = Field(description="Precise domain instructions for what entities to extract")
    example_text: str = Field(description="An exact sentence or short paragraph verbatim from the snippet")
    example_extractions: List[ExtractedEntityItem] = Field(description="Grounded extractions for the example text")

def locate_character_offsets(source_text: str, target_substring: str, search_start: int = 0) -> tuple[int, int]:
    """
    Robustly finds the start_char and end_char of a substring inside source_text.
    Supports exact matching, whitespace-normalized matching, and case-insensitive fallback.
    """
    if not source_text or not target_substring:
        return 0, 0

    target = target_substring.strip()
    if not target:
        return 0, 0

    # 1. Exact match starting from search_start
    idx = source_text.find(target, search_start)
    if idx != -1:
        return idx, idx + len(target)

    # 2. Exact match from beginning
    idx = source_text.find(target)
    if idx != -1:
        return idx, idx + len(target)

    # 3. Case-insensitive search
    idx = source_text.lower().find(target.lower())
    if idx != -1:
        return idx, idx + len(target)

    # 4. Normalized whitespace regex search
    pattern = re.escape(target)
    pattern = re.sub(r'\\\s+', r'\\s+', pattern)
    match = re.search(pattern, source_text, re.IGNORECASE)
    if match:
        return match.start(), match.end()

    return 0, len(target)

class LangExtractEngine:
    """
    Optimized LangExtract Engine for grounded entity extraction, source grounding,
    and interactive HTML visualizer generation.
    Supports Native Gemini API (Gemini 3.6/3.5 Flash), Ollama, and OpenAI backends.
    """

    PRESETS = {
        "technical_components": {
            "prompt": "Extract hardware/electronic components, ICs, microcontrollers, sensors, RF modules, and passive elements with part numbers, types, and functions.",
            "examples": [
                {
                    "text": "The ATmega328P microcontroller operates at 16MHz and interfaces with an MPU6050 accelerometer via I2C bus.",
                    "extractions": [
                        {
                            "extraction_class": "microcontroller",
                            "extraction_text": "ATmega328P",
                            "attributes": {"frequency": "16MHz", "bus": "I2C"}
                        },
                        {
                            "extraction_class": "sensor",
                            "extraction_text": "MPU6050",
                            "attributes": {"type": "accelerometer", "interface": "I2C"}
                        }
                    ]
                }
            ]
        },
        "circuit_specifications": {
            "prompt": "Extract circuit specifications, operating voltages, current limits, clock frequencies, communication protocols, impedances, and power ratings.",
            "examples": [
                {
                    "text": "Power supply voltage is 5.0V DC with 200mA maximum current. SPI clock frequency is up to 10 MHz with 50 Ω line termination.",
                    "extractions": [
                        {
                            "extraction_class": "voltage_spec",
                            "extraction_text": "5.0V DC",
                            "attributes": {"parameter": "Power supply voltage"}
                        },
                        {
                            "extraction_class": "current_spec",
                            "extraction_text": "200mA",
                            "attributes": {"parameter": "Maximum current"}
                        },
                        {
                            "extraction_class": "impedance_spec",
                            "extraction_text": "50 Ω",
                            "attributes": {"parameter": "Line termination"}
                        }
                    ]
                }
            ]
        },
        "engineering_exercise_sheet": {
            "prompt": "Extract academic university engineering courses, exercise/lab tasks, points, technical parameters (voltage, resistance, power, frequency, SNR, dBm), theoretical formulas, and software blocks (e.g. GNURadio).",
            "examples": [
                {
                    "text": "Lab Work 'Communications' - Summer Semester 2026. Task 1: Signal Power (8 points). Consider a coaxial line with wave resistance R = 50 Ω. Calculate power level in dBm.",
                    "extractions": [
                        {
                            "extraction_class": "course_header",
                            "extraction_text": "Lab Work 'Communications'",
                            "attributes": {"term": "Summer Semester 2026"}
                        },
                        {
                            "extraction_class": "task_item",
                            "extraction_text": "Task 1: Signal Power (8 points)",
                            "attributes": {"points": 8, "task_id": 1}
                        },
                        {
                            "extraction_class": "parameter",
                            "extraction_text": "R = 50 Ω",
                            "attributes": {"name": "R", "value": "50 Ω", "type": "wave_resistance"}
                        }
                    ]
                }
            ]
        },
        "software_units": {
            "prompt": "Extract code architecture units, functions, classes, API endpoints, data structures, algorithms, and security considerations.",
            "examples": [
                {
                    "text": "The class DataPipeline handles async SQLite batch writes and validates incoming JSON schemas via Pydantic.",
                    "extractions": [
                        {
                            "extraction_class": "class_definition",
                            "extraction_text": "DataPipeline",
                            "attributes": {"function": "handles async SQLite batch writes", "dependency": "Pydantic"}
                        }
                    ]
                }
            ]
        },
        "generic_technical_qa": {
            "prompt": "Extract technical facts, definitions, scientific laws, formulas, procedures, and empirical values with exact source grounding.",
            "examples": [
                {
                    "text": "Ohm's Law states that V = I * R, where V is voltage in volts, I is current in amperes, and R is resistance in ohms.",
                    "extractions": [
                        {
                            "extraction_class": "scientific_law",
                            "extraction_text": "Ohm's Law",
                            "attributes": {"formula": "V = I * R", "variables": "V=voltage, I=current, R=resistance"}
                        }
                    ]
                }
            ]
        }
    }

    def __init__(self, config_or_path: Any = "config.json"):
        if isinstance(config_or_path, dict):
            self.config = config_or_path
        else:
            cpath = Path(config_or_path)
            if cpath.exists():
                with open(cpath, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
            else:
                self.config = {}

        self.logger = get_project_logger()
        self.provider = self.config.get("langextract_provider", "gemini").lower()
        self.model_id = self.config.get("langextract_model_id") or "gemini-3.6-flash"
        self.gemini_client = get_gemini_client(self.config)
        self.openai_api_key = self.config.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "ollama")
        self.openai_base_url = self.config.get("openai_base_url") or os.environ.get("OPENAI_BASE_URL", "")
        self.ollama_url = self.config.get("ollama_url", "http://localhost:11434")

    def get_provider_status(self) -> Dict[str, Any]:
        """Returns provider availability and configuration status."""
        has_gemini = self.gemini_client.is_available()
        has_openai = bool(self.openai_api_key and self.openai_api_key != "ollama")
        return {
            "active_provider": self.provider,
            "active_model_id": self.model_id,
            "providers": {
                "ollama": {
                    "available": True,
                    "endpoint": self.ollama_url,
                    "default": True,
                    "cost": "Free (Local)"
                },
                "openai": {
                    "available": has_openai or bool(self.openai_base_url),
                    "endpoint": self.openai_base_url or "https://api.openai.com/v1",
                    "has_key": has_openai,
                    "cost": "API Billing"
                },
                "gemini": {
                    "available": has_gemini,
                    "has_key": has_gemini,
                    "model": "gemini-3.6-flash",
                    "cost": "Google Developer Program Credits / Billing"
                }
            }
        }

    def generate_dynamic_examples_and_prompt(
        self,
        text: str,
        schema_preset: str = "generic_technical_qa"
    ) -> Dict[str, Any]:
        """
        Pre-scans document snippet and dynamically synthesizes high-precision prompt description
        and 1-shot grounded examples directly from the text using Gemini.
        """
        snippet = text[:3000].strip()
        if not snippet:
            preset_data = self.PRESETS.get(schema_preset, self.PRESETS["technical_components"])
            return {"prompt": preset_data["prompt"], "examples": preset_data["examples"], "is_dynamic": False}

        system_instruction = """You are an expert Google LangExtract schema architect.
Analyze the provided engineering/technical document text snippet and generate:
1. 'prompt_description': Clear, highly targeted instructions on what entities, formulas, parameters, tasks, or components to extract.
2. 'example_text': Exactly ONE representative sentence or paragraph taken VERBATIM from the snippet.
3. 'example_extractions': Array of extracted entities from example_text with 'extraction_class', exact 'extraction_text' substring, and contextual 'attributes' dictionary.
"""
        user_prompt = f"Document Snippet:\n{snippet}\n\nGenerate dynamic few-shot extraction schema."

        if self.gemini_client.is_available():
            res = self.gemini_client.generate_content(
                prompt=user_prompt,
                system_instruction=system_instruction,
                model="gemini-3.6-flash",
                response_schema=DynamicFewShotPackage,
                purpose="langextract_dynamic_fewshot"
            )
            if res["success"] and res["json_data"]:
                try:
                    pkg = DynamicFewShotPackage(**res["json_data"])
                    raw_ex = [{
                        "text": pkg.example_text,
                        "extractions": [e.model_dump() for e in pkg.example_extractions]
                    }]
                    return {
                        "prompt": pkg.prompt_description,
                        "examples": raw_ex,
                        "is_dynamic": True
                    }
                except Exception as e:
                    self.logger.warning(f"Could not parse dynamic few-shot package: {e}", module="langextract")

        preset_data = self.PRESETS.get(schema_preset, self.PRESETS["technical_components"])
        return {"prompt": preset_data["prompt"], "examples": preset_data["examples"], "is_dynamic": False}

    def extract_grounded_entities(
        self,
        text: str,
        schema_preset: str = "technical_components",
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes grounded entity extraction on unstructured text with robust character offset mapping.
        """
        if not text or not text.strip():
            return {"entities": [], "grounded_spans": [], "count": 0, "preset": schema_preset, "provider": "none"}

        active_provider = (provider_override or self.provider).lower()
        active_model = model_override or self.model_id

        # 1. Generate prompt & few-shot examples
        dyn_data = self.generate_dynamic_examples_and_prompt(text, schema_preset=schema_preset)
        prompt_desc = dyn_data["prompt"]
        examples = dyn_data["examples"]

        extracted_entities = []
        grounded_spans = []

        # High-performance native Gemini execution path
        if active_provider == "gemini" and self.gemini_client.is_available():
            system_instruction = f"""You are a high-precision Grounded Information Extraction Engine.
Goal: {prompt_desc}

Rule:
- Every 'extraction_text' MUST be an exact verbatim substring from the source document.
- Assign appropriate 'extraction_class' and rich 'attributes' metadata (values, units, pins, types, etc.).
"""
            res = self.gemini_client.generate_content(
                prompt=f"### Source Document Text:\n{text}\n\nPerform grounded extraction.",
                system_instruction=system_instruction,
                model=active_model if "gemini" in active_model else "gemini-3.6-flash",
                response_schema=ExtractionPayload,
                purpose="langextract_extraction"
            )

            if res["success"] and res["json_data"]:
                try:
                    payload = ExtractionPayload(**res["json_data"])
                    last_search_offset = 0
                    for item in payload.extractions:
                        stext = item.extraction_text
                        start, end = locate_character_offsets(text, stext, search_start=last_search_offset)
                        if start > 0:
                            last_search_offset = start

                        ent_dict = {
                            "text_span": stext,
                            "start_char": start,
                            "end_char": end,
                            "extraction_class": item.extraction_class,
                            "attributes": item.attributes,
                            "preset": schema_preset
                        }
                        extracted_entities.append(ent_dict)
                        grounded_spans.append({"start": start, "end": end, "text": stext, "attr": item.attributes, "class": item.extraction_class})

                    return {
                        "entities": extracted_entities,
                        "grounded_spans": grounded_spans,
                        "count": len(extracted_entities),
                        "preset": schema_preset,
                        "provider": "gemini",
                        "model": res["model"]
                    }
                except Exception as e:
                    self.logger.warning(f"Error parsing Gemini LangExtract response: {e}", module="langextract")

        # Fallback heuristic extractor
        fallback_res = self._fallback_heuristic_extractor(text, schema_preset)
        fallback_res["provider"] = f"{active_provider}_fallback"
        fallback_res["model"] = active_model
        return fallback_res

    def _fallback_heuristic_extractor(self, text: str, schema_preset: str) -> Dict[str, Any]:
        """High-precision heuristic fallback extractor for technical documents."""
        entities = []
        spans = []

        patterns = []
        if schema_preset == "technical_components":
            patterns = [
                (r'\b(ATmega\w+|ESP32\w*|STM32\w*|PIC\w*|MPU\d+|LM\d+|NE555|MAX\d+|RP2040|nRF\d+|BME\d+|ADS\d+)\b', "microcontroller_ic"),
                (r'\b(\d+(?:\.\d+)?\s*(?:kΩ|MΩ|Ω|pF|nF|µF|uF|mF|V|mA|A|MHz|GHz|kHz))\b', "component_spec")
            ]
        elif schema_preset in ("engineering_exercise_sheet", "academic_course_materials"):
            patterns = [
                (r'\b(Task\s*\d+:[^\(\n]+|\bProblem\s*\d+:?[^\(\n]+)', "task_header"),
                (r'\b(\d+\s*points?)\b', "points_allocation"),
                (r'\b([A-Z][a-zA-Z0-9_,\s]{0,10}\s*=\s*[\-0-9\.\s]+(?:[a-zA-ZΩµμ%]+|dBm|dB|Hz|kHz|MHz|GHz|mW|W|mV|V|pW|nW|Ω))\b', "engineering_param"),
                (r'\b(GNURadio|Signal Source|LTI-Systems|Signal Theory|Signal Flow Graph|LNA|SNR|dBm|coaxial line)\b', "topic_concept")
            ]
        else:
            patterns = [
                (r'\b(\d+(?:\.\d+)?\s*(?:V|VAC|VDC|mA|A|MHz|kHz|GHz|W|mW|dBm|Ω|kΩ))\b', "spec_value"),
                (r'\b([A-Z][a-zA-Z0-9_\-]{2,})\b', "technical_term")
            ]

        for pat, ent_type in patterns:
            for match in re.finditer(pat, text, re.IGNORECASE):
                val = match.group(0)
                start, end = match.span()
                ent = {
                    "text_span": val,
                    "start_char": start,
                    "end_char": end,
                    "extraction_class": ent_type,
                    "attributes": {"entity_type": ent_type, "value": val},
                    "preset": schema_preset
                }
                entities.append(ent)
                spans.append({"start": start, "end": end, "text": val, "attr": ent["attributes"], "class": ent_type})

        return {
            "entities": entities,
            "grounded_spans": spans,
            "count": len(entities),
            "preset": schema_preset
        }

    def generate_visualization_html(self, text: str, extraction_results: Dict[str, Any], output_path: str) -> str:
        """
        Generates a modern, interactive HTML visualization report highlighting grounded source entities.
        """
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

        spans = extraction_results.get("grounded_spans", [])
        preset = extraction_results.get("preset", "technical_components")
        provider = extraction_results.get("provider", self.provider)

        highlighted_text = text
        sorted_spans = sorted(spans, key=lambda s: s.get("start", 0), reverse=True)

        for s in sorted_spans:
            start = s.get("start", 0)
            end = s.get("end", 0)
            stext = s.get("text", "")
            eclass = s.get("class", "entity")
            attr_str = json.dumps(s.get("attr", {}), ensure_ascii=False)

            if 0 <= start < end <= len(highlighted_text):
                tag = f'<mark class="lx-entity {eclass}" data-attr=\'{attr_str}\' style="background-color: #38bdf822; color: #38bdf8; padding: 2px 5px; border-radius: 4px; border: 1px solid #38bdf888; font-weight: 600;" title=\'[{eclass}] {attr_str}\'>{stext}</mark>'
                highlighted_text = highlighted_text[:start] + tag + highlighted_text[end:]

        html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LangExtract Visual Grounding Report - {preset}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: #0b0f19;
            color: #e2e8f0;
            padding: 28px;
            margin: 0;
            line-height: 1.6;
        }}
        .header {{
            background: #111827;
            padding: 20px 28px;
            border-radius: 12px;
            border-left: 5px solid #38bdf8;
            margin-bottom: 24px;
        }}
        .badge {{
            display: inline-block;
            background: #1f2937;
            color: #38bdf8;
            padding: 4px 12px;
            border-radius: 16px;
            font-size: 0.85rem;
            margin-right: 8px;
            font-weight: 500;
        }}
        .content-box {{
            background: #111827;
            padding: 24px;
            border-radius: 12px;
            white-space: pre-wrap;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 0.95rem;
            border: 1px solid #1f2937;
            line-height: 1.8;
        }}
        .stats-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 24px;
            background: #111827;
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid #1f2937;
        }}
        .stats-table th, .stats-table td {{
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid #1f2937;
        }}
        .stats-table th {{
            background: #030712;
            color: #94a3b8;
            font-weight: 600;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h2 style="margin: 0 0 10px 0; color: #60a5fa;">⚡ LangExtract Grounded Extraction & Audit</h2>
        <div>
            <span class="badge">Provider: {provider}</span>
            <span class="badge">Preset: {preset}</span>
            <span class="badge">Entities: {len(spans)}</span>
        </div>
    </div>

    <h3>📄 Grounded Document Source</h3>
    <div class="content-box">
{highlighted_text}
    </div>

    <h3>🔍 Extracted Spans & Attributes</h3>
    <table class="stats-table">
        <thead>
            <tr>
                <th>Class</th>
                <th>Span Text</th>
                <th>Offset</th>
                <th>Attributes</th>
            </tr>
        </thead>
        <tbody>
"""
        for s in spans:
            stext = s.get("text", "")
            start = s.get("start", 0)
            end = s.get("end", 0)
            eclass = s.get("class", "entity")
            attr_str = json.dumps(s.get("attr", {}), ensure_ascii=False)
            html_content += f"""            <tr>
                <td><span class="badge" style="color:#a78bfa;">{eclass}</span></td>
                <td><strong>{stext}</strong></td>
                <td><code>[{start}:{end}]</code></td>
                <td><code>{attr_str}</code></td>
            </tr>\n"""

        html_content += """        </tbody>
    </table>
</body>
</html>
"""
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(html_content)

        return str(out_file)
