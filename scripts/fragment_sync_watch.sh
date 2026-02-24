#!/bin/zsh
set -u

cd '/Users/nexapai/Downloads/подарки' || exit 1

# Optional local overrides (API keys, feature toggles).
if [ -f ".env.local" ]; then
  set -a
  source ".env.local"
  set +a
fi

if [ "${FRAGMENT_RESERVE_SYNC_ENABLED:-true}" != "true" ] && [ "${FRAGMENT_RESERVE_SYNC_ENABLED:-true}" != "1" ]; then
  exit 0
fi

LOG_FILE="/tmp/fragment_sync_watch.log"
PID_FILE="/tmp/fragment_sync_watch.pid"
FAST_LOOP_SLEEP_SEC="${FAST_LOOP_SLEEP_SEC:-180}"
FULL_SYNC_EVERY_SEC="${FULL_SYNC_EVERY_SEC:-3600}"
MAX_SYNC_SEC_FAST="${MAX_SYNC_SEC_FAST:-720}"
MAX_SYNC_SEC_FULL="${MAX_SYNC_SEC_FULL:-1500}"
BACKOFF_BASE_SEC="${BACKOFF_BASE_SEC:-60}"
BACKOFF_MAX_SEC="${BACKOFF_MAX_SEC:-1800}"
FAIL_STREAK=0
LAST_FULL_TS_FILE="/tmp/fragment_sync_last_full.ts"

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

next_mode() {
  NOW_TS=$(date +%s)
  LAST_FULL_TS=0
  if [ -f "$LAST_FULL_TS_FILE" ]; then
    LAST_FULL_TS=$(cat "$LAST_FULL_TS_FILE" 2>/dev/null || echo 0)
  fi
  if [ -z "${LAST_FULL_TS:-}" ]; then
    LAST_FULL_TS=0
  fi
  if [ $((NOW_TS - LAST_FULL_TS)) -ge "$FULL_SYNC_EVERY_SEC" ]; then
    echo "FULL"
  else
    echo "FAST"
  fi
}

run_sync_mode() {
  MODE="$1"
  START_TS=$(date +%s)

  if [ "$MODE" = "FULL" ]; then
    MODE_MAX_SYNC_SEC="$MAX_SYNC_SEC_FULL"
    MODE_MAX_PAGES="${FULL_MAX_PAGES_PER_COLLECTION:-120}"
    MODE_INCLUDE_SOLD="${FULL_INCLUDE_SOLD:-true}"
    MODE_ENRICH_TRAITS="${FULL_ENRICH_LOT_TRAITS:-true}"
    MODE_DETAIL_WORKERS="${FULL_LOT_DETAIL_WORKERS:-10}"
    MODE_FETCH_BUDGET_SEC="${FULL_FETCH_BUDGET_SEC:-1400}"
    MODE_MIN_REQ_INTERVAL="${FULL_MIN_REQUEST_INTERVAL_SEC:-0.18}"
    MODE_REQ_JITTER="${FULL_REQUEST_JITTER_SEC:-0.06}"
  else
    MODE_MAX_SYNC_SEC="$MAX_SYNC_SEC_FAST"
    MODE_MAX_PAGES="${FAST_MAX_PAGES_PER_COLLECTION:-18}"
    MODE_INCLUDE_SOLD="${FAST_INCLUDE_SOLD:-false}"
    MODE_ENRICH_TRAITS="${FAST_ENRICH_LOT_TRAITS:-false}"
    MODE_DETAIL_WORKERS="${FAST_LOT_DETAIL_WORKERS:-4}"
    MODE_FETCH_BUDGET_SEC="${FAST_FETCH_BUDGET_SEC:-420}"
    MODE_MIN_REQ_INTERVAL="${FAST_MIN_REQUEST_INTERVAL_SEC:-0.32}"
    MODE_REQ_JITTER="${FAST_REQUEST_JITTER_SEC:-0.12}"
  fi

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] dns_ok run_sync mode=$MODE pages=$MODE_MAX_PAGES include_sold=$MODE_INCLUDE_SOLD enrich=$MODE_ENRICH_TRAITS" >> "$LOG_FILE"
  FRAGMENT_SSL_NO_VERIFY=true \
  FRAGMENT_GIFTS_URL=https://fragment.com/gifts \
  FRAGMENT_MAX_PAGES_PER_COLLECTION="$MODE_MAX_PAGES" \
  FRAGMENT_INCLUDE_SOLD="$MODE_INCLUDE_SOLD" \
  FRAGMENT_ENRICH_LOT_TRAITS="$MODE_ENRICH_TRAITS" \
  FRAGMENT_LOT_DETAIL_WORKERS="$MODE_DETAIL_WORKERS" \
  FRAGMENT_FETCH_BUDGET_SEC="$MODE_FETCH_BUDGET_SEC" \
  FRAGMENT_MIN_REQUEST_INTERVAL_SEC="$MODE_MIN_REQ_INTERVAL" \
  FRAGMENT_REQUEST_JITTER_SEC="$MODE_REQ_JITTER" \
  FRAGMENT_REQUEST_RETRIES="${FRAGMENT_REQUEST_RETRIES:-3}" \
  FRAGMENT_REQUEST_BACKOFF_SEC="${FRAGMENT_REQUEST_BACKOFF_SEC:-0.8}" \
  FRAGMENT_BATCH_SIZE="${FRAGMENT_BATCH_SIZE:-8}" \
  FRAGMENT_BATCH_RETRIES="${FRAGMENT_BATCH_RETRIES:-6}" \
  FRAGMENT_RESUME=true \
  FRAGMENT_SYNC_STATE_FILE=data/fragment_sync_state.json \
  VERIFIED_API_TIMEOUT_SEC=20 \
  VERIFIED_DATA_FILE=data/verified_gifts.json \
  python3 -u sync_fragment_batches.py >> "$LOG_FILE" 2>&1 &
  SYNC_PID=$!

  while kill -0 "$SYNC_PID" 2>/dev/null; do
    NOW_TS=$(date +%s)
    ELAPSED=$((NOW_TS - START_TS))
    if [ "$ELAPSED" -ge "$MODE_MAX_SYNC_SEC" ]; then
      echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] sync_timeout mode=$MODE pid=$SYNC_PID elapsed=${ELAPSED}s limit=${MODE_MAX_SYNC_SEC}s" >> "$LOG_FILE"
      kill -TERM "$SYNC_PID" 2>/dev/null || true
      sleep 2
      kill -KILL "$SYNC_PID" 2>/dev/null || true
      break
    fi
    sleep 5
  done
  wait "$SYNC_PID" 2>/dev/null
  SYNC_EXIT=$?
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] sync_exit mode=$MODE code=$SYNC_EXIT" >> "$LOG_FILE"

  if [ "$SYNC_EXIT" -eq 0 ]; then
    FAIL_STREAK=0
    if [ "$MODE" = "FULL" ]; then
      date +%s > "$LAST_FULL_TS_FILE"
    fi
  else
    FAIL_STREAK=$((FAIL_STREAK + 1))
  fi

  python3 - <<'PY' >> "$LOG_FILE" 2>&1
import json
from pathlib import Path
p=Path("data/verified_gifts.json")
if not p.exists():
    print("snapshot_missing")
else:
    j=json.loads(p.read_text(encoding="utf-8"))
    m=j.get("meta") if isinstance(j,dict) else {}
    print("snapshot", {
        "generated_at": j.get("generated_at"),
        "gifts": len(j.get("gifts") or []),
        "collections": len((j.get("filters") or {}).get("collections") or []),
        "models": len((j.get("filters") or {}).get("models") or {}),
        "backdrops": len((j.get("filters") or {}).get("backdrops") or {}),
        "symbols": len((j.get("filters") or {}).get("symbols") or {}),
        "meta_total_for_sale": (m or {}).get("total_for_sale"),
        "meta_total_sold": (m or {}).get("total_sold"),
    })
PY
}

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
    MODE=$(next_mode)
    run_sync_mode "$MODE"
  else
    FAIL_STREAK=$((FAIL_STREAK + 1))
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] dns_unavailable fail_streak=$FAIL_STREAK" >> "$LOG_FILE"
  fi

  BACKOFF_SEC=$((BACKOFF_BASE_SEC * (2 ** (FAIL_STREAK > 5 ? 5 : FAIL_STREAK))))
  if [ "$BACKOFF_SEC" -gt "$BACKOFF_MAX_SEC" ]; then
    BACKOFF_SEC="$BACKOFF_MAX_SEC"
  fi
  NEXT_SLEEP="$FAST_LOOP_SLEEP_SEC"
  if [ "$BACKOFF_SEC" -gt "$NEXT_SLEEP" ]; then
    NEXT_SLEEP="$BACKOFF_SEC"
  fi
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] watcher_sleep sec=$NEXT_SLEEP fail_streak=$FAIL_STREAK" >> "$LOG_FILE"
  sleep "$NEXT_SLEEP"
done
