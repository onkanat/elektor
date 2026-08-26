# Changelog

All notable changes to the **Elektor Universal PDF & Rendergit Code Dataset Generator** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [19.5.0] - 2026-08-24

### Added
- **Hybrid Local/Cloud Embedding Router (`pipeline/llm_client.py` & `pipeline/vector_store.py`)**:
  - Added `get_embedding_client()` with automatic cloud-to-local fallback: when the primary LLM is configured on Ollama Cloud (`https://ollama.com/v1`), vector embeddings automatically route to local Ollama (`http://localhost:11434/v1`) or dedicated `embedding_url` to bypass missing cloud `/v1/embeddings` endpoints.
- **Sequence-Aware JSON & LaTeX Preservation Parser (`pipeline/analyzer.py`)**:
  - Upgraded `_parse_json_robust` with RFC 8259 sequence-aware backslash handling and `JSONDecoder(strict=False).raw_decode()`.
  - Preserves mathematical LaTeX commands starting with control letters (`\frac`, `\beta`, `\theta`, `\tau`, `\text`, `\rho`, `\begin`, `\nabla`) from being corrupted into JSON control characters (`\f`, `\b`, `\t`, `\r`).
  - Gracefully fixes unescaped backslashes (`\mu`, `\Omega`, `\d+`) without double-escaping existing valid `\\` pairs.
- **Tuple & Slice Range Limit Support (`run.py`, `pipeline/kiwix_extractor.py`, `pipeline/extractor.py`)**:
  - Full support for slice limits (`--limit 6:11`, `100:200`) across all subcommands (`extract`, `kiwix`, `enrich`, `embed`, `pipeline`).
  - Added SQLite offset querying (`LIMIT count OFFSET start`) in `ArchiveExtractor.run_langextract_all()`.
- **Comprehensive Documentation Suite (`tools/docs/`)**:
  - Created [`tools/docs/kiwix_zim_mode.md`](file:///Users/hakankilicaslan/Git/elektor/tools/docs/kiwix_zim_mode.md) detailing Kiwix ZIM architecture, auto DPO/SFT extraction, Web UI integration, and CLI workflows.
  - Updated [`tools/docs/phase1_extraction.md`](file:///Users/hakankilicaslan/Git/elektor/tools/docs/phase1_extraction.md) with Kiwix extraction engine, updated mermaid diagram, and new SQLite columns (`source_type`, `tags`, `vote_score`, `is_accepted`, `is_vetoed`, `metadata_json`).
  - Updated [`tools/README.md`](file:///Users/hakankilicaslan/Git/elektor/tools/README.md) with central documentation index.

---

## [19.4.0] - 2026-08-24

### Added
- **Kiwix ZIM StackExchange RLHF / DPO & SFT Pipeline (`pipeline/kiwix_extractor.py`)**:
  - Full StackExchange DOM parser: extracts question title, tags (`<a class="post-tag">`), question score (`data-score`), question body, closed/veto notices, and answers with vote scores.
  - Automatic DPO/ORPO pair synthesis: pairs accepted/top-voted answers (*chosen*) against downvoted/low-score answers (*rejected*) with configurable score delta (`kiwix_min_vote_diff: 2`).
  - Automatic SFT Q&A generation: structures domain-tagged question prompts mapped to accepted/gold-standard answers.
  - Dual-mode extraction: auto-detects or switches between `stackexchange` and `wiki` (encyclopedic Markdown) modes (`--mode auto|stackexchange|wiki`).
  - High-speed zero-dependency HTML-to-Markdown cleaner: converts `<pre><code>` to Markdown code fences, preserves LaTeX KaTeX/MathJax expressions (`$...$`, `$$...$$`), lists, and blockquotes.
  - High-performance batch writing: commits SQLite records in batches (default 500) using WAL mode (`PRAGMA synchronous = NORMAL; PRAGMA journal_mode = WAL;`).
- **Kiwix Web UI & Visual Inspection Suite (`frontend/src/`)**:
  - **Interactive Configuration Panel (`SectionConfig.tsx` & `ConfigEditorModal.tsx`)**: Added `kiwix` input mode, extraction mode selector (`auto`, `stackexchange`, `wiki`), SQLite batch commit size (`kiwix_batch_size`), and DPO vote delta sliders/inputs.
  - **Rich SQLite Table & Detail Modal (`SectionDatasetViewer.tsx`)**: Displays StackExchange domain tag pills (`#rf`, `#antennas`), net vote score badges (`▲ 14 oy`), green accepted solution badges (`✓ Kabul Edildi`), and community veto/closed warning badges (`🚫 Kapatılmış/Veto`). Detail modal provides top metadata cards and live KaTeX mathematical formula rendering.
  - **Dataset Preview Cards (`SectionDatasetViewer.tsx`)**: Displays `🏆 Chosen Score` vs `⚠️ Rejected Score` comparison cards for DPO datasets and domain tag context boxes for SFT datasets.
  - **TypeScript Definitions (`types.ts`)**: Added `kiwix_extract_mode`, `kiwix_min_chosen_score`, `kiwix_min_vote_diff`, and `kiwix_batch_size` to `PipelineConfig`.
- **FastAPI Kiwix Pipeline Integration (`api_server.py`)**:
  - Connected `/api/pipeline/run` endpoint to pass `--mode` and `--batch-size` CLI arguments to the Kiwix background extractor.
- **Direct Dataset Compilation from Kiwix (`pipeline/dataset_builder.py`)**:
  - `DatasetBuilder.export_datasets()` now directly compiles ground-truth SFT and DPO records from Kiwix SQLite tables into `sft_dataset.jsonl`, `dpo_dataset.jsonl`, `chat_dataset.jsonl` and `.parquet` files without requiring prior LLM inference.
- **Kiwix Test Suite (`tests/test_kiwix_extractor.py`)**:
  - Comprehensive unit and integration test suite testing HTML fragment cleaning, StackExchange DOM parsing, real `.zim` archive extraction, and dataset compilation.

---

## [19.3.0] - 2026-08-22

### Added
- **Production Cloud Templates & Environment Interpolation**: Added `templates/ollama_cloud.json` (`minimax-m3`, `gpt-oss:120b`, `gpt-oss:20b`) and `templates/gemini.json` (`gemini-3.6-flash`) with dynamic `${VAR_NAME}` environment variable resolution.
- **Dedicated Diagnostic Test Suite in `tools/`**:
  - `tools/test_ollama_cloud.py`: Supports server model probing (`--probe-models`), single model override (`--model`), and reasoning `<think>` block extraction.
  - `tools/test_gemini_config.py`: 4-stage end-to-end test verifying API connectivity, structured JSON schema extraction, technical translation, and multimodal vision OCR on circuit schematics.
  - `tools/test_langextract.py`: Diagnostic tool testing grounded entity extraction, verbatim substring character offsets, and heuristic fallback across Gemini, Ollama, OpenAI, and Fallback engines.
- **Multi-Provider LangExtract Execution**: Added native OpenAI-compatible structured JSON extraction in `pipeline/langextract_engine.py` for Ollama and OpenAI backends.
- **Templates User Guide**: Created comprehensive `templates/USER_GUIDE.md` detailing cloud template configurations, API key setups, and troubleshooting guides.

### Fixed
- **Bilingual & Direct Turkish Dataset Isolation**: Fixed `pipeline/analyzer.py` and `pipeline/dataset_builder.py` so that English datasets (`chat_dataset.jsonl`, `sft_dataset.jsonl`, `dpo_dataset.jsonl`) remain strictly in English while Turkish datasets (`tr_chat_dataset.jsonl`, `tr_sft_dataset.jsonl`, `tr_dpo_dataset.jsonl`) contain Turkish generations without cross-contamination.
- **LangExtract Heuristic Fallback Precision**: Optimized `_fallback_heuristic_extractor` regex patterns with stop-words filtering to eliminate common word noise and extract sharp technical acronyms (`HF`, `VHF`, `SDR`), ICs (`ESP32`, `STM32`), and spec values (`28 MHz`, `500 mA`).
- **Ollama Cloud 401 Unauthorized Troubleshooting**: Added automated key length verification and diagnostic guidance for truncated/missing API keys.

---

## [19.2.0] - 2026-08-21

### Added
- **VLM Vision OCR & Non-Thinking Reasoning Optimization (Faz 11)**: Configurable `vision_max_tokens` (default 4096), Qwen 3.5 non-thinking options (`enable_thinking: False`, `think: False`, `temperature: 0.7`, `top_p: 0.8`), and automatic reasoning recovery fallback to prevent empty VLM responses when reasoning tokens exhaust the budget.
- **FastAPI Static Route Mount for `/exports`**: Mounted `app.mount("/exports", StaticFiles(directory="exports"))` and added dynamic markdown image URL rewriter in `/api/dataset/catalog` to render WebP figures seamlessly in React frontend.
- **UI Dataset List Live Refresh & Multi-Project Bar**: Added `🔄 Listeyi Yenile` manual refresh button and improved multi-project filtering in `SectionDatasetViewer.tsx`.
- **Gemini API Pydantic `$defs` / `$ref` Schema Inliner**: Added recursive schema flattening in `pipeline/gemini_client.py` resolving 400 Bad Request errors on nested structured output requests.
- **Kiwix ZIM Binary MIME Filtering**: Enhanced `KiwixExtractor` to automatically skip sprite graphics and non-article binary assets in OpenZIM archives.
- **Pytest Suite Expansion**: Expanded automated unit test suite to 51 passing tests (100% pass rate).

### Fixed
- **Empty VLM Output on Heavy Schemas**: Fixed issue where reasoning models (`qwen3.5:4b`, etc.) spent all completion tokens in thinking mode, leaving empty content strings.
- **Broken Markdown Catalog Images**: Fixed 404 image errors on `multimodal_catalog.md` in browser by routing images via `/exports/<project_id>/images/`.
- **Project Explorer Export Discovery**: Fixed active project mismatch hiding newly exported JSONL and multimodal catalog files in dataset viewer.

---

## [19.0.0] - 2026-08-19

### Added
- **Gemini API Hardening & Token Budgeting (Faz 14)**: Connection-pooled `GeminiClient` with jitter exponential backoff, structured Pydantic JSON schema enforcement, and SQLite `TokenBudgetManager` for Google Developer Program credit monitoring.
- **LLM-as-a-Judge & Editor-in-Chief Arbitration (Faz 15-16)**: `JudgeEngine` with two-tier evaluation: `strict` mode for fast scoring/filtering and `hybrid_editor` for surgical rewriting of borderline SFT/DPO pairs into gold-standard candidates.
- **Optimized LangExtract Grounding & Offset Alignment (Faz 16)**: Direct Gemini 3.6 Flash integration, `locate_character_offsets` substring alignment, and dynamic few-shot meta-prompt synthesis.
- **Multimodal Markdown Catalog (Faz 17)**: `multimodal_catalog.md` generated alongside `multimodal_visual_dataset.jsonl` with embedded figures and DeepSeek-OCR technical breakdowns.
- **Managed Agents Environment Hooks & Scheduled Triggers (Faz 18)**: `.agents/hooks.json` implementation featuring pre-tool `security_gate.py`, post-tool `dataset_linter.py` (Python AST, LaTeX, JSON checks), and `scheduled_triggers.py` background audit scheduler.
- **Cloud Training Kit & Vertex AI Tuning Recipes (Faz 19)**: Unsloth/Axolotl export automation combined with Google Vertex AI Gemini fine-tuning configuration (`vertex_ai_tuning.json`).
- **React Web UI Entegrasyonu & SectionJudge (Faz 14-19 UI)**: Added new dedicated `🏛️ LLM Hakem & Editor` tab (`SectionJudge.tsx`) with Google Developer Program token/cost budget tracker, score breakdown cards, Managed Agents Hooks/Triggers panel, and in-browser Multimodal Markdown Catalog viewer (`SectionDatasetViewer.tsx`).

---

## [15.0.0] - 2026-08-18

### Added
- **Kiwix OpenZIM Catalog Extractor (`kiwix`)**: OpenZIM `.zim` archives (Wikipedia, StackOverflow) extractor via `libzim.Archive` + `BeautifulSoup4` + `html2text` HTML-to-Markdown cleaner.
- **Dynamic Document Pre-Scanning & Few-Shot Generator**: `generate_dynamic_examples_and_prompt()` and `build_lx_example_objects()` for on-the-fly customized `lx.data.ExampleData` objects in Google LangExtract.
- **Autonomous System Health Diagnostics (`self_test`)**: 5-stage health check module via `python run.py self_test` verifying SQLite WAL DB, Qdrant, Ollama VRAM status, DeepSeek-OCR VLM, and Pytest suite.
- **OpenAI-Compatible API & Cloud Endpoint Support**: Enhanced endpoint and key resolution for `https://ollama.com/v1`, custom OpenAI proxies, and API keys.

### Fixed
- Fixed `--reset` flag handling in `run.py langextract` subcommand.
- Fixed `test_qdrant_info` missing `collection` field on exception response in `api_server.py`.
- Increased Pytest execution timeout in `self_test.py` to 90 seconds.

---

## [12.0.0] - 2026-08-17

### Added
- **Google LangExtract Grounded Entity Extraction**: Multi-provider support (Ollama, OpenAI, Gemini API) with exact character offsets (`start_char`, `end_char`).
- **Engineering Exercise Sheet Schema Preset**: University engineering textbook, exercise sheet, exam problem, and GNURadio simulation extraction.
- **Self-Contained HTML Visualizer**: Grounded HTML visualization reports for extracted entities (`exports/<project_id>/langextract_visualizations/`).

---

## [10.0.0] - 2026-08-16

### Added
- **DeepSeek-OCR VLM Multimodal Vision Pipeline**: `deepseek-ocr:3b-bf16` integration with smart bounding box layout filtering.
- **2x GPU Parallel Sharding**: Parallel processing across Port 11434 & 11435 in SQLite WAL mode.
