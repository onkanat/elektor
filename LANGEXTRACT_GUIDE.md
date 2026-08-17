# ⚡ Google LangExtract Custom Schema & Developer Guide

This document is the official developer and user guide for creating, extending, and testing custom structured extraction schemas using **Google LangExtract** within the Elektor Universal PDF & Git Code Dataset Generator pipeline.

Official Reference: [github.com/google/langextract](https://github.com/google/langextract)

---

## 📌 1. Overview & Core Philosophy

**LangExtract** is Google's open-source Python library designed to extract structured information from unstructured text documents using Large Language Models (LLMs). Unlike conventional LLM text generation, LangExtract enforces strict output schemas and provides **exact character offset grounding** (`start_char`, `end_char`), linking every extracted entity back to its exact location in the original text.

### Key Capabilities in Elektor
1. **Multi-Provider Support**:
   - **`Ollama` (Default)**: Zero-cost local LLMs (`ornith:35b`, `qwen2.5-coder`, `llama3.2`).
   - **`OpenAI`**: OpenAI API models (`gpt-4o`, `gpt-4o-mini`).
   - **`Gemini API`**: Google Gemini models (`gemini-2.5-flash`, `gemini-2.5-pro`) via `google-genai`.
2. **Provider Selection Priority**:
   - Default sequence is **`Ollama ➔ OpenAI ➔ Gemini`** to minimize external API billing costs.
3. **Interactive Visualizer Reports**:
   - Generates self-contained HTML visualizer reports in `exports/<project_id>/langextract_visualizations/` highlighting entity spans interactively.
4. **Dataset Integration**:
   - Exports `langextract_grounded_dataset.jsonl` and `.parquet` and integrates grounded spans as evidence in DPO preference pair generation.

---

## 📐 2. Built-in Schema Presets Reference

Elektor includes 6 production-grade schema presets defined in `pipeline/langextract_engine.py`:

| Preset Identifier | Target Domain & Use Case | Extracted Entities / Attributes |
| :--- | :--- | :--- |
| `technical_components` | Hardware datasheets, ICs, microcontrollers, sensors. | `component_name`, `type`, `frequency`, `interface`, `value`. |
| `circuit_specifications` | Electrical schematics, power supplies, signals. | `spec_type`, `parameter`, `value` ($5.0\,\text{V}$, $200\,\text{mA}$, $10\,\text{MHz}$). |
| `software_units` | Code architecture, AST classes, functions. | `unit_name`, `unit_type`, `description`, `dependency`. |
| `pinout_mappings` | Pinout tables, microcontroller headers, signal lines. | `pin_number`, `pin_name`, `direction` (In/Out), `function`. |
| `generic_technical_qa` | Definitions, formulas, technical facts. | `concept`, `formula`, `variables`. |
| `engineering_exercise_sheet` | University textbooks, exam sheets, lab work. | `course_name`, `task_name`, `points`, `parameters`, `topics`. |

---

## 🛠️ 3. Step-by-Step: Creating a New Custom Schema Preset

Follow this step-by-step workflow to add a new custom extraction schema preset to Elektor.

### Step 1: Define the Preset in `PRESETS` (`pipeline/langextract_engine.py`)

Open `pipeline/langextract_engine.py` and locate the `PRESETS` dictionary inside `LangExtractEngine`. Add your new preset entry:

```python
PRESETS = {
    # ... existing presets ...

    "robotics_kinematics": {
        "prompt": "Extract robotics kinematic parameters, joint types, link lengths, degrees of freedom (DoF), motor torque specs, and controller protocols.",
        "examples": [
            {
                "text": "The 6-DoF robotic arm features revolute joints driven by 24V DC brushless servomotors with 4.5 Nm peak torque over EtherCAT bus.",
                "output": [
                    {
                        "system": "robotic arm",
                        "dof": 6,
                        "joint_type": "revolute",
                        "voltage": "24V DC",
                        "motor_type": "brushless servomotor",
                        "peak_torque": "4.5 Nm",
                        "protocol": "EtherCAT"
                    }
                ]
            }
        ]
    }
}
```

### Step 2: Implement Heuristic Fallback Regex Rules

To ensure robustness when LLMs or network APIs are offline, add regex extraction rules for your new preset in `_fallback_heuristic_extractor()` inside `pipeline/langextract_engine.py`:

```python
elif schema_preset == "robotics_kinematics":
    patterns = [
        (r'\b(\d+\s*\-?\s*DoF|\d+\s*degrees\s*of\s*freedom)\b', "dof_spec"),
        (r'\b(revolute|prismatic|spherical|planar)\s+joints?\b', "joint_type"),
        (r'\b(\d+(?:\.\d+)?\s*(?:Nm|N\.m|mNm|kgcm))\b', "torque_spec"),
        (r'\b(EtherCAT|CANopen|Modbus|ROS|ROS2|PWM|UART)\b', "controller_protocol")
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
```

### Step 3: Register New Preset in Web UI (`frontend/src/components/SectionConfig.tsx`)

Open `frontend/src/components/SectionConfig.tsx` and add your preset option to the **Şema Şablonu (Preset Schema)** dropdown menu:

```tsx
<select
  name="langextract_schema_preset"
  className="form-control"
  value={formData.langextract_schema_preset || 'technical_components'}
  onChange={handleChange}
>
  <option value="technical_components">Hardware & Technical Components</option>
  <option value="circuit_specifications">Circuit & Electrical Specs</option>
  <option value="software_units">Software Architecture & AST</option>
  <option value="pinout_mappings">Pinout & Signal Mappings</option>
  <option value="generic_technical_qa">Generic Technical Q&A</option>
  <option value="engineering_exercise_sheet">Engineering Exercise Sheet</option>
  <option value="robotics_kinematics">Robotics & Kinematics Specs</option>
</select>
```

Rebuild the frontend UI bundle:
```bash
npm --prefix frontend run build
```

---

## 💻 4. Running Extractions & Verification

### Running via CLI
Run the extraction command with your new preset:
```bash
python run.py langextract --provider ollama --preset robotics_kinematics --limit 5 --visualize
```

For Gemini API (with Google GenAI):
```bash
GEMINI_API_KEY="AIzaSy..." python run.py langextract --provider gemini --preset robotics_kinematics --limit 5 --visualize
```

### Inspecting Results
1. **Interactive Visualizer**: Open `exports/<project_id>/langextract_visualizations/article_<id>_grounded.html` in your browser.
2. **Exported Datasets**: Inspect `exports/<project_id>/langextract_grounded_dataset.jsonl` and `.parquet`.

---

## 🧪 5. Adding Unit Tests

Add a unit test in `tests/test_langextract_engine.py` to verify your new schema preset:

```python
def test_custom_robotics_preset():
    engine = LangExtractEngine()
    sample = "The 6-DoF arm has revolute joints with 4.5 Nm torque over EtherCAT."
    res = engine.extract_grounded_entities(sample, schema_preset="robotics_kinematics")
    assert res["count"] >= 1
    assert any("6-DoF" in e["text_span"] for e in res["entities"])
```

Run pytest:
```bash
PYTHONPATH=. python3 -m pytest tests/test_langextract_engine.py
```
