# GiftMarketZone DNS Cutover Checklist

## Before DNS switch
- Set `PUBLIC_BASE_URL=https://giftmarketzone.com` in Render for the public web service.
- Keep Render service hostname active; only public entrypoint changes.
- Set `CORS_ALLOWED_ORIGINS=https://giftmarketzone.com,https://telegram-gifts-market.onrender.com,http://localhost:5173,http://127.0.0.1:5173` during transition.
- Set `TON_PROOF_ALLOWED_DOMAINS=giftmarketzone.com,telegram-gifts-market.onrender.com,localhost,127.0.0.1` during transition.
- Decide cookie scope:
  - host-only cookies: leave `AUTH_COOKIE_DOMAIN` and `TON_COOKIE_DOMAIN` empty
  - shared subdomain cookies: set both to `giftmarketzone.com`
- Verify `frontend-react/public/tonconnect-manifest.json` and `/tonconnect-manifest.json` return `https://giftmarketzone.com`.

## DNS switch
- Point `giftmarketzone.com` to the Render web service.
- Wait for certificate issuance on Render.
- Verify HTTPS opens without redirect loops.
- Verify app assets load from `https://giftmarketzone.com`.

## Auth checks after switch
- Telegram auth:
  - login succeeds
  - `Set-Cookie` contains `Secure` on production
  - session persists after refresh
- TON auth:
  - `/api/auth/ton/config` reports `public_base_url=https://giftmarketzone.com`
  - TonConnect manifest resolves from the new domain
  - ton proof verify succeeds with `giftmarketzone.com`
- CORS:
  - `OPTIONS /api/auth/telegram/verify` returns `204`
  - `Access-Control-Allow-Origin` echoes `https://giftmarketzone.com`
  - `Access-Control-Allow-Credentials=true`

## Telegram delivery checks
- Run test `gift_signal` from Settings.
- Run test `market_status` from Settings.
- Confirm journal shows a sent record and no new delivery errors.

## After stabilization
- Remove `https://telegram-gifts-market.onrender.com` from `CORS_ALLOWED_ORIGINS`.
- Remove `telegram-gifts-market.onrender.com` from `TON_PROOF_ALLOWED_DOMAINS`.
- If old hostname should stop serving users, disable its public routing or redirect it to `https://giftmarketzone.com`.
