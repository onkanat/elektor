# ⚡ Elektor Universal PDF & Rendergit Sentetik Veri Platformu
## 📖 Detaylı Kullanım Kılavuzu & Ekran Görüntülü Rehber

Bu kılavuz, **Elektor Universal PDF & Rendergit Code Dataset Generator Platformu**'nun tüm modüllerinin, arayüz bölümlerinin ve arka plan işleme adımlarının detaylı kullanım talimatlarını ve **birebir ekran görüntülerini** içermektedir.

---

## 📑 İçindekiler
1. [Genel Bakış & Sistem Mimarisi](#1-genel-bakış--sistem-mimarisi)
2. [⚙️ Bölüm A: Girdi & Sentetik Veri Parametreleri & Canlı Terminal](#2-bölüm-a-girdi--sentetik-veri-parametreleri--canlı-terminal)
3. [📊 Bölüm B: Dataset & Veritabanı Görüntüleyici](#3-bölüm-b-dataset--veritabanı-görüntüleyici)
4. [💬 Bölüm C: Analyzer Chat & Model Sandbox](#4-bölüm-c-analyzer-chat--model-sandbox)
5. [🗂️ Proje Gezgini & Veri Seti Birleştirme Motoru (Faz 3)](#5-proje-gezgini--veri-seti-birleştirme-motoru-faz-3)
6. [🤗 Hugging Face Hub & Bulut GPU Dağıtım Kiti (Faz 4)](#6-hugging-face-hub--bulut-gpu-dağıtım-kiti-faz-4)
7. [🚀 OpenAI-Uyumlu API & Performans Oturumu (Faz 9)](#7-openai-uyumlu-api--performans-oturumu-faz-9)
8. [👁️ Multimodal Vizyon (DeepSeek-OCR) & 2x GPU Paralel Sharding (Faz 10)](#8-multimodal-vizyon-deepseek-ocr--2x-gpu-paralel-sharding-faz-10)
9. [🔍 Google LangExtract Entegrasyonu Kullanım Rehberi (Faz 12)](#9--google-langextract-entegrasyonu-kullanım-rehberi-faz-12)
10. [📦 Kiwix OpenZIM Ansiklopedi Veri Hattı (Faz 13)](#10--kiwix-openzim-ansiklopedi-veri-hattı-faz-13)
11. [✨ Dinamik Ön Tarama & Few-Shot Örnek Sentezi (Faz 14)](#11--dinamik-ön-tarama--few-shot-örnek-sentezi-faz-14)
12. [🩺 Otonom Sistem Teşhis & Sağlık Modülü (`self_test`) (Faz 15)](#12--otonom-sistem-teşhis--sağlık-modülü-self_test-faz-15)

---

## 1. Genel Bakış & Sistem Mimarisi

Platform; teknik dökümanları (PDF kitaplar, veri kâğıtları, dergi arşivleri) ve Python Git repolarını (Andrej Karpathy'nin `rendergit` yöntemiyle) analiz ederek yüksek kalitede **SFT (Supervised Fine-Tuning)**, **DPO (Direct Preference Optimization)** ve **Çok Turlu (Multi-turn) Diyalog** veri setleri üreten evrensel bir yapay zekâ veri hattıdır.

### Üst Bar ve Sistem Göstergeleri:
- **❓ Hızlı Yardım Butonu**: Bu detaylı kullanım kılavuzunu açar.
- **Canlı Metrik Paneli**: Anlık **CPU**, **RAM** ve GPU **VRAM** kullanımını (`ornith:35b` model hafızasını) takip eder.
- **🗂️ Proje Etiketi**: Aktif çalışılan projeyi gösterir. Tıklandığında Proje Gezgini açılır.
- **🤗 HF & Bulut GPU**: Faz 4 Hugging Face ve Cloud GPU aktarım modalını açar.
- **Ollama Durumu**: Yerel Ollama LLM sunucusunun bağlantı durumunu gösterir.

---

## 🚀 Kurulum & Çalıştırma (Venv & API Server)

### 📦 Sanal Ortam Kurulumu (Python Virtual Environment)
Projenin bağımlılıklarını izole ve kararlı bir şekilde çalıştırmak için sanal ortam (venv) kullanılması şiddetle tavsiye edilir:
```bash
# 1. Sanal ortamı oluşturun (Python 3.11+)
python3.11 -m venv .venv

# 2. Sanal ortamı aktif edin
# macOS/Linux:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# 3. Bağımlılıkları yükleyin
pip install -r requirements.txt
```

### 🖥️ Web UI Dashboard'u Başlatma (FastAPI + React)
Platformun birleşik web arayüzünü ve API sunucusunu iki şekilde başlatabilirsiniz:
* **run.py Üzerinden (Önerilen):**
  ```bash
  python run.py api
  ```
* **Uvicorn ile Doğrudan:**
  ```bash
  python -m uvicorn api_server:app --reload --port 3456
  ```
Sunucu başladığında tarayıcınızda `http://localhost:3456` adresini açarak sentetik veri platformunu kullanmaya başlayabilirsiniz.

---

## 2. ⚙️ Bölüm A: Girdi & Sentetik Veri Parametreleri & Canlı Terminal

Bölüm A, veri alma modlarının seçildiği, AI model parametrelerinin yapılandırıldığı ve boru hattının (pipeline) çalıştırıldığı ana kontrol merkezidir.

![Ekran 1: Bölüm A - Girdi & Sentetik Veri Parametreleri & Canlı Terminal](/guide_images/section_a.png)

### 2.1 1. Döküman & Sentetik Veri Parametreleri (Sol Panel)
- **İşleme Modu (Input Mode)**:
  - **Rendergit Mode (Git Kod Reposu / GitHub URL)**: Kod deposunu klonlar, tüm kodu tek bir markdown dosyasında birleştirir ve AST (Soyut Sentaks Ağacı) analizi ile sınıf/fonksiyon kod birimlerini SQLite veritabanına çıkarır.
  - **Book Mode (Tek PDF Kitap)**: PDF içindekiler tablosunu (outline bookmarks) tarayarak otomatik bölüm dilimlemesi yapar.
  - **Folder Mode (PDF Klasörü)**: Dizindeki tüm PDF dosyalarını özyinelemeli olarak işler.
- **Veri Seti Dağılım Modu (Pragmatic vs. Pedagogik Slider)**:
  - **%100 Pragmatik**: Selamlama veya persona tanımlarını kaldırarak doğrudan koda ve teknik açıklamaya odaklanan veri üretir.
  - **%100 Pedagojik**: Derin teorik ve tasarımsal eğitim açıklamaları üretir.
- **Veri Seti Kalite & Üretim Tercihleri (Faz 1)**:
  - ☑️ **Doğrudan Türkçe Üretim**: 2-pass çeviri aşamasını atlayarak dökümandan doğrudan Türkçe SFT/DPO/Chat üretir.
  - ☑️ **DPO Teknik Doğrulama Katmanı**: Chosen (tercih edilen) ve Rejected (reddedilen) kod yanıtlarını mühendislik mantığına göre otomatik doğrular.
  - ☑️ **Çok Turlu (Multi-turn) Diyalog Sentezi**: Adım adım donanım/yazılım sorun giderme sohbetleri üretir.
- **Faz 2 Sentetik Kod Çeşitliliği Kategorileri**:
  - ☑️ **📝 Kod Açıklama & Mimari**: Statik audit ve mimari analiz.
  - ☑️ **💻 Kod Tamamlama (İmza ➔ Kod)**: Fonksiyon imzası ve docstring'den temiz kod uygulaması sentezi.
  - ☑️ **🐛 Hata Ayıklama & Güvenlik**: Kod içerisindeki hataların ve güvenlik açıklarının tespiti & düzeltilmesi.
  - ☑️ **🧪 pytest Birim Test Üretimi**: Tam `pytest` test kiti üretimi.

### 2.2 2. Pipeline Çalıştırma & Canlı Terminal (Sağ Panel)
- **Örnek Limiti**: İşlenecek makale veya kod birimi sayısını belirler (örn: `5`, `10:20` veya `all`).
- **Veritabanını Sıfırla (`--reset`)**: Eski veri setlerini ve veritabanını temizleyerek sıfırdan başlatır.
- **🚀 TAM PIPELINE ÇALIŞTIRMA**:
  - **⚡ Hızlı Test**: Belirlenen limit kadar örnek üzerinde 4 adımı (Metin Ayıkla ➔ AI Zenginleştir ➔ Vektörle ➔ Veri Seti Aktar) otomatik çalıştırır.
  - **🔥 Tüm Dökümanı İşle**: Tüm veriyi ardışık olarak işler.
- **Tekil Adım Çalıştırıcılar**: İstenen adımı bağımsız olarak çalıştırma olanağı sunar.
- **Konsol Çıktısı (PYTHONUNBUFFERED=1)**: Arka planda çalışan Python betiğinin çıktılarını anlık olarak terminal ekranına yansıtır.

---

## 3. 📊 Bölüm B: Dataset & Veritabanı Görüntüleyici

Bölüm B, üretilen veri setlerinin, SQLite veritabanı tablolarının ve Qdrant vektör indekslerinin incelendiği alandır.

![Ekran 2: Bölüm B - Dataset & Veritabanı Görüntüleyici](/guide_images/section_b.png)

### 3.1 JSONL Veri Setleri Sekmesi
- **Yan Yana DPO Görselleştirme**:
  - **Prompt**: İstem veya teknik soru.
  - **✓ Chosen (Tercih Edilen)**: Yeşil kart içerisinde yüksek kaliteli, doğrulanmış yanıt.
  - **✗ Rejected (Reddedilen)**: Kırmızı kart içerisinde mantık hatası veya eksik içeren yanıt.
- **Veri Seti Filtresi**: `sft_dataset.jsonl`, `dpo_dataset.jsonl`, `chat_dataset.jsonl`, `tr_sft_dataset.jsonl`, `code_sft_dataset.jsonl` vb. dosyalar arasında geçiş yapma.
- **Arama & Sayfalama**: Veri seti içeriğinde anlık kelime araması.

### 3.2 Lite SQLite Sorgulayıcı & Lite Qdrant Vektör Arama Sekmeleri
- **SQLite**: `articles`, `enrichments`, `code_units`, `synthetic_code_pairs` tablolarını sorgulama.
- **Qdrant**: Vektör veritabanı semantik arama ve benzerlik skorlarını görüntüleme.

---

## 4. 💬 Bölüm C: Analyzer Chat & Model Sandbox

Öğretmen ve Analizci LLM modelinin (`ornith:35b-q4_K_M`) canlı olarak test edildiği alandır.

![Ekran 3: Bölüm C - Analyzer Chat & Model Sandbox](/guide_images/section_c.png)

- **Standart Model Sohbet**: Modele doğrudan teknik sorular yöneltme veya istem kalıplarını test etme.
- **Model & Prompt Sandbox Ayarları**: Uzmanlık personasını (`Senior Principal Software Architect & Code Auditor`) ve konu odağını değiştirerek model üzerindeki etkisini canlı gözlemleme.
- **Pre-FT Etki Simülatörü**: İnce ayar öncesi varsayılan model yanıtı ile fine-tuning sonrası hedeflenen yanıt yapısını karşılaştırma.

---

## 5. 🗂️ Proje Gezgini & Veri Seti Birleştirme Motoru (Faz 3)

Üst bardaki **Proje** butonuna tıklandığında açılan yönetim pencereleridir.

![Ekran 4: Proje Gezgini & Çoklu Veri Setleri Modal](/guide_images/project_explorer.png)

### 5.1 Proje Gezgini
- **Kayıtlı Proje Listesi**: Disk üzerindeki tüm `projects_*.json` dosyaları otomatik keşfedilir. `Geçiş Yap ▶` butonu ile anında aktif proje değiştirilir.
- **➕ Yeni Proje Oluştur**: Yeni döküman veya kod reposu için sıfırdan proje tanımlama.

### 5.2 🔀 Projeleri Birleştir (Merge) Motoru
Yüzlerce saatlik GPU emeğini korumak için 2 aşamalı güvenlik akışı sunar:
- **🔍 1. İki Kez Doğrulama ve Test Çalıştırması Yap (Dry-Run Audit)**:
  - Çakışmaları önlemek için SQLite şemalarını ve JSONL satır sentaksını tarar.
  - Canlı **🛠️ Hata Ayıklama & Ön Denetim Konsolu** üzerinde kontrol raporu sunar.
- **⚡ 2. Güvenli Birleştirmeyi Başlat (Execute Merge)**:
  - Yalnızca dry-run testi geçtiğinde aktifleşir.
  - Seçilen tüm projeleri atomik olarak `exports/merged_<project>/` klasörüne ve veritabanına konsolide eder.

---

## 6. 🤗 Hugging Face Hub & Bulut GPU Dağıtım Kiti (Faz 4)

Üst bardaki **🤗 HF & Bulut GPU** butonuna tıklandığında açılan dağıtım modalıdır.

![Ekran 5: Hugging Face Hub & Bulut GPU Dağıtım Kiti Modal](/guide_images/hf_modal.png)

### 6.1 🤗 Hugging Face Dataset Hub Sekmesi
- **Repository ID Auto-Preset & Dropdown**:
  - Aktif projenizin adı otomatik preset gelir (örn: `onkanat/rendergit_merged_all-dataset`).
  - **🔍 Projeden Seç** dropdown menüsünden diğer projeler tek tıkla seçilebilir.
- **2 Adımlı Split Butonlar**:
  - **Sol Buton (Aktif)**: **`🔍 1. Test Çalıştırması Yap (Dry-Run)`**
    - Yüklenecek dosyaları (16 dosya, 6.53 MB), satır sayılarını ve CLI komutlarını Hata Ayıklama Konsolunda önizler.
  - **Sağ Buton (Kilitli ➔ Denetim Sonrası Aktif)**: **`🚀 2. Hugging Face Hub'a Yükle`**
    - Test başarıyla geçtiğinde aktifleşir ve tek tıkla veri setini ile otomatik **Dataset Card (`README.md`)** belgesini Hugging Face Hub'a yükler.

### 6.2 ⚡ Bulut GPU Fine-Tuning Kiti Sekmesi
- **Base Model Seçimi**: `unsloth/Qwen2.5-Coder-7B-Instruct`, `unsloth/Llama-3.1-8B-Instruct` vb.
- **Tek Tıkla Paket Üretimi**:
  - `unsloth_finetune.py`: 5 kat hızlı Unsloth LoRA eğitim betiği.
  - `axolotl_config.yaml`: Çoklu GPU Axolotl konfigürasyonu.
  - `run_cloud_gpu.sh`: RunPod bağımlılık kurulumu ve çalıştırma betiği.
  - Üretilen paket `exports/<project_id>/cloud_payload/` dizininde hazır hâle getirilir.

---

## 7. 🚀 OpenAI-Uyumlu API & Performans Oturumu (Faz 9)

- **Evrensel Client Standardı**: Ham Ollama istemcisinden `openai` SDK (`v1/chat/completions`) mimarisine geçilmiştir.
- **Sunucu & Donanım Bağımsızlığı**: Tek bir kod tabanı ile yerel Ollama, vLLM, SGLang, Groq ve Hugging Face uç noktalarına tak-çalıştır erişim.
- **Canlı Log Akışı Kaydırma Kilidi**: Ön uç terminal panelinde akıllı kaydırma kilidi (auto-scroll-lock) ile canlı günlük akışında sayfa yenilense dahi geçmiş okuma kolaylaştırılmıştır.

---

## 8. 👁️ Multimodal Vizyon (DeepSeek-OCR) & 2x GPU Paralel Sharding (Faz 10)

- **`deepseek-ocr:3b-bf16` Vizyon Entegrasyonu**: PDF belgelerindeki devre şemaları, pinout diyagramları, grafik şemaları ve görsel tablolar `<image>\n<|grounding|>` istem formatı ile anlamlandırılır.
- **Akıllı Çerçeve & Düzen Analizi (Smart Layout Filtering)**: Ince ayraç çizgileri, küçük ikonlar ve sayfa kenarlıkları otomatik elenerek yalnızca gerçek teknik görseller VLM'e gönderilir.
- **VRAM Offloading & 2x 16GB GPU Sharding**: 
  - Vizyon taraması tüm döküman çıkarma aşaması boyunca VRAM'de sabit kalır ve extraction adımı bitince `extractor.close()` ile VRAM'den kaldırılır.
  - 2 fiziksel 16GB GPU (Port 11434 & 11435) üzerinde SQLite WAL modunda (`PRAGMA journal_mode=WAL;`) kilitlenmesiz paralel zenginleştirme sağlanır.

---

## 9. 🔍 Google LangExtract Entegrasyonu Kullanım Rehberi (Faz 12)

Platforma eklenen Google `langextract` kütüphanesi entegrasyonu, ham metin ve döküman içerisindeki teknik kavramları, bileşenleri ve parametreleri **karakter bazlı kaynak offset aralıkları (`start_char`, `end_char`)** ile tespit ederek doğrulanabilir (grounded) veri kümelerine dönüştürür.

### 9.1 Web UI Üzerinden Yapılandırma (`SectionConfig.tsx`)

Bölüm A (Parametreler) sekmesinde yer alan **🔍 Google LangExtract Entegrasyonu** kartından şu ayarları yönetebilirsiniz:

1. **LangExtract Aktif Anahtarı**: Otomatik döküman alım adımlarında LangExtract modülünü aktif/pasif yapar.
2. **Sağlayıcı Önceliği (Provider Selector)**:
   - **`1. Ollama (Yerel Ücretsiz)` (Varsayılan)**: Yerel modeller üzerinde 0 maliyetle çalışır.
   - **`2. OpenAI (API)`**: OpenAI API veya vLLM/Groq uyumlu uç noktaları kullanır.
   - **`3. Gemini API (Google)`**: Google Vertex / Gemini API uç noktasını kullanır (`gemini-2.5-flash`).
3. **Şema Şablonu (Preset Schema)**:
   - `Hardware & Technical Components`: Entegreler, mikrodenetleyiciler, sensörler.
   - `Circuit & Electrical Specs`: Voltaj, akım, frekans, empedans değerleri.
   - `Software Architecture & AST`: Sınıflar, fonksiyonlar, bağımlılıklar.
   - `Pinout & Signal Mappings`: Pin numaraları, sinyal yönleri, modlar.
   - `Generic Technical Q&A`: Genel teknik tanımlar, formüller.
   - `Engineering Exercise Sheet`: Üniversite ders kitapları, alıştırma föyleri, problem puanları ve GNURadio simülasyon parametreleri.
4. **Gemini API Key Field**: Gemini API kullanıldığında API anahtarınızı güvenli şekilde girmenizi sağlar.

### 9.2 Komut Satırından (CLI) Çalıştırma

LangExtract çıkarma ve görselleştirme adımlarını CLI üzerinden doğrudan tetikleyebilirsiniz:

```bash
# Yerel Ollama ile Mühendislik Alıştırma Föyü Şablonunda Çıkarma ve HTML Görselleştirici Üretme
python run.py langextract --provider ollama --preset engineering_exercise_sheet --limit 5 --visualize

# Google Gemini API Kullanarak Donanım Şablonunda Çıkarma
GEMINI_API_KEY="AIzaSy..." python run.py langextract --provider gemini --preset technical_components --limit 10 --visualize
```

### 9.3 Etkileşimli HTML Görselleştirici Raporlarını Görüntüleme

LangExtract tarafından işlenen dökümanlar için `exports/<project_id>/langextract_visualizations/article_<doc_id>_grounded.html` konumunda self-contained HTML görselleştirici üretilir.

- Tarayıcınızda doğrudan veya Web UI `/api/langextract/visualize/{project_id}/{doc_id}` uç noktası üzerinden açabilirsiniz.
- Metin üzerindeki varlıklar sarı ve turuncu alt çizgilerle vurgulanır; üzerlerine gelindiğinde offset aralıkları ve öznitelik nesneleri (attributes) gösterilir.

---

## 10. 📦 Kiwix OpenZIM Ansiklopedi Veri Hattı (Faz 13)

Kiwix veri alım hattı, İnternet erişimi kısıtlı veya devasa çevrimdışı arşivleri (Wikipedia Türkçe/İngilizce, StackOverflow, Vikisözlük) doğrudan sentetik veri setlerine dönüştürür.

- **Kullanım (CLI)**:
  ```bash
  python run.py kiwix --zim downloads/wikipedia_tr_all.zim --limit 100
  ```
- **Filtreleme & Temizlik**:
  - `libzim.Archive` API okuyucusu.
  - `BeautifulSoup4` + `html2text` ile şablon ve HTML gürültülerinden arındırılmış temiz Markdown üretimi.
  - Minimum karakter filtresi (`kiwix_min_chars: 300`).

---

## 11. ✨ Dinamik Ön Tarama & Few-Shot Örnek Sentezi (Faz 14)

LangExtract modülü, sabit promptlar yerine işlenen dökümanın ilk 2.500 karakterlik bölümünü ön tarayarak dokümana özel `prompt_description` ve `lx.data.ExampleData` nesneleri üretir.

- **Ayarlama (Web UI & `config.json`)**:
  - Web UI LangExtract panelinde **✨ Dinamik Doküman Ön Taraması & Few-Shot Örnek Üretimi** seçeneğini aktif/pasif yapabilirsiniz.
  - `"enable_langextract_dynamic_examples": true`

---

## 12. 🩺 Otonom Sistem Teşhis & Sağlık Modülü (`self_test`) (Faz 15)

Sistemin tüm bileşenlerinin (SQLite, Qdrant, Ollama VRAM, Vision OCR ve Pytest test kiti) çalışırlığını 5 aşamalı otonom test ile denetler.

- **Çalıştırma**:
  ```bash
  python run.py self_test
  ```
- **Raporlama**:
  ```text
  🎯 SELF-TEST COMPLETED: 5/5 System Checks Passed!
  ```

---

*Rehber Son Güncelleme: 2026-08-18 | Elektor Universal Pipeline v15.0*
