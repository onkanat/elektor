#!/usr/bin/env bash
# Elektor haftalık dataset yayını — yeni kaynak → boru hattı → export → datasets dalı (pi516G01).
# Deterministik: LLM ajanı yok; zenginleştirme boru hattının kendi enrich adımıdır (ECE ollama).
# Kapılar: (0) ollama erişilemezse görünür başarısızlık (1) yeni kaynak yoksa ATLA
#          (2) export bu koşuda üretilmemişse push yok. Marker yalnız başarılı yayında dokunulur.
set -u
unset PYTHONPATH  # ajan kabuk sızıntısı temizliği (ölçüldü 04.11: 3.14 site-packages PIL'i kırıyor)

REPO="$HOME/Git/elektor"
PY="$REPO/.venv/bin/python"
LOG="$HOME/.hermes/aikonsol/elektor-haftalik.log"
MARKER="$REPO/.haftalik-son-kaynak"
YAYIN_REMOTE="git@pi516G01.local:/mnt/nvme/git_repo/elektor.git"
YAYIN_DAL="datasets"

ts() { date '+%F %H:%M:%S'; }
log() { local l="[$(ts)] $*"; echo "$l" >> "$LOG"; echo "$l"; }

cd "$REPO" || { log "HATA: repo yok: $REPO"; exit 1; }

INPUT="$("$PY" -c 'import json;print(json.load(open("config.json"))["input_path"])' 2>>"$LOG")"
PROJ="$("$PY" -c 'import json;print(json.load(open("config.json"))["project_id"])' 2>>"$LOG")"
EXPORTS="$REPO/exports/$PROJ"
OLLAMA_URL="$("$PY" -c 'import json;print(json.load(open("config.json"))["ollama_url"])' 2>>"$LOG")"

# Kapı 0: altyapı ayakta mı
if ! curl -s --max-time 8 -o /dev/null "$OLLAMA_URL/api/tags"; then
    log "HATA: ollama erişilemez: $OLLAMA_URL — durduruldu (marker dokunulmadı; sonraki koşu yeniden dener)"
    exit 1
fi

# Kapı 1: yeni kaynak var mı
if [ ! -d "$INPUT" ]; then log "HATA: kaynak klasörü yok: $INPUT"; exit 1; fi
YENI=$(find "$INPUT" -type f -newer "$MARKER" 2>/dev/null | head -1 || true)
if [ -f "$MARKER" ] && [ -z "$YENI" ]; then
    log "ATLANDI: yeni kaynak yok ($INPUT)"
    exit 0
fi
log "BAŞLADI: proje=$PROJ · kaynak: ${YENI:-ilk koşu (marker yok)}"

# Aşamalar — herbiri rc=0 dönmeli; aksi halde görünürlüğü bozmadan dur
adim() {
    log "  ADIM: $1"
    if ! "$PY" run.py "$1" >> "$LOG" 2>&1; then
        log "HATA: $1 başarısız — yayında durduruldu (marker dokunulmadı)"
        exit 1
    fi
}
adim extract
adim enrich
adim embed
adim clean_boilerplate
adim export

# Kapı 2: export bu koşuda üretilmiş mi (son 4 saatte taze jsonl)
TAZE=$(find "$EXPORTS" -maxdepth 1 -name '*.jsonl' -mmin -240 2>/dev/null | wc -l)
if [ "$TAZE" -lt 1 ]; then
    log "HATA: export taze değil ($EXPORTS) — push yapılmadı"
    exit 1
fi
SATIR=$(cat "$EXPORTS"/*.jsonl 2>/dev/null | wc -l)
log "  export: $TAZE taze jsonl · toplam $SATIR satır"

# Yayın: yetim dal — pi516G01 elektor.git 'datasets' (kod dalına dokunmaz)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
git init -q "$TMP"
cp -a "$EXPORTS"/. "$TMP"/
printf 'Elektor dataset yayını\nproje: %s\ntarih: %s\nsatır: %s\nkaynak: %s\n' \
    "$PROJ" "$(date '+%F %H:%M')" "$SATIR" "${YENI:-mevcut korpus}" > "$TMP/YAYIN.md"
git -C "$TMP" add -A
git -C "$TMP" -c user.name='Aikonsol' -c user.email='Aikonsol@delinux01.local' \
    commit -qm "dataset: $(date '+%F') · $PROJ · $SATIR satır"
if ! git -C "$TMP" push -q --force "$YAYIN_REMOTE" "HEAD:refs/heads/$YAYIN_DAL" >> "$LOG" 2>&1; then
    log "HATA: datasets dalına push başarısız ($YAYIN_REMOTE)"
    exit 1
fi
SHA=$(git -C "$TMP" rev-parse --short HEAD)

touch "$MARKER"
log "OK: yayımlandı $SHA → $YAYIN_REMOTE ($YAYIN_DAL) · $SATIR satır"