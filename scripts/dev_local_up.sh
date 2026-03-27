#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BACK_PID_FILE="/tmp/gmz_server_local.pid"

cleanup() {
  if [ -f "$BACK_PID_FILE" ]; then
    pid="$(cat "$BACK_PID_FILE" 2>/dev/null || true)"
    if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  fi
}
trap cleanup EXIT INT TERM

echo "Starting backend..."
LOCAL_DEV_FORCE_AUTH_DISABLED=true ./scripts/server_local_start.sh

echo "Waiting for backend health..."
for i in {1..45}; do
  if curl -fsS "http://127.0.0.1:8080/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if [ ! -d "$ROOT/frontend-react/node_modules" ]; then
  echo "Installing frontend dependencies..."
  (cd "$ROOT/frontend-react" && npm install)
fi

echo "Starting React dev server..."
echo "Open: http://127.0.0.1:5173/"
echo "Press Ctrl+C to stop both React and backend."
cd "$ROOT/frontend-react"
exec env VITE_API_PROXY_TARGET=http://127.0.0.1:8080 ./node_modules/.bin/vite --host 127.0.0.1 --port 5173
