#!/bin/zsh
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

echo "== React dev server :5173 =="
lsof -nP -iTCP:5173 -sTCP:LISTEN || true
echo "---"
curl -sS -o /dev/null -w "react_code=%{http_code}\n" http://127.0.0.1:5173/ || true
echo "---"
tail -n 40 /tmp/gmz_frontend_react.log || true
