# Render env — GiftMarketZone

Ниже список env-переменных для перехода на `giftmarketzone.com` и для новых блоков Telegram delivery / Telegram auth / owned gifts.

## 1) `telegram-gifts-market`

Обязательные:
- `PUBLIC_BASE_URL=https://giftmarketzone.com`
- `CORS_ALLOWED_ORIGINS=https://giftmarketzone.com,https://telegram-gifts-market.onrender.com,http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173`
- `TON_PROOF_ALLOWED_DOMAINS=giftmarketzone.com,telegram-gifts-market.onrender.com,localhost,127.0.0.1`
- `TELEGRAM_BOT_TOKEN=<bot token>`
- `TG_BOT_USERNAME=<bot username without @>`

Рекомендуемые:
- `AUTH_REQUIRED=false`
- `TON_AUTH_REQUIRED=false`
- `AUTH_SESSION_COOKIE=gmz_session`
- `TON_SESSION_COOKIE=gmz_ton_session`
- `AUTH_COOKIE_DOMAIN=`
- `TON_COOKIE_DOMAIN=`
- `TELEGRAM_AUTH_MAX_AGE_SEC=300`
- `TON_AUTH_SESSION_TTL_SEC=86400`
- `TON_PROOF_MAX_AGE_SEC=300`
- `TON_CHALLENGE_TTL_SEC=180`

Telegram delivery:
- `TG_CHAT_ID=<working telegram chat id>`
- `TELEGRAM_CHAT_ID=<optional alias, if TG_CHAT_ID not used>`
- `TELEGRAM_CONFIG_DIR=/opt/render/project/src/config/telegram`
- `TELEGRAM_OWNED_GIFTS_API_URL=https://giftmarketzone.com/bridge/gifts/owned`
- `TELEGRAM_OWNED_GIFTS_API_TOKEN=<optional bearer token>`
- `TELEGRAM_OWNED_GIFTS_TIMEOUT_SEC=8`
- `TELEGRAM_OWNED_GIFTS_CACHE_TTL_SEC=60`

Переходный период DNS:
- старый onrender host пока оставить в `CORS_ALLOWED_ORIGINS`
- старый onrender host пока оставить в `TON_PROOF_ALLOWED_DOMAINS`

## 2) `gift-api-bridge`

Если этот сервис будет источником owned gifts:
- `PUBLIC_BASE_URL=https://giftmarketzone.com`
- `BRIDGE_API_TOKEN=<shared bearer token>`
- `OWNED_GIFTS_ENABLED=true`
- `OWNED_GIFTS_FILE=/opt/render/project/src/data/owned_gifts_by_user.json`

Если добавите endpoint для кабинета, он должен уметь принимать:
- `GET /bridge/gifts/owned?telegram_user_id=<id>&username=<username>`
- `telegram_user_id`
- `username`

## 3) `gift-api-upstream`

Оставить действующие ingestion/env, дополнительно:
- `PUBLIC_BASE_URL=https://giftmarketzone.com`

Если upstream будет источником inventory/owned gifts:
- `OWNED_GIFTS_ENABLED=true`
- `OWNED_GIFTS_API_TOKEN=<shared bearer token>`

## 4) `gift-listing-mtproto-bridge`

Оставить текущие bridge/env как есть.

При необходимости:
- `PUBLIC_BASE_URL=https://giftmarketzone.com`

## 5) `tz-formula-gates-check`

Обновить URL сигналов:
- `TZ_GATES_SIGNALS_URL=https://giftmarketzone.com/v1/signals`

## После стабилизации DNS
- убрать `https://telegram-gifts-market.onrender.com` из `CORS_ALLOWED_ORIGINS`
- убрать `telegram-gifts-market.onrender.com` из `TON_PROOF_ALLOWED_DOMAINS`
- при необходимости задать `AUTH_COOKIE_DOMAIN=giftmarketzone.com`
- при необходимости задать `TON_COOKIE_DOMAIN=giftmarketzone.com`
