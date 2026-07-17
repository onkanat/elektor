# Batch-Optimized Model Integration for Elektor Pipeline

This plan outlines the updated architecture to integrate `qwen3.6:35b-a3b-mtp-q4_K_M` (for English enrichment) and `translategemma:12b-it-q4_K_M` (for Turkish translation). 

To prevent the massive time loss of loading and unloading models for every single article, the execution is split into **two separate batch passes**, keeping each model warm in memory during its pass and unloading it only when the pass completes.

---

## 💾 Disk Space Verification

We verified the local and USB drive disk capacities:
- **Local drive (`/System/Volumes/Data`)**: **45 GB** of free space available.
- **USB Drive (`/Volumes/USB DISK`)**: **34 GB** of free space available.

Since the entire index database and exported JSONL training datasets for the 11,000+ files will require **under 1 GB** of storage, our current disk space of 45 GB is extremely safe.

---

## 🛠️ Batch Execution Architecture

Instead of calling Qwen and TranslateGemma sequentially per article, the pipeline will execute in two distinct stages:

### Pass 1: English Enrichment Batch
1. **Model**: `qwen3.6:35b-a3b-mtp-q4_K_M`.
2. **Action**: Loops through articles requiring enrichment and generates `summary`, `topics`, `sft_qa`, and `dpo_pair` in English.
3. **Optimizations**:
   - The model is kept warm in memory throughout the loop (`keep_alive` set to default/5 minutes).
   - Once the entire batch is completed, an empty request with `keep_alive=0` is sent to unload Qwen and free VRAM/RAM.

### Pass 2: Turkish Translation Batch
1. **Model**: `translategemma:12b-it-q4_K_M`.
2. **Action**: Loops through successfully enriched articles that are missing Turkish translations, translating the title and English summary.
3. **Optimizations**:
   - The model is kept warm in memory throughout the translation loop.
   - Once all translations are completed, an empty request with `keep_alive=0` is sent to unload TranslateGemma.

---

## 🛠️ Proposed Changes

### [Component 1] Configuration

#### [MODIFY] [config.json](file:///Users/hakankilicaslan/Git/elektor/config.json)
- Point `ollama_url` to the remote server `http://192.168.1.14:11434`.
- Set `model_analyzer` to `qwen3.6:35b-a3b-mtp-q4_K_M` (70.08 t/s).
- Add `model_translator` set to `translategemma:12b-it-q4_K_M`.

---

### [Component 2] Pipeline Analyzer

#### [MODIFY] [analyzer.py](file:///Users/hakankilicaslan/Git/elektor/pipeline/analyzer.py)
- Update `__init__` to load `self.translator_model` from config.
- Update `call_ollama_json` to accept `model` and `keep_alive` parameters.
- Create `analyze_article_english(self, article_id, title, text)` to generate English summaries, topics, Q&A, and DPO pairs using Qwen.
- Create `translate_to_turkish(self, title, summary)` to translate data using TranslateGemma.
- Refactor `enrich_all(self, limit=None)` to run as two sequential batch runs:
  - **Batch 1**: Select articles missing `summary` -> Run Qwen loop -> Send final unload request for Qwen.
  - **Batch 2**: Select enrichments missing `turkish_summary` -> Run TranslateGemma translation loop -> Send final unload request for TranslateGemma.

---

## 🔍 Verification Plan

### Automated Tests
- Run unit tests to verify the database and structure:
  ```bash
  python3.11 -m pytest tests/
  ```
- Run a test run of the pipeline on 2 files using the remote models:
  ```bash
  python3.11 run.py pipeline --limit 2
  ```

### Manual Verification
- Check the generated SQLite entries to verify the English analysis from `qwen3.6` and correct Turkish translations from `translategemma`.
- Run a search query to test embedding and retrieval.
