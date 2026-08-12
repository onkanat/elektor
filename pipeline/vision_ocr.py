import base64
import json
from pathlib import Path
from pipeline.llm_client import get_openai_client

class VisionOCRManager:
    def __init__(self, config_path="config.json"):
        self.config_path = Path(config_path)
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
            
        self.model_vision = self.config.get("model_vision", "deepseek-ocr:3b-bf16")
        self.client = get_openai_client(self.config)

    def unload(self):
        """Unloads the vision model from GPU VRAM if Ollama is used."""
        try:
            from pipeline.llm_client import unload_ollama_model
            unload_ollama_model(self.config, self.model_vision)
        except Exception as e:
            print(f"Warning: Failed to unload vision model '{self.model_vision}': {e}")

    def describe_image(self, image_path: str, caption_context: str = "") -> str:
        """
        Uses a vision-language model (VLM) via the OpenAI-compatible API
        to analyze a cropped drawing/chart image and return a detailed markdown description.
        """
        img_path = Path(image_path)
        if not img_path.exists():
            return f"[Error: Image file not found at {image_path}]"
            
        try:
            # Base64 encode the image
            with open(img_path, "rb") as img_file:
                base64_data = base64.b64encode(img_file.read()).decode("utf-8")
                
            if "deepseek" in self.model_vision.lower():
                prompt = "<image>\n<|grounding|>Parse the technical figure/diagram in detail. Extract and convert all visible text, labels, pinouts, component values, signal paths, and schematics into clean markdown."
                if caption_context:
                    prompt += f"\nContext/Caption: {caption_context}"
            else:
                prompt = (
                    "You are an expert technical document visual parser. Analyze this cropped image from a technical manual or datasheet.\n"
                    "Provide a precise, comprehensive markdown description of the image content:\n"
                    "1. **Type**: Classify the image (e.g., Circuit Diagram, Schematic, Flowchart, Plot/Graph, Block Diagram, Mechanical Drawing, Data Table).\n"
                    "2. **Data & Details**: Extract all text labels, pins, component names/values, signal paths, axis titles, data points, or legends visible.\n"
                    "3. **Technical Explanation**: Explain what is happening or represented in this diagram in clean technical terms.\n"
                    "Maintain absolute precision. Do not hypothesize about components not shown."
                )
                if caption_context:
                    prompt += f"\n\nContext/Caption from surrounding text:\n{caption_context}"

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_data}"
                            }
                        }
                    ]
                }
            ]
            
            response = self.client.chat.completions.create(
                model=self.model_vision,
                messages=messages,
                max_tokens=2048,
                temperature=0.2
            )
            
            description = response.choices[0].message.content
            return description.strip()
            
        except Exception as e:
            return f"[VLM Extraction Error: {str(e)}]"
