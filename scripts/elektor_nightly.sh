#!/usr/bin/env bash
# Elektor technical-corpus nightly batch.
# Schedule: weekdays 02:00-07:00, weekends 00:00-08:00 (Pi local time).
set -uo pipefail

ROOT="/home/onkanat/Git/elektor"
PY="$ROOT/.venv/bin/python"
CONFIG="$ROOT/projects_macair-teknik-nightly.json"
ENV_FILE="/home/onkanat/.config/aikon/elektor-strata.env"
LOG_DIR="$ROOT/logs/nightly"
LOG="$LOG_DIR/$(date +%Y%m%d).log"
LOCK="$ROOT/.elektor-nightly.lock"
STATE="$ROOT/database/macair-teknik.nightly.next"
DONE_FILE="$ROOT/database/macair-teknik.nightly.done"
BATCH_SIZE=25
STRATA_URL="http://192.168.1.105:8080/v1/models"

mkdir -p "$LOG_DIR"
touch "$LOG"
exec 9>"$LOCK"
if ! flock -n 9; then
    echo "$(date '+%F %T %z') another nightly run is active; exiting" >> "$LOG"
    exit 0
fi
exec >> "$LOG" 2>&1

echo "===== $(date '+%F %T %z') nightly start ====="
cd "$ROOT" || exit 1
set -a
. "$ENV_FILE"
set +a

if ! command -v "$PY" >/dev/null 2>&1; then
    echo "Python venv missing: $PY"
    exit 1
fi
if [ ! -f "$CONFIG" ]; then
    echo "Config missing: $CONFIG"
    exit 1
fi
if [ -z "${STRATA_API_KEY:-}" ]; then
    echo "STRATA_API_KEY is not set"
    exit 1
fi

# Stop new batches at the end of the approved window. A batch that is already
# running is allowed to finish; the next cron run resumes from the state file.
DOW=$(date +%u)
if [ "$DOW" -ge 6 ]; then END_HOUR=8; else END_HOUR=7; fi
HOUR=$((10#$(date +%H)))

if ! curl -fsS -m 15 -H "Authorization: Bearer $STRATA_API_KEY" "$STRATA_URL" >/dev/null; then
    echo "Strata health check failed; refusing to start"
    exit 1
fi
echo "Strata health OK; window ends at ${END_HOUR}:00"

if [ "${1:-}" = "--check" ]; then
    echo "check mode: config, env, lock and Strata health OK"
    exit 0
fi

article_count() {
    "$PY" - "$ROOT/database/macair-teknik.db" <<'PY'
import sqlite3, sys
from pathlib import Path
p = Path(sys.argv[1])
if not p.exists():
    print(0)
    raise SystemExit
try:
    c = sqlite3.connect(str(p))
    print(c.execute("select count(*) from articles").fetchone()[0])
except Exception:
    print(0)
PY
}

TOTAL=$(article_count)
if [ "$TOTAL" -eq 0 ]; then
    echo "No articles yet; running full filtered extraction (max 3h)..."
    timeout 3h "$PY" run.py --config "$CONFIG" extract
    rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "extract failed/timeout rc=$rc"
        exit "$rc"
    fi
    TOTAL=$(article_count)
fi
if [ "$TOTAL" -le 0 ]; then
    echo "Extraction produced zero articles; check input/config"
    exit 1
fi

if [ -f "$DONE_FILE" ]; then
    echo "Nightly corpus already marked done ($TOTAL articles); exiting"
    exit 0
fi

NEXT=0
if [ -f "$STATE" ]; then
    NEXT=$(tr -cd '0-9' < "$STATE")
    [ -n "$NEXT" ] || NEXT=0
fi
echo "articles=$TOTAL next_start=$NEXT batch_size=$BATCH_SIZE"

while [ "$NEXT" -lt "$TOTAL" ]; do
    HOUR=$((10#$(date +%H)))
    if [ "$HOUR" -ge "$END_HOUR" ]; then
        echo "window ended at hour $HOUR; stopping before next batch"
        break
    fi

    END=$((NEXT + BATCH_SIZE))
    if [ "$END" -gt "$TOTAL" ]; then END=$TOTAL; fi
    echo "--- enrich range [$NEXT:$END] at $(date '+%F %T') ---"
    timeout 45m "$PY" run.py --config "$CONFIG" enrich --limit "$NEXT:$END" --pass all
    rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "enrich failed/timeout rc=$rc at range [$NEXT:$END]; state kept for retry"
        exit "$rc"
    fi
    NEXT=$END
    printf '%s\n' "$NEXT" > "$STATE.tmp"
    mv "$STATE.tmp" "$STATE"
done

if [ "$NEXT" -ge "$TOTAL" ]; then
    echo "--- all articles processed; exporting ---"
    "$PY" run.py --config "$CONFIG" export
    rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "export failed rc=$rc"
        exit "$rc"
    fi
    # Token layer is a validation artifact; do not fail the nightly job if the
    # tokenizer cannot be fetched.
    timeout 30m "$PY" run.py --config "$CONFIG" tokens \
        --project macair-teknik \
        --tokenizer Qwen/Qwen2.5-0.5B-Instruct \
        --max-len 4096 || echo "token layer skipped/failed (non-fatal)"
    touch "$DONE_FILE"
    echo "nightly corpus complete"
fi

echo "===== $(date '+%F %T %z') nightly end ====="
