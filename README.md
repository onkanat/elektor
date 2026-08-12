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

---

## 🚀 Key Features & Capabilities (Ana Özellikler)

### 1. Multi-Mode Ingestion (Çoklu Veri Alım Modları)
- **Rendergit Mode (`input_mode: "rendergit"`)**: Clones Git repositories (or parses local source folders), flattens codebase structure into a unified Markdown file (`exports/<project_id>_rendergit.md`), and extracts Abstract Syntax Tree (AST) code units (classes, functions) into SQLite `code_units`.
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

---

## 📁 Directory Structure (Dizin Yapısı)

```
elektor/
  ├── config.json               # Active project configuration settings
  ├── projects_index.json       # Project registry and active project tracker
  ├── projects_*.json           # Individual project configuration files
  ├── run.py                    # Unified Command Line Interface (CLI)
  ├── run_production.py         # Production batch orchestrator
  ├── api_server.py             # FastAPI backend server with project merger endpoints
  ├── pipeline/
  │    ├── __init__.py
  │    ├── extractor.py         # PDF text extraction & SQLite metadata indexing
  │    ├── code_extractor.py    # Rendergit repo flattener & AST code parser
  │    ├── analyzer.py          # Ollama LLM enrichment & synthetic code analyzer
  │    ├── vector_store.py      # Word-boundary chunking & Qdrant DB indexer
  │    ├── dataset_builder.py   # JSONL & Parquet training dataset exporter
  │    └── project_merger.py    # Phase 3 Safe Project & Dataset Merger Engine
  ├── database/                 # Dedicated SQLite database directory (*.db)
  ├── exports/                  # Project-isolated dataset export directory
  ├── frontend/                 # React + Vite Web UI with Hata Ayıklama Konsolu
  ├── .antigravity/             # System architecture reference docs (ARCHITECTURE.md)
  └── README.md
```

---

## ⚙️ Requirements & System Setup

### System Dependencies
- **Python 3.11+**
- **Tesseract OCR CLI**: Installed and available in PATH (e.g. `/opt/homebrew/bin/tesseract` on macOS).
- **Ollama Local LLM Server**: Installed and running locally. Pull required models:
  ```bash
  ollama pull nomic-embed-text:latest
  ollama pull translategemma:12b-it-q4_K_M
  ollama pull ornith:35b-q4_K_M
  ```

### Python & Frontend Setup
1. **Python Environment**:
   ```bash
    pip install pypdf pypdfium2 ollama openai qdrant-client pandas pytest fastapi uvicorn
   ```
2. **Frontend Web UI Build**:
   ```bash
   cd frontend
   npm install
   npm run build
   cd ..
   ```

---

## 🔧 Configuration Reference (`config.json` / `projects_<id>.json`)

```json
{
  "input_mode": "rendergit",
  "input_path": "https://github.com/karpathy/rendergit",
  "db_path": "database/rendergit_01.db",
  "qdrant_db_path": "qdrant_rendergit_01",
  "ollama_url": "http://192.168.1.14:11434",
  "model_embedding": "nomic-embed-text:latest",
  "model_analyzer": "ornith:35b-q4_K_M",
  "model_translator": "translategemma:12b-it-q4_K_M",
  "llm_persona": "Senior Principal Software Architect & Code Auditor",
  "llm_subject": "Python Software Architecture, AST Analysis, Performance & Security",
  "generation_language": "bilingual",
  "translation_target": "tr",
  "sft_qa_count": 15,
  "direct_tr_generation": true,
  "enable_dpo_verification": true,
  "generate_multi_turn_chat": true,
  "code_cat_explanation": true,
  "code_cat_completion": true,
  "code_cat_bug_fix": true,
  "code_cat_unit_test": true,
  "chunk_size": 800,
  "chunk_overlap": 150,
  "ocr_threshold_chars": 100,
  "tesseract_cmd": "/opt/homebrew/bin/tesseract",
  "project_id": "rendergit_01"
}
```

* **OpenAI Uyumlu Yapılandırma Seçenekleri (Opsiyonel)**:
  * `"openai_base_url"`: LLM / Embedding istekleri için temel OpenAI API URL'i (Örn: `http://192.168.1.14:11434/v1`, vLLM, SGLang, Groq). Tanımlanmazsa varsayılan olarak `"ollama_url"` parametresi sonuna otomatik `/v1` eklenerek çözümlenir.
  * `"openai_api_key"`: Groq, DeepSeek vb. harici sağlayıcılar için API anahtarı. Varsayılan: `"ollama"`.
  * `"openai_timeout"`: Soket bağlantı zaman aşımı süresi (saniye). Varsayılan: `600.0`.
  * `"analyzer_max_chars"`: LLM zenginleştirme aşamasına gönderilen döküman segmentlerinin maksimum karakter uzunluğu. Daha güçlü donanım ve geniş bağlam penceresine (context window) sahip modeller için artırılabilir. Varsayılan: `4000`.
  * `"analyzer_max_tokens"`: Üretilecek yanıtın maksimum token sınırı (`num_predict` / `max_tokens`). Varsayılan: `8192`.

---

## 📖 Usage & Execution Guide (Kullanım Rehberi)

### 1. Web UI Dashboard (FastAPI + React)
Launch the unified web dashboard with interactive project merger and debug console:
```bash
python run.py api
# Or directly via uvicorn:
python -m uvicorn api_server:app --reload --port 3456
```
Open `http://localhost:3456` in your browser.

### 2. Project Merger Workflow (Faz 3 Proje Birleştirme)
1. Open **"🗂️ Proje Gezgini & Çoklu Veri Setleri"** in Web UI.
2. Click **"🔀 Projeleri Birleştir (Merge)"**.
3. Select at least 2 source projects (e.g. `rendergit_01`, `rendergit_02`, `rendergit_03`) and enter target project ID.
4. Click **"🔍 1. İki Kez Doğrulama ve Test Çalıştırması Yap (Dry-Run Audit)"**.
5. Inspect the **🛠️ Hata Ayıklama & Ön Denetim Konsolu** report.
6. Click **"⚡ 2. Güvenli Birleştirmeyi Başlat"** to perform atomic consolidation.

### 3. Command Line Interface (CLI)
- **Full Pipeline Run**:
  ```bash
  python run.py pipeline --limit 10
  ```
- **Text & AST Code Extraction**:
  ```bash
  python run.py extract --limit 10
  ```
- **LLM Enrichment & Code Analysis**:
  ```bash
  python run.py enrich --limit 10
  ```
- **Vector Embedding (Qdrant Indexing)**:
  ```bash
  python run.py embed
  ```
- **Export Training Datasets (JSONL & Parquet)**:
  ```bash
  python run.py export
  ```

---

## 🔬 Unit Tests & Verification
Run unit tests to verify AST code parsing, repository flattening, DPO verification, and project merger logic:
```bash
PYTHONPATH=. python -m pytest tests/
```
