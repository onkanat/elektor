Listed directory elektor
Listed directory pipeline
Viewed USER_GUIDE.md:1-120
Viewed run.py:1-150
Viewed run.py:151-400
Viewed run.py:401-659
Listed directory Git
Listed directory .agents
Listed directory config
Listed directory skills
Viewed SKILL.md:1-60

### 🔍 Elektor Pipeline Mimarisi & Paralel Orkestrasyon Analizi

Projedeki tüm pipeline modülleri, veri akışları, veritabanı şemaları ve çalıştırma mekanizmaları incelenmiştir. Kod çalıştırılmadan ve herhangi bir değişiklik yapılmadan gerçekleştirilen derinlemesine mimari analiz ve tasarlanan **Global Antigravity-CLI Skill** mimarisi aşağıda özetlenmiştir.

---

### 1. Mevcut Pipeline Mimarisi & Yetenekler Özeti

Platform, heterojen veri kaynaklarını uçtan uca işleyip LLM eğitimine hazır (SFT, DPO, Chat, Multimodal) veri setlerine dönüştüren çok katmanlı bir boru hattına sahiptir:

```
[Girdi Kaynakları]
  ├── PDF (Book, Klasör, Makale) ──► ArchiveExtractor (PyMuPDF, OCR)
  ├── Git Repo / Kod Ağacı       ──► Rendergit (AST parser, Sınıf/Fonksiyon çıkarma)
  └── Kiwix ZIM (.zim arşivi)    ──► KiwixZimExtractor (libzim / HTML parse)
                                        │
                                        ▼
                                [SQLite (WAL Modu)]
                                        │
             ┌──────────────────────────┴──────────────────────────┐
             ▼                                                     ▼
     [ArchiveAnalyzer]                                   [LangExtractEngine]
 (SFT, DPO, Multi-turn Chat,                         (Grounded Entity & Span Extraction,
  Kod Çeşitliliği, Sharded Ollama)                    HTML Görselleştirici)
             │                                                     │
             └──────────────────────────┬──────────────────────────┘
                                        ▼
                                  [JudgeEngine]
                        (LLM-as-a-Judge, Editor-in-Chief,
                         Strict / Hybrid Editor, Gemini Batch)
                                        │
             ┌──────────────────────────┼──────────────────────────┐
             ▼                          ▼                          ▼
    [DatasetBuilder]          [VisualDatasetBuilder]       [ArchiveVectorStore]
  (JSONL / Parquet İhracı)    (WebP Multimodal LLaVA)     (Qdrant Vektör İndeksleme)
             │                          │
             └──────────────────────────┴──────────────────────────┐
                                                                   ▼
                                                          [HF / Colab Offload]
                                                      (HuggingFace Hub, Unsloth NB)
```

#### Mevcut Altyapının Güçlü Yönleri

1. **İzolasyon & Proje Yönetimi:** Her proje `config.json` üzerinden bağımsız SQLite (`database/<proje>.db`), Qdrant ve `exports/<proje>/` klasörlerine ayrılmıştır.
2. **Eşzamanlılık (Concurrency) Desteği:** SQLite `PRAGMA journal_mode=WAL;` ve `busy_timeout=60000;` ayarlarıyla çoklu process/shard yazma çakışmalarına karşı dayanıklıdır.
3. **Paralel GPU Sharding:** `run.py enrich --shards N --shard-ports 11434,11435` ile yerel Ollama örnekleri arasında veri aralıklarını (`--limit start:end`) bölüştürerek paralel çalışabilmektedir.
4. **Kalite Hakem Katmanı (Judge):** Üretilen veri setleri `run.py judge` veya `run.py trigger` ile otomatik elenmekte veya düzeltilmektedir.

---

### 2. Paralel Pipeline & Antigravity-CLI Yönetim Mimarisi

Birden fazla farklı girdi kaynağını (`.pdf`, `git repo`, `.zim`, klasör) aynı anda paralel süreçler halinde çalıştırmak ve bunları Antigravity-CLI üzerinden tek elden takip etmek için gereken mimari yapı:

```
[Kullanıcı / Antigravity Agent]
           │
           ▼  (Basit Skill Komutları: dataset-üret, dataset-kalite-kontrol, dataset-durum)
┌────────────────────────────────────────────────────────────────────────┐
│                        Antigravity Global Skill                        │
├────────────────────────────────────────────────────────────────────────┤
│  1. Config Factory: Her girdi için izole dinamik config üretir         │
│  2. Resource Allocator: GPU/Ollama portlarını process'lere paylaştırır  │
│  3. Process Runner: Arka plan görevlerini başlatır (PID & Log takibi)  │
│  4. Watchdog & Auditor: Log akışını ve SQLite tamamlanma oranını izler │
└────────────────────────────────────────────────────────────────────────┘
           │
 ┌─────────┼─────────────────────────┐
 ▼         ▼                         ▼
[Task 1] [Task 2]                 [Task N]
(Book-PDF) (Git-Repo)             (Kiwix ZIM)
(Port: 11434) (Port: 11435)       (Gemini Batch)
(PID: 20411)  (PID: 20412)        (PID: 20413)
```

---

### 3. Tasarlanan Global `SKILL.md` Doküman Taslağı

Aşağıdaki tasarım, `~/.gemini/config/skills/parallel-dataset-orchestrator/SKILL.md` (veya global skill dizininize) eklenebilecek standart Antigravity Skill formatındadır:

```markdown
---
name: dataset-orchestrator
description: >-
  Heterojen veri kaynaklarından (PDF, Git Repo, Kiwix ZIM, Kitap) eşzamanlı ve paralel
  sentetik veri seti (SFT/DPO/Chat) üretimi, kalite kontrolü (LLM Judge) ve
  Antigravity-CLI arka plan süreç yönetim orkestratörü.
---

# 🚀 Universal Parallel Dataset Orchestrator

Bu skill, Antigravity Agent'a farklı kaynaklardan eşzamanlı sentetik veri üretme, paralel GPU/Ollama iş yüklerini yönetme ve üretilen veri setlerini otomatik LLM hakem testlerinden geçirme yeteneği kazandırır.

---

## 📌 Hızlı Komut Arayüzü (CLI Ergonomisi)

Agent aşağıdaki üst seviye yönergeleri aldığında ilgili arka plan adımlarını yürütür:

### 1. `dataset-üret` (Veri Üretim Hattı)
Farklı formatlardaki girdileri tek komutla izole pipeline olarak başlatır.
* **PDF / Kitap:**
  `python run.py --config configs/auto_<proje>.json pipeline --limit all`
* **Git Reposu (Rendergit Modu):**
  `python run.py --config configs/auto_<repo>.json pipeline --limit all`
* **Kiwix ZIM Dosyası:**
  `python run.py --config configs/auto_<zim>.json kiwix --zim path/to/file.zim --limit all`
* **Paralel Çoklu Shard (Multi-GPU/Port):**
  `python run.py --config configs/auto_<proje>.json enrich --shards 2 --shard-ports 11434,11435`

### 2. `dataset-kalite-kontrol` (LLM-as-a-Judge & Editor)
Üretilmiş SFT/DPO verilerini hakem onayından geçirir ve zayıf yanıtları otomatik yeniden yazar.
* **Hızlı Denetim:** `python run.py --config configs/<proje>.json judge --mode strict --threshold 7.5`
* **Otomatik Düzeltici:** `python run.py --config configs/<proje>.json judge --mode hybrid_editor`
* **Gemini Batch (50% İndirim & Sıfır Rate-Limit):** `python run.py --config configs/<proje>.json judge --batch`

### 3. `dataset-durum` (Canlı Süreç ve İlerleme Takibi)
Arka planda çalışan tüm pipeline süreçlerinin PID, aktif port, işlenen makale sayısı ve SQLite durumunu listeler.

---

## 🛠️ Paralel Çalıştırma & İzolasyon Protokolü

Agent paralel iş başlatırken şu kurallara kesinlikle uyar:

1. **İzole Konfigürasyon Dosyası Üretimi:**
   Her paralel görev için `configs/run_<proje_id>.json` oluşturulur:
   * `db_path`: `"database/<proje_id>.db"`
   * `qdrant_db_path`: `"qdrant_extract/<proje_id>"`
   * `export_dir`: `"exports/<proje_id>"`
   * `ollama_url`: Hedef boşta olan port (örn: `http://localhost:11434` veya `11435`)

2. **Arka Plan Süreç Yönetimi (Background Process Lifecycle):**
   * Görevler `run_command` (veya `manage_task`) üzerinden bağımsız daemon/background olarak başlatılır.
   * `PYTHONUNBUFFERED=1` ile loglar `exports/<proje_id>/pipeline.log` dosyasına anlık yazılır.
   * Süreçlerin kilitlenmemesi için `PRAGMA busy_timeout=60000;` varsayılan olarak devrededir.

3. **Otomatik Tamamlanma & Bildirim Takibi:**
   * Agent periyodik bekleme döngülerine girmeden `schedule` veya reactive `manage_task` bildirimleriyle süreçlerin bitişini yakalar.
   * Tamamlanan veri seti otomatik olarak `exports/<proje_id>/sft_dataset.jsonl` ve `dpo_dataset.jsonl` formatında derlenir.
```

---

### 4. Önerilen Bir Sonraki Adım

Bu analize ve şablona onay vermeniz durumunda:

1. `~/.gemini/config/skills/` altında global skill dizini ve `SKILL.md` dosyası oluşturulabilir.
2. Birden fazla pipeline'ı tek satırda konfigüre edip başlatan hafif bir CLI orkestrasyon betiği (`tools/orchestrator.py` gibi) kurgulanabilir.
