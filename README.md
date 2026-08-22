# Elektor & Universal PDF / Rendergit Code Dataset Generator

An end-to-end Python pipeline and web application designed to extract, enrich, embed, query, and merge PDF documents and Git repositories into high-quality LLM fine-tuning datasets (SFT, DPO, Multi-turn Chat, Code Completion, Bug Fix, Unit Test).

Originally built for the Elektor Magazine Archive (1974–2025), the pipeline has been refactored into a **Universal PDF & Git Repository Code Dataset Generator** supporting PDFs, technical textbooks, datasheets, and Python Git repositories via Andrej Karpathy's `rendergit` methodology.

---

## 📌 Proje Fazları ve Gelişim Durumu (Project Phase Tracker)

| Faz | Açıklama | Durum |
| :--- | :--- | :--- |
| **FAZ 1** | **Veri Seti Kalite & Doğrudan Türkçe Katmanı**: 2-Pass çeviri karmaşasını önleyen doğrudan Türkçe üretimi (`direct_tr_generation`), otomatik DPO teknik doğrulama ve izlenebilirlik metadataları. | ✅ **Tamamlandı** |
| **FAZ 2** | **Sentetik Kod Çeşitliliği Stratejisi**: AST birimlerinden 4 farklı kod üretim kategorisi (`explanation`, `completion`, `bug_fix`, `unit_test`) ve UI üzerinden aktif/deaktif etme onay kutuları. | ✅ **Tamamlandı** |
| **FAZ 3** | **Proje & Veri Seti Birleştirme Motoru**: Otomatik proje keşfi (`projects_*.json`), iki kez kontrol ("Dry-Run Audit"), canlı Hata Ayıklama Konsolu ve atomik SQLite/JSONL birleştiricisi. | ✅ **Tamamlandı** |
| **FAZ 4** | **Hugging Face Otomatik Dağıtım & Cloud GPU Offloading**: Birleştirilmiş master veri setlerinin Hugging Face Hub ortamına 2 aşamalı güvenlik denetimi ile aktarımı ve RunPod/Unsloth/Axolotl bulut GPU paket üreticisi. | ✅ **Tamamlandı** |
| **FAZ 5** | **Proje Bazlı İzole Hata & Uyarı Log Sistemi**: Her proje ihraç dizininde (`exports/<project_id>/errors_and_warnings.log`) yalnızca `WARNING` ve `ERROR` seviyelerindeki günlükleri tutan hafif log motoru. | ✅ **Tamamlandı** |
| **FAZ 6** | **Proje Gezgini Entegre System Prompt & Persona Editörü**: `prompt.html` şablonunun Proje Gezgini modalına entegrasyonu ve `system_prompts` (`persona_map.yaml`) şablon motoru. | ✅ **Tamamlandı** |
| **FAZ 7** | **HF Serverless Inference & ZeroGPU Hibrit Fallback Motoru**: Yerel GPU (`192.168.1.14`) çevrimdışı/yoğun olduğunda HF Serverless Inference API ve ZeroGPU Spaces üzerine otomatik istek yönlendirme. | 💡 **Gelecek Vizyonu** |
| **FAZ 8** | **Chat Arenası Tam Markdown & LaTeX Matematik Formül Desteği + İnsan Onaylı RLHF/DPO Puanlama Katmanı**: Chat Arenası (`SectionModelChat.tsx`) ve Veri Seti İnceleyicide (`SectionDatasetViewer.tsx`) KaTeX ile karmaşık LaTeX formülleri, matrisler ve Markdown tablolarının canlı rendering entegrasyonu; ham metin hata analizi için KaTeX On/Off (Aç/Kapa) anahtarı; insan onaylı veri seti puanlama (👍 Beğendim / 👎 Beğenmedim) ve tahribatsız silme (🗑️ Veri Setinden Sil / Excluded) API katmanı. | ✅ **Tamamlandı** |
| **FAZ 9** | **OpenAI-Uyumlu API Standardına Geçiş & Sunucu Performans / Hata Ayıklama Oturumu**: Ham Ollama istemcisinden evrensel `OpenAI` (`v1/chat/completions`) SDK standardına geçiş; vLLM, Ollama v1, SGLang ve Cloud API tak-çalıştır desteği; sunucu soket/zaman aşımı iyileştirmeleri, bellek sızıntısı ve kod refactoring oturumu. Ön uç terminal panelinde akıllı kaydırma kilidi (auto-scroll-lock) ile canlı log akışında sayfa yenilense dahi geçmiş okuma kolaylığı sağlandı. | ✅ **Tamamlandı** |
| **FAZ 10** | **Multimodal Tarama & Çizim / Grafik Anlamlandırma Motoru (DeepSeek-OCR)**: Taralı PDF'lerdeki teknik çizimleri, devre şemalarını, grafik şemaları ve görsel tabloları anlamlandırmak için `deepseek-ocr:3b-bf16` vizyon modeli entegrasyonu, akıllı yerleşim/kutu filtreleme (smart bounding box filtering) ve otomatik VRAM offload mekanizması. 2x 16GB GPU üzerinde Paralel Sharding (Port 11434 & 11435) ile SQLite WAL modunda eşzamanlı çalışma desteği. | ✅ **Tamamlandı** |
| **FAZ 11** | **Otomatik Multimodal Görsel İnce-Ayar Veri Seti Motoru (Visual Instruction Tuning / LLaVA Format)**: PDF'lerden kırpılan teknik çizim, şema ve grafiklerin (`downloads/extracted_images/`) VLM (`deepseek-ocr:3b-bf16`, `qwen3.5:4b`) ile otomatik etiketlenerek LLaVA/Qwen-VL uyumlu bağımsız **Görsel Veri Seti** (`multimodal_visual_dataset.jsonl`), WebP optimizasyonu ve `multimodal_catalog.md` olarak paketlenmesi. | ✅ **Tamamlandı** |
| **FAZ 12** | **Google LangExtract Entegrasyonu & Karakter Bazlı Kaynak Bağlama (Source Grounding)**: Google'ın `langextract` kütüphanesinin **Gemini API** (Google GenAI), **OpenAI** ve **Ollama** sağlayıcıları ile entegrasyonu; hassas karakter offset aralıkları (`start_char`, `end_char`), hazır mühendislik ve ders kitabı şemaları (`engineering_exercise_sheet`), etkileşimli HTML görselleştirme raporları ve `langextract_grounded_dataset.jsonl` ihracı. | ✅ **Tamamlandı** |
| **FAZ 13** | **Kiwix OpenZIM Kataloğu & Ansiklopedi Veri Hattı (`kiwix`)**: OpenZIM (`.zim`) formatındaki Wikipedia (Türkçe/İngilizce), StackOverflow ve akademik ansiklopedi arşivlerini `libzim` ile doğrudan okuyup SQLite `articles` tablosuna ve eğitime hazır JSONL veri setlerine dönüştüren yüksek hızlı veri alım hattı. | ✅ **Tamamlandı** |
| **FAZ 14** | **Gemini API Sağlamlaştırma & Token Bütçe Yöneticisi**: `gemini-3.6-flash`, `gemini-3.5-flash` desteği, `httpx.Limits` bağlantı havuzlama, jitter içeren üstel geri çekilme ve SQLite tabanlı `TokenBudgetManager` ile Google Developer Program kredi denetimi. | ✅ **Tamamlandı** |
| **FAZ 15** | **Bağımsız LLM-as-a-Judge & Editor-in-Chief Hakemliği**: SFT ve DPO çiftlerinin teknik doğruluk, mantık ve Türkçe sentaks açısından 1-10 skalasında hızlı puanlanması (`strict`) ve sınırda kalanların cerrahi düzeltilmesi (`hybrid_editor`). `python run.py judge` CLI ve REST API desteği. | ✅ **Tamamlandı** |
| **FAZ 16** | **LangExtract Kaynak Doğrulama & Dinamik Few-Shot Optimizasyonu**: `locate_character_offsets` ile kaynak metin hizalama, Pydantic şema zorlaması ve dökümana özel 1-shot dinamik sentezleme. | ✅ **Tamamlandı** |
| **FAZ 17** | **DeepSeek-OCR Multimodal Markdown Kataloğu**: Şema ve devre kırpmalarını görsel etiketleri (`Figure: images/crop.webp`) ve teknik dökümleriyle ihraç eden `multimodal_catalog.md` raporu. | ✅ **Tamamlandı** |
| **FAZ 18** | **Managed Agents Environment Hooks & Scheduled Triggers**: `.agents/hooks.json` altında Pre-tool Security Gate (`rm -rf /` ve bütçe engeli), Post-tool Dataset Linter (Python AST, LaTeX kontrolü) ve otonom `run.py trigger` zamanlayıcısı. | ✅ **Tamamlandı** |
| **FAZ 19** | **Hugging Face Hub & Google Vertex AI Gemini Tuning**: Gelişmiş dataset kartları, Unsloth/Axolotl kitleri ve Google Vertex AI Supervised Fine-Tuning reçetesi (`vertex_ai_tuning.json`). | ✅ **Tamamlandı** |
| **FAZ 20** | **Bulut Şablonları & Çift Dilli Veri İzolasyonu (Ollama Cloud, Gemini & Heuristic Fallback)**: Üretime hazır `templates/ollama_cloud.json` (`minimax-m3`, `gpt-oss:120b`) ve `templates/gemini.json` (`gemini-3.6-flash`) şablonları; dinamik ortam değişkeni `${VAR_NAME}` çözümleme; İngilizce ve Türkçe JSONL veri setlerinin mutlak izolasyonu; `tools/` altında 3 yeni tanı aracı (`test_gemini_config.py`, `test_ollama_cloud.py`, `test_langextract.py`) ve LangExtract çoklu sağlayıcı sezgisel kurtarma motoru. | ✅ **Tamamlandı** |

---

## 🚀 Key Features & Capabilities (Ana Özellikler)

### 1. Multi-Mode Ingestion (Çoklu Veri Alım Modları)
- **Rendergit Mode (`input_mode: "rendergit"`)**: Clones Git repositories (or parses local source folders), flattens codebase structure into a unified Markdown file (`exports/<project_id>_rendergit.md`), and extracts Abstract Syntax Tree (AST) code units (classes, functions) into SQLite `code_units`.
- **Kiwix ZIM Mode (`input_mode: "kiwix"`)**: Parses OpenZIM (`.zim`) encyclopedia/Wikipedia archives using `libzim`, converts HTML to clean Markdown with `BeautifulSoup4` + `html2text`, and indexes articles directly into SQLite.
- **Folder Mode (`input_mode: "folder"`)**: Recursively parses PDF document directories.
- **Book Mode (`input_mode: "book"`)**: Splits large PDF textbooks or datasheets into contiguous chapters using PDF outline bookmarks, with a 10-page fallback slice generator.

### 2. Synthetic Code Diversity (Faz 2 Sentetik Kod Çeşitliliği)
Generates 4 distinct, production-grade synthetic coding dataset split categories from extracted AST units:
1. **📝 Kod Açıklama & Mimari Analiz (`explanation`)**: Static audit, architectural breakdown, and complexity analysis.
2. **💻 Kod Tamamlama (`completion`)**: Function signature + docstring ➔ Clean production-grade implementation.
3. **🐛 Hata Ayıklama & Güvenlik (`bug_fix`)**: Logic bug detection, edge case handling, and vulnerability fixes.
4. **🧪 Birim Test Sentezi (`unit_test`)**: Full `pytest` test suite generation with mock fixtures.
- **Interactive UI Toggles**: Toggle individual categories on/off dynamically in `SectionConfig.tsx` via `code_cat_*` config flags.

### 3. Dataset Quality & Direct TR Generation (Faz 1 Kalite Katmanı)
- **Direct Turkish Generation (`direct_tr_generation`)**: Generates SFT Q&A, DPO pairs, and technical chats directly in Turkish, bypassing translation bottlenecks.
- **Automated DPO Verification (`enable_dpo_verification`)**: Technically validates chosen/rejected pairs for plausibility.
- **Multi-turn Technical Chat (`generate_multi_turn_chat`)**: Synthesizes step-by-step diagnostic dialogs.
- **Dataset Traceability**: Includes `quality_status`, `language`, and `dataset_type` metadata objects in JSONL exports.

### 4. Safe Project & Dataset Merger Engine (Faz 3 Birleştirme Motoru)
- **Auto-Discovery**: Scans workspace for any unindexed `projects_*.json` files and registers them automatically.
- **Two-Pass Dry-Run Audit**: Verifies database presence, table schemas, JSONL syntax integrity line-by-line, and primary key remapping strategies before execution.
- **Live Debug & Audit Console**: Color-coded UI terminal displaying safety checks and projected merged row counts.
- **Atomic Consolidated Merge**: Merges SQLite databases using dynamic column mapping (`_merge_table_dynamic`) and exports unified JSONL/Parquet datasets in `exports/<target_project_id>/`.

### 5. Google LangExtract Structured Extraction & Grounding (Faz 12 & 14 Entegrasyonu)
- **Multi-Provider Priority**: Supports **Ollama** (default zero-cost local models), **OpenAI**, **https://ollama.com/v1** cloud API, and **Gemini API** (`google-genai` / `gemini-2.5-flash`).
- **Dynamic Pre-scan & Few-Shot Generator**: Pre-scans document content to synthesize customized `prompt_description` and `lx.data.ExampleData` objects on-the-fly.
- **Precise Source Grounding**: Maps extracted entity spans back to exact character offsets (`start_char`, `end_char`) in the source text.
- **Built-in Schema Presets**:
  - `technical_components`: Hardware ICs, microcontrollers, passive elements, and functions.
  - `circuit_specifications`: Electrical parameters, voltages, current, clock frequencies, and protocols.
  - `software_units`: Code architecture, classes, functions, dependencies, and security rules.
  - `pinout_mappings`: Pin numbers, signal names, directions, and alternate functions.
  - `generic_technical_qa`: Facts, definitions, formulas, and Q&A statements.
  - `engineering_exercise_sheet`: University engineering textbook chapters, exam problems, points, parameters ($R=50\,\Omega$, $P_S=250\,\text{mW}$), theoretical formulas, and GNURadio simulation flow graphs.
- **Interactive Visualizer & Grounded Datasets**: Generates self-contained HTML visualizer reports and exports `langextract_grounded_dataset.jsonl` & `.parquet`.

---

## 📁 Directory Structure (Dizin Yapısı)

```
elektor/
  ├── config.json               # Active project configuration settings
  ├── templates/                # Production cloud templates (ollama_cloud.json, gemini.json, USER_GUIDE.md)
  ├── tools/                    # Diagnostic & verification test suite (test_ollama_cloud.py, test_gemini_config.py, test_langextract.py)
  ├── projects_index.json       # Project registry and active project tracker
  ├── projects_*.json           # Individual project configuration files
  ├── run.py                    # Unified Command Line Interface (CLI)
  ├── run_production.py         # Production batch orchestrator
  ├── api_server.py             # FastAPI backend server with project merger & LangExtract endpoints
  ├── LANGEXTRACT_GUIDE.md      # Comprehensive guide for creating custom LangExtract schema presets
  ├── USER_GUIDE.md             # End-to-end platform user guide with Web UI walkthroughs
  ├── ROADMAP.md                # Multi-phase development roadmap
  ├── .agents/                  # Gemini Managed Agents Environment Hooks & Scripts
  ├── pipeline/
  │    ├── __init__.py
  │    ├── gemini_client.py     # Resilient Gemini API client with TokenBudgetManager
  │    ├── judge_engine.py      # LLM-as-a-Judge & Editor-in-Chief arbitration engine
  │    ├── agent_hooks.py       # Pre/Post Environment Hooks manager & runner
  │    ├── scheduled_triggers.py# Autonomous scheduled trigger & background audit cron
  │    ├── extractor.py         # PDF text extraction & SQLite metadata indexing
  │    ├── code_extractor.py    # Rendergit repo flattener & AST code parser
  │    ├── kiwix_extractor.py   # Kiwix OpenZIM (.zim) catalog archive extractor
  │    ├── langextract_engine.py# Google LangExtract engine with dynamic few-shot generator, multi-provider & heuristic fallback
  │    ├── analyzer.py          # LLM enrichment & grounded DPO pair synthesizer (isolated EN & TR)
  │    ├── visual_dataset_builder.py # Multimodal Visual dataset & Markdown catalog builder
  │    ├── vector_store.py      # Word-boundary chunking & Qdrant DB indexer
  │    ├── dataset_builder.py   # JSONL & Parquet training dataset exporter (isolated EN & TR)
  │    ├── hf_deployer.py       # Hugging Face Hub automated deployment
  │    ├── cloud_gpu_offloader.py# Cloud GPU (Unsloth/Axolotl/Vertex AI) offloader
  │    ├── self_test.py         # 5-Stage autonomous system health diagnostic module
  │    └── project_merger.py    # Phase 3 Safe Project & Dataset Merger Engine
  ├── database/                 # Dedicated SQLite database directory (*.db)
  ├── exports/                  # Project-isolated dataset export directory
  ├── frontend/                 # React + Vite Web UI with Hata Ayıklama Konsolu & LangExtract panel
  ├── tests/                    # Pytest test suite (51 test cases)
  └── README.md
```

---

## ⚙️ Requirements & System Setup

### System Dependencies
- **Python 3.11+**
- **Tesseract OCR CLI**: Installed and available in PATH (e.g. `/opt/homebrew/bin/tesseract` on macOS).
- **Ollama Local / Cloud**: Local server (`http://127.0.0.1:11434`) or Ollama Cloud (`https://ollama.com/v1`).
- **Google Gemini API**: Free Tier Developer API key for `gemini-3.6-flash`.

---

## 🚀 Running Diagnostic Tools & Pipeline

### 1. Cloud & Diagnostic Verification Tools (`tools/`)
- **Google Gemini 4-Stage Test** (Connectivity, JSON Schema, Translation, Multimodal OCR):
  ```bash
  PYTHONPATH=. uv run python tools/test_gemini_config.py --config templates/gemini.json
  ```
- **Ollama Cloud Diagnostic & Model Probe**:
  ```bash
  # Model probing:
  PYTHONPATH=. uv run python tools/test_ollama_cloud.py --probe-models

  # Run test with template:
  PYTHONPATH=. uv run python tools/test_ollama_cloud.py --config templates/ollama_cloud.json
  ```
- **LangExtract Multi-Provider Grounding & Fallback Test**:
  ```bash
  PYTHONPATH=. uv run python tools/test_langextract.py --provider gemini
  PYTHONPATH=. uv run python tools/test_langextract.py --provider ollama
  PYTHONPATH=. uv run python tools/test_langextract.py --provider fallback
  ```

### 2. Web UI Dashboard (FastAPI + React)
Launch the unified web dashboard:
```bash
python run.py api
# Or directly via uvicorn:
python -m uvicorn api_server:app --reload --port 3456
```
Open `http://localhost:3456` in your browser.

### 3. Pipeline Execution with Templates
```bash
# Run with Google Gemini:
PYTHONPATH=. uv run python run.py --config templates/gemini.json

# Run with Ollama Cloud:
PYTHONPATH=. uv run python run.py --config templates/ollama_cloud.json
```

---

## 🔬 Unit Tests & Verification
Run the unit test suite:
```bash
PYTHONPATH=. uv run pytest tests/
```

### 4. Kiwix OpenZIM Catalog Extractor (`kiwix`)
Extract ZIM archives directly into SQLite database:
```bash
python run.py kiwix --zim downloads/wikipedia_tr_all.zim --limit 100
```

---

## 🔧 Configuration Reference (`config.json` / `projects_<id>.json`)

```json
{
  "input_mode": "folder",
  "input_path": "downloads/Exercisesheet1.pdf",
  "db_path": "database/extract.db",
  "qdrant_db_path": "qdrant_extract",
  "ollama_url": "http://127.0.0.1:11434",
  "openai_timeout": 600,
  "model_embedding": "nomic-embed-text:latest",
  "model_analyzer": "qwen3.5:4b",
  "model_translator": "qwen3.5:4b",
  "llm_persona": "Professional Systems Engineer",
  "llm_subject": "Technical Documentation & Architecture",
  "generation_language": "bilingual",
  "translation_target": "tr",
  "sft_qa_count": 10,
  "direct_tr_generation": true,
  "enable_dpo_verification": true,
  "generate_multi_turn_chat": true,
  "enable_langextract": true,
  "enable_langextract_dynamic_examples": true,
  "langextract_provider": "ollama",
  "langextract_schema_preset": "generic_technical_qa",
  "kiwix_zim_path": "downloads/wikipedia_tr_all.zim",
  "kiwix_min_chars": 300
}
```

---

## 🔬 Unit Tests & Verification
Run the complete unit test suite across all modules (23 passing unit tests):
```bash
PYTHONPATH=. uv run pytest tests/
```

