#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE_API="http://127.0.0.1:8080"
BASE_UI="http://127.0.0.1:5173"

check_url() {
  local url="$1"
  local code
  code="$(curl -sS -o /dev/null -w "%{http_code}" "$url" || true)"
  if [ "$code" != "200" ]; then
    echo "FAIL $code $url"
    return 1
  fi
  echo "OK   $code $url"
}

if ! lsof -nP -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Backend :8080 is down. Starting local backend..."
  "$ROOT/scripts/server_local_start.sh" >/tmp/server_local_start_last.log 2>&1 || true
  sleep 2
fi

if ! lsof -nP -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "React :5173 is down. Starting dev server..."
  "$ROOT/scripts/react_start.sh" >/tmp/react_start_last.log 2>&1 || true
  sleep 2
fi

echo "== API smoke =="
check_url "$BASE_API/v1/overview?mode=tz"
check_url "$BASE_API/v1/signals?mode=tz&limit=5"
check_url "$BASE_API/v1/variants?mode=tz&limit=5"
check_url "$BASE_API/v1/market/status?window=30m"
check_url "$BASE_API/v1/metrics?metric=MARKET_INDEX&scope=MARKET&mode=tz"
check_url "$BASE_API/v1/listings/new?limit=5"
check_url "$BASE_API/v1/listings/race?limit=5"
check_url "$BASE_API/v1/listings/signals?limit=5"

echo "== UI smoke =="
check_url "$BASE_UI/"

echo "Smoke check completed."
