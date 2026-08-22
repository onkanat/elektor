# 🧪 Elektor Universal Sentetik Veri Platformu
## 📋 19 Faz Kapsamlı Manuel Kullanıcı Doğrulama ve Sürüm Onay Test Kılavuzu (`test_manuel_user.md`)

Bu kılavuz, **Elektor Universal PDF & Rendergit Code Dataset Generator** platformunun **19 gelişim fazının tamamının** son kullanıcı (tester / mühendis) tarafından adım adım manuel olarak test edilmesi ve doğrulanması için hazırlanmıştır.

Bu test adımları başarıyla tamamlanıp onay raporu oluşturulduğunda projeye nihai **Majör Sürüm (Release Version)** verilecektir.

---

## 🎯 Test Metodolojisi

Her bir faz için **2 farklı test yöntemi** bulunmaktadır:
1. **💻 Konsol Komutu ile Test (CLI / Terminal):** Terminalden bağımsız komutlar, bayraklar (`flags`) ve API istekleri ile yapılan doğrudan çekirdek motor testleri.
2. **🖥️ Web UI Üzerinden Test (React Ön Yüz):** `http://localhost:3456` arayüzü üzerinden butonlar, formlar, sekmeler ve görsel önizleyiciler ile yapılan kullanıcı deneyimi testleri.

---

## 🚀 Test Öncesi Hazırlık (Ortamın Başlatılması)

1. **Sanal Ortamı Aktif Edin ve Bağımlılıkları Doğrulayın:**
   ```bash
   cd /Users/hakankilicaslan/Git/elektor
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Otomatik Birim Test Sağlamasını Çalıştırın (Temel Sağlık Kontrolü):**
   ```bash
   PYTHONPATH=. uv run pytest tests/
   # Beklenen Çıktı: 51 passed
   ```

3. **FastAPI Backend ve React UI Sunucusunu Başlatın:**
   ```bash
   python run.py api
   ```
   *Tarayıcınızda `http://localhost:3456` adresini açarak UI'ın yüklendiğini teyit edin.*

---

## 📑 19 FAZ MANUEL TEST SENARYOLARI

---

### 🔹 FAZ 1: Veri Seti Kalite & Doğrudan Türkçe Katmanı
* **Amaç:** 2-Pass çeviri karmaşasını engelleyip doğrudan Türkçe (`direct_tr_generation`) SFT, DPO ve çok turlu teknik sohbet veri setleri üretmek; DPO çiftlerini otomatik mantık süzgecinden geçirmek.

#### 💻 1. Konsol Komutu ile Test:
```bash
# Doğrudan Türkçe ve DPO doğrulama bayrakları ile 2 makale işleyin:
python run.py pipeline --limit 2
```
* **Konsol Çıktısı Kontrolü:** Terminalde `[Pipeline] Direct TR Generation: Enabled` ve `DPO Verification: Passed` satırlarını görün.
* **Dosya Kontrolü:** `exports/<project_id>/` altında şu dosyaları inceleyin:
  - `sft_dataset.jsonl` ve `tr_sft_dataset.jsonl`
  - `dpo_dataset.jsonl` ve `tr_dpo_dataset.jsonl`
  - `chat_dataset.jsonl` ve `tr_chat_dataset.jsonl`
* **JSON Kontrolü:** Satırların içinde `"quality_status": "verified"`, `"language": "tr"` alanlarının olduğunu doğrulayın.

#### 🖥️ 2. Web UI ile Test:
1. `http://localhost:3456` adresinde **⚙️ Bölüm A: Girdi & Parametreler** sekmesine gelin.
2. Sol panelde **Veri Seti Kalite & Üretim Tercihleri** kartında:
   - ☑️ **Doğrudan Türkçe Üretim (`direct_tr_generation`)**
   - ☑️ **DPO Teknik Doğrulama Katmanı (`enable_dpo_verification`)**
   - ☑️ **Çok Turlu (Multi-turn) Diyalog Sentezi**
   onay kutularını işaretleyin ve sağ üstteki **Ayarları Kaydet**'e basın.
3. **📊 Bölüm B: Dataset Viewer ➔ 📄 JSONL Veri Setleri** sekmesine geçin.
4. Açılır menüden `dpo_dataset.jsonl` seçin; sol tarafta yeşil **✓ Chosen**, sağ tarafta kırmızı **✗ Rejected** kartlarının Türkçe ve kaliteli olarak yan yana görüntülendiğini doğrulayın.

---

### 🔹 FAZ 2: Sentetik Kod Çeşitliliği Stratejisi (Rendergit AST)
* **Amaç:** Python repolarından AST (Soyut Sentaks Ağacı) analizi ile 4 farklı kategoride (`explanation`, `completion`, `bug_fix`, `unit_test`) sentetik kod eğitim çiftleri üretmek.

#### 💻 1. Konsol Komutu ile Test:
```bash
# Yerel bir repoyu klonlayıp AST birimlerini çıkarın:
python -c "
from pipeline.code_extractor import extract_and_store_code_units, parse_python_files_ast
from pathlib import Path
units = extract_and_store_code_units(parse_python_files_ast(Path('pipeline')), Path('.'), Path('database/test_code.db'), 'test_code')
print(f'Çıkarılan Kod Birimi: {len(units)}')
"
```
* **Konsol Çıktısı Kontrolü:** `Çıkarılan Kod Birimi: > 10` ve sınıfların/fonksiyonların ayrıştırıldığını görün.

#### 🖥️ 2. Web UI ile Test:
1. **⚙️ Bölüm A** sekmesinde **İşleme Modu** olarak `Rendergit Mode (Git Kod Reposu / GitHub URL)` seçin.
2. **Girdi Yolu** alanına `https://github.com/karpathy/micrograd.git` veya `pipeline/` yazın.
3. Sol alttaki **Faz 2 Sentetik Kod Çeşitliliği** onay kutularından 4 kategorinin de (Açıklama, Tamamlama, Hata Ayıklama, Unit Test) seçilebilir olduğunu test edin.
4. **Hızlı Test (5 Makale/Kod)** butonuna basın; terminalde kod bloklarının analiz edildiğini izleyin.

---

### 🔹 FAZ 3: Proje & Veri Seti Birleştirme Motoru
* **Amaç:** Farklı veri setlerini ve SQLite veritabanlarını çakışmasız, 2 aşamalı (Dry-Run Audit + Atomic Merge) olarak tek bir master projede birleştirmek.

#### 💻 1. Konsol Komutu ile Test:
```bash
# REST API üzerinden birleştirme denetimi (Dry-Run) simülasyonu:
curl -s -X POST http://localhost:3456/api/projects/merge/audit \
  -H "Content-Type: application/json" \
  -d '{"source_projects": ["extract"], "target_project_id": "merged_master"}' | grep -o '"status":"[^"]*"'
```
* **Konsol Çıktısı Kontrolü:** `"status":"success"` veya `"ready"` cevabının döndüğünü görün.

#### 🖥️ 2. Web UI ile Test:
1. Üst bardaki **🗂️ Proje: [aktif_proje]** butonuna tıklayarak **Proje Gezgini** modalını açın.
2. Modalın üstündeki **🔀 Projeleri Birleştir (Merge Motoru)** sekmesine geçin.
3. Listeden en az 1 kaynak proje seçin, hedef proje ID'si girin (`master_all`).
4. **`🔍 1. İki Kez Doğrulama ve Test Çalıştırması Yap (Dry-Run Audit)`** butonuna basın.
5. Canlı Hata Ayıklama Konsolunda yeşil onayların yandığını ve ardından **`⚡ 2. Güvenli Birleştirmeyi Başlat`** butonunun kilit açtığını (aktifleştiğini) doğrulayın.

---

### 🔹 FAZ 4: Hugging Face Otomatik Dağıtım & Cloud GPU Offloading
* **Amaç:** Birleştirilen veri setlerini tek tıkla Hugging Face Hub'a yüklemek ve RunPod / Unsloth / Axolotl bulut eğitim paketlerini üretmek.

#### 💻 1. Konsol Komutu ile Test:
```bash
# Bulut eğitim paket üreticisini test edin:
python -c "
from pipeline.cloud_gpu_offloader import CloudGPUOffloader
offloader = CloudGPUOffloader(config_path='config.json')
pkg = offloader.generate_training_package(base_model='unsloth/Qwen2.5-Coder-7B-Instruct')
print('Paket Dizini:', pkg.get('package_dir'))
"
```
* **Konsol Çıktısı Kontrolü:** `exports/<project_id>/cloud_payload/` altında `unsloth_finetune.py`, `axolotl_config.yaml` ve `run_cloud_gpu.sh` dosyalarının üretildiğini görün.

#### 🖥️ 2. Web UI ile Test:
1. Üst bardaki **🤗 HF & Bulut GPU** butonuna tıklayın.
2. **🤗 Hugging Face Dataset Hub** sekmesinde `🔍 1. Test Çalıştırması Yap (Dry-Run)` butonuna basın; konsolda yüklenecek JSONL dosyalarının listelendiğini görün.
3. **⚡ Bulut GPU Fine-Tuning Kiti** sekmesine geçin; Base Model olarak `unsloth/Qwen2.5-Coder-7B-Instruct` seçip **📦 Bulut Eğitim Paketini Üret** butonuna basın. "Bulut paketi başarıyla hazırlandı" bildirimini doğrulayın.

---

### 🔹 FAZ 5: Proje Bazlı İzole Hata & Uyarı Log Sistemi
* **Amaç:** Her projenin kendi ihraç dizininde (`exports/<project_id>/errors_and_warnings.log`) yalnızca `WARNING` ve `ERROR` seviyelerindeki günlükleri kaydederek disk ve bellek tasarrufu sağlamak.

#### 💻 1. Konsol Komutu ile Test:
```bash
# Log motorunu test edin:
python -c "
from pipeline.logger import ProjectLogger
logger = ProjectLogger('test_log_proj')
logger.warning('Test uyarı mesajı', module='test_mod')
logger.error('Test hata mesajı', module='test_mod')
log_file = logger.get_log_file_path()
print('Log Dosyası Mevcut:', log_file.exists(), '| İçerik Satır Sayısı:', len(log_file.read_text().splitlines()))
"
```
* **Konsol Çıktısı Kontrolü:** `Log Dosyası Mevcut: True | İçerik Satır Sayısı: 2` olduğunu doğrulayın.

#### 🖥️ 2. Web UI ile Test:
1. Bir işlem sırasında bilerek geçersiz bir model adı girin veya boş arama yapın.
2. İlgili projenin `exports/<project_id>/errors_and_warnings.log` dosyasına yalnızca bu uyarının yazıldığını, normal `INFO` mesajlarıyla şişmediğini kontrol edin.

---

### 🔹 FAZ 6: Proje Gezgini Entegre System Prompt & Persona Editörü
* **Amaç:** `prompt.html` / `persona_map.yaml` üzerinden her proje için özelleştirilmiş AI personası ve konu odağı tanımlamak.

#### 💻 1. Konsol Komutu ile Test:
```bash
# config.json içindeki persona alanlarını kontrol edin:
python -c "
import json
cfg = json.load(open('config.json'))
print('Mevcut Persona:', cfg.get('llm_persona'))
print('Mevcut Subject:', cfg.get('llm_subject'))
"
```
* **Konsol Çıktısı Kontrolü:** Değerlerin dolu olduğunu doğrulayın.

#### 🖥️ 2. Web UI ile Test:
1. Üst bardan **🗂️ Proje** modalını açın ➔ **➕ Yeni Proje Oluştur** sekmesine gelin.
2. **LLM Personası** ve **Döküman Konu Başlığı** alanlarını düzenleyin (`"Otomotiv Elektroniği Uzmanı"`).
3. Projeyi kaydedip geçiş yapın; **⚙️ Bölüm A** ve **💬 Bölüm C** ekranlarında personanın güncellendiğini görün.

---

### 🔹 FAZ 7: HF Serverless Inference & ZeroGPU Hibrit Fallback Motoru
* **Amaç:** Yerel GPU sunucusu çevrimdışı olduğunda istekleri otomatik olarak Hugging Face Serverless veya yedek API'lere yönlendirme altyapısı.

#### 💻 1. Konsol Komutu ile Test:
```bash
# Ollama kapalıyken OpenAI proxy veya fallback endpoint testini simüle edin:
python -c "
from pipeline.gemini_client import get_openai_client
client = get_openai_client({'ollama_url': 'http://127.0.0.1:11434', 'openai_timeout': 5})
print('İstemci Başarıyla Örneklendi:', client is not None)
"
```

#### 🖥️ 2. Web UI ile Test:
1. Üst bardaki **Ollama Durumu** rozetini inceleyin; bağlantı koptuğunda UI'ın çökmeden kullanıcıya sarı/kırmızı uyarı verdiğini doğrulayın.

---

### 🔹 FAZ 8: Chat Arenası Markdown & LaTeX Matematik Formül Desteği + İnsan Onaylı RLHF Puanlama
* **Amaç:** KaTeX ile $f = \frac{1}{2\pi\sqrt{LC}}$ gibi karmaşık formülleri render etmek, KaTeX On/Off anahtarı sunmak; veri seti kayıtlarını 👍 Beğen / 👎 Beğenme / 🗑️ İhraç Dışı Bırak butonlarıyla etiketlemek.

#### 💻 1. Konsol Komutu ile Test:
```bash
# İnsan puanlama ve dışlama API uç noktalarını test edin:
curl -s -X POST http://localhost:3456/api/dataset/rate \
  -H "Content-Type: application/json" \
  -d '{"article_id": 1, "rating": 1, "feedback": "Mükemmel formül doğrulaması"}' | grep -o '"status":"[^"]*"'

curl -s -X POST http://localhost:3456/api/dataset/exclude \
  -H "Content-Type: application/json" \
  -d '{"article_id": 1, "exclude": true}' | grep -o '"status":"[^"]*"'
```
* **Konsol Çıktısı Kontrolü:** Her iki komuttan da `"status":"success"` döndüğünü görün.

#### 🖥️ 2. Web UI ile Test:
1. **📊 Bölüm B ➔ 🗄️ Lite SQLite Sorgulayıcı** sekmesine gelin.
2. Herhangi bir satırın yanındaki **🔍 Detay / Metin** butonuna tıklayın.
3. Açılan modalda:
   - **👁️ KaTeX Render** onay kutusunu açıp kapatın; matematiksel formüllerin kusursuz render olduğunu ve ham modda `$` işaretlerinin göründüğünü test edin.
   - **👍 Beğendim** ve **👎 Beğenmedim** butonlarına basın; rozet renginin yeşil/kırmızı olduğunu görün.
   - **🗑️ Veri Setinden Sil** butonuna basın; başlıkta `🗑️ İhraç Dışı (Silindi)` etiketinin belirdiğini doğrulayın.

---

### 🔹 FAZ 9: OpenAI-Uyumlu API Standardı & Canlı Log Kaydırma Kilidi
* **Amaç:** Evrensel `OpenAI` (`v1/chat/completions`) SDK standardı ile vLLM/Ollama/Cloud uyumluluğu sağlamak; canlı terminal akışında fare ile yukarı çıkıldığında otomatik kaydırmayı kilitlemek (auto-scroll-lock).

#### 💻 1. Konsol Komutu ile Test:
```bash
# api_server.py üzerindeki /api/chat uç noktasına OpenAI formatında test isteği atın:
curl -s -X POST http://localhost:3456/api/chat \
  -H "Content-Type: application/json" \
  -d '{"model": "qwen3.5:4b", "messages": [{"role": "user", "content": "Elektronikte osilatör nedir?"}]}' | grep -o '"role":"assistant"'
```
* **Konsol Çıktısı Kontrolü:** `"role":"assistant"` cevabının geldiğini teyit edin.

#### 🖥️ 2. Web UI ile Test:
1. **⚙️ Bölüm A** sağ panelindeki **Konsol Çıktısı** alanına gelin.
2. Bir işlem çalışırken terminal kutusunda yukarı kaydırma (scroll up) yapın; yeni loglar geldikçe sayfanın aşağıya zorla zıplamadığını, fare bırakıldığında en alta indiğini doğrulayın.

---

### 🔹 FAZ 10: Multimodal Tarama & Çizim / Grafik Anlamlandırma Motoru
* **Amaç:** Taralı PDF'lerdeki teknik çizim ve şemaları VLM (`deepseek-ocr:3b-bf16` veya `qwen3.5:4b`) ile tespit edip 2x GPU port sharding (Port 11434 & 11435) ile işlemek.

#### 💻 1. Konsol Komutu ile Test:
```bash
# Vision OCR motorunun crop analiz metodunu test edin:
python -c "
from pipeline.vision_ocr import VisionOCR
ocr = VisionOCR(config_path='config.json')
print('Vision OCR Başlatıldı:', ocr.model, '| Port Havuzu:', ocr.shard_ports)
"
```
* **Konsol Çıktısı Kontrolü:** Model adının ve port listesinin başarıyla yüklendiğini görün.

#### 🖥️ 2. Web UI ile Test:
1. **⚙️ Bölüm A** sekmesinde **Girdi Yolu** olarak içinde devre şemaları olan bir PDF (`downloads/U070262.pdf`) seçin.
2. **Hızlı Test** çalıştırın; konsolda görsel kırpmaların (`draw_*`, `img_*`) VLM tarafından ayrıştırıldığını gözlemleyin.

---

### 🔹 FAZ 11: Otomatik Multimodal Görsel İnce-Ayar Veri Seti Motoru
* **Amaç:** Kırpılan teknik çizimleri LLaVA/Qwen2-VL formatında `multimodal_visual_dataset.jsonl` ve optimize WebP görselleri olarak ihraç etmek; hibrit düşünme modellerinde non-thinking parametreleri (`enable_thinking: false`, `max_tokens: 4096`) uygulamak.

#### 💻 1. Konsol Komutu ile Test:
```bash
# Multimodal görsel ihracını çalıştırın:
python run.py export_visual --clear
```
* **Konsol Çıktısı Kontrolü:**
  ```text
  Multimodal Visual Dataset exported successfully:
    Visual JSONL      : X samples -> exports/<project_id>/multimodal_visual_dataset.jsonl
    Markdown Catalog  : Embedded visual report -> exports/<project_id>/multimodal_catalog.md
    Optimized Images  : X WebP files in exports/<project_id>/images
    Failed/Skipped    : 0 crops
  ```

#### 🖥️ 2. Web UI ile Test:
1. **📊 Bölüm B ➔ 📄 JSONL Veri Setleri** sekmesine gelin.
2. **🔄 Listeyi Yenile** butonuna tıklayın.
3. Açılır listeden `multimodal_visual_dataset.jsonl` dosyasını seçin ve görsel soru-cevap kayıtlarının listelendiğini doğrulayın.

---

### 🔹 FAZ 12: Google LangExtract Entegrasyonu & Karakter Bazlı Kaynak Bağlama
* **Amaç:** Ham metindeki frekans, voltaj, bileşen ve terimleri kesin karakter offset aralıklarıyla (`start_char`, `end_char`) çıkarıp `langextract_grounded_dataset.jsonl` ve self-contained HTML raporu üretmek.

#### 💻 1. Konsol Komutu ile Test:
```bash
# LangExtract çıkarma ve HTML görselleştirici üretim komutunu çalıştırın:
python run.py langextract --provider ollama --preset generic_technical_qa --limit 2 --visualize
```
* **Konsol Çıktısı Kontrolü:** `Grounded dataset exported: exports/<project_id>/langextract_grounded_dataset.jsonl` ve HTML dosyalarının üretildiğini görün.
* **HTML Kontrolü:** Üretilen `exports/<project_id>/langextract_visualizations/article_1_grounded.html` dosyasını tarayıcıda açıp metin üzerindeki sarı/turuncu vurgulamaları inceleyin.

#### 🖥️ 2. Web UI ile Test:
1. **⚙️ Bölüm A ➔ 🔍 Google LangExtract Entegrasyonu** kartına gelin.
2. Sağlayıcı olarak `1. Ollama (Yerel Ücretsiz)` ve Şema Şablonu olarak `Generic Technical Q&A` seçin.
3. **Ayarları Kaydet**'e basın.
4. **📊 Bölüm B ➔ 📄 JSONL Veri Setleri** sekmesinde `langextract_grounded_dataset.jsonl` dosyasını seçerek `start_char`, `end_char` ve `attributes` alanlarını görüntüleyin.

---

### 🔹 FAZ 13: Kiwix OpenZIM Kataloğu & Ansiklopedi Veri Hattı
* **Amaç:** `.zim` formatındaki Wikipedia ve StackOverflow arşivlerini `libzim` ile okuyup, binary/sprite dosyalarını filtreleyerek temiz Markdown ve SQLite kayıtlarına dönüştürmek.

#### 💻 1. Konsol Komutu ile Test:
```bash
# Kiwix ZIM çıkarıcı modülünü test edin (eğer .zim dosyanız varsa):
python -c "
from pipeline.kiwix_extractor import KiwixExtractor
print('KiwixExtractor Modülü Hazır ve libzim Entegre!')
"
```
* **Konsol Çıktısı Kontrolü:** Hata vermeden başarıyla yüklendiğini görün.

#### 🖥️ 2. Web UI ile Test:
1. **⚙️ Bölüm A** sekmesinde **İşleme Modu** olarak `Kiwix ZIM Mode` seçin.
2. ZIM Dosya Yolu alanına arşiv dosyanızın yolunu girin ve tekil adımlardan **1. Metin Ayıkla** butonuna basarak makalelerin SQLite tablosuna dolduğunu izleyin.

---

### 🔹 FAZ 14: Gemini API Sağlamlaştırma & Token Bütçe Yöneticisi
* **Amaç:** Gemini 3.6 Flash için bağlantı havuzlama, $defs/$ref şema düzleştirme ve SQLite tabanlı kredi/maliyet takibi (`TokenBudgetManager`).

#### 💻 1. Konsol Komutu ile Test:
```bash
# Token Bütçe Yöneticisini test edin:
python -c "
from pipeline.gemini_client import TokenBudgetManager
mgr = TokenBudgetManager()
usage = mgr.get_current_usage()
print('Toplam Harcanan Token:', usage['total_tokens'], '| Harcanan TL:', usage['estimated_cost_try'], 'TL')
"
```
* **Konsol Çıktısı Kontrolü:** Bütçe özetinin hatasız basıldığını görün.

#### 🖥️ 2. Web UI ile Test:
1. **🏛️ LLM Hakem & Editor** sekmesine geçin.
2. En üstte yer alan **💎 Google Developer Program Kredi & Token Bütçesi** kartında toplam harcanan token, kalan bütçe ve ilerleme çubuğunun (progress bar) canlı görüntülendiğini doğrulayın.

---

### 🔹 FAZ 15: Bağımsız LLM-as-a-Judge & Editor-in-Chief Hakemliği
* **Amaç:** SFT ve DPO verilerini 1-10 puan skalasında denetlemek (`strict`) ve sınırda kalanları cerrahi olarak yeniden yazmak (`hybrid_editor`).

#### 💻 1. Konsol Komutu ile Test:
```bash
# Hakem motorunu simülasyon/dry-run modunda tetikleyin:
python run.py judge --mode strict --threshold 7.0 --limit 5
```
* **Konsol Çıktısı Kontrolü:** Terminalde `[Judge] Evaluated X pairs, Approved: Y, Rejected: Z` özet tablosunu görün.

#### 🖥️ 2. Web UI ile Test:
1. **🏛️ LLM Hakem & Editor** sekmesine gelin.
2. **Hakem Çalışma Modu** olarak `Editor-in-Chief (Cerrahi Düzeltme & İyileştirme)` seçin.
3. Onay Eşiği slider'ını `7.5` yapın.
4. **⚖️ Hakem Değerlendirmesini Başlat** butonuna basın; aşağıdaki canlı skor kartlarının (Onaylanan, Cerrahi Düzeltilen, Reddedilen) anlık güncellendiğini doğrulayın.

---

### 🔹 FAZ 16: LangExtract Kaynak Doğrulama & Dinamik Few-Shot Optimizasyonu
* **Amaç:** Dökümanın ilk 2.500 karakterini tarayarak o dökümana özel dinamik meta-prompt ve 1-shot `lx.data.ExampleData` sentezlemek.

#### 💻 1. Konsol Komutu ile Test:
```bash
# Dinamik few-shot üreticisini test edin:
python -c "
from pipeline.langextract_engine import generate_dynamic_examples_and_prompt
prompt_desc, examples = generate_dynamic_examples_and_prompt('Bu makale 48 kHz örneklemeli SDR alıcısı ve NE612 mikserini anlatmaktadır.')
print('Dinamik Prompt Açıklaması:', prompt_desc)
print('Üretilen Örnek Sayısı:', len(examples))
"
```
* **Konsol Çıktısı Kontrolü:** Dokümana özel teknik prompt açıklaması ve en az 1 örnek üretildiğini görün.

#### 🖥️ 2. Web UI ile Test:
1. **⚙️ Bölüm A ➔ 🔍 Google LangExtract Entegrasyonu** kartında:
   - ☑️ **✨ Dinamik Doküman Ön Taraması & Few-Shot Örnek Üretimi**
   onay kutusunu işaretleyin. Pipeline çalıştırıldığında dökümanın içeriğine göre dinamik şablon oluşturulduğunu loglardan gözlemleyin.

---

### 🔹 FAZ 17: Multimodal Markdown Kataloğu & WebP Canlı Önizleme
* **Amaç:** `multimodal_catalog.md` dosyasını üretmek, FastAPI statik `/exports` route'u üzerinden WebP şema çizimlerini kırık link olmadan tarayıcıda canlı render etmek.

#### 💻 1. Konsol Komutu ile Test:
```bash
# Katalog dosyasının varlığını ve içindeki görsel linklerini kontrol edin:
python -c "
from pathlib import Path
cat = Path('exports/extract/multimodal_catalog.md')
print('Katalog Mevcut:', cat.exists())
if cat.exists():
    print('Katalog Boyutu:', cat.stat().st_size, 'bytes')
"
```

#### 🖥️ 2. Web UI ile Test:
1. **📊 Bölüm B: Dataset & Veritabanı Görüntüleyici** sekmesine gelin.
2. Sağdaki **🖼️ Multimodal Katalog (.md)** alt sekmesine tıklayın.
3. Sayfada teknik şema kırpmalarının (WebP resimler) ve altlarında DeepSeek-OCR teknik dökümlerinin eksiksiz ve görsel olarak yüklendiğini doğrulayın.
4. **🔄 Kataloğu Yenile** butonuna basarak anlık güncelleme yapabildiğinizi test edin.

---

### 🔹 FAZ 18: Managed Agents Environment Hooks & Scheduled Triggers
* **Amaç:** `.agents/hooks.json` ile güvenlik kapısı (Security Gate), veri linter'ı (AST, LaTeX, JSON doğrulaması) ve zamanlanmış arka plan tarayıcısı çalıştırmak.

#### 💻 1. Konsol Komutu ile Test:
```bash
# Hook ve linter sağlık kontrolünü çalıştırın:
python run.py hooks --check
```
* **Konsol Çıktısı Kontrolü:**
  ```text
  [Hooks] Pre-Tool Security Gate: ACTIVE
  [Hooks] Post-Tool Dataset Linter: ACTIVE (LaTeX, AST, JSON checks passing)
  ```

#### 🖥️ 2. Web UI ile Test:
1. **🏛️ LLM Hakem & Editor** sekmesinin alt panelindeki **🛡️ Managed Agents Kancaları & Zamanlanmış Görevler** bölümüne gelin.
2. **Pre-tool Güvenlik Kapısı** ve **Post-tool Veri Seti Linter** rozetlerinin yeşil `AKTİF` yandığını doğrulayın.

---

### 🔹 FAZ 19: Hugging Face Hub & Google Vertex AI Gemini Tuning
* **Amaç:** Veri setlerini Hugging Face Hub kartları ve Google Vertex AI Gemini Fine-Tuning reçetesi (`vertex_ai_tuning.json`) ile bulut eğitime hazır hale getirmek.

#### 💻 1. Konsol Komutu ile Test:
```bash
# Vertex AI tuning reçetesini üretip kontrol edin:
python -c "
from pipeline.cloud_gpu_offloader import CloudGPUOffloader
offloader = CloudGPUOffloader(config_path='config.json')
recipe = offloader.generate_vertex_ai_recipe(model_name='gemini-1.5-flash-002')
print('Vertex AI Reçetesi Hazır:', recipe.get('status') == 'success')
"
```
* **Konsol Çıktısı Kontrolü:** `Vertex AI Reçetesi Hazır: True` olduğunu görün.

#### 🖥️ 2. Web UI ile Test:
1. Üst bardaki **🤗 HF & Bulut GPU** modalını açın.
2. **⚡ Bulut GPU Fine-Tuning Kiti** sekmesinde **Google Vertex AI Gemini Tuning** seçeneğini seçip paketi üretin.
3. `exports/<project_id>/cloud_payload/vertex_ai_tuning.json` dosyasının oluştuğunu ve eğitim hiperparametrelerini içerdiğini doğrulayın.

---

## 📋 Kullanıcı Doğrulama ve Geri Bildirim Raporu Şablonu

Tüm testleri tamamladıktan sonra lütfen aşağıdaki kontrol tablosunu doldurarak geliştirici etmene geri besleme olarak iletiniz:

| Faz No | Faz Başlığı | Konsol Testi | UI Testi | Durum (Geçti / Kaldı) | Notlar & Bulgular |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **FAZ 1** | Veri Seti Kalite & Doğrudan Türkçe | [ ] | [ ] | ⏳ Bekliyor | |
| **FAZ 2** | Sentetik Kod Çeşitliliği (Rendergit AST) | [ ] | [ ] | ⏳ Bekliyor | |
| **FAZ 3** | Proje & Veri Seti Birleştirme Motoru | [ ] | [ ] | ⏳ Bekliyor | |
| **FAZ 4** | Hugging Face & Bulut GPU Dağıtımı | [ ] | [ ] | ⏳ Bekliyor | |
| **FAZ 5** | İzole Hata & Uyarı Log Sistemi | [ ] | [ ] | ⏳ Bekliyor | |
| **FAZ 6** | Proje Gezgini & Persona Editörü | [ ] | [ ] | ⏳ Bekliyor | |
| **FAZ 7** | HF Serverless & Fallback Altyapısı | [ ] | [ ] | ⏳ Bekliyor | |
| **FAZ 8** | Chat KaTeX Formül & İnsan RLHF Puanlama | [ ] | [ ] | ⏳ Bekliyor | |
| **FAZ 9** | OpenAI-Uyumlu API & Scroll-Lock | [ ] | [ ] | ⏳ Bekliyor | |
| **FAZ 10** | Multimodal Tarama & 2x GPU Sharding | [ ] | [ ] | ⏳ Bekliyor | |
| **FAZ 11** | Multimodal Görsel Veri Seti Motoru | [ ] | [ ] | ⏳ Bekliyor | |
| **FAZ 12** | Google LangExtract & Offset Grounding | [ ] | [ ] | ⏳ Bekliyor | |
| **FAZ 13** | Kiwix OpenZIM Ansiklopedi Veri Hattı | [ ] | [ ] | ⏳ Bekliyor | |
| **FAZ 14** | Gemini API & Token Bütçe Yöneticisi | [ ] | [ ] | ⏳ Bekliyor | |
| **FAZ 15** | LLM-as-a-Judge & Editor-in-Chief | [ ] | [ ] | ⏳ Bekliyor | |
| **FAZ 16** | LangExtract Dinamik Few-Shot | [ ] | [ ] | ⏳ Bekliyor | |
| **FAZ 17** | Multimodal Markdown Kataloğu & WebP | [ ] | [ ] | ⏳ Bekliyor | |
| **FAZ 18** | Environment Hooks & Scheduled Triggers | [ ] | [ ] | ⏳ Bekliyor | |
| **FAZ 19** | HF Hub & Vertex AI Gemini Tuning | [ ] | [ ] | ⏳ Bekliyor | |

---

### ✍️ Onay ve İmza
* **Test Eden Kullanıcı / Mühendis:** ____________________
* **Test Tarihi:** 2026-08-21
* **Genel Değerlendirme:** [ ] BAŞARILI (Sürüme Hazır) / [ ] DÜZELTME GEREKİYOR
* **Önerilen Sürüm Numarası:** `v20.0.0-RELEASE`
