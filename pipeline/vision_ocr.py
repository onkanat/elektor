import base64
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from pipeline.llm_client import get_openai_client

class VisionOCRManager:
    def __init__(self, config_path="config.json", config_dict=None):
        if isinstance(config_path, dict):
            self.config = config_path
            self.config_path = Path("config.json")
        elif config_dict is not None:
            self.config = config_dict
            self.config_path = Path(config_path) if isinstance(config_path, (str, Path)) else Path("config.json")
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
        """Strips raw ChatML / prompt control tokens and think tags from VLM model outputs."""
        if not text:
            return ""
        import re
        # Remove thinking blocks if present in standard content
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        for token in ["<|im_start|>user", "<|im_start|>assistant", "<|im_start|>", "<|im_end|>", "<|endoftext|>", "<think>", "</think>"]:
            text = text.replace(token, "")
        return text.strip()

    def describe_image(self, image_path: str, caption_context: str = "") -> str:
        """Uses a vision-language model (VLM) via OpenAI API or native Ollama API
        to analyze a cropped drawing/chart image and return a detailed markdown description.
        """
        base64_data = self._image_to_png_base64(image_path)
        if not base64_data:
            return f"[Error: Could not load image at {image_path}]"
            
        vision_tokens = int(self.config.get("vision_max_tokens", 4096))
        try:
            if "deepseek" in self.model_vision.lower():
                prompt = "<image>\n<|grounding|>Parse the technical figure/diagram in detail. Extract and convert all visible text, labels, pinouts, component values, signal paths, and schematics into clean markdown."
                if caption_context:
                    prompt += f"\nContext/Caption: {caption_context}"
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
                temp = 0.2
                top_p = 0.95
            else:
                system_prompt = "You are an expert technical document visual parser. Provide a direct, concise and structured markdown description of the technical diagram immediately without overthinking or lengthy internal deliberation."
                prompt = (
                    "Analyze this cropped technical diagram or schematic and provide a precise, comprehensive markdown description:\n"
                    "1. **Type**: Classify the image (e.g., Circuit Diagram, Schematic, Block Diagram, Plot/Graph, Data Table).\n"
                    "2. **Data & Details**: Extract all text labels, pins, component names/values, signal paths, axis titles, or legends visible.\n"
                    "3. **Technical Explanation**: Explain what is happening or represented in this diagram in clean technical terms.\n"
                    "Maintain absolute precision. Output structured markdown directly."
                )
                if caption_context:
                    prompt += f"\n\nContext/Caption from surrounding text:\n{caption_context}"

                messages = [
                    {"role": "system", "content": system_prompt},
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
                temp = 0.7
                top_p = 0.8

            # Try OpenAI SDK endpoint first
            try:
                response = self.client.chat.completions.create(
                    model=self.model_vision,
                    messages=messages,
                    max_tokens=vision_tokens,
                    temperature=temp,
                    top_p=top_p,
                    extra_body={"enable_thinking": False, "keep_alive": "30m"}
                )
                choice = response.choices[0]
                content = (choice.message.content or "").strip()
                # Safety fallback: If model exhausted budget during reasoning, use extracted reasoning analysis
                if not content and getattr(choice.message, "reasoning", None):
                    content = choice.message.reasoning.strip()
                return self._clean_vlm_response(content)
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
                    "options": {
                        "temperature": temp,
                        "top_p": top_p,
                        "num_predict": vision_tokens,
                        "think": False
                    },
                    "stream": False,
                    "keep_alive": "30m"
                }
                req = urllib.request.Request(
                    endpoint,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    raw_content = res_data.get("message", {}).get("content", "")
                    return self._clean_vlm_response(raw_content)

        except Exception as e:
            return f"[VLM Extraction Error: {str(e)}]"

    def describe_cropped_image(self, image_path: str, caption_context: str = "") -> str:
        """FAZ-11: Analyzes cropped figure/diagram with official DeepSeek-OCR prompt (<image>\\nParse the figure.) or direct VLM prompt."""
        base64_data = self._image_to_png_base64(image_path)
        if not base64_data:
            return f"[Error: Could not load image at {image_path}]"

        vision_tokens = int(self.config.get("vision_max_tokens", 4096))
        try:
            if "deepseek" in self.model_vision.lower():
                prompt = "<image>\nParse the figure."
                if caption_context:
                    prompt += f"\nContext: {caption_context}"
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
                temp = 0.2
                top_p = 0.95
            else:
                system_prompt = "You are a concise technical diagram analyzer. Do not overthink or produce long deliberations. Immediately output direct, clean structured markdown analysis."
                prompt = f"Analyze and describe this technical figure/diagram in detail. Context: {caption_context}"
                messages = [
                    {"role": "system", "content": system_prompt},
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
                temp = 0.7
                top_p = 0.8

            try:
                response = self.client.chat.completions.create(
                    model=self.model_vision,
                    messages=messages,
                    max_tokens=vision_tokens,
                    temperature=temp,
                    top_p=top_p,
                    extra_body={"enable_thinking": False, "keep_alive": "30m"}
                )
                choice = response.choices[0]
                content = (choice.message.content or "").strip()
                # Safety fallback: If model spent budget in reasoning, extract from reasoning
                if not content and getattr(choice.message, "reasoning", None):
                    content = choice.message.reasoning.strip()
                return self._clean_vlm_response(content)
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
                    "options": {
                        "temperature": temp,
                        "top_p": top_p,
                        "num_predict": vision_tokens,
                        "think": False
                    },
                    "stream": False,
                    "keep_alive": "30m"
                }
                req = urllib.request.Request(
                    endpoint,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
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
