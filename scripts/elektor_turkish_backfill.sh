#!/usr/bin/env bash
# One-time Turkish backfill for already English-enriched Elektor articles.
# Usage: elektor_turkish_backfill.sh [START] [END] [BATCH]
# The nightly lock is shared, so a nightly run cannot overlap this backfill.
set -uo pipefail

ROOT="/home/onkanat/Git/elektor"
PY="$ROOT/.venv/bin/python"
CONFIG="$ROOT/projects_macair-teknik-nightly.json"
ENV_FILE="/home/onkanat/.config/aikon/elektor-strata.env"
LOG_DIR="$ROOT/logs/nightly"
LOG="$LOG_DIR/turkish-backfill-$(date +%Y%m%d).log"
LOCK="$ROOT/.elektor-nightly.lock"
STRATA_URL="http://192.168.1.105:8080/v1/models"

START="${1:-0}"
END="${2:-800}"
BATCH="${3:-25}"

mkdir -p "$LOG_DIR"
exec 9>"$LOCK"
if ! flock -n 9; then
    echo "$(date '+%F %T %z') another Elektor run holds the lock; exiting" >> "$LOG"
    exit 0
fi
exec >> "$LOG" 2>&1
cd "$ROOT" || exit 1

set -a
. "$ENV_FILE"
set +a

echo "===== $(date '+%F %T %z') Turkish backfill start range [$START:$END] batch=$BATCH ====="
if [ -z "${STRATA_API_KEY:-}" ]; then
    echo "STRATA_API_KEY is not set"
    exit 1
fi
if ! curl -fsS -m 15 -H "Authorization: Bearer $STRATA_API_KEY" "$STRATA_URL" >/dev/null; then
    echo "Strata health check failed; refusing to start"
    exit 1
fi
echo "Strata health OK"

for ((S=START; S<END; S+=BATCH)); do
    E=$((S + BATCH))
    if [ "$E" -gt "$END" ]; then E=$END; fi
    echo "--- turkish range [$S:$E] at $(date '+%F %T') ---"
    timeout 45m "$PY" run.py --config "$CONFIG" enrich --limit "$S:$E" --pass turkish
    RC=$?
    if [ "$RC" -ne 0 ]; then
        echo "Turkish enrich failed/timeout rc=$RC at range [$S:$E]; stopping for retry"
        exit "$RC"
    fi
done

echo "--- backfill ranges complete; exporting at $(date '+%F %T') ---"
"$PY" run.py --config "$CONFIG" export
RC=$?
if [ "$RC" -ne 0 ]; then
    echo "export failed rc=$RC"
    exit "$RC"
fi
echo "===== $(date '+%F %T %z') Turkish backfill complete ====="
