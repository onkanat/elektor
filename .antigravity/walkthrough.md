# Universal Pipeline & SDR Book Processing Walkthrough

We have successfully updated the pipeline to be fully universal and completed a successful end-to-end processing run on the textbook **"Software-Defined Radio for Engineers"**.

---

## 🛠️ Completed Implementations

### 1. Decoupled Dynamic Prompts
- Integrated `dataset_name`, `dataset_name_tr`, and `qdrant_collection_name` parameters to dynamically replace any hardcoded domain names (like "Elektor Magazine") in prompt instructions and output files.
- Configured Qwen and TranslateGemma system prompts to format with `llm_persona` and `llm_subject` parameters directly from `config.json`.

### 2. Single-Book Chapter Segmentation
- Parsed the PDF outline structure (`pypdf` outline) recursively to automatically detect and segment chapters/ranges.
- Handled empty page range issues and non-integer year parsing in PDF metadata.

### 3. Dynamic Export Directory Structure
- Restructured `DatasetBuilder` and CLI reset logic to export files directly to `exports/<db_basename>/`. This completely prevents branch merge conflicts on shared repositories.
- Updated `.gitignore` to use wildcard filters (`*.db`, `qdrant_*/`, `hf_upload_temp*/`) to keep the working tree clean.

### 4. Unbuffered Remote Server Connection
- Implemented unbuffered Python log streaming (`PYTHONUNBUFFERED=1`) to monitor remote Ollama server loading.
- Optimized memory overhead: switched from `qwen3.6:35b` to the highly stable and fast `qwen3.6:27b-mtp-q4_K_M` model to prevent VRAM allocation crashes (500 errors) under parallel settings on 2x RTX 4060 Ti GPUs.

---

## 📊 Pipeline Run Results (SDR4Engineers.pdf)

We ran the universal pipeline on `/Users/hakankilicaslan/Documents/SDR4Engineers.pdf` book mode:
- **Extraction**: Sliced range bookmarks outline, extracting **160 chapters/segments** into `sdr_engineers.db`.
- **Pass 1 (Qwen 27B)**: Successfully generated 10 English technical Q&A pairs, summary, and DPO pair per segment.
- **Pass 2 (TranslateGemma 12B)**: Successfully translated 158 segments into Turkish.
- **Embedding**: Loaded **1,278 vectors** to local Qdrant collection `"sdr_articles"` in `qdrant_sdr/`.
- **Dataset Export**: Generated 6 output files in `exports/sdr_engineers/` (approx 1.5MB total size per SFT split).
- **Hugging Face Upload**: Automatically created the repository and published the files to [onkanat/sdr-engineers-dataset](https://huggingface.co/datasets/onkanat/sdr-engineers-dataset).
- **RAG Verification**: Tested semantic query searches; matched index and chapter segments with accurate scores.
