# Elektor Pipeline Configuration & User Guide

Bu rehber, **Elektor Arşiv ve Veri Damıtma Boru Hattı** için oluşturulmuş bulut yapılandırma şablonlarının (`ollama_cloud.json` ve `gemini.json`), tanı ve test araçlarının (`tools/`) ve uçtan uca çalıştırma adımlarının kullanım kılavuzudur.

---

## 1. Hazır Yapılandırma Şablonları (`templates/`)

Boru hattı için iki adet üretime hazır ve doğrulanmış ön tanımlı şablon sunulmaktadır:

### A. Ollama Cloud Şablonu ([`templates/ollama_cloud.json`](file:///Users/hakankilicaslan/Git/elektor/templates/ollama_cloud.json))
Ollama'nın OpenAI uyumlu bulut inferans uç noktası (`https://ollama.com/v1`) için optimize edilmiştir.

- **Uç Nokta**: `https://ollama.com/v1`
- **Ön Tanımlı Analiz Modeli (`model_analyzer`)**: `minimax-m3` (Hızlı teknik akıl yürütme, SFT QA ve DPO üretimi)
- **Ön Tanımlı Çeviri Modeli (`model_translator`)**: `minimax-m3` (Teknik terimleri koruyan akıcı Türkçe çeviri)
- **Ön Tanımlı Görsel Model (`model_vision`)**: `minimax-m3` (Multimodal şema ve görsel anlama)
- **Alternatif Bulut Modelleri**: `gpt-oss:120b`, `gpt-oss:20b`, `nemotron-3-nano:30b`, `qwen3.5:397b`, `glm-5.2`
- **Gömme Modeli (`model_embedding`)**: `nomic-embed-text:latest`
- **Üretim Dili & Mod**: Çift dilli (`bilingual`), Doğrudan Türkçe Sentezi (`direct_tr_generation: true`), Çok turlu sohbet (`generate_multi_turn_chat: true`), DPO kalite denetimi (`enable_dpo_verification: true`).

```json
{
  "input_mode": "folder",
  "input_path": "downloads",
  "db_path": "database/archive.db",
  "qdrant_db_path": "qdrant_archive",
  "openai_base_url": "https://ollama.com/v1",
  "ollama_url": "https://ollama.com",
  "ollama_api_key": "${OLLAMA_API_KEY}",
  "openai_timeout": 600,
  "analyzer_max_chars": 6000,
  "analyzer_max_tokens": 4096,
  "model_embedding": "nomic-embed-text:latest",
  "model_analyzer": "minimax-m3",
  "model_translator": "minimax-m3",
  "model_vision": "minimax-m3",
  "generation_language": "bilingual",
  "direct_tr_generation": true,
  "enable_dpo_verification": true,
  "generate_multi_turn_chat": true
}
```

---

### B. Google Gemini Şablonu ([`templates/gemini.json`](file:///Users/hakankilicaslan/Git/elektor/templates/gemini.json))
Google Gemini API için optimize edilmiştir (Geniş bağlam, yüksek hızlı şema çıkarımı ve gelişmiş OCR).

- **Uç Nokta**: `https://generativelanguage.googleapis.com/v1beta`
- **Ön Tanımlı Model**: `gemini-3.6-flash` (1M+ token bağlamı, Pydantic/JSON Schema tam uyumu)
- **Görsel OCR Modeli (`model_vision`)**: `gemini-3.6-flash` (Elektronik şemaları, pinout'lar ve blok diyagramlarda SOTA OCR)
- **LangExtract Sağlayıcısı**: `gemini` (`generic_technical_qa` şema önayarı)
- **Gömme Modeli (`model_embedding`)**: `nomic-embed-text:latest` (veya `text-embedding-004`)
- **Üretim Dili & Mod**: Çift dilli (`bilingual`), Doğrudan Türkçe Sentezi (`direct_tr_generation: true`), Görsel OCR ve LangExtract aktif.

```json
{
  "input_mode": "folder",
  "input_path": "downloads",
  "db_path": "database/archive.db",
  "qdrant_db_path": "qdrant_archive",
  "gemini_api_key": "${GEMINI_API_KEY}",
  "gemini_model": "gemini-3.6-flash",
  "model_analyzer": "gemini-3.6-flash",
  "model_translator": "gemini-3.6-flash",
  "model_vision": "gemini-3.6-flash",
  "langextract_provider": "gemini",
  "generation_language": "bilingual",
  "direct_tr_generation": true,
  "enable_vision_ocr": true,
  "enable_langextract": true
}
```

---

## 2. API Anahtarlarının Yapılandırılması

Şablonlar, API anahtarlarını doğrudan dosya içine yazmak yerine ortam değişkenlerinden dinamik olarak yükler (`${OLLAMA_API_KEY}`, `${GEMINI_API_KEY}`).

### A. Ollama Cloud Anahtarı
1. [ollama.com/settings/keys](https://ollama.com/settings/keys) adresine gidin.
2. **Keys** sekmesinden tam API anahtarını (57 karakter uzunluğundaki anahtar) kopyalayın.
3. Terminalinizde veya `~/.zshrc` dosyanızda tanımlayın:
   ```bash
   export OLLAMA_API_KEY="f08b...Cfs_"
   ```

### B. Google Gemini API Anahtarı
1. [Google AI Studio](https://aistudio.google.com/app/apikey) üzerinden bir API anahtarı alın.
2. Terminalinizde veya `~/.zshrc` dosyanızda tanımlayın:
   ```bash
   export GEMINI_API_KEY="AIzaSy..."
   ```

---

## 3. Tanı ve Test Araçları (`tools/`)

Boru hattını çalıştırmadan önce uç noktaların, modellerin ve kimlik doğrulamanın çalıştığını test etmek için `tools/` altındaki araçları kullanabilirsiniz.

### A. Google Gemini Doğrulama Aracı
4 aşamalı tanı testi yürütür (Bağlantı, Yapılandırılmış JSON Şeması, Türkçe Çeviri, Multimodal Devre Şeması OCR, Token/Maliyet Analizi):

```bash
PYTHONPATH=. uv run python tools/test_gemini_config.py --config templates/gemini.json
```

**Örnek Çıktı:**
```text
================================================================================
  GEMINI DIAGNOSTIC SUMMARY
================================================================================
| Diagnostic Step                     | Status   | Metrics / Details              |
|-------------------------------------|----------|--------------------------------|
| API Connectivity                    | ✅ PASS  | Response in 10.00s             |
| Structured JSON (gemini-3.6-flash)  | ✅ PASS  | 5.13s (309 tokens)             |
| Technical Translation (TR)          | ✅ PASS  | 2.65s                          |
| Multimodal Vision OCR               | ✅ PASS  | 2.80s (LM7805 tespit edildi)   |
================================================================================
```

---

### B. Ollama Cloud Doğrulama Aracı
Model keşfi, yapılandırılmış JSON çıkarımı, Türkçe çeviri ve model tarama yeteneklerine sahiptir:

```bash
# Standart şablon testi:
PYTHONPATH=. uv run python tools/test_ollama_cloud.py --config templates/ollama_cloud.json

# Belirli bir modeli test etme:
PYTHONPATH=. uv run python tools/test_ollama_cloud.py --model minimax-m3
PYTHONPATH=. uv run python tools/test_ollama_cloud.py --model gpt-oss:120b
PYTHONPATH=. uv run python tools/test_ollama_cloud.py --model gpt-oss:20b

# Sunucudaki tüm modelleri otomatik tarama:
PYTHONPATH=. uv run python tools/test_ollama_cloud.py --probe-models

# Yerel Ollama sunucusunu test etme:
PYTHONPATH=. uv run python tools/test_ollama_cloud.py --host http://127.0.0.1:11434
```

**Örnek Çıktı:**
### C. Google LangExtract Varlık Çıkarım & Fallback Doğrulama Aracı
LangExtract motorunun sağlayıcılarını (`gemini`, `ollama`, `openai`, `fallback`) ve metin içi kanıt (`grounded span`) çıkarma yeteneklerini test eder:

```bash
# Gemini ile test:
PYTHONPATH=. uv run python tools/test_langextract.py --provider gemini

# Ollama ile test:
PYTHONPATH=. uv run python tools/test_langextract.py --config templates/ollama_cloud.json --provider ollama

# Yerel sezgisel fallback kural motorunu test:
PYTHONPATH=. uv run python tools/test_langextract.py --provider fallback
```

---

## 4. Boru Hattını Çalıştırma (Pipeline Execution)

Hazır şablonlarla veri damıtma sürecini başlatmak için:

### A. Gemini Şablonu ile Çalıştırma:
```bash
PYTHONPATH=. uv run python run.py --config templates/gemini.json
```

### B. Ollama Cloud Şablonu ile Çalıştırma:
```bash
PYTHONPATH=. uv run python run.py --config templates/ollama_cloud.json
```

### C. Özel Bir Proje Olarak Çalıştırma:
Şablonu kendi proje adınızla kopyalayarak özelleştirebilirsiniz:
```bash
cp templates/gemini.json projects_myproject.json
# input_path, dataset_name vb. alanları düzenleyin
PYTHONPATH=. uv run python run.py --config projects_myproject.json
```

---

## 5. Sorun Giderme (Troubleshooting)

| Sorun / Hata | Olası Neden | Çözüm |
|---|---|---|
| `401 Unauthorized` (Ollama Cloud) | API anahtarı eksik veya 32 karakterde kırpılmış. | [ollama.com/settings/keys](https://ollama.com/settings/keys) üzerinden 57 karakterlik tam anahtarı kopyalayıp `export OLLAMA_API_KEY="..."` yapın. |
| `GEMINI_API_KEY not configured` | Gemini API anahtarı tanımlanmamış. | [Google AI Studio](https://aistudio.google.com/app/apikey) üzerinden anahtar alıp `export GEMINI_API_KEY="..."` tanımlayın. |
| Model Yanıtında Boş Çeviri | Düşünce (Reasoning) modelinin token limitine ulaşması. | `analyzer_max_tokens` değerini `4096` veya `8192` olarak artırın. |
| `Connection error` (Local Ollama) | Yerel Ollama sunucusu kapalı. | Terminalde `ollama serve` komutunu çalıştırın. |
