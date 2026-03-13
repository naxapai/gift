#!/bin/zsh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

WATCHDOG_LOCK="/tmp/server_watchdog_start.lock"
WATCHDOG_PID_FILE="/tmp/server_watchdog.pid"

acquire_watchdog_lock() {
  if ( set -o noclobber; echo "$$" > "$WATCHDOG_LOCK" ) 2>/dev/null; then
    return 0
  fi
  return 1
}

release_watchdog_lock() {
  rm -f "$WATCHDOG_LOCK" 2>/dev/null || true
}

wait_backend() {
  local max_wait="${1:-45}"
  local waited=0
  while [ "$waited" -lt "$max_wait" ]; do
    if curl -fsS "http://127.0.0.1:8080/healthz" >/dev/null 2>&1; then
      echo "backend_ready=true waited_sec=$waited"
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  echo "backend_ready=false waited_sec=$max_wait"
  return 1
}

existing_watchdog="$(pgrep -f 'server_watchdog.sh' | head -n 1 || true)"
existing_pid_file=""
if [ -f "$WATCHDOG_PID_FILE" ]; then
  existing_pid_file="$(cat "$WATCHDOG_PID_FILE" 2>/dev/null || true)"
fi
if curl -fsS "http://127.0.0.1:8080/healthz" >/dev/null 2>&1; then
  echo "backend already healthy on :8080, skip watchdog start"
elif [ -n "${existing_pid_file:-}" ] && kill -0 "$existing_pid_file" 2>/dev/null; then
  echo "server watchdog already running pid=$existing_pid_file (pid file)"
elif [ -n "${existing_watchdog:-}" ]; then
  echo "server watchdog already running pid=$existing_watchdog"
else
  if acquire_watchdog_lock; then
    trap release_watchdog_lock EXIT INT TERM
    existing_watchdog_after_lock="$(pgrep -f 'server_watchdog.sh' | head -n 1 || true)"
    if [ -n "${existing_watchdog_after_lock:-}" ]; then
      echo "server watchdog already running pid=$existing_watchdog_after_lock (after lock)"
    else
      if ./scripts/server_local_start.sh >/tmp/server_local_start_last.log 2>&1; then
        echo "local backend started via server_local_start.sh"
      else
        nohup ./scripts/server_watchdog.sh >/tmp/server_watchdog_runner.log 2>&1 < /dev/null &
        SPID=$!
        echo "server watchdog start requested pid=$SPID"
      fi
    fi
    release_watchdog_lock
    trap - EXIT INT TERM
  else
    echo "server watchdog start lock is busy, waiting for existing starter..."
  fi
fi

wait_backend 45 || true

existing_sync="$(pgrep -f 'fragment_sync_watch.sh' | head -n 1 || true)"
if [ -n "${existing_sync:-}" ]; then
  echo "sync watcher already running pid=$existing_sync"
else
  nohup ./scripts/fragment_sync_watch.sh >/tmp/fragment_sync_watch_runner.log 2>&1 < /dev/null &
  WPID=$!
  echo "watcher start requested pid=$WPID"
fi
