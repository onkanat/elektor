#!/usr/bin/env bash
# Elektor embed — parçalı koşu (CPU fan koruması).
# Kural (kullanıcı, 16.11.2026): 30 dk iş + 5 dk bekleme; tek turda LIMIT makale.
# Durum: articles.is_embedded üzerinden ilerler → kesilse de kaldığı yerden devam eder.
set -uo pipefail

ROOT="/home/onkanat/Git/elektor"
PY="$ROOT/.venv/bin/python"
CONFIG="$ROOT/projects_macair-teknik-nightly.json"
DB="$ROOT/database/macair-teknik.db"
LOG_DIR="$ROOT/logs/embed"
LOG="$LOG_DIR/$(date +%Y%m%d).log"
LOCK="$ROOT/.elektor-embed.lock"

LIMIT="${LIMIT:-150}"        # tur başına makale
MAX_SEC="${MAX_SEC:-1800}"   # tur süresi (30 dk)
SLEEP="${SLEEP:-300}"        # turlar arası bekleme (5 dk)
MAX_TUR="${MAX_TUR:-0}"      # 0 = kalan bitene kadar
WINDOW_END="${WINDOW_END:-0}" # 0 = pencere kısıtı yok; 8 = saat >=8 olunca yeni tur açma
LABEL="${LABEL:-embed-parcali}"

mkdir -p "$LOG_DIR"
exec 9>"$LOCK"
if ! flock -w 60 9; then
    echo "$(date '+%F %T %z') başka bir embed koşusu kilidi tutuyor; çıkılıyor" >> "$LOG"
    exit 0
fi
exec >> "$LOG" 2>&1

kalan() { sqlite3 "$DB" "select count(*) from articles where is_embedded = 0;" 2>/dev/null || echo 0; }

echo "===== $(date '+%F %T %z') $LABEL başladı · kalan=$(kalan) · LIMIT=$LIMIT MAX_SEC=$MAX_SEC SLEEP=$SLEEP MAX_TUR=$MAX_TUR WINDOW_END=$WINDOW_END"

tur=0
while :; do
    k=$(kalan)
    if [ "${k:-0}" -le 0 ]; then
        echo "$(date '+%F %T') kalan 0 — iş bitti"
        break
    fi
    if [ "$MAX_TUR" -gt 0 ] && [ "$tur" -ge "$MAX_TUR" ]; then
        echo "$(date '+%F %T') tur sınırı ($MAX_TUR) doldu; kalan=$k"
        break
    fi
    if [ "$WINDOW_END" -gt 0 ]; then
        HOUR=$((10#$(date +%H)))
        if [ "$HOUR" -ge "$WINDOW_END" ]; then
            echo "$(date '+%F %T') pencere kapandı (saat $HOUR >= $WINDOW_END); kalan=$k"
            break
        fi
    fi

    tur=$((tur + 1))
    echo "--- tur $tur · kalan $k · limit $LIMIT · $(date '+%F %T') ---"
    timeout "$MAX_SEC" "$PY" run.py --config "$CONFIG" embed --limit "$LIMIT" \
        | grep -vE "FutureWarning|warnings.warn|UserWarning|create_payload_index"
    rc=${PIPESTATUS[0]}
    k2=$(kalan)
    echo "tur $tur bitti · rc=$rc · kalan $k2 · $(date '+%F %T')"
    [ "${k2:-0}" -le 0 ] && break
    if [ "$MAX_TUR" -gt 0 ] && [ "$tur" -ge "$MAX_TUR" ]; then continue; fi
    echo "fan soğuma: ${SLEEP}s bekleniyor"
    sleep "$SLEEP"
done

echo "===== $(date '+%F %T %z') $LABEL bitti · kalan=$(kalan)"
