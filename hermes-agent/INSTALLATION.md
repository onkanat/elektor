# Kurulum ve Yapılandırma Kılavuzu (`INSTALLATION.md`)

Bu belge, `/home/hakan/Git/elektor/hermes-agent/` içindeki yeteneklerin (Skills), yardımcı CLI betiğinin ve MCP sunucusunun **Nous Research Hermes Agent** (`https://hermes-agent.nousresearch.com/docs`) ortamına nasıl tanıtılacağını açıklar.

---

## Yöntem 1: `skills.external_dirs` ile Doğrudan Bağlama (Önerilen)

Hermes Agent, `~/.hermes/config.yaml` içindeki `skills.external_dirs` ayarını kullanarak harici Git depolarındaki skill dizinlerini kopyalama yapmadan doğrudan yükleyebilir:

```yaml
# ~/.hermes/config.yaml (veya ~/.hermes/profiles/akillibidik/config.yaml)
skills:
  external_dirs:
    - /home/hakan/Git/elektor/hermes-agent/skills
  config:
    elektor:
      repo_path: "/home/hakan/Git/elektor"
      api_url: "http://127.0.0.1:3456"
```

Bu yapılandırma eklendiğinde Hermes Agent açılışta `skills/data/` altındaki 4 skill'i (`elektor-dataset-pipeline`, `elektor-ocr-layout`, `elektor-rag-memory`, `elektor-dataset-curation`) otomatik olarak indeksler.

---

## Yöntem 2: `install_skills.sh` ile `$HERMES_HOME/skills/data/` Altına Kurulum

Skill klasörlerini doğrudan `~/.hermes/skills/data/` dizinine sembolik bağ (symlink) veya kopya olarak kurmak için [install_skills.sh](file:///home/hakan/Git/elektor/hermes-agent/scripts/install_skills.sh) betiğini kullanabilirsiniz:

```bash
# 1. Mevcut durumu ve SKILL.md standart uyumluluğunu denetle (Salt-okunur):
/home/hakan/Git/elektor/hermes-agent/scripts/install_skills.sh --check

# 2. Sembolik bağ (symlink) olarak ~/.hermes/skills/data/ altına bağla:
/home/hakan/Git/elektor/hermes-agent/scripts/install_skills.sh --link

# 3. Bağımsız kopya olarak kurmak için (--force ile mevcut kopyaların üzerine yazılır):
/home/hakan/Git/elektor/hermes-agent/scripts/install_skills.sh --copy

# 4. Belirli bir Hermes profiline (örn. akillibidik) kurmak için:
HERMES_HOME="$HOME/.hermes/profiles/akillibidik" /home/hakan/Git/elektor/hermes-agent/scripts/install_skills.sh --link

# 5. Hermes CLI üzerinden Elektor depo ve API adresini yapılandırmak için:
hermes config set skills.config.elektor.repo_path /home/hakan/Git/elektor
hermes config set skills.config.elektor.api_url http://127.0.0.1:3456
```

---

## Yöntem 3: Stdio MCP Sunucusu Olarak Kaydetme (`elektor_mcp_server.py`)

Hermes ajanlarının `search_vector_rag`, `query_sqlite_knowledge`, `inject_sft_dpo_context` ve `evaluate_knowledge_gap` araçlarını birinci sınıf MCP aracı (native tool) olarak çağırması için `~/.hermes/config.yaml` dosyasına şu bloğu ekleyin:

```yaml
mcp_servers:
  elektor:
    command: "/home/hakan/Git/elektor/.venv/bin/python"
    args:
      - "/home/hakan/Git/elektor/hermes-agent/scripts/elektor_mcp_server.py"
    env:
      ELEKTOR_REPO_PATH: "/home/hakan/Git/elektor"
```

---

## Ortam Değişkenleri (`required_environment_variables`)

Hermes Agent `terminal` ve `execute_code` sanal alanları (sandbox), güvenlik gereği yalnızca beyaz listedeki ortam değişkenlerini alt süreçlere aktarır. `SKILL.md` ön bilgilerinde (`frontmatter`) tanımlanan aşağıdaki değişkenler Hermes tarafından otomatik olarak tanınır:

- `GEMINI_API_KEY`: Hibrit modda (`llm.provider: "hybrid"` veya `"gemini"`) SFT/DPO sentezi ve Judge hakemliği için kullanılır.
- `HF_TOKEN`: `run.py hf_upload` komutuyla Hugging Face Hub'a veri seti yüklerken kullanılır.

Değişkenleri `~/.hermes/.env` dosyasına ekleyebilir veya `hermes config set` ile tanımlayabilirsiniz.
