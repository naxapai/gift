#!/bin/zsh
set -u

cd '/Users/nexapai/Downloads/подарки' || exit 1

LOG_FILE="/tmp/fragment_sync_watch.log"
PID_FILE="/tmp/fragment_sync_watch.pid"
MAX_SYNC_SEC="${MAX_SYNC_SEC:-900}"
LOOP_SLEEP_SEC="${LOOP_SLEEP_SEC:-25}"

if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
  if [ -n "${OLD_PID:-}" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] watcher_already_running pid=$OLD_PID" >> "$LOG_FILE"
    exit 0
  fi
fi

echo $$ > "$PID_FILE"
cleanup() {
  rm -f "$PID_FILE"
}
trap cleanup EXIT INT TERM

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] watcher_start" >> "$LOG_FILE"

while true; do
  DNS_OK=0
  python3 - <<'PY' >/dev/null 2>&1
import socket,sys
try:
    socket.gethostbyname("fragment.com")
    sys.exit(0)
except Exception:
    sys.exit(1)
PY
  DNS_OK=$?

  if [ "$DNS_OK" -eq 0 ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] dns_ok run_sync" >> "$LOG_FILE"
    START_TS=$(date +%s)
    FRAGMENT_SSL_NO_VERIFY=true \
    FRAGMENT_GIFTS_URL=https://fragment.com/gifts \
    FRAGMENT_MAX_PAGES_PER_COLLECTION=120 \
    FRAGMENT_ENRICH_LOT_TRAITS=true \
    FRAGMENT_LOT_DETAIL_WORKERS=12 \
    FRAGMENT_BATCH_SIZE=8 \
    FRAGMENT_BATCH_RETRIES=6 \
    FRAGMENT_RESUME=true \
    FRAGMENT_SYNC_STATE_FILE=data/fragment_sync_state.json \
    VERIFIED_API_TIMEOUT_SEC=20 \
    VERIFIED_DATA_FILE=data/verified_gifts.json \
    python3 -u sync_fragment_batches.py >> "$LOG_FILE" 2>&1 &
    SYNC_PID=$!

    while kill -0 "$SYNC_PID" 2>/dev/null; do
      NOW_TS=$(date +%s)
      ELAPSED=$((NOW_TS - START_TS))
      if [ "$ELAPSED" -ge "$MAX_SYNC_SEC" ]; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] sync_timeout pid=$SYNC_PID elapsed=${ELAPSED}s" >> "$LOG_FILE"
        kill -TERM "$SYNC_PID" 2>/dev/null || true
        sleep 2
        kill -KILL "$SYNC_PID" 2>/dev/null || true
        break
      fi
      sleep 5
    done
    wait "$SYNC_PID" 2>/dev/null
    SYNC_EXIT=$?
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] sync_exit code=$SYNC_EXIT" >> "$LOG_FILE"

    python3 - <<'PY' >> "$LOG_FILE" 2>&1
import json
from pathlib import Path
p=Path("data/verified_gifts.json")
if not p.exists():
    print("snapshot_missing")
else:
    j=json.loads(p.read_text(encoding="utf-8"))
    print("snapshot", {
        "generated_at": j.get("generated_at"),
        "gifts": len(j.get("gifts") or []),
        "collections": len((j.get("filters") or {}).get("collections") or []),
        "models": len((j.get("filters") or {}).get("models") or {}),
        "backdrops": len((j.get("filters") or {}).get("backdrops") or {}),
        "symbols": len((j.get("filters") or {}).get("symbols") or {}),
    })
PY
  else
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] dns_unavailable" >> "$LOG_FILE"
  fi

  sleep "$LOOP_SLEEP_SEC"
done
