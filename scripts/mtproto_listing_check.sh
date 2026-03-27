#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-${LISTING_MT_API_URL:-}}"
API_TOKEN="${2:-${LISTING_MT_API_TOKEN:-}}"
TOKEN_HEADER="${LISTING_MT_API_TOKEN_HEADER:-Authorization}"
TOKEN_PREFIX="${LISTING_MT_API_TOKEN_PREFIX:-Bearer }"

if [ -z "$BASE_URL" ]; then
  echo "usage: scripts/mtproto_listing_check.sh <LISTING_MT_API_URL> [LISTING_MT_API_TOKEN]"
  exit 1
fi

normalize_candidates() {
  local raw="$1"
  IFS=',' read -r -a urls <<< "$raw"
  local seen=""
  seen_has() {
    local target="$1"
    case ",$seen," in
      *",$target,"*) return 0 ;;
      *) return 1 ;;
    esac
  }
  seen_add() {
    local target="$1"
    if [ -z "$seen" ]; then
      seen="$target"
    else
      seen="$seen,$target"
    fi
  }
  for u in "${urls[@]}"; do
    u="$(echo "$u" | xargs)"
    [ -z "$u" ] && continue
    if ! seen_has "$u"; then
      echo "$u"
      seen_add "$u"
    fi
    if [[ "$u" =~ /api/listing-bridge/status$ ]]; then
      local v="${u%/api/listing-bridge/status}/api/listings/new"
      if ! seen_has "$v"; then echo "$v"; seen_add "$v"; fi
    elif [[ "$u" =~ /api/listings/new$ ]]; then
      local v="${u%/api/listings/new}/api/listing-bridge/status"
      if ! seen_has "$v"; then echo "$v"; seen_add "$v"; fi
    elif [[ "$u" =~ ^https?://[^/]+/?$ ]]; then
      local root="${u%/}"
      local v="$root/api/listings/new"
      if ! seen_has "$v"; then echo "$v"; seen_add "$v"; fi
    fi
  done
}

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "MTProto listing source check"
echo "BASE_URL=$BASE_URL"

idx=0
while IFS= read -r url; do
  idx=$((idx+1))
  out="$TMP_DIR/out_${idx}.txt"
  code="000"
  if [ -n "$API_TOKEN" ]; then
    code=$(curl -m 15 -sS -H "$TOKEN_HEADER: ${TOKEN_PREFIX}${API_TOKEN}" -o "$out" -w "%{http_code}" "$url" || true)
  else
    code=$(curl -m 15 -sS -o "$out" -w "%{http_code}" "$url" || true)
  fi
  first_line="$(head -n 1 "$out" 2>/dev/null || true)"
  echo "[$idx] $url -> HTTP $code"
  if grep -qi "Service Suspended" "$out"; then
    echo "    status: SERVICE_SUSPENDED"
  elif grep -qi "unauthorized\|mt_bridge_token_not_configured" "$out"; then
    echo "    status: UNAUTHORIZED_OR_TOKEN_MISSING"
  elif echo "$first_line" | grep -q '^{'; then
    if command -v jq >/dev/null 2>&1; then
      echo "    json: $(jq -c '{ok: .ok, error: .error, source: .source, updated_at: .updated_at, items: (.items|length?)}' "$out" 2>/dev/null || head -c 160 "$out")"
    else
      echo "    json: $(head -c 160 "$out")"
    fi
  else
    echo "    body: ${first_line:0:160}"
  fi

done < <(normalize_candidates "$BASE_URL")
