# Elektor runtime contract

Bu dosya, B1–B5 düzeltmelerinin dış davranış sözleşmesidir.

## Provider yetenekleri

Çekirdek sağlayıcı adı sormaz; `pipeline/providers.py` üzerinden yetenek sorar:

- `analyzer_capabilities(config)`: `kind`, `remote`, `supports_sharding`, `native_unload`, `structured_output`.
- `ocr_capabilities(config)`: `kind`, `remote`, `native_api`, `native_unload`, `family`.

Uzak OpenAI-compatible analyzer (ör. Strata) için `supports_sharding=false`, `native_unload=false`. ECE'deki Ollama OCR uç noktası LAN'da olsa bile native Ollama'dır; `native_unload=true`.

## JSON / LaTeX

LaTeX üreten analyzer çağrıları varsayılan olarak **client-side parse** kullanır:

- `response_format=json_object` gönderilmez.
- `parse_json_robust` + `json_repair`; `\frac`, `\pi` gibi LaTeX komutları korunur.
- `structured_output_mode="server_json"` yalnız LaTeX üretmeyen kısa çağrılar içindir; structured-output hatasında bir kez `response_format` olmadan tekrar dener.

## Fallback ve exit

- Fallback satırı = retry marker (boş/`Summary unavailable.` çıktı). Veri bozulması değildir.
- `pipeline`: varsayılan strict. `fallback>0` veya `failed>0` → `EXIT=2`; embed/export çalışmaz.
- `enrich`: varsayılan resume. `EXIT=0`; fallback satırları sonraki koşumda yeniden seçilir.
- `--strict` / `--allow-fallback` ile override.
- Her koşum sonunda: `ELEKTOR_RESULT={"enriched":N,"fallback":M,"skipped":K,"failed":F,"strict":true|false}`.

## Unload

`unload_ollama_model` yalnız hedef hostta native yüklü modeli boşaltır. Uzak analyzer adına OCR hostuna `keep_alive:0` gönderilmez; yerel OCR modelinin unload'u korunur.

## Token katmanı

- Boş `output` / DPO `chosen`/`rejected` satırı üretilmez.
- Eğitilebilir maskesi olmayan (zero-mask) satır üretilmez.
- `n_completion_tokens` mevcut span anlamını korur; `n_trainable_tokens=sum(loss_mask)` eklenir.

## API / UI

- `/api/health`: `providers.analyzer` ve `providers.ocr` (kind, online, yetenekler).
- `/api/pipeline/status`: `result` alanı; `exit_code=2` → `status=failed`.
- `/api/pipeline/run`: `strict` / `allow_fallback`; uzak analyzer + `shards>1` → HTTP 400.
- UI: sonuç bandı, run hatası, ayrı analyzer/OCR rozetleri, Strata'da sharding kapalı.
- `analyzer_max_tokens` bir **veri seti çıktı bütçesi**dir; model bağlam penceresi değildir (`compact=4096`, `rich=8192/16384`).
