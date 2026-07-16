# Elektor Archive Processing Pipeline

This project aims to build an end-to-end processing pipeline for the Elektor magazine archive (1974-2025) located at `/Volumes/USB DISK`. The extracted and enriched data will be utilized for:
1. **Vector Database RAG**: Enabling semantic search and question answering over the historical archive.
2. **AI Model Training Datasets**: Creating SFT (Supervised Fine-Tuning), DPO (Direct Preference Optimization), and Chat datasets based on technical articles.
3. **Local Ollama Inference**: Extracting topics, creating Q&As, and translating articles using local LLMs.

---

## User Review Required

Please review the following configuration parameters and design decisions:
- **Chunk Size for RAG**: Defaulting to 800 characters with 150 characters overlap for chunking.
- **Ollama Models**:
  - Embedding: `nomic-embed-text:latest`
  - Generation (Coding/Design phase): `qwen3.5:2b` or `qwen3.5:4b`
  - Generation (Production phase): Large network models (e.g., `qwen2.5:72b` or equivalent)
- **Data Formats**:
  - SFT Data: Hugging Face instruction format `{"instruction": "...", "input": "...", "output": "..."}`
  - DPO Data: `{"prompt": "...", "chosen": "...", "rejected": "..."}`
  - Chat Data: OpenAssistant format `{"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}`
- **OCR Strategy**: If direct PDF text extraction contains less than 100 characters per page, the pipeline falls back to Tesseract OCR via `pypdfium2` rendering.

---

## Open Questions

1. **OCR / Language Scope**: Do you want to process non-English versions (e.g., German, French, Dutch, Turkish) if found, and translate them to English/Turkish?
2. **Batch Processing Size**: The USB contains over 11,000 articles. For the test/development phase, we propose processing a subset (e.g., 20-50 articles) to verify quality and avoid long runtimes. Do you agree with this sample size?
3. **DPO Generation Policy**: DPO dataset requires a preferred (chosen) and dispreferred (rejected) response. Should we generate the rejected response by prompting a smaller model to make deliberate mistakes (e.g. circuit design errors, outdated concepts) or by using a lower temperature/worse prompt?

---

## Proposed Changes

We will create a structured Python package `pipeline` inside the workspace `/Users/hakankilicaslan/Git/elektor`.

### Configuration & CLI

#### [NEW] [config.json](file:///Users/hakankilicaslan/Git/elektor/config.json)
Configuration file specifying system paths, model names, Ollama URL, OCR thresholds, chunking sizes, and vector DB parameters.

#### [NEW] [run.py](file:///Users/hakankilicaslan/Git/elektor/run.py)
Orchestrator script providing a unified CLI interface:
- `python run.py extract` : Extract text from PDFs and index metadata.
- `python run.py enrich` : Call local Ollama LLM to generate Q&A, SFT, and DPO pairs.
- `python run.py embed` : Load processed documents into local Qdrant.
- `python run.py query` : Run a RAG query to search the vector database.
- `python run.py export` : Compile datasets for SFT/DPO training.

### Pipeline Modules

#### [NEW] [extractor.py](file:///Users/hakankilicaslan/Git/elektor/pipeline/extractor.py)
Handles PDF text extraction.
- Maps files using `/Volumes/USB DISK/lib/zoom_pageinfo.csv`.
- Reads files under `/Volumes/USB DISK/articles`.
- Extracts text via `pypdf`.
- Falls back to `pypdfium2` page rendering and `tesseract` CLI OCR if character count is $<100$.
- Stores results in a local SQLite file `elektor_archive.db` to prevent re-processing.

#### [NEW] [analyzer.py](file:///Users/hakankilicaslan/Git/elektor/pipeline/analyzer.py)
Integrates with the Ollama server.
- Connects to `http://localhost:11434` (configurable).
- Sends article text to generate:
  - Concise summaries and key topics.
  - SFT training pairs (Q&A style).
  - DPO comparison pairs (evaluating technical accuracy).
  - Turkish translations of abstracts/titles (or full articles).

#### [NEW] [vector_store.py](file:///Users/hakankilicaslan/Git/elektor/pipeline/vector_store.py)
Implements Vector DB storage.
- Chunks text from SQLite using a recursive character text splitter.
- Computes embeddings using Ollama's `nomic-embed-text:latest` API.
- Stores vectors and metadata in Qdrant (stored locally under `./qdrant_db`).
- Supports similarity search and hybrid search.

#### [NEW] [dataset_builder.py](file:///Users/hakankilicaslan/Git/elektor/pipeline/dataset_builder.py)
Compiles training datasets.
- Queries enriched SQLite data.
- Exports SFT dataset (`sft_dataset.jsonl`), DPO dataset (`dpo_dataset.jsonl`), and Chat datasets.

---

## Verification Plan

### Automated Tests
We will write a test suite inside `/Users/hakankilicaslan/Git/elektor/tests` to verify:
1. `pytest tests/test_extractor.py`: Verify that text is extracted from a sample PDF, and Tesseract fallback works correctly.
2. `pytest tests/test_analyzer.py`: Mock the Ollama server and verify generation formats.
3. `pytest tests/test_vector_store.py`: Verify Qdrant creation, embedding generation, and document retrieval.

### Manual Verification
1. Run a sample pipeline extraction on 5 articles: `python3.11 run.py extract --sample 5`.
2. Enrich the samples using Ollama: `python3.11 run.py enrich --sample 5`.
3. Load them into Qdrant: `python3.11 run.py embed`.
4. Perform search queries: `python3.11 run.py query "ESP32 bluetooth low energy"`.
5. Check generated dataset files under `exports/` folder.
