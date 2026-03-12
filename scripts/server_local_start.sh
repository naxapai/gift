#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PID_FILE="/tmp/gmz_server_local.pid"
LOG_FILE="/tmp/gmz_server_local.log"
# Force loopback for local React proxy compatibility.
HOST_LOCAL="127.0.0.1"
PORT_LOCAL="8080"
HEALTH_URL="http://${HOST_LOCAL}:${PORT_LOCAL}/healthz"
LOCAL_DEV_FORCE_AUTH_DISABLED="${LOCAL_DEV_FORCE_AUTH_DISABLED:-true}"

if [ -f ".env.local" ]; then
  set -a
  source ".env.local"
  set +a
fi

# Local QA/dev should work without auth headers from browser by default.
if [ "$LOCAL_DEV_FORCE_AUTH_DISABLED" = "true" ]; then
  AUTH_REQUIRED="false"
  TON_AUTH_REQUIRED="false"
fi

is_healthy() {
  local code
  code="$(curl -sS -o /dev/null -w "%{http_code}" "$HEALTH_URL" || true)"
  [ "$code" = "200" ]
}

if is_healthy; then
  echo "backend already healthy: $HEALTH_URL"
  exit 0
fi

# If another local process occupies the port but does not answer health checks,
# terminate it to avoid endless bind loops.
stale_port_pids="$(lsof -tiTCP:${PORT_LOCAL} -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "${stale_port_pids:-}" ]; then
  echo "stale listeners on :${PORT_LOCAL}: $stale_port_pids; terminating"
  kill -TERM $stale_port_pids 2>/dev/null || true
  sleep 1
  kill -KILL $stale_port_pids 2>/dev/null || true
fi

if [ -f "$PID_FILE" ]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${old_pid:-}" ] && kill -0 "$old_pid" 2>/dev/null; then
    echo "stopping previous local backend pid=$old_pid"
    kill -TERM "$old_pid" 2>/dev/null || true
    sleep 1
    kill -KILL "$old_pid" 2>/dev/null || true
  fi
fi

if command -v setsid >/dev/null 2>&1; then
  nohup setsid env \
    HOST="$HOST_LOCAL" \
    PORT="$PORT_LOCAL" \
    AUTH_REQUIRED="${AUTH_REQUIRED:-false}" \
    TON_AUTH_REQUIRED="${TON_AUTH_REQUIRED:-false}" \
    VERIFIED_ONLY="${VERIFIED_ONLY:-true}" \
    VERIFIED_SOURCE="${VERIFIED_SOURCE:-hybrid}" \
    VERIFIED_REFRESH_SEC="${VERIFIED_REFRESH_SEC:-300}" \
    INGEST_INTERVAL_SEC="${INGEST_INTERVAL_SEC:-300}" \
    DATA_STALE_SEC="${DATA_STALE_SEC:-900}" \
    FRAGMENT_SSL_NO_VERIFY="${FRAGMENT_SSL_NO_VERIFY:-true}" \
    python3 -u server.py >"$LOG_FILE" 2>&1 < /dev/null &
else
  nohup env \
    HOST="$HOST_LOCAL" \
    PORT="$PORT_LOCAL" \
    AUTH_REQUIRED="${AUTH_REQUIRED:-false}" \
    TON_AUTH_REQUIRED="${TON_AUTH_REQUIRED:-false}" \
    VERIFIED_ONLY="${VERIFIED_ONLY:-true}" \
    VERIFIED_SOURCE="${VERIFIED_SOURCE:-hybrid}" \
    VERIFIED_REFRESH_SEC="${VERIFIED_REFRESH_SEC:-300}" \
    INGEST_INTERVAL_SEC="${INGEST_INTERVAL_SEC:-300}" \
    DATA_STALE_SEC="${DATA_STALE_SEC:-900}" \
    FRAGMENT_SSL_NO_VERIFY="${FRAGMENT_SSL_NO_VERIFY:-true}" \
    python3 -u server.py >"$LOG_FILE" 2>&1 < /dev/null &
fi
new_pid=$!
echo "$new_pid" > "$PID_FILE"
echo "backend start requested pid=$new_pid"

for i in {1..60}; do
  if is_healthy; then
    echo "backend ready: $HEALTH_URL"
    exit 0
  fi
  sleep 1
done

echo "backend failed to become healthy: $HEALTH_URL"
tail -n 80 "$LOG_FILE" || true
exit 1
