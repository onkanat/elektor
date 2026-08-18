import os
import json
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    import langextract as lx
    LANGEXTRACT_AVAILABLE = True
except ImportError:
    LANGEXTRACT_AVAILABLE = False

from pipeline.project_logger import get_project_logger

class LangExtractEngine:
    """
    LangExtract Engine for structured information extraction, source grounding,
    and interactive HTML visualization generation.
    Supports Ollama (default), OpenAI, and Gemini API backends.
    """

    PRESETS = {
        "technical_components": {
            "prompt": "Extract hardware/electronic components, ICs, microcontrollers, sensors, and passive elements with their component names, part numbers, and functions.",
            "examples": [
                {
                    "text": "The ATmega328P microcontroller operates at 16MHz and interfaces with an MPU6050 accelerometer via I2C bus.",
                    "output": [
                        {
                            "component_name": "ATmega328P",
                            "type": "microcontroller",
                            "frequency": "16MHz",
                            "interface": "I2C"
                        },
                        {
                            "component_name": "MPU6050",
                            "type": "accelerometer",
                            "interface": "I2C"
                        }
                    ]
                }
            ]
        },
        "circuit_specifications": {
            "prompt": "Extract circuit specifications, operating voltages, current draw, clock frequencies, communication protocols, and pin configurations.",
            "examples": [
                {
                    "text": "Power supply voltage is 5.0V DC with 200mA maximum current. SPI clock frequency is up to 10 MHz.",
                    "output": [
                        {
                            "parameter": "Power supply voltage",
                            "value": "5.0V DC"
                        },
                        {
                            "parameter": "Maximum current",
                            "value": "200mA"
                        },
                        {
                            "parameter": "SPI clock frequency",
                            "value": "10 MHz"
                        }
                    ]
                }
            ]
        },
        "software_units": {
            "prompt": "Extract code architecture components, functions, classes, API endpoints, data structures, and security considerations.",
            "examples": [
                {
                    "text": "The class DataPipeline handles async SQLite batch writes and validates incoming JSON schemas via Pydantic.",
                    "output": [
                        {
                            "unit_name": "DataPipeline",
                            "unit_type": "class",
                            "description": "handles async SQLite batch writes",
                            "dependency": "Pydantic"
                        }
                    ]
                }
            ]
        },
        "pinout_mappings": {
            "prompt": "Extract pin names, pin numbers, signal names, direction (input/output), and alternate pin functions.",
            "examples": [
                {
                    "text": "Pin 1 (TXD, Output): Serial data transmit line connected to UART controller.",
                    "output": [
                        {
                            "pin_number": "1",
                            "pin_name": "TXD",
                            "direction": "Output",
                            "function": "Serial data transmit"
                        }
                    ]
                }
            ]
        },
        "generic_technical_qa": {
            "prompt": "Extract technical facts, definitions, formulas, procedures, and Q&A statements with exact source evidence.",
            "examples": [
                {
                    "text": "Ohm's Law states that V = I * R, where V is voltage in volts, I is current in amperes, and R is resistance in ohms.",
                    "output": [
                        {
                            "concept": "Ohm's Law",
                            "formula": "V = I * R",
                            "variables": "V=voltage, I=current, R=resistance"
                        }
                    ]
                }
            ]
        },
        "engineering_exercise_sheet": {
            "prompt": "Extract academic university course details, exam/lab exercise tasks, points, technical parameters (voltage, resistance, power, frequency, gains), theoretical formulas, and software simulation blocks (e.g. GNURadio).",
            "examples": [
                {
                    "text": "Lab Work 'Communications' - Summer Semester 2026. Task 1: Signal Power (8 points). Consider a voltage signal on a coaxial line with wave resistance R = 50 Ω. Calculate power level in dBm.",
                    "output": [
                        {
                            "course_name": "Lab Work 'Communications'",
                            "term": "Summer Semester 2026",
                            "task_name": "Task 1: Signal Power",
                            "points": 8,
                            "parameters": [
                                {"name": "R", "value": "50 Ω", "type": "wave_resistance"}
                            ],
                            "topics": ["Signal Power", "dBm conversion", "Signal Theory"]
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
        
        # Provider hierarchy: Default is 'ollama', then 'openai', then 'gemini'
        self.provider = self.config.get("langextract_provider", "ollama").lower()
        self.model_id = self.config.get("langextract_model_id") or self.config.get("model_analyzer", "ornith:35b-q4_K_M")
        self.gemini_api_key = self.config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
        self.openai_api_key = self.config.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "ollama")
        self.openai_base_url = self.config.get("openai_base_url") or os.environ.get("OPENAI_BASE_URL", "")
        self.ollama_url = self.config.get("ollama_url", "http://localhost:11434")

    def get_provider_status(self) -> Dict[str, Any]:
        """Returns the current status of all 3 providers (Ollama, OpenAI, Gemini)."""
        has_gemini = bool(self.gemini_api_key)
        has_openai = bool(self.openai_api_key and self.openai_api_key != "ollama")
        
        return {
            "langextract_installed": LANGEXTRACT_AVAILABLE,
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
                    "model": "gemini-2.5-flash",
                    "cost": "API Billing"
                }
            }
        }

    def _resolve_model_config(self, provider_override: Optional[str] = None, model_override: Optional[str] = None):
        """Builds LangExtract ModelConfig or fallback kwargs based on active provider."""
        provider = (provider_override or self.provider).lower()
        model_id = model_override or self.model_id

        if not LANGEXTRACT_AVAILABLE:
            return None, provider, model_id

        try:
            if provider == "gemini":
                if not self.gemini_api_key:
                    self.logger.warning("Gemini API key missing. Falling back to Ollama.", module="langextract")
                    provider = "ollama"
                else:
                    target_model = model_id if "gemini" in model_id.lower() else "gemini-2.5-flash"
                    config = lx.factory.ModelConfig(
                        model_id=target_model,
                        provider="GeminiLanguageModel",
                        provider_kwargs={"api_key": self.gemini_api_key}
                    )
                    return lx.factory.create_model(config), provider, target_model

            if provider == "openai":
                target_model = model_id if ("gpt" in model_id.lower() or "o3" in model_id.lower()) else "gpt-4o-mini"
                p_kwargs = {"api_key": self.openai_api_key}
                if self.openai_base_url:
                    p_kwargs["base_url"] = self.openai_base_url
                config = lx.factory.ModelConfig(
                    model_id=target_model,
                    provider="OpenAILanguageModel",
                    provider_kwargs=p_kwargs
                )
                return lx.factory.create_model(config), provider, target_model

            # Default: Ollama
            config = lx.factory.ModelConfig(
                model_id=model_id,
                provider="OllamaLanguageModel",
                provider_kwargs={"host": self.ollama_url}
            )
            return lx.factory.create_model(config), "ollama", model_id

        except Exception as e:
            self.logger.warning(f"Could not build LangExtract model config for '{provider}': {e}", module="langextract")
            return None, provider, model_id

    def generate_dynamic_examples_and_prompt(
        self,
        text: str,
        schema_preset: str = "generic_technical_qa"
    ) -> Dict[str, Any]:
        """
        Pre-scans document snippet and uses LLM to dynamically generate domain-tailored prompt_description
        and high-quality lx.data.ExampleData objects directly extracted from the actual text.
        """
        snippet = text[:2500].strip()
        if not snippet:
            preset_data = self.PRESETS.get(schema_preset, self.PRESETS["technical_components"])
            return {"prompt": preset_data["prompt"], "examples": preset_data["examples"], "is_dynamic": False}

        from pipeline.llm_client import call_llm

        system_instruction = """You are an expert Google LangExtract schema architect.
Analyze the provided document text snippet and generate:
1. 'prompt_description': Clear, precise instructions on what entities, technical concepts, parameters, functions, formulas, or relationships to extract in order of appearance.
2. 'examples': Exactly ONE high-quality example constructed directly using a sentence or paragraph from the text snippet.
The example MUST contain:
- 'text': An exact quote/sentence from the provided snippet.
- 'extractions': An array of objects, each having:
    * 'extraction_class': The type/category (e.g., 'concept', 'component', 'parameter', 'formula', 'task', 'relationship').
    * 'extraction_text': The exact verbatim substring inside 'text'.
    * 'attributes': Key-value object with contextual details (e.g. {'unit': 'MHz', 'type': 'microcontroller'}).

Output ONLY valid JSON with keys "prompt_description" and "examples"."""

        user_prompt = f"Document Snippet:\n{snippet}\n\nGenerate dynamic LangExtract prompt and few-shot example JSON."

        try:
            raw_response = call_llm(self.config, system_instruction, user_prompt, temperature=0.1)
            import re
            json_match = re.search(r"\{.*\}", raw_response, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group(0))
                prompt_desc = parsed.get("prompt_description") or self.PRESETS.get(schema_preset, {}).get("prompt", "")
                raw_examples = parsed.get("examples", [])
                if prompt_desc and raw_examples:
                    self.logger.info("Generated dynamic LangExtract prompt & few-shot example for document.", module="langextract")
                    return {
                        "prompt": prompt_desc,
                        "examples": raw_examples,
                        "is_dynamic": True
                    }
        except Exception as e:
            self.logger.warning(f"Could not generate dynamic examples: {e}. Falling back to preset.", module="langextract")

        preset_data = self.PRESETS.get(schema_preset, self.PRESETS["technical_components"])
        return {"prompt": preset_data["prompt"], "examples": preset_data["examples"], "is_dynamic": False}

    def build_lx_example_objects(self, raw_examples: List[Dict[str, Any]]) -> List[Any]:
        """Converts raw dictionary examples into Google LangExtract lx.data.ExampleData objects if available."""
        if not LANGEXTRACT_AVAILABLE:
            return raw_examples

        lx_examples = []
        try:
            for ex in raw_examples:
                if hasattr(ex, "text") and hasattr(ex, "extractions"):
                    lx_examples.append(ex)
                    continue

                t = ex.get("text", "")
                exts = ex.get("extractions") or ex.get("output") or []
                lx_ext_list = []

                for item in exts:
                    if hasattr(item, "extraction_class") and hasattr(item, "extraction_text"):
                        lx_ext_list.append(item)
                    elif isinstance(item, dict):
                        e_class = item.get("extraction_class") or item.get("type") or item.get("category") or "entity"
                        e_text = item.get("extraction_text") or item.get("text") or item.get("component_name") or item.get("concept") or ""
                        attrs = item.get("attributes") or {k: v for k, v in item.items() if k not in ("extraction_class", "extraction_text", "text", "type")}
                        if e_text:
                            lx_ext_list.append(
                                lx.data.Extraction(
                                    extraction_class=e_class,
                                    extraction_text=e_text,
                                    attributes=attrs
                                )
                            )
                if t and lx_ext_list:
                    lx_examples.append(
                        lx.data.ExampleData(
                            text=t,
                            extractions=lx_ext_list
                        )
                    )
            return lx_examples if lx_examples else raw_examples
        except Exception as e:
            self.logger.warning(f"Could not build lx.data.ExampleData objects: {e}. Using dict format.", module="langextract")
            return raw_examples

    def extract_grounded_entities(
        self,
        text: str,
        schema_preset: str = "technical_components",
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None,
        dynamic_prompt: Optional[str] = None,
        dynamic_examples: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        """
        Executes grounded entity extraction on unstructured text using dynamic or preset examples.
        Returns a dict containing extracted entities with character spans and metadata.
        """
        if not text or not text.strip():
            return {"entities": [], "grounded_spans": [], "count": 0, "preset": schema_preset}

        # Check if dynamic examples are enabled or provided
        enable_dynamic = self.config.get("enable_langextract_dynamic_examples", True)

        if dynamic_prompt and dynamic_examples:
            prompt_desc = dynamic_prompt
            raw_examples = dynamic_examples
            is_dynamic = True
        elif enable_dynamic:
            dyn_data = self.generate_dynamic_examples_and_prompt(text, schema_preset=schema_preset)
            prompt_desc = dyn_data["prompt"]
            raw_examples = dyn_data["examples"]
            is_dynamic = dyn_data.get("is_dynamic", False)
        else:
            preset_data = self.PRESETS.get(schema_preset, self.PRESETS["technical_components"])
            prompt_desc = preset_data["prompt"]
            raw_examples = preset_data["examples"]
            is_dynamic = False

        examples = self.build_lx_example_objects(raw_examples)

        model_obj, active_provider, active_model = self._resolve_model_config(provider_override, model_override)

        extracted_entities = []
        grounded_spans = []

        if LANGEXTRACT_AVAILABLE and model_obj is not None:
            try:
                # Call langextract.extract
                res = lx.extract(
                    text_or_documents=text,
                    prompt_description=prompt_desc,
                    examples=examples,
                    model_id=active_model
                )
                
                # Parse LangExtract result (handles dict and object return types)
                extractions_list = []
                if isinstance(res, dict):
                    extractions_list = res.get("extractions") or res.get("entities") or res.get("data") or []
                elif hasattr(res, "extractions"):
                    extractions_list = res.extractions or []
                
                for item in extractions_list:
                    if isinstance(item, dict):
                        span_text = item.get("text") or item.get("text_span") or ""
                        start = item.get("start_char", 0)
                        end = item.get("end_char", len(span_text))
                        attr = item.get("attributes", {})
                    else:
                        span_text = getattr(item, "text", "") or ""
                        start = getattr(item, "start_char", 0)
                        end = getattr(item, "end_char", len(span_text))
                        attr = getattr(item, "attributes", {}) or {}
                    
                    entity_record = {
                        "text_span": span_text,
                        "start_char": start,
                        "end_char": end,
                        "attributes": attr,
                        "preset": schema_preset
                    }
                    extracted_entities.append(entity_record)
                    grounded_spans.append({"start": start, "end": end, "text": span_text, "attr": attr})
                
                return {
                    "entities": extracted_entities,
                    "grounded_spans": grounded_spans,
                    "count": len(extracted_entities),
                    "preset": schema_preset,
                    "provider": active_provider,
                    "model": active_model,
                    "raw_res": str(res)
                }
            except Exception as e:
                self.logger.warning(f"LangExtract library execution error ({active_provider}): {e}. Using fallback extractor.", module="langextract")

        # Fallback Grounded Extractor when langextract library or model fails
        fallback_res = self._fallback_heuristic_extractor(text, schema_preset)
        fallback_res["provider"] = f"{active_provider}_fallback"
        fallback_res["model"] = active_model
        return fallback_res

    def _fallback_heuristic_extractor(self, text: str, schema_preset: str) -> Dict[str, Any]:
        """Heuristic fallback extractor that identifies technical entities and character offsets."""
        import re
        entities = []
        spans = []

        if schema_preset == "technical_components":
            # Find ICs, Microcontrollers, and component codes like ATmega328P, MPU6050, ESP32, NE555, LM7805
            patterns = [
                (r'\b(ATmega\w+|ESP32|STM32\w*|PIC\w*|MPU\d+|LM\d+|NE555|MAX\d+|RP2040|nRF\d+)\b', "microcontroller_ic"),
                (r'\b(\d+\s*(?:kΩ|MΩ|Ω|pF|nF|µF|uF|mF|V|mA|A|MHz|GHz|kHz))\b', "component_spec")
            ]
            for pat, ent_type in patterns:
                for match in re.finditer(pat, text, re.IGNORECASE):
                    val = match.group(0)
                    start, end = match.span()
                    ent = {
                        "text_span": val,
                        "start_char": start,
                        "end_char": end,
                        "attributes": {"entity_type": ent_type, "value": val},
                        "preset": schema_preset
                    }
                    entities.append(ent)
                    spans.append({"start": start, "end": end, "text": val, "attr": ent["attributes"]})

        elif schema_preset == "circuit_specifications":
            # Voltage/Current/Freq specs
            pat = r'\b(\d+(?:\.\d+)?\s*(?:V|VAC|VDC|mA|A|MHz|kHz|GHz|W|mW))\b'
            for match in re.finditer(pat, text, re.IGNORECASE):
                val = match.group(0)
                start, end = match.span()
                ent = {
                    "text_span": val,
                    "start_char": start,
                    "end_char": end,
                    "attributes": {"spec_type": "electrical_parameter", "value": val},
                    "preset": schema_preset
                }
                entities.append(ent)
                spans.append({"start": start, "end": end, "text": val, "attr": ent["attributes"]})

        elif schema_preset == "pinout_mappings":
            # Pin designations Pin 1, TXD, RXD, GPIO12, VCC, GND
            pat = r'\b(Pin\s*\d+|GPIO\d+|TXD\d*|RXD\d*|VCC|GND|SCL|SDA|MOSI|MISO|SCK|CS)\b'
            for match in re.finditer(pat, text, re.IGNORECASE):
                val = match.group(0)
                start, end = match.span()
                ent = {
                    "text_span": val,
                    "start_char": start,
                    "end_char": end,
                    "attributes": {"pin_designator": val},
                    "preset": schema_preset
                }
                entities.append(ent)
                spans.append({"start": start, "end": end, "text": val, "attr": ent["attributes"]})

        elif schema_preset in ("engineering_exercise_sheet", "academic_course_materials"):
            patterns = [
                (r'\b(Task\s*\d+:[^\(\n]+|\bProblem\s*\d+:?[^\(\n]+)', "task_header"),
                (r'\b(\d+\s*points?)\b', "points_allocation"),
                (r'\b([A-Z][a-zA-Z0-9_,\s]{0,10}\s*=\s*[\-0-9\.\s]+(?:[a-zA-ZΩµμ%]+|dBm|dB|Hz|kHz|MHz|GHz|mW|W|mV|V|pW|nW|Ω))\b', "engineering_param"),
                (r'\b(GNURadio|Signal Source|LTI-Systems|Signal Theory|Signal Flow Graph|LNA|SNR|dBm|coaxial line)\b', "topic_concept")
            ]
            for pat, ent_type in patterns:
                for match in re.finditer(pat, text, re.IGNORECASE):
                    val = match.group(0)
                    start, end = match.span()
                    ent = {
                        "text_span": val,
                        "start_char": start,
                        "end_char": end,
                        "attributes": {"entity_type": ent_type, "value": val},
                        "preset": schema_preset
                    }
                    entities.append(ent)
                    spans.append({"start": start, "end": end, "text": val, "attr": ent["attributes"]})

        else:
            # General capitalized technical terms
            pat = r'\b([A-Z][a-zA-Z0-9_\-]{2,})\b'
            for match in re.finditer(pat, text):
                val = match.group(0)
                start, end = match.span()
                ent = {
                    "text_span": val,
                    "start_char": start,
                    "end_char": end,
                    "attributes": {"term": val},
                    "preset": schema_preset
                }
                entities.append(ent)
                spans.append({"start": start, "end": end, "text": val, "attr": ent["attributes"]})

        return {
            "entities": entities,
            "grounded_spans": spans,
            "count": len(entities),
            "preset": schema_preset
        }

    def generate_visualization_html(self, text: str, extraction_results: Dict[str, Any], output_path: str) -> str:
        """
        Generates an interactive HTML visualization report highlighting extracted grounded entities.
        """
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

        spans = extraction_results.get("grounded_spans", [])
        preset = extraction_results.get("preset", "technical_components")
        provider = extraction_results.get("provider", self.provider)

        # Highlight spans in text
        highlighted_text = text
        # Sort spans in reverse order to preserve string offsets during replacement
        sorted_spans = sorted(spans, key=lambda s: s.get("start", 0), reverse=True)
        
        for s in sorted_spans:
            start = s.get("start", 0)
            end = s.get("end", 0)
            stext = s.get("text", "")
            attr_str = json.dumps(s.get("attr", {}), ensure_ascii=False)
            
            if 0 <= start < end <= len(highlighted_text):
                tag = f'<mark class="lx-entity" data-attr=\'{attr_str}\' style="background-color: #ffeb3b; padding: 2px 4px; border-radius: 3px; border-bottom: 2px solid #f57c00; font-weight: bold;" title=\'{attr_str}\'>{stext}</mark>'
                highlighted_text = highlighted_text[:start] + tag + highlighted_text[end:]

        html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LangExtract Visual Grounding Report - {preset}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: #121824;
            color: #e2e8f0;
            padding: 24px;
            margin: 0;
            line-height: 1.6;
        }}
        .header {{
            background: #1e293b;
            padding: 16px 24px;
            border-radius: 8px;
            border-left: 4px solid #3b82f6;
            margin-bottom: 24px;
        }}
        .header h2 {{
            margin: 0 0 8px 0;
            color: #60a5fa;
        }}
        .badge {{
            display: inline-block;
            background: #334155;
            color: #38bdf8;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 0.85rem;
            margin-right: 8px;
        }}
        .content-box {{
            background: #1e293b;
            padding: 24px;
            border-radius: 8px;
            white-space: pre-wrap;
            font-family: monospace;
            font-size: 0.95rem;
            border: 1px solid #334155;
        }}
        .stats-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 24px;
            background: #1e293b;
            border-radius: 8px;
            overflow: hidden;
        }}
        .stats-table th, .stats-table td {{
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid #334155;
        }}
        .stats-table th {{
            background: #0f172a;
            color: #94a3b8;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h2>⚡ LangExtract Source Grounding & Extraction Audit</h2>
        <div>
            <span class="badge">Provider: {provider}</span>
            <span class="badge">Preset Schema: {preset}</span>
            <span class="badge">Total Entities: {len(spans)}</span>
        </div>
    </div>

    <h3>📄 Grounded Document Content</h3>
    <div class="content-box">
{highlighted_text}
    </div>

    <h3>🔍 Extracted Entity Attributes & Spans</h3>
    <table class="stats-table">
        <thead>
            <tr>
                <th>Span Text</th>
                <th>Start Offset</th>
                <th>End Offset</th>
                <th>Attributes</th>
            </tr>
        </thead>
        <tbody>
"""
        for s in spans:
            stext = s.get("text", "")
            start = s.get("start", 0)
            end = s.get("end", 0)
            attr_str = json.dumps(s.get("attr", {}), ensure_ascii=False)
            html_content += f"""            <tr>
                <td><strong>{stext}</strong></td>
                <td>{start}</td>
                <td>{end}</td>
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
