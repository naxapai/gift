# GiftMarketZone Spec Map (v1)

Last updated: 2026-03-05

## Purpose

This map links TZ/OpenAPI contracts to concrete runtime implementation files.
It is used as a production checklist for contract integrity, debugging, and release validation.

## Core Contracts

1. OpenAPI source (external reference)
- `/Users/nexapai/Downloads/openapi_full_v1.3.yaml`

2. Canonical in-repo contracts
- `config/contracts/schema_signal.created.json`
- `config/contracts/schema_metric.updated.json`
- `config/contracts/frontend_metrics_mapping.json`
- `config/contracts/bento_ui_blocks.json`

3. Signals contracts
- `config/signals/schema_signal.created.v2.json`
- `config/signals/schema_market.status.v1.json`
- `config/signals/signals_page_pro_ui_mapping.json`
- `config/signals/frontend_signals_ui_mapping.json`
- `config/signals/bento_ui_signals_blocks.json`

4. Listing contracts
- `config/listing/bento_ui_blocks_new_listings.json`
- `config/listing/signal_profiles_by_regime.json`
- `config/listing/edgerank_weights_by_regime.json`

## API Endpoints -> Implementation

1. HTTP routing
- `server.py` (`RequestHandler.do_GET/do_POST/do_DELETE`)

2. V1 overview/collections/variants/signals/metrics
- `core.py` (`overview_v1`, `collections_v1`, `variants_v1`, `signals_v1`, `metrics_v1`)

3. Listing pipeline API
- `core.py` (`listings_new_v1`, `listings_race_v1`, `listings_history_v1`, `listings_signals_v1`)
- `server.py` (`/v1/listings/*` + SSE streams)

4. Auth/favorites/alerts
- `server.py` + `core.py`

## Frontend (React, contract-driven)

1. App shell and routing
- `frontend-react/src/components/AppShell.tsx`
- `frontend-react/src/App.tsx`

2. Contract-driven API client
- `frontend-react/src/lib/api.ts`
- `frontend-react/src/lib/openapi.ts`
- `frontend-react/src/lib/metricsCatalog.ts`

3. Signals/Listing pages (PRO)
- `frontend-react/src/pages/SignalsPage.tsx`
- `frontend-react/src/pages/ListingPage.tsx`
  - listing signals table is config-driven via `TABLE_LISTING_SIGNALS` in `config/listing/bento_ui_blocks_new_listings.json`
  - market status fallback is `v1/overview` first; legacy `/api/market/overview` fallback is gated by `VITE_ENABLE_LEGACY_MARKET_OVERVIEW_FALLBACK=true`

4. Variant/Overview Bento pages
- `frontend-react/src/pages/VariantPage.tsx`
- `frontend-react/src/pages/OverviewPage.tsx`

## Validation Tests

1. Contract consistency
- `tests/test_contract_configs_consistency.py`

2. Event schemas
- `tests/test_v1_event_schema_validation.py`

3. HTTP contract
- `tests/test_v1_http_contract.py`

4. Formula invariants
- `tests/test_v1_formula_contract.py`

5. Frontend stack and contract usage
- `tests/test_frontend_react_stack.py`

## Release Gate (minimum)

1. `python3 -m unittest discover -s tests`
2. `cd frontend-react && npm run build`
3. Local smoke:
   - `GET /v1/overview?mode=tz`
   - `GET /v1/signals?mode=tz&limit=5`
   - `GET /v1/listings/new?window=30m&limit=5`
   - React dev server responds on `127.0.0.1:5173`
