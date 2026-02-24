#!/bin/zsh
set -u

cd '/Users/nexapai/Downloads/подарки' || exit 1

# Optional local overrides (API keys, model, timeouts).
if [ -f ".env.local" ]; then
  set -a
  source ".env.local"
  set +a
fi

LOG_FILE="/tmp/server_watchdog.log"
PID_FILE="/tmp/server_watchdog.pid"
SERVER_LOG="/tmp/gifts_local_8080.log"
CHECK_URL="${SERVER_CHECK_URL:-http://127.0.0.1:8080/healthz}"
CHECK_INTERVAL_SEC="${SERVER_CHECK_INTERVAL_SEC:-5}"
MAX_FAILS="${SERVER_MAX_FAILS:-3}"

if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
  if [ -n "${OLD_PID:-}" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] watchdog_already_running pid=$OLD_PID" >> "$LOG_FILE"
    exit 0
  fi
fi

echo $$ > "$PID_FILE"
cleanup() {
  rm -f "$PID_FILE"
}
trap cleanup EXIT INT TERM

start_server() {
  VERIFIED_SOURCE_RUNTIME="${VERIFIED_SOURCE:-hybrid}"
  VERIFIED_REFRESH_RUNTIME="${VERIFIED_REFRESH_SEC:-300}"
  INGEST_INTERVAL_RUNTIME="${INGEST_INTERVAL_SEC:-300}"
  DATA_STALE_RUNTIME="${DATA_STALE_SEC:-900}"
  FRAGMENT_MAX_COLLECTIONS_RUNTIME="${FRAGMENT_MAX_COLLECTIONS:-0}"
  FRAGMENT_MAX_PAGES_RUNTIME="${FRAGMENT_MAX_PAGES_PER_COLLECTION:-500}"
  env \
    TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}" \
    TELEGRAM_BOT_USERNAME="${TELEGRAM_BOT_USERNAME:-}" \
    TELEGRAM_GIFTS_API_URL="${TELEGRAM_GIFTS_API_URL:-}" \
    TELEGRAM_GIFTS_API_TOKEN="${TELEGRAM_GIFTS_API_TOKEN:-}" \
    TELEGRAM_GIFTS_API_TOKEN_HEADER="${TELEGRAM_GIFTS_API_TOKEN_HEADER:-Authorization}" \
    TELEGRAM_GIFTS_API_TOKEN_PREFIX="${TELEGRAM_GIFTS_API_TOKEN_PREFIX:-Bearer }" \
    TELEGRAM_GIFTS_API_TIMEOUT_SEC="${TELEGRAM_GIFTS_API_TIMEOUT_SEC:-25}" \
    AUTH_REQUIRED="${AUTH_REQUIRED:-true}" \
    FRAGMENT_SSL_NO_VERIFY="${FRAGMENT_SSL_NO_VERIFY:-true}" \
    FRAGMENT_MAX_COLLECTIONS="$FRAGMENT_MAX_COLLECTIONS_RUNTIME" \
    FRAGMENT_MAX_PAGES_PER_COLLECTION="$FRAGMENT_MAX_PAGES_RUNTIME" \
    FRAGMENT_FETCH_BUDGET_SEC="${FRAGMENT_FETCH_BUDGET_SEC:-1400}" \
    FRAGMENT_TIMEOUT_SEC="${FRAGMENT_TIMEOUT_SEC:-20}" \
    FRAGMENT_MIN_EVENTS="${FRAGMENT_MIN_EVENTS:-0}" \
    FRAGMENT_MIN_COLLECTIONS="${FRAGMENT_MIN_COLLECTIONS:-0}" \
    FRAGMENT_MIN_BACKGROUNDS="${FRAGMENT_MIN_BACKGROUNDS:-0}" \
    INGEST_INTERVAL_SEC="$INGEST_INTERVAL_RUNTIME" \
    DATA_STALE_SEC="$DATA_STALE_RUNTIME" \
    VERIFIED_REFRESH_SEC="$VERIFIED_REFRESH_RUNTIME" \
    VERIFIED_ONLY=true \
    VERIFIED_SOURCE="$VERIFIED_SOURCE_RUNTIME" \
    VERIFIED_MIN_GIFTS_ABS="${VERIFIED_MIN_GIFTS_ABS:-200}" \
    VERIFIED_MIN_GIFTS_RATIO="${VERIFIED_MIN_GIFTS_RATIO:-0.60}" \
    VERIFIED_MIN_COLLECTIONS_RATIO="${VERIFIED_MIN_COLLECTIONS_RATIO:-0.50}" \
    VERIFIED_MIN_MODELS_RATIO="${VERIFIED_MIN_MODELS_RATIO:-0.40}" \
    HOST=127.0.0.1 PORT=8080 \
    python3 -u server.py >> "$SERVER_LOG" 2>&1 &
  SERVER_PID=$!
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] server_started pid=$SERVER_PID" >> "$LOG_FILE"
}

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] watchdog_start" >> "$LOG_FILE"
FAILS=0
SERVER_PID=""
start_server

while true; do
  if [ -n "${SERVER_PID:-}" ] && ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] server_exit pid=$SERVER_PID restart" >> "$LOG_FILE"
    FAILS=0
    start_server
    sleep 2
  fi

  CODE=$(curl -s -m 2 -o /dev/null -w "%{http_code}" "$CHECK_URL" 2>/dev/null || true)
  if [ -z "$CODE" ]; then
    CODE="000"
  fi
  if [ "$CODE" != "200" ]; then
    FAILS=$((FAILS + 1))
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] health_fail code=$CODE fails=$FAILS pid=$SERVER_PID" >> "$LOG_FILE"
    if [ "$FAILS" -ge "$MAX_FAILS" ]; then
      if [ -n "${SERVER_PID:-}" ]; then
        kill -TERM "$SERVER_PID" 2>/dev/null || true
        sleep 1
        kill -KILL "$SERVER_PID" 2>/dev/null || true
      fi
      FAILS=0
      start_server
      sleep 2
    fi
  else
    FAILS=0
  fi

  sleep "$CHECK_INTERVAL_SEC"
done
