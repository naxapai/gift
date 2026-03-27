#!/bin/zsh
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

echo "== server =="
lsof -nP -iTCP:8080 -sTCP:LISTEN || true
lsof -nP -iTCP:8090 -sTCP:LISTEN || true
echo "---"
curl -sS -o /dev/null -w "index_code=%{http_code}\n" http://127.0.0.1:8080/index.html || true
curl -sS -o /dev/null -w "index_code_8090=%{http_code}\n" http://127.0.0.1:8090/index.html || true
echo "---"
echo "== sync =="
pgrep -fl 'fragment_sync_watch.sh|sync_fragment_batches.py' || true
echo "---"
tail -n 20 /tmp/fragment_sync_watch.log || true
