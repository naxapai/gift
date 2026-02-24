#!/bin/zsh
set -e
cd '/Users/nexapai/Downloads/подарки'

if [ -f '.env.local' ]; then
  set -a
  source '.env.local'
  set +a
fi

BRIDGE_HOST="${BRIDGE_HOST:-127.0.0.1}"
BRIDGE_PORT="${BRIDGE_PORT:-8098}"
LOG_FILE="${BRIDGE_LOG_FILE:-/tmp/gift_bridge.log}"
PID_FILE="${BRIDGE_PID_FILE:-/tmp/gift_bridge.pid}"

if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
  if [ -n "${OLD_PID:-}" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "bridge already running pid=$OLD_PID"
    exit 0
  fi
fi

nohup env \
  BRIDGE_HOST="$BRIDGE_HOST" \
  BRIDGE_PORT="$BRIDGE_PORT" \
  python3 -u bridge_api.py >> "$LOG_FILE" 2>&1 < /dev/null &
BPID=$!
echo "$BPID" > "$PID_FILE"
disown $BPID || true

echo "bridge start requested pid=$BPID host=$BRIDGE_HOST port=$BRIDGE_PORT log=$LOG_FILE"
