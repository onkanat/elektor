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

## 3. İkili Görü Hattı (ölçümlü, 2026-11-08 · commit `7406e14`)

Görü işleri tek modelden **iki hatta** ayrıldı; kanıt = iki bağımsız koşum + çapraz doğrulama:

| hat | model | uç | ne için | ölçüm |
|---|---|---|---|---|
| **belge** (metin sayfası/scan) | `deepseek-ocr:3b-bf16` | ECE `.26:11434` `/api/generate` (NATİVE; `/v1` yedek) | `convert_document_to_markdown` | 100-150 tok/s; koordinat kutuları `text[x1,y1,x2,y2]` doğru; döngü yok |
| **şema/figür** (CAD, blok, pinout) | `qwen3.8-flash-next-q2_0` (strata 180B) | Precision `.105:8080/v1` | `describe_cropped_image` zone-walk sözleşmesi | ~40-48 tok/s; pin eşlemeleri birebir |

- **Neden:** deepseek-ocr 3B, yoğun CAD/şema kropasında **tekrar döngüsüne düşer** (iki koşumda aynı "John\Desktop" döngüsü; şemada kullanılamaz). Strata uzun şema okumada sağlam (5 tur testi → `~/Aikonsol/docs/olcum/strata-gorsel-prompt-testi-2026-11-08.md`).
- **Rota anahtarları (`config.json`):** `vision_route_schematic_strata` (on/off) · `model_schematic_strata` · `schematic_strata_url` · `schematic_strata_api_key` (`${STRATA_API_KEY}` env genişlemeli) · `model_document_ocr` · `vision_max_tokens_schematic=3900` (yoğun şema için; 1300'de kesilir).
- **Düşüş garantili:** strata erişilemez/boş dönerse mevcut deepseek-ocr + tesseract + ornith hattı aynen devrede.
- **API anahtarı:** servis tarafında `~/.systemd user elektor-api.service` → `EnvironmentFile=%h/.config/aikon/elektor-strata.env` (0600; parmak izi `834eb3be0cf9`).
- **Tuzak (ölçüldü):** `/v1` chat-completions yolu + deepseek-ocr = bozuk çıktı ("\>"); `/api/generate` NATİVE yolu kullan (prompt'ta `<image>` öneki elle YAZILMAZ — şablonca eklenir).
- **Strata prompt sözleşmesi:** bölüm-başlık-yazılmazsa-geçersiz kuralı; kısa prompt'ta tahmin moduna girer. Tam şablon: skill `strata-kurulum-ve-olcum` → `references/gorsel-prompt-sanati.md`.
