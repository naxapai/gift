#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONT="$ROOT/frontend-react"
LOG="/tmp/gmz_frontend_react.log"
PORT=5173
MAX_WAIT_SEC="${REACT_START_MAX_WAIT_SEC:-30}"

wait_backend() {
  local max_wait="${1:-45}"
  local waited=0
  while [ "$waited" -lt "$max_wait" ]; do
    if curl -fsS "http://127.0.0.1:8080/healthz" >/dev/null 2>&1; then
      echo "Backend is healthy on :8080 (waited ${waited}s)"
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  echo "Backend health check timeout after ${max_wait}s"
  return 1
}

# Ensure backend is available for Vite proxy, otherwise UI shows HTTP 500
# for every API call.
if ! lsof -nP -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Backend on :8080 is not running, starting local backend..."
  "$ROOT/scripts/server_local_start.sh" || true
fi
if ! wait_backend 45; then
  echo "Backend is still unavailable; React will start but API calls may fail until backend is up."
fi

# Always restart React dev server to apply updated Vite proxy config.
OLD_PID=$(lsof -tiTCP:${PORT} -sTCP:LISTEN || true)
if [ -n "${OLD_PID:-}" ]; then
  echo "Stopping old React dev server pid=$OLD_PID"
  kill -TERM "$OLD_PID" 2>/dev/null || true
  sleep 1
fi

# Run via detached shell to prevent parent-shell HUP/job-control side effects.
RUN_CMD="cd \"$FRONT\" && exec env VITE_API_PROXY_TARGET=http://127.0.0.1:8080 ./node_modules/.bin/vite --host 127.0.0.1 --port $PORT"
if command -v setsid >/dev/null 2>&1; then
  nohup setsid /bin/sh -c "$RUN_CMD" >"$LOG" 2>&1 < /dev/null &
else
  nohup /bin/sh -c "$RUN_CMD" >"$LOG" 2>&1 < /dev/null &
fi
PID=$!

waited=0
while [ "$waited" -lt "$MAX_WAIT_SEC" ]; do
  if lsof -nP -iTCP:${PORT} -sTCP:LISTEN >/dev/null 2>&1; then
    if curl -fsS "http://127.0.0.1:${PORT}/" >/dev/null 2>&1; then
      echo "React dev server started pid=$PID"
      echo "URL: http://127.0.0.1:${PORT}/"
      echo "Proxy target: http://127.0.0.1:8080"
      exit 0
    fi
  fi
  sleep 1
  waited=$((waited + 1))
done

echo "Failed to start React dev server. Last log:"
tail -n 80 "$LOG" || true
exit 1
