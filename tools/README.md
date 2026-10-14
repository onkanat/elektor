# Tools & Utilities Directory

Bu klasör, projenin yardımcı araçlarını, benchmark testlerini ve donanım envanter scriptlerini barındırır:

- **`benchmark_ollama.py`**: Ollama LLM / VLM modelleri için hız, token/s ve yanıt gecikmesi performans kıyaslama test aracı.
- **`benchmark.md`**: Model performans sonuçları ve kıyaslama raporu dokümanı.
- **`inspect_usb.py`**: Harici USB/NVMe depolama sürücülerini tarayıp PDF ve kaynak veri seti envanteri çıkartan yardımcı script.
- **`usb_inventory_report.json`**: USB envanter tarama rapor çıktısı.

## 📚 Mimari & Kullanım Rehberleri (`tools/docs/`)

- **[`tools/docs/phase1_extraction.md`](docs/phase1_extraction.md)**: Metin, vizyon, kod ve Kiwix ZIM çıkarma mimarisi ve SQLite şemaları.
- **[`tools/docs/kiwix_zim_mode.md`](docs/kiwix_zim_mode.md)**: Kiwix `.zim` arşivleri, StackExchange SFT/DPO eşleştirme motoru ve Web UI rehberi.
- **[`tools/docs/book_mode.md`](docs/book_mode.md)**: Tekli veya çoklu PDF kitap bölümleme ve multimodal vizyon veri üretim hattı.
- **[`tools/docs/folder_mode.md`](docs/folder_mode.md)**: Özyinelemeli yerel klasör ve dosya tarama motoru.
- **[`tools/docs/rendergit.md`](docs/rendergit.md)**: Andrej Karpathy'nin Rendergit metodolojisiyle Git kodu düzleştirme ve AST ayrıştırma.
- **[`tools/docs/LANGEXTRACT_GUIDE.md`](docs/LANGEXTRACT_GUIDE.md)**: Google LangExtract şema şablonları ve grounded karakter çapaları geliştirici rehberi.
- **[`tools/docs/huggingface_distillation_and_compute_guide.md`](docs/huggingface_distillation_and_compute_guide.md)**: Hugging Face TRL model distilasyonu ve hesaplama gücü rehberi.
