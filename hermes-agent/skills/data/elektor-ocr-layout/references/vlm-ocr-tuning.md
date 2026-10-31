# Vision LLM (VLM) OCR & Multimodal Catalog Tuning Reference

## 1. Two-Stage Vision OCR & Engineering Synthesis (`pipeline/vision_ocr.py` & `pipeline/visual_dataset_builder.py`)

Elektor uses a two-stage multimodal architecture configured in flat `config.json`:
1. **Stage 1 — Visual & Schematic OCR (`model_vision: "deepseek-ocr:3b-bf16"`)**:
   - Reads raw circuit schematics, block diagrams, and pinouts using `<image>\nParse the figure.` and `<image>\n<|grounding|>` prompts.
2. **Stage 2 — Ground-Truth PDF Context & Technical Synthesis (`model_analyzer: "ornith-1.5:9b"`)**:
   - Combines Stage 1 visual tokens with original PyMuPDF page text and table context to produce publication-grade GitHub-Flavored Markdown in `exports/<project_id>/multimodal_catalog.md` and instruction-tuning records in `exports/<project_id>/multimodal_visual_dataset.jsonl`.

## 2. Anti-Loop Filtering, Control-Token Stripping & Failover

- **Table-Aware Anti-Loop Filter (`pipeline/vision_ocr.py`)**:
  - Collapses genuine repetitive text loops while explicitly preserving valid Markdown table separator rows (`|---|---|`) and repeated register table headers.
- **Control-Token & Thought Sanitization (`clean_vlm_response`)**:
  - Strips `<|grounding|>`, closed and unclosed `<think>...</think>` blocks, DeepSeek full-width thought tags (`<｜begin▁of▁thought｜>`), `<|im_start|>`, and conversational preambles before writing to `multimodal_catalog.md` or `multimodal_visual_dataset.jsonl`.
- **Resilient Ollama Failover (`ResilientOllamaClient` in `pipeline/llm_client.py`)**:
  - Automatically probes `ollama_url` (e.g., `http://192.168.1.26:11434`) and fails over to local `http://127.0.0.1:11434` on connection errors or timeouts.
