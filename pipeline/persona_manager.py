import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional

SYSTEM_PROMPTS_REPO_PATH = Path("/Users/hakankilicaslan/Git/system_prompts")

class PersonaManager:
    """
    Manages pre-configured personas, system prompts, and tool schemas from
    system_prompts repository or built-in fallback engine.
    """
    def __init__(self, repo_path: Optional[Path] = None):
        self.repo_path = repo_path or SYSTEM_PROMPTS_REPO_PATH
        self.prompts_file = self.repo_path / "prompts.json"
        self.persona_map_file = self.repo_path / "persona_map.yaml"

    def get_all_personas(self) -> List[Dict[str, Any]]:
        """Returns a list of all available personas with id, title, and description."""
        personas = []
        if self.prompts_file.exists():
            try:
                with open(self.prompts_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for pid, pdata in data.items():
                        meta = pdata.get("metadata", {})
                        personas.append({
                            "persona_id": pid,
                            "title": pid.replace("_", " ").title(),
                            "description": meta.get("description", ""),
                            "author": meta.get("author", "System"),
                            "system_prompt": pdata.get("system_prompt", "").strip()
                        })
            except Exception as e:
                print(f"Warning: Failed to parse system_prompts/prompts.json: {e}")

        # Always append default platform personas
        default_personas = [
            {
                "persona_id": "sdr_systems_engineer",
                "title": "Senior Software-Defined Radio (SDR) Systems Engineer",
                "description": "Expert in RF signals, DSP architecture, GNU Radio, and embedded firmware.",
                "author": "Elektor Platform",
                "system_prompt": "You are a professional software-defined radio (SDR) engineer and signals intelligence expert. Provide detailed technical breakdowns, RF mathematical models, and runnable C++/Python code implementations."
            },
            {
                "persona_id": "senior_python_architect",
                "title": "Senior Python Code Auditor & Architect",
                "description": "Expert in static analysis, design patterns, type safety, and AST refactoring.",
                "author": "Elektor Platform",
                "system_prompt": "You are a pragmatic, concise Python software architect. Provide direct code analysis and refactoring starting immediately with structured Markdown headings, without greetings or introductory filler."
            },
            {
                "persona_id": "embedded_firmware_developer",
                "title": "Embedded Microcontroller & Firmware Specialist",
                "description": "Specialist in RP2040, STM32, C/C++ bare-metal, freeRTOS, and peripheral drivers.",
                "author": "Elektor Platform",
                "system_prompt": "You are a senior embedded software engineer. Provide memory-safe, low-latency C/C++ firmware implementations with detailed peripheral register and hardware pinout configurations."
            }
        ]

        # Merge defaults if not present
        existing_ids = {p["persona_id"] for p in personas}
        for dp in default_personas:
            if dp["persona_id"] not in existing_ids:
                personas.append(dp)

        return personas

    def get_persona(self, persona_id: str) -> Optional[Dict[str, Any]]:
        all_p = self.get_all_personas()
        for p in all_p:
            if p["persona_id"] == persona_id:
                return p
        return None

def get_persona_manager() -> PersonaManager:
    return PersonaManager()
