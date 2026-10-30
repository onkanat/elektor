import base64
import json
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from pipeline.llm_client import get_openai_client


def _is_markdown_table_row(s: str) -> bool:
    if not s or s.startswith("#"):
        return False
    if s.startswith("|") and s.endswith("|"):
        return True
    # GFM / CommonMark table row without outer pipes (e.g. "Register | Offset | Type | Description")
    if "|" in s and not s.startswith(("- ", "* ", "> ")):
        return True
    return False


def filter_repetition_anti_loop(text: str) -> str:
    """Anti-loop filter preserving Markdown table rows (Feature 12)."""
    if not text:
        return ""
    lines = text.split("\n")
    cleaned_lines = []

    last_line = None
    repeats = 0
    for line in lines:
        s = line.strip()
        is_table_row = _is_markdown_table_row(s)
        if stripped := s:
            if stripped == last_line and not is_table_row:
                repeats += 1
                if repeats < 2:
                    cleaned_lines.append(line)
                elif repeats == 2:
                    cleaned_lines.append("*(Repetitive sequence truncated)*")
                continue
            else:
                repeats = 0
                last_line = stripped
                cleaned_lines.append(line)
        else:
            cleaned_lines.append(line)

    line_counts = {}
    for l in cleaned_lines:
        s = l.strip()
        if len(s) > 5 and not _is_markdown_table_row(s):
            line_counts[s] = line_counts.get(s, 0) + 1

    final_lines = []
    seen = {}
    for l in cleaned_lines:
        s = l.strip()
        is_table_row = _is_markdown_table_row(s)
        if not is_table_row and len(s) > 5 and line_counts.get(s, 0) > 4:
            seen[s] = seen.get(s, 0) + 1
            if seen[s] <= 3:
                final_lines.append(l)
            elif seen[s] == 4:
                final_lines.append(f"*(Further repetitions of '{s}' truncated)*")
            continue
        final_lines.append(l)

    return "\n".join(final_lines).strip()


def clean_vlm_response(text: str) -> str:
    """Strips control tokens, unclosed thinking tags, tokenizer artifacts, DeepSeek brackets,
    and applies table-aware anti-loop filtering (Features 12 & 13).
    """
    if not text:
        return ""

    cleaned = text
    # Iteratively remove innermost <think>...</think> blocks until none remain (supports nested tags)
    prev = None
    while prev != cleaned and "<think>" in cleaned and "</think>" in cleaned:
        prev = cleaned
        cleaned = re.sub(r"<think>(?:(?!<think>).)*?</think>", "", cleaned, flags=re.DOTALL)
    # Remove unclosed thinking tags caused by generation cutoff
    cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL)

    # DeepSeek Unicode thought tags (closed & unclosed, supports nesting)
    prev = None
    while prev != cleaned and "<｜thought｜>" in cleaned and "<｜end of thought｜>" in cleaned:
        prev = cleaned
        cleaned = re.sub(r"<｜thought｜>(?:(?!<｜thought｜>).)*?<｜end of thought｜>", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"<｜thought｜>.*$", "", cleaned, flags=re.DOTALL)

    # DeepSeek fullwidth brackets
    cleaned = re.sub(r"【.*?】", "", cleaned)

    # Llama 3 header tags block - MUST be stripped BEFORE individual token replacement
    cleaned = re.sub(r"<\|start_header_id\|>.*?<\|end_header_id\|>", "", cleaned, flags=re.DOTALL)

    tokens_to_strip = [
        "<|im_start|>user", "<|im_start|>assistant", "<|im_start|>system",
        "<|im_start|>", "<|im_end|>", "<|endoftext|>", "<|grounding|>",
        "<|start_header_id|>", "<|end_header_id|>", "<start_of_turn>", "<end_of_turn>",
        "<|eot_id|>", "<|begin_of_text|>",
        "<｜begin of sentence｜>", "<｜end of sentence｜>",
        "<｜User｜>", "<｜Assistant｜>",
        "<think>", "</think>"
    ]
    for tok in tokens_to_strip:
        cleaned = cleaned.replace(tok, "")

    # Tokenizer file artifacts (e.g. <|file:users.md:1:1|>)
    cleaned = re.sub(r"<\|file:[^>]+>", "", cleaned)

    # Strip conversational monologue preamble before first header or paragraph
    cleaned = re.sub(r"^(?:let me|i will|analyzing|looking at).*?(?=\n#|\n\n|\Z)", "", cleaned, flags=re.IGNORECASE | re.DOTALL)

    # Strip pre-header internal monologue if present
    first_header_match = re.search(r"^#{1,3}\s+", cleaned, flags=re.MULTILINE)
    if first_header_match and first_header_match.start() > 0:
        preamble = cleaned[:first_header_match.start()].strip().lower()
        if any(k in preamble for k in ["let me", "i will", "the user wants", "analyzing", "reconstruct", "looking at", "carefully"]):
            cleaned = cleaned[first_header_match.start():]

    # Apply table-preserving anti-loop filter
    cleaned = filter_repetition_anti_loop(cleaned)
    return cleaned.strip()


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
            
        self.model_vision = self.config.get("model_vision", "gemma4:latest")
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
        """Loads an image (PNG, WebP, JPEG, etc.) directly into a base64 encoded string."""
        img_path = Path(image_path)
        if not img_path.exists():
            return None
        try:
            with open(img_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception:
            return None

    def _clean_vlm_response(self, text: str) -> str:
        """Strips raw ChatML / prompt control tokens, think tags, and deduplicates repetitive loops."""
        return clean_vlm_response(text)

    def describe_image(self, image_path: str, caption_context: str = "") -> str:
        """Uses a vision-language model (VLM) via OpenAI API or native Ollama API
        to analyze a cropped drawing/chart image and return a detailed markdown description.
        """
        return self.describe_cropped_image(image_path=image_path, caption_context=caption_context)

    def describe_cropped_image(self, image_path: str, caption_context: str = "") -> str:
        """FAZ-11 & FAZ-17: Analyzes cropped figure/diagram/table with structured engineering prompt
        and anti-loop safeguards.
        """
        base64_data = self._image_to_png_base64(image_path)
        if not base64_data:
            return f"[Error: Could not load image at {image_path}]"

        vision_tokens = int(self.config.get("vision_max_tokens", 4096))
        prompt = (
            "Analyze and describe this technical diagram, pinout, or table in detail. "
            "Extract all visible components, pin numbers, signal names, data tables, memory blocks, and architectural connections. "
            "If it contains a table, format all data into a clean, well-aligned Markdown table. "
            "Explain what is happening and the hardware functions in clear technical terms. "
            "Output structured GitHub-flavored Markdown directly without meta-commentary."
        )
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
        top_p = 0.9

        # For Ollama endpoints, prioritize native /api/chat which reliably binds images
        ollama_url = self.config.get("ollama_url", "http://localhost:11434")
        native_ollama_url = ollama_url.rstrip("/").removesuffix("/v1")
        is_ollama_provider = "11434" in ollama_url or "ollama" in str(self.config.get("openai_api_key", "ollama")).lower()

        if is_ollama_provider:
            # Stage 1: If using DeepSeek-OCR, use specialized prompt for document/diagram extraction
            if "deepseek" in self.model_vision.lower():
                try:
                    import urllib.request
                    ocr_endpoint = f"{native_ollama_url}/api/chat"
                    ocr_payload = {
                        "model": self.model_vision,
                        "messages": [
                            {
                                "role": "user",
                                "content": "<|grounding|>Convert the document to markdown.",
                                "images": [base64_data]
                            }
                        ],
                        "options": {
                            "temperature": 0.0,
                            "repeat_penalty": 1.25,
                            "num_predict": 1024
                        },
                        "stream": False,
                        "keep_alive": "10m"
                    }
                    req = urllib.request.Request(
                        ocr_endpoint,
                        data=json.dumps(ocr_payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"}
                    )
                    raw_ocr = ""
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        res_data = json.loads(resp.read().decode("utf-8"))
                        raw_ocr = res_data.get("message", {}).get("content", "").strip()

                    # Also extract complementary crisp alphanumeric tokens via Tesseract if available
                    tess_text = ""
                    try:
                        import pytesseract
                        from PIL import Image
                        with Image.open(image_path) as img:
                            tess_text = pytesseract.image_to_string(img).strip()
                    except Exception:
                        pass

                    combined_tokens = f"Visual Extraction:\n{raw_ocr}\n\nAlphanumeric Tokens:\n{tess_text}".strip()

                    # Stage 2: Technical Synthesis via configured Analyzer Model (e.g. ornith-1.5:9b)
                    synth_model = self.config.get("model_analyzer", "ornith-1.5:9b")
                    synth_prompt = (
                        "You are a senior hardware and embedded systems engineer. "
                        "Analyze the following technical visual element and extracted OCR tokens from a microcontroller datasheet, "
                        "and produce a comprehensive, publication-grade technical breakdown in GitHub-flavored Markdown.\n\n"
                        f"Context / Caption: {caption_context}\n"
                        f"Extracted Visual Tokens:\n{combined_tokens}\n\n"
                        "Requirements:\n"
                        "1. **Diagram / Table Classification**: Classify the visual item (e.g. System Architecture Block Diagram, Package Pinout Table, Product Selection Table, Model Numbering Breakdown).\n"
                        "2. **Structured Content Extraction**: Format all tabular/pinout data into clean, well-aligned Markdown tables with proper headers. For architecture block diagrams, categorize components into systematic subsystem blocks.\n"
                        "3. **Hardware Analysis & Signal Flow**: Clearly explain operational functions, buses, signals, memory blocks, and architectural features in rigorous technical terms.\n"
                        "Output strictly clean GitHub-flavored Markdown without conversational meta-introductions or repetition loops."
                    )

                    synth_system_msg = (
                        "You are a senior hardware and embedded systems engineer. "
                        "Output strictly the final, publication-grade GitHub-flavored Markdown technical breakdown. "
                        "Do NOT output internal thinking, conversational filler, self-dialogue, or preambles."
                    )
                    synth_payload = {
                        "model": synth_model,
                        "messages": [
                            {"role": "system", "content": synth_system_msg},
                            {"role": "user", "content": synth_prompt}
                        ],
                        "options": {
                            "temperature": 0.1,
                            "num_predict": 4096
                        },
                        "stream": False,
                        "keep_alive": "10m"
                    }
                    req_synth = urllib.request.Request(
                        f"{native_ollama_url}/api/chat",
                        data=json.dumps(synth_payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"}
                    )
                    with urllib.request.urlopen(req_synth, timeout=240) as resp_synth:
                        synth_data = json.loads(resp_synth.read().decode("utf-8"))
                        msg = synth_data.get("message", {})
                        synth_content = (msg.get("content") or "").strip()
                        # If content was empty or cut off, look for markdown header in thinking
                        if not synth_content and msg.get("thinking"):
                            th = msg.get("thinking", "")
                            hdr_m = re.search(r"^#{1,3}\s+", th, flags=re.MULTILINE)
                            if hdr_m:
                                synth_content = th[hdr_m.start():].strip()
                        if synth_content and len(synth_content) > 100:
                            return self._clean_vlm_response(synth_content)
                except Exception as e:
                    pass

            # Direct native Ollama VLM path (for models like qwen2.5-vl)
            try:
                import urllib.request
                endpoint = f"{native_ollama_url}/api/chat"
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
                        "repeat_penalty": 1.2,
                        "repeat_last_n": 64,
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
                    raw_content = res_data.get("message", {}).get("content", "").strip()
                    if raw_content and not any(k in raw_content.lower() for k in ["no technical image", "no image provided", "input appears to be blank", "please upload"]):
                        return self._clean_vlm_response(raw_content)
            except Exception:
                pass

        # Try OpenAI SDK endpoint (for cloud providers or fallback)
        try:
            response = self.client.chat.completions.create(
                model=self.model_vision,
                messages=messages,
                max_tokens=vision_tokens,
                temperature=temp,
                top_p=top_p,
                extra_body={
                    "enable_thinking": False,
                    "keep_alive": "30m",
                    "repeat_penalty": 1.2,
                    "frequency_penalty": 0.2,
                    "presence_penalty": 0.2
                }
            )
            choice = response.choices[0]
            content = (choice.message.content or "").strip()
            # Safety fallback: If model spent budget in reasoning, extract from reasoning
            if not content and getattr(choice.message, "reasoning", None):
                content = choice.message.reasoning.strip()
            return self._clean_vlm_response(content)
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
                raw_content = response.choices[0].message.content or ""
                return self._clean_vlm_response(raw_content.strip())
            except Exception:
                import urllib.request
                import json
                primary_url = self.config.get("ollama_url", "http://127.0.0.1:11434").rstrip("/").removesuffix("/v1")
                fallback_url = "http://127.0.0.1:11434"

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
                data_bytes = json.dumps(payload).encode("utf-8")

                def _send(base: str) -> str:
                    clean_b = base.rstrip("/").removesuffix("/v1")
                    endpoint = f"{clean_b}/api/chat"
                    req = urllib.request.Request(
                        endpoint,
                        data=data_bytes,
                        headers={"Content-Type": "application/json"}
                    )
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        res_data = json.loads(resp.read().decode("utf-8"))
                        return res_data.get("message", {}).get("content", "") or ""

                try:
                    raw_content = _send(primary_url)
                except Exception:
                    if primary_url != fallback_url:
                        raw_content = _send(fallback_url)
                    else:
                        raise
                return self._clean_vlm_response(raw_content.strip())
        except Exception as e:
            from pipeline.project_logger import safe_print
            safe_print(f"Warning: DeepSeek-OCR document to markdown conversion error: {e}")
            return ""
