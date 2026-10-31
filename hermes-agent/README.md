# Elektor Dataset Pipeline — Hermes Agent Integration (`hermes-agent/`)

Bu dizin, [Nous Research Hermes Agent](https://hermes-agent.nousresearch.com/docs) (`akillibidik`, `aikonsol`, Hermes CLI, Gateway Bot ve Kanban iş akışları) için **Elektor Veri Seti Pipeline**'ını tam kapsamlı bir yetenek setine (Skill + CLI + MCP Server) dönüştüren resmi paket yapısını içerir.

Tüm `SKILL.md` tanımlamaları, resmi [Hermes Agent Creating Skills](https://hermes-agent.nousresearch.com/docs/developer-guide/creating-skills), [Skills System](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills) ve yerel `hermes-agent-skill-authoring` standartlarına (**Progressive Disclosure Level 0/1/2**, `${HERMES_SKILL_DIR}` token desteği, `<= 60` karakterlik keskin `description`, `metadata.hermes`, `required_environment_variables` ve `[[as_document]]` medya etiketleri) %100 uyumlu olarak hazırlanmıştır.

---

## Dizin Yapısı

```text
hermes-agent/
├── README.md                          # Genel bakış, kullanım senaryoları ve hızlı başlangıç
├── INSTALLATION.md                    # Kurulum, external_dirs, symlink ve MCP entegrasyon kılavuzu
├── ARCHITECTURE.md                    # Hermes Agent <-> Elektor Pipeline mimari eşleşme belgesi
├── .well-known/
│   └── skills/
│       └── index.json                 # Hermes Skill Discovery (Otomatik keşif manifestosu)
├── scripts/
│   ├── elektor_hermes_cli.py          # Hermes ajanları için birleşik JSON/CLI köprüsü
│   ├── elektor_mcp_server.py          # Sıfır bağımlılıklı Stdio JSON-RPC 2.0 MCP Sunucusu
│   └── install_skills.sh              # $HERMES_HOME/skills/data/ kurulum ve doğrulama betiği
└── skills/
    └── data/
        ├── DESCRIPTION.md             # Veri & Veri Seti Mühendisliği kategori tanımı
        ├── elektor-dataset-pipeline/  # 1. Uçtan uca pipeline ve çoklu proje orkestrasyonu
        │   ├── SKILL.md
        │   ├── references/
        │   │   ├── cli-and-api.md
        │   │   └── config-schema.md
        │   ├── templates/
        │   │   └── project_config.json
        │   └── scripts/
        │       └── elektor_hermes_cli.py
        ├── elektor-ocr-layout/        # 2. PDF sayfa düzeni, OCR ve şema/diyagram kırpma
        │   ├── SKILL.md
        │   ├── references/
        │   │   ├── layout-and-cropping.md
        │   │   └── vlm-ocr-tuning.md
        │   └── scripts/
        │       └── elektor_hermes_cli.py
        ├── elektor-rag-memory/        # 3. Qdrant vektör hafıza, SQLite ve MCP sorgulama
        │   ├── SKILL.md
        │   ├── references/
        │   │   ├── qdrant-and-sqlite.md
        │   │   └── mcp-integration.md
        │   └── scripts/
        │       └── elektor_hermes_cli.py
        └── elektor-dataset-curation/  # 4. Türkçe SFT/DPO kürasyonu, Judge ve Unsloth ihracı
            ├── SKILL.md
            ├── references/
            │   ├── sft-dpo-schemas.md
            │   └── judge-and-autonomous-cron.md
            ├── templates/
            │   └── hermes_cron_blueprint.yaml
            └── scripts/
                └── elektor_hermes_cli.py
```

---

## Hermes Ajanlarına Açılan 4 Temel Skill

| Skill Adı (`name`) | Açıklama (`description` <= 60 kr.) | Kapsadığı Elektor Yetenekleri |
| :--- | :--- | :--- |
| **`elektor-dataset-pipeline`** | `Orchestrate Elektor PDF-to-SFT/DPO dataset pipeline.` | Sistem sağlığı (`health`), çoklu proje yönetimi (`projects`), aşamalı çalıştırma (`extract`, `enrich`, `embed`, `export`, `colab`, `self_test`). |
| **`elektor-ocr-layout`** | `Extract PDF layouts, OCR text, and schematic crops.` | Çok sütunlu PDF okuma sırası, register tablosu koruma, şema/diyagram bütünlüklü kırpma (`inspect-crops`), VLM OCR ve `[[as_document]]` kayıpsız gönderim. |
| **`elektor-rag-memory`** | `Query Elektor Qdrant vectors and SQLite knowledge.` | Qdrant semantik vektör arama (`rag-search`), SQLite makale/zenginleştirme sorgulama (`sqlite-search`), bilgi boşluğu analizi (`dataset-context`) ve Stdio MCP sunucusu. |
| **`elektor-dataset-curation`** | `Curate, judge, and export Turkish SFT/DPO datasets.` | Lisans/telif gürültüsü temizliği (`clean_boilerplate`), `"input": ""` sızıntısız Alpaca SFT & DPO şeması (`sft_dataset.jsonl`, `dpo_dataset.jsonl`), LLM-as-a-Judge (`judge` / `trigger --mode strict`) ve Unsloth hazırlığı. |

---

## Hızlı Başlangıç

### 1. Skill Dosyalarını Doğrulama
```bash
/home/hakan/Git/elektor/.venv/bin/python /home/hakan/Git/elektor/hermes-agent/scripts/elektor_hermes_cli.py validate-skills
```

### 2. Sistem ve Veri Tabanı Sağlığını Kontrol Etme
```bash
/home/hakan/Git/elektor/.venv/bin/python /home/hakan/Git/elektor/hermes-agent/scripts/elektor_hermes_cli.py health
```

### 3. Hermes Agent İçine Kurulum (`~/.hermes/skills/data/`)
```bash
/home/hakan/Git/elektor/hermes-agent/scripts/install_skills.sh --check
# Symlink ile kurmak için:
/home/hakan/Git/elektor/hermes-agent/scripts/install_skills.sh --link
```

### 4. Hermes CLI veya Sohbet İçinde Kullanım
Hermes etkileşimli oturumunda (`hermes` veya `hermes -p akillibidik`):
```text
/elektor-dataset-pipeline RP2040 projesinin sağlık durumunu kontrol et ve özetle.
/elektor-rag-memory RP2040 PIO state machine FIFO derinliğini Qdrant üzerinden araştır.
/elektor-ocr-layout Çıkartılan devre şemalarını incele ve multimodal kataloğu güncelle.
/elektor-dataset-curation Telif/lisans gürültüsünü temizle ve Unsloth için SFT/DPO veri setlerini dışa aktar.
```
