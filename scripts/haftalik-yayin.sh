#!/usr/bin/env bash
# Elektor haftalık dataset yayını — PROJE BAŞINA AKIŞ (v2).
# Kaynak modeli: ~/PDF/<klasör> = bir proje. Sürücü her klasörü kendi marker'ıyla izler:
#   • klasörde marker'dan yeni dosya varsa → proje yoksa OLUŞTUR, seç, tüm aşamaları koştur, yayınla.
#   • yeni dosya yoksa o projeyi ATLA (ATLANDI satırı). Marker yalnız başarılı yayında dokunulur.
# Kapılar: (0) ollama erişilemezse görünürlüğü bozmadan dur (1) yeni kaynak yoksa atla
#          (2) export bu koşuda üretilmemişse push yok. Ajan yok — LLM yalnız enrich adımının kendi (ECE).
set -u
unset PYTHONPATH  # ajan kabuk sızıntısı temizliği (ölçüldü 04.11: 3.14 site-packages PIL'i kırıyor)

REPO="$HOME/Git/elektor"
PY="$REPO/.venv/bin/python"
CLI="python3 $HOME/.hermes/shared-skills/data/elektor-dataset-pipeline/scripts/elektor_hermes_cli.py"
LOG="$HOME/.hermes/aikonsol/elektor-haftalik.log"
PDF_KOK="$HOME/PDF"
YAYIN_REMOTE="git@pi516G01.local:/mnt/nvme/git_repo/elektor.git"
YAYIN_DAL="datasets"

ts() { date '+%F %H:%M:%S'; }
log() { local l="[$(ts)] $*"; echo "$l" >> "$LOG"; echo "$l"; }

cd "$REPO" || { log "HATA: repo yok: $REPO"; exit 1; }

# Kapı 0: altyapı ayakta mı
OLLAMA_URL="$("$PY" -c 'import json;print(json.load(open("config.json"))["ollama_url"])' 2>>"$LOG")"
if ! curl -s --max-time 8 -o /dev/null "$OLLAMA_URL/api/tags"; then
    log "HATA: ollama erişilemez: $OLLAMA_URL — durduruldu (markerlara dokunulmadı)"
    exit 1
fi
# Kapı 0b: Elektor API (proje oluşturma/seçme bu ucu kullanır; list'in dosya-fallback'i create'te yok)
if ! curl -s --max-time 8 -o /dev/null http://127.0.0.1:3456/api/health; then
    log "HATA: Elektor API kapalı (127.0.0.1:3456) — elektor-api.service çalışmıyor mu?"
    exit 1
fi

adim() {  # mevcut seçili proje için bir pipeline aşaması; başarısızsa HATA bayrağı + proje atlanır
    log "  [$PROJE] ADIM: $1"
    if ! "$PY" run.py "$1" >> "$LOG" 2>&1; then
        log "HATA: [$PROJE] $1 başarısız — proje atlandı (marker dokunulmadı)"
        HATA=1
        return 1
    fi
}

# Klasör → proje eşlemesi: projects_*.json içindeki input_path eşleşmesinden;
# yoksa klasör adından YENİ proje oluştur (input_mode=folder).
proje_bul() {  # $1=klasör yolu → stdout: project_id (boşsa yok)
    "$PY" - "$1" <<'PYEOF'
import glob, json, os, sys
klasor = os.path.abspath(sys.argv[1])
for p in glob.glob("projects_*.json"):
    try:
        c = json.load(open(p))
        if os.path.abspath(c.get("input_path", "")) == klasor:
            print(c.get("project_id") or p[len("projects_"):-len(".json")])
            break
    except Exception:
        pass
PYEOF
}

YAYIN_GEREKLI=0
HATA=0

for KLASOR in "$PDF_KOK"/*/; do
    [ -d "$KLASOR" ] || continue
    AD=$(basename "$KLASOR")
    MARKER="$REPO/.haftalik-$AD"
    KAYNAK=$(find "$KLASOR" -type f -newer "$MARKER" 2>/dev/null | head -1 || true)
    if [ -f "$MARKER" ] && [ -z "$KAYNAK" ]; then
        log "ATLANDI: yeni kaynak yok ($AD)"
        continue
    fi
    log "BAŞLADI: $AD · kaynak: ${KAYNAK:-ilk koşu (marker yok)}"

    PROJE=$(proje_bul "$KLASOR")
    if [ -z "$PROJE" ]; then
        PROJE=$(echo "$AD" | tr -c 'a-zA-Z0-9-' '-' | sed 's/-\{2,\}/-/g; s/-*$//')
        log "  [$PROJE] yeni proje oluşturuluyor (kaynak: $KLASOR)"
        $CLI projects create --project-id "$PROJE" --project-name "$PROJE" \
            --input-mode folder --pdf-source "$KLASOR" >> "$LOG" 2>&1 || {
            log "HATA: proje oluşturulamadı: $PROJE"; HATA=1; continue; }
    fi
    $CLI projects select --project-id "$PROJE" >> "$LOG" 2>&1 || { log "HATA: seçilemedi: $PROJE"; HATA=1; continue; }
    log "  [$PROJE] aktif"

    adim extract    || { HATA=1; continue; }
    adim enrich     || { HATA=1; continue; }
    adim embed      || { HATA=1; continue; }
    adim clean_boilerplate || { HATA=1; continue; }
    adim export     || { HATA=1; continue; }

    EXPORTS="$REPO/exports/$PROJE"
    TAZE=$(find "$EXPORTS" -maxdepth 1 -name '*.jsonl' -mmin -240 2>/dev/null | wc -l)
    SATIR=$(cat "$EXPORTS"/*.jsonl 2>/dev/null | wc -l)
    # BOŞ export = başarısız koşu (ölçüldü 05.11: kaynakta çıkarılabilir doküman yoksa 7 taze ama 0 satır üretiliyor)
    if [ "$TAZE" -lt 1 ] || [ "$SATIR" -lt 1 ]; then
        log "HATA: [$PROJE] export boş ya da taze değil ($TAZE jsonl · $SATIR satır) — yayınlanmadı (marker dokunulmadı)"
        HATA=1
        continue
    fi
    log "  [$PROJE] export: $TAZE taze jsonl · $SATIR satır"

    touch "$MARKER"
    YAYIN_GEREKLI=1
done

# Yayın: yetim dal — tüm projelerin GÜNCEL export anlık görüntüsü (kod dalına dokunmaz)
if [ "$YAYIN_GEREKLI" -ne 1 ]; then
    log "BİTİŞ: yayınlanacak taze proje yok (hata=$HATA)"
    [ "$HATA" -eq 0 ] || exit 1
    exit 0
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
git init -q "$TMP"
for D in "$REPO"/exports/*/; do
    [ -d "$D" ] || continue
    P=$(basename "$D")
    # Yalnız VERİSİ OLAN projeler yayınlanır (boş/test kalıntıları dala girmez — ölçüldü 05.11)
    N=$(cat "$D"/*.jsonl 2>/dev/null | wc -l)
    if [ "$N" -lt 1 ]; then log "  [yayın] ATLANDI (boş): $P"; continue; fi
    mkdir -p "$TMP/$P"; cp -a "$D"/. "$TMP/$P"/
done
PROJELER=$(ls -d "$TMP"/*/ 2>/dev/null | xargs -n1 basename | tr '\n' ' ')
printf 'Elektor dataset yayını (projeler: %s)\ntarih: %s\n' "$PROJELER" "$(date '+%F %H:%M')" > "$TMP/YAYIN.md"
git -C "$TMP" add -A
git -C "$TMP" -c user.name='Aikonsol' -c user.email='Aikonsol@delinux01.local' \
    commit -qm "dataset: $(date '+%F') · projeler: $PROJELER"
if ! git -C "$TMP" push -q --force "$YAYIN_REMOTE" "HEAD:refs/heads/$YAYIN_DAL" >> "$LOG" 2>&1; then
    log "HATA: datasets dalına push başarısız — markerlar güncel ama yayına ulaşmadı"
    exit 1
fi
SHA=$(git -C "$TMP" rev-parse --short HEAD)
log "OK: yayımlandı $SHA → $YAYIN_REMOTE ($YAYIN_DAL) · projeler: $PROJELER"
[ "$HATA" -eq 0 ] || exit 1
exit 0