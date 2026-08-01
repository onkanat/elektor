# Önerilerden oluşmaktadır

Döküman tartışmaya açıktır. [roadmap_universal_pipeline.md][./antigravity/roadmap_universal_pipeline.md] dosyasına eklenmesi düşünülmektedir.

### İnceleme sonucu

Mevcut arşiv pipeline’ı, bu proje için **iyi bir başlangıç mimarisi** sunuyor. Temel akış doğru kurulmuş:

$$
\text{PDF} \rightarrow \text{metin/OCR} \rightarrow \text{SQLite} \rightarrow \text{LLM zenginleştirme} \rightarrow \text{Türkçe veri seti} \rightarrow \text{Qdrant/RAG}
$$

Elektor arşivi için tasarlanmış olsa da; kaynak dizini, veri modeli, promptlar, kalite kontrolü ve çıktı şeması değiştirilerek elektronik/elektrik/MCU/Raspberry Pi Pico PDF koleksiyonuna uygulanabilir.

Mevcut üretim durum dosyası, pipeline’ın büyük veri hacminde fiilen kullanıldığını gösteriyor:

- Toplam arşiv kaydı: `11.773`
- İngilizce zenginleştirilmiş kayıt: `11.114`
- Türkçe SFT çevirisi yapılmış kayıt: `7.023`
- Son işlenen batch: `8150:8200`

Bu, batch, kaldığı yerden devam etme ve model bellek boşaltma stratejisinin pratikte faydalı olduğunu gösterir.

### Güçlü yönler ve bu projede doğrudan kullanılabilecek parçalar

#### 1. PDF çıkarma + OCR fallback

`extractor.py` dijital PDF metnini önce `pypdf` ile almaya çalışıyor; metin kısa kalırsa `pypdfium2` ile sayfaları render edip Tesseract OCR kullanıyor.

Bu, mevcut proje için özellikle önemlidir çünkü kaynaklarda:

- metin tabanlı ders kitapları,
- taranmış laboratuvar föyleri,
- devre şemaları,
- pinout sayfaları,
- veri sayfaları,
- teknik çizimler

bir arada bulunuyor.

Mevcut yaklaşımın temel avantajları:

- OCR gerektirmeyen PDF’lerde gereksiz maliyeti azaltır.
- Taranmış dokümanları tamamen dışlamaz.
- SQLite içinde OCR kaynağını `is_ocr` alanıyla izler.
- Hatalı OCR karakterlerini düzeltmek için bir normalizasyon katmanı vardır.

Ancak mevcut `clean_ocr_text()` yalnızca İngilizce Elektor devre terminolojisine göre hazırlanmış. Bu proje için Türkçe OCR hataları ve veri sayfası karakterleri de ele alınmalı:

- `I` / `1` / `l`
- `O` / `0`
- `µ` / `u`
- `Ω` / `Q`
- `VCC`, `GND`, `GPIO`, `I²C`, `SPI`, `UART`
- `3.3 V`, `5 V`, `10 kΩ`, `100 nF`, `1 µF`
- pin isimleri ve tablolar
- sayfa başlık/altlık tekrarları
- PDF içindeki lisans/copyright sayfaları

#### 2. SQLite tabanlı işlem durumu

`articles` ve `enrichments` tabloları, büyük PDF koleksiyonlarında tekrar işlemeyi önleyen doğru bir tasarım tercihidir.

Bu projede `articles` yerine daha genel bir `documents` ya da `source_documents` tablosu kullanılmalı. Çünkü koleksiyon yalnızca makalelerden oluşmuyor; ders kitabı, veri sayfası, kart şeması, uygulama notu ve teknik resim de içeriyor.

Önerilen temel kaynak belge alanları:

```text
id
file_path
filename
document_title
document_type
domain
language
page_count
extracted_text
is_ocr
ocr_quality_score
source_hash
source_license_note
processed_at
is_embedded
```

Önerilen belge tipleri:

```text
datasheet
reference_manual
application_note
user_guide
technical_book
laboratory_manual
schematic
pinout
technical_drawing
academic_paper
```

Örnek alan etiketleri:

```text
electronics
electrical_circuits
analog_electronics
digital_electronics
op_amp
transistors
signals_and_systems
microcontrollers
pic
rp2040
rp2350
raspberry_pi_pico
raspberry_pi_pico_w
wireless
rf
technical_drawing
```

#### 3. Ollama ile iki aşamalı üretim

`analyzer.py` içindeki iki aşamalı işlem fikri çok uygundur:

1. Teknik içerik analizi, soru-cevap ve DPO çifti üretimi
2. Türkçe çeviri / Türkçe veri seti üretimi

Ayrıca `keep_alive=0` ile modelin bellekten boşaltılması, iki adet RTX 4060 Ti 16 GB içeren yerel sistem için yararlıdır. Özellikle farklı modeller sırayla çalıştırılıyorsa VRAM baskısını azaltır.

Mevcut tasarımın olumlu yönleri:

- Her kaynak için özet, konu etiketi, SFT ve DPO üretiyor.
- Yanlış DPO yanıtlarını “gerçekçi mühendislik hatası” çevresinde üretmeyi hedefliyor.
- Türkçe teknik terimlerin korunması için çeviri promptu var.
- Çıktıyı JSON bekleyerek ayrıştırmayı kolaylaştırıyor.
- Tüm arşivde model değiştirme maliyetini azaltıyor.

### Bu proje için kritik değişiklikler

#### 1. İngilizce üretip Türkçeye çevirmek yerine doğrudan Türkçe üretim

Mevcut akış:

```text
İngilizce kaynak → İngilizce SFT/DPO → Türkçe çeviri
```

Bu kaynak koleksiyonu için daha güçlü yaklaşım:

```text
İngilizce/Türkçe kaynak → kaynak temelli teknik çıkarım → doğrudan Türkçe SFT/DPO/chat üretimi
```

Nedeni:

- Teknik kavramların Türkçedeki doğru karşılıkları doğrudan kurulabilir.
- Çeviri sırasında soru/yanıt yapısının bozulma riski azalır.
- Türkçe kullanıcıların sorma biçimlerine daha doğal veri üretilir.
- “doğru ama Türkçesi zayıf” kayıt sayısı azalır.
- DPO’nun `chosen` ve `rejected` cevaplarındaki teknik nüanslar daha iyi korunur.

İngilizce çıktı yine de isteğe bağlı ikinci veri seti olarak korunabilir; fakat bu projenin ana hedefi Türkçe olduğundan ana eğitim çıktısı Türkçe olmalıdır.

#### 2. Kaynağın ilk 4.000 karakteriyle sınırlı analiz yeterli değil

`analyzer.py`, metni ilk `4000` karaktere kesiyor. Bu Elektor makalelerinde hız açısından anlamlı olabilir; fakat özellikle aşağıdaki kaynaklarda yetersizdir:

- `rp2040-datasheet.pdf`
- `RP-008373-DS-2-rp2350-datasheet.pdf`
- `raspberry-pi-pico-c-sdk.pdf`
- `Signal_and_Systems_Hwei_P_Hsu.pdf`
- `1588498236-fundamentals-of-electric-circuits-5th-edgnv64.pdf`
- `hardware-design-with-rp2040.pdf`

Bu tip uzun teknik dokümanlarda yalnızca ilk bölüm işlenirse, veri seti giriş/özet konularına yığılır; GPIO, DMA, PIO, ADC, güç, debug, PCB tasarımı veya ileri çevre birimleri gibi bölümler dışarıda kalır.

Bu nedenle analiz birimi belge değil, **bölüm veya kaynak parçası** olmalı:

```text
PDF
  └── bölüm
       └── alt başlık
            └── 800–2.000 tokenlık bağlam parçası
                 └── SFT / DPO / chat kayıtları
```

Her üretilen kayıtta aşağıdakiler tutulmalı:

```json
{
  "source_file": "rp2040-datasheet.pdf",
  "source_pages": "12-15",
  "chapter": "GPIO",
  "section": "Function select and pad control",
  "chunk_id": "rp2040_gpio_001",
  "domain": "rp2040",
  "language": "tr"
}
```

#### 3. Sadece tek turlu chat üretimi yeterli değil

Mevcut `chat_dataset.jsonl`, SFT soru-cevap kayıtlarını basitçe şu yapıya çeviriyor:

```json
{
  "messages": [
    {"role": "user", "content": "Soru"},
    {"role": "assistant", "content": "Yanıt"}
  ]
}
```

Bu, chat biçiminde SFT verisidir; fakat gerçek çok turlu teknik sohbet değildir.

Bu proje için ek olarak şu diyalog türleri üretilmeli:

- Kullanıcının eksik devre bilgisini tamamlatma
- Adım adım hata ayıklama
- Yanlış bağlantı şeması yorumlama
- Kod ve donanım bağlantısını birlikte değerlendirme
- Başlangıç seviyesi kullanıcıdan ileri seviye kullanıcıya açıklama uyarlama
- Güvenlik uyarısı gerektiren elektrik uygulamaları
- Veri sayfasındaki çelişkili görünen iki parametreyi açıklama
- Pico/Pico W bağlantı ve pin seçim diyalogları
- Ölçüm sonucu yorumlama

Örnek çok turlu yapı:

```json
{
  "messages": [
    {
      "role": "system",
      "content": "Sen Türkçe konuşan, kaynak temelli ve güvenlik odaklı bir gömülü sistemler asistanısın."
    },
    {
      "role": "user",
      "content": "Raspberry Pi Pico ile bir LED yakmak istiyorum ama LED yanmıyor."
    },
    {
      "role": "assistant",
      "content": "Önce bağlantıyı ve kullanılan GPIO numarasını doğrulayalım. LED hangi GPIO pinine bağlı, LED ile seri direnç kullandın mı ve kodda hangi pin numarası tanımlı?"
    },
    {
      "role": "user",
      "content": "GPIO 15'e bağladım. Direnç kullanmadım."
    },
    {
      "role": "assistant",
      "content": "LED ile seri direnç kullanmanız gerekir. Direnç olmadan LED ve GPIO pini aşırı akıma maruz kalabilir. Bağlantıyı kapatıp LED ile GPIO 15 arasına uygun bir seri direnç ekleyin; ardından LED'in anot-katot yönünü ve kodda GPIO 15 tanımını kontrol edin."
    }
  ],
  "metadata": {
    "domain": "raspberry_pi_pico",
    "topic": "gpio_led",
    "difficulty": "temel",
    "safety_relevant": true,
    "language": "tr"
  }
}
```

#### 4. DPO üretiminde doğrulama katmanı gerekli

Mevcut pipeline her içerikten bir DPO çifti üretmektedir. Bu faydalı olsa da, DPO verisinde yanlış seçilmiş `chosen` cevabı model kalitesine zarar verebilir.

DPO için aşağıdaki kontroller önerilir:

- `chosen` yanıtı kaynak parçada destekleniyor mu?
- `rejected` yanıtı gerçekten hatalı mı, yoksa yalnızca farklı bir çözüm mü?
- Hata güvenlik açısından riskli mi?
- Yanlış cevap, doğru cevaba fazlasıyla benziyor mu?
- Doğru cevap, reddedilen cevaptan daha açıklayıcı ve uygulanabilir mi?
- Kaynakta olmayan kesin sayısal iddialar var mı?
- Pin, gerilim, akım ve frekans değerleri doğru mu?
- DPO çifti gerçek bir tercih sinyali taşıyor mu?

Özellikle RP2040/RP2350, Pico ve Pico W verilerinde şu yanlış türleri DPO için çok değerlidir:

- `3,3 V` GPIO’ya doğrudan `5 V` bağlama önerisi
- LED’i seri direnç olmadan sürme
- I²C pull-up dirençlerini yanlış yorumlama
- UART TX/TX ve RX/RX bağlama
- ADC giriş sınırlarını yok sayma
- güç hattı decoupling capacitor gereksinimini atlama
- GPIO akım sınırlarını göz ardı etme
- SPI `CS` hattını yanlış yorumlama
- boot/debug pinlerini gelişigüzel kullanma
- Pico W ağ bağlantısı sorununu yalnızca yazılım hatası sayma

#### 5. Veri seti çıktısında kaynak izlenebilirliği korunmalı

Mevcut `dataset_builder.py`, temel eğitim kayıtlarını dışarı aktarıyor; ancak kaynak dosya ve sayfa bilgisini korumuyor. Bu, kalite kontrol ve ileri aşamada hatalı veri temizliği için eksikliktir.

Önerilen Türkçe SFT çıktısı:

```json
{
  "messages": [
    {
      "role": "system",
      "content": "Sen Türkçe teknik eğitim asistanısın. Belirsiz veya güvenlik açısından riskli durumlarda bunu açıkça belirt."
    },
    {
      "role": "user",
      "content": "RP2040 GPIO girişinde dahili pull-up ne amaçla kullanılır?"
    },
    {
      "role": "assistant",
      "content": "Dahili pull-up, giriş pini açıkta kaldığında lojik seviyenin belirsizleşmesini önlemek için pini varsayılan olarak lojik 1 seviyesine çeker. Butonun diğer ucu GND'ye bağlandığında butona basılmasıyla pin lojik 0 okunabilir."
    }
  ],
  "metadata": {
    "dataset_type": "sft",
    "language": "tr",
    "domain": "rp2040",
    "topic": "gpio_input_pullup",
    "difficulty": "temel",
    "source_file": "rp2040-datasheet.pdf",
    "source_pages": "doğrulanmış sayfa aralığı",
    "source_chunk_id": "rp2040_gpio_pullup_001",
    "quality_status": "validated"
  }
}
```

Önerilen DPO çıktısı:

```json
{
  "prompt": "RP2040 GPIO girişinde pull-up direnci ne işe yarar?",
  "chosen": "Pull-up direnci, giriş pini açıkta kaldığında oluşabilecek belirsiz lojik seviyeyi önler ve pini varsayılan olarak lojik 1 seviyesinde tutar.",
  "rejected": "Pull-up direnci, GPIO pininin 5 V sinyalleri güvenle kabul etmesini sağlar.",
  "metadata": {
    "dataset_type": "dpo",
    "language": "tr",
    "domain": "rp2040",
    "topic": "gpio_input_pullup",
    "error_type": "incorrect_voltage_level_claim",
    "source_file": "rp2040-datasheet.pdf",
    "quality_status": "validated"
  }
}
```

### Mevcut kodda görünen kritik sorunlar

Dosya içerikleri üzerinden bakıldığında, bazı Python dosyalarında **girintileme hataları** görünüyor. Bu hatalar dosyaların gerçek halinde de varsa pipeline çalışmaz.

Örnekler:

- `extractor.py`
  - `ocr_pdf()` içinde `if result.returncode != 0:` altındaki `print` ve `continue` satırları girintisiz görünüyor.
  - `if txt_path.exists():` altındaki işlemler de girintisiz görünüyor.

- `vector_store.py`
  - `chunk_text()` içinde `if overlap_len + len(w) + 1 > self.chunk_overlap:` sonrasındaki `break` girintisi bozuk görünüyor.

- `dataset_builder.py`
  - `if isinstance(...)` blokları ve içindeki `for` / `if` satırlarında ciddi girinti kaymaları görünüyor.

- `run.py`
  - `--reset` sırasında export dosyası silme bölümünde `file.unlink()` ve hata yakalama bloklarının girintisi bozuk görünüyor.

Bu bozukluklar yalnızca dosya görüntüleme aktarımından kaynaklanmıyorsa, ilk iş olarak tüm dosyalarda çalıştırma doğrulaması yapılmalı:

```bash
python -m py_compile extractor.py analyzer.py vector_store.py dataset_builder.py run.py run_production.py
```

Ayrıca mevcut `run.py`, modülleri `pipeline.extractor` gibi çağırıyor; fakat yüklenen dosyalar kök dizinde görünmekte. Gerçek klasör yapısında `pipeline/` paketi yoksa importlar başarısız olur. Bu yapı ya korunmalı ya da importlar proje dizinine göre düzeltilmelidir.

### Bu proje için önerilen uyarlanmış pipeline

```text
PDF kaynakları
    ↓
Belge envanteri ve sınıflandırma
    ↓
Metin çıkarma / OCR / OCR kalite skoru
    ↓
Sayfa, bölüm ve alt başlık tabanlı parçalama
    ↓
Teknik veri normalizasyonu
    ↓
Kaynak temelli Türkçe SFT üretimi
    ↓
Kaynak temelli Türkçe DPO üretimi
    ↓
Çok turlu teknik chat üretimi
    ↓
Kural + LLM tabanlı kalite doğrulama
    ↓
Tekrar temizleme ve eğitim/validation/test ayrımı
    ↓
JSONL ihracı + Qdrant kaynak indeksi
```

### Proje için dosya bazlı yeniden kullanım önerisi

| Mevcut dosya | Yeniden kullanım | Gerekli uyarlama |
| --- | --- | --- |
| `extractor.py` | Yüksek | `articles` yerine tüm PDF türlerini destekleyen belge yapısı; sayfa/bölüm metadatası; gelişmiş OCR kalite kontrolü |
| `analyzer.py` | Yüksek | Doğrudan Türkçe üretim; bölüm tabanlı kaynak bağlamı; çoklu DPO; kalite/doğrulama geçişi |
| `dataset_builder.py` | Orta-yüksek | Kaynak sayfası, konu, zorluk, kalite skoru ve split bilgisini dışa aktarma |
| `vector_store.py` | Yüksek | Koleksiyon adını genelleştirme; sayfa/bölüm/chunk metadatası; belge türü ve alan filtreleri |
| `run.py` | Yüksek | `ingest`, `classify`, `chunk`, `generate-sft`, `generate-dpo`, `generate-chat`, `validate`, `export` alt komutları |
| `run_production.py` | Yüksek | PDF sayısı dinamik keşfedilmeli; sabit `11773` kaldırılmalı; başarısız belge listesi tutulmalı |
| `config.json` | Yüksek | Kaynak klasörleri, modeller, batch boyutu, üretim adetleri, kalite eşikleri ve çıktı klasörleri eklenmeli |
| `production_status.json` | Orta | Batch durumuna ek olarak hata sayısı, kalite reddi, üretilen SFT/DPO/chat adetleri tutulmalı |

### Donanımınıza göre üretim stratejisi

İki adet RTX 4060 Ti 16 GB için daha güvenli üretim düzeni:

1. **Extraction/OCR** CPU ağırlıklı ayrı aşama olarak çalışsın.
2. **Embedding** ayrı çalışsın; LLM ile aynı anda VRAM kullanımı sınırlansın.
3. SFT/DPO üretimi bir analiz modeliyle batch bazlı yapılsın.
4. Doğrudan Türkçe üretim başarısız veya yetersiz olursa çeviri modeli yalnızca seçili kayıtlar için kullanılsın.
5. Modelin her batch sonunda boşaltılması sürdürülmeli.
6. Her kayıtta ham model çıktısı, doğrulanmış çıktı ve ret sebebi izlenmeli.
7. Uzun veri sayfaları ve kitaplar, belge başına değil bölüm/parça başına işlenmeli.
8. Eğitim verisi üretiminden önce küçük bir pilot küme hazırlanmalı.

İlk pilot küme için en uygun PDF grubu:

- `getting-started-with-pico.pdf`
- `rp2040-datasheet.pdf`
- `raspberry-pi-pico-c-sdk.pdf`
- `connecting-to-the-internet-with-pico-w.pdf`
- `hardware-design-with-rp2040.pdf`
- `Pico-R3-A4-Pinout.pdf`
- `PicoW-A4-Pinout.pdf`

Bu grup üzerinden önce kaynak çıkarma kalitesi, Türkçe teknik terimler, DPO doğruluğu ve chat kalitesi test edilmelidir. Ardından elektrik devreleri, op-amp, transistor ve sinyaller-sistemler kaynaklarına geçmek daha kontrollü olur.

### Sonuç

Bu pipeline’ın mimari yaklaşımı proje için değerlidir ve özellikle **SQLite durum takibi, OCR fallback, batch üretim, Ollama entegrasyonu, model bellek boşaltma, Qdrant indeksleme ve JSONL ihracı** doğrudan faydalanılabilir parçalardır.

Ancak yeni projede aşağıdaki değişiklikler temel öncelik olmalıdır:

1. Belge yerine bölüm/parça tabanlı işleme  
2. İngilizce ara üretim yerine kaynak temelli doğrudan Türkçe üretim  
3. Kaynak dosya + sayfa + bölüm metadata’sının her kayıtta korunması  
4. Gerçek çok turlu chat üretimi  
5. DPO çiftleri için teknik doğrulama  
6. Veri seti kalite/tekrar/güvenlik kontrolü  
7. Mevcut Python dosyalarındaki görünen girintileme ve paket yapısı sorunlarının doğrulanması  

Bu şekilde mevcut arşiv pipeline’ı, elektronik ve gömülü sistemler odaklı Türkçe SFT, DPO ve chat veri seti üretim sistemi için sağlam bir temele dönüştürülebilir.
