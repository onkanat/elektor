import base64
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from pipeline.llm_client import get_openai_client

class VisionOCRManager:
    def __init__(self, config_path="config.json", config_dict=None):
        if config_dict is not None:
            self.config = config_dict
            self.config_path = Path(config_path)
        else:
            self.config_path = Path(config_path)
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
            
        self.model_vision = self.config.get("model_vision", "deepseek-ocr:3b-bf16")
        self.client = get_openai_client(self.config)

    def check_health(self) -> bool:
        """Fast ping check (2s timeout) to verify if vision server / Ollama host:port is reachable."""
        try:
            import urllib.parse
            import socket
            ollama_url = self.config.get("ollama_url", "http://localhost:11434")
            parsed = urllib.parse.urlparse(ollama_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 11434
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except Exception:
            return False

    def unload(self):
        """Unloads the vision model from GPU VRAM if Ollama is used."""
        try:
            from pipeline.llm_client import unload_ollama_model
            unload_ollama_model(self.config, self.model_vision)
        except Exception as e:
            print(f"Warning: Failed to unload vision model '{self.model_vision}': {e}")

    def _image_to_png_base64(self, image_path: str) -> Optional[str]:
        """Loads an image (PNG, WebP, JPEG, etc.), converts to RGB, and returns base64 PNG string."""
        img_path = Path(image_path)
        if not img_path.exists():
            return None
        try:
            from PIL import Image
            from io import BytesIO
            with Image.open(img_path) as img:
                buf = BytesIO()
                img.convert("RGB").save(buf, format="PNG")
                return base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception:
            try:
                with open(img_path, "rb") as f:
                    return base64.b64encode(f.read()).decode("utf-8")
            except Exception:
                return None

    def describe_image(self, image_path: str, caption_context: str = "") -> str:
        """Uses a vision-language model (VLM) via OpenAI API or native Ollama API

        to analyze a cropped drawing/chart image and return a detailed markdown description.
        """
        base64_data = self._image_to_png_base64(image_path)
        if not base64_data:
            return f"[Error: Could not load image at {image_path}]"
            
        try:
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

            # Try OpenAI SDK endpoint first
            try:
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
                    temperature=0.2,
                    extra_body={"keep_alive": "30m"}
                )
                return response.choices[0].message.content.strip()
            except Exception as sdk_err:
                # Native Ollama /api/chat fallback
                import urllib.request
                ollama_url = self.config.get("ollama_url", "http://localhost:11434").rstrip("/")
                endpoint = f"{ollama_url}/api/chat"
                payload = {
                    "model": self.model_vision,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt,
                            "images": [base64_data]
                        }
                    ],
                    "stream": False,
                    "keep_alive": "30m"
                }
                req = urllib.request.Request(
                    endpoint,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=90) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    return res_data.get("message", {}).get("content", "").strip()

        except Exception as e:
            return f"[VLM Extraction Error: {str(e)}]"

    def _clean_vlm_response(self, text: str) -> str:
        """Strips raw ChatML / prompt control tokens from VLM model outputs."""
        if not text:
            return ""
        for token in ["<|im_start|>user", "<|im_start|>assistant", "<|im_start|>", "<|im_end|>", "<|endoftext|>"]:
            text = text.replace(token, "")
        return text.strip()

    def describe_cropped_image(self, image_path: str, caption_context: str = "") -> str:
        """FAZ-11: Analyzes cropped figure/diagram with official DeepSeek-OCR prompt (<image>\nParse the figure.)."""
        base64_data = self._image_to_png_base64(image_path)
        if not base64_data:
            return f"[Error: Could not load image at {image_path}]"

        try:
            if "deepseek" in self.model_vision.lower():
                prompt = "<image>\nParse the figure."
                if caption_context:
                    prompt += f"\nContext: {caption_context}"
            else:
                prompt = f"Analyze and describe this technical figure/diagram in detail. Context: {caption_context}"

            try:
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
                    temperature=0.2,
                    extra_body={"keep_alive": "30m"}
                )
                return self._clean_vlm_response(response.choices[0].message.content)
            except Exception:
                # Native Ollama /api/chat fallback
                import urllib.request
                ollama_url = self.config.get("ollama_url", "http://localhost:11434").rstrip("/")
                endpoint = f"{ollama_url}/api/chat"
                payload = {
                    "model": self.model_vision,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt,
                            "images": [base64_data]
                        }
                    ],
                    "stream": False,
                    "keep_alive": "30m"
                }
                req = urllib.request.Request(
                    endpoint,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=90) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    raw_content = res_data.get("message", {}).get("content", "")
                    return self._clean_vlm_response(raw_content)

        except Exception as e:
            return f"[Vision Extraction Error: {str(e)}]"

    def convert_document_to_markdown(self, image_path: str) -> str:
        """FAZ-10 & FAZ-11: Converts scanned or complex PDF page image to Markdown with DeepSeek-OCR

        (<image>\n<|grounding|>Convert the document to markdown.).
        """
        base64_data = self._image_to_png_base64(image_path)
        if not base64_data:
            return ""

        try:
            prompt = "<image>\n<|grounding|>Convert the document to markdown."
            try:
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
                    max_tokens=4096,
                    temperature=0.1
                )
                return response.choices[0].message.content.strip()
            except Exception:
                import urllib.request
                ollama_url = self.config.get("ollama_url", "http://localhost:11434").rstrip("/")
                endpoint = f"{ollama_url}/api/chat"
                payload = {
                    "model": self.model_vision,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt,
                            "images": [base64_data]
                        }
                    ],
                    "stream": False
                }
                req = urllib.request.Request(
                    endpoint,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=90) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    return res_data.get("message", {}).get("content", "").strip()
        except Exception as e:
            print(f"Warning: DeepSeek-OCR document to markdown conversion error: {e}")
            return ""
