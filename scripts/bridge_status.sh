#!/bin/zsh
set -u

PID_FILE="${BRIDGE_PID_FILE:-/tmp/gift_bridge.pid}"
LOG_FILE="${BRIDGE_LOG_FILE:-/tmp/gift_bridge.log}"
BRIDGE_PORT="${BRIDGE_PORT:-8098}"

if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE" 2>/dev/null || true)
  echo "pid_file: $PID_FILE"
  echo "pid: ${PID:-none}"
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    echo "process: running"
  else
    echo "process: not running"
  fi
else
  echo "pid_file: not found"
fi

echo "bridge status API:"
curl -sS "http://127.0.0.1:${BRIDGE_PORT}/api/bridge/status" || true
echo

echo "last log lines:"
tail -n 20 "$LOG_FILE" 2>/dev/null || true
