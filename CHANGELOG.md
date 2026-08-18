# Changelog

All notable changes to the **Elektor Universal PDF & Rendergit Code Dataset Generator** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
