
# GiftMarketZone — SYSTEM ARCHITECTURE (PRO)
Version: 1.0
Audience: Backend / Frontend / Infra developers + AI agents (Codex)
Goal: Provide an actionable, implementation-ready architecture view of the entire system:
- services and responsibilities
- event flows (topics/streams)
- data pipeline for metrics
- signal engine pipeline
- new listings + race-mode scanners
- API/SSE integration
- observability + latency budgets

---------------------------------------------------------------------
1) HIGH-LEVEL SYSTEM MAP
---------------------------------------------------------------------

             ┌────────────────────────────────────────────────────┐
             │                 Telegram MTProto                    │
             │          payments.getResaleStarGifts                │
             └───────────────┬────────────────────────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ ResaleHeadPoller│  head polling 300–800ms
                    └───────┬─────────┘
                            │  raw gifts
                            ▼
                    ┌──────────────────┐
                    │ ListingNormalizer │  normalize -> internal DTO
                    └───────┬──────────┘
                            │ normalized listings
                            ▼
                    ┌──────────────────┐
                    │ ListingStateTracker│ detect NEW / PRICE_CHANGED / REMOVED
                    └───────┬──────────┘
                            │ listing events
                            ▼
                    ┌──────────────────┐
                    │ ListingEnricher   │ metrics + fair/undervalue + depth + etc
                    └───────┬──────────┘
                            │ enriched listing events
                            ▼
                    ┌──────────────────┐
                    │ SignalEngine      │ Score100 + Conf + EdgeRank + reasons/risk_flags
                    └───────┬──────────┘
                            │ signal events
                            ▼
                    ┌──────────────────┐
                    │ DecisionEngine    │ BUY/SELL/WATCH/SKIP (regime-adaptive)
                    └───────┬──────────┘
                            │ decisions
                            ├──────────────► TelegramNotifier (channel signals)
                            │
                            ▼
                     ┌──────────────────┐
                     │ Redis Streams     │ stream:listings / stream:signals / stream:market
                     └───────┬──────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │ API Gateway       │ REST + SSE
                    └───────┬──────────┘
                            │
                            ▼
                    ┌──────────────────┐
                    │ Frontend (Bento UI)│ Overview / Variant / Signals / New Listings
                    └──────────────────┘

---------------------------------------------------------------------
2) SERVICE RESPONSIBILITIES (BACKEND)
---------------------------------------------------------------------

2.1 GiftTypesSyncService
- Sync gift types and static attributes (collection/model/background/pattern)
- Build variant_id mapping
- Cache attributes in Redis and persist to PostgreSQL variants table
- Output: variant registry used by Normalizer/Enricher

2.2 ResaleHeadPoller
- Calls payments.getResaleStarGifts with limit=50..100
- Dynamic polling 300–800ms depending on load + flood-wait handling
- Produces raw listing snapshots

2.3 BackfillPoller (offset scanner)
- Uses next_offset / pagination
- Runs every 5–10s
- Goal: detect missed head listings, confirm removals

2.4 ListingNormalizer
- Convert MTProto types -> internal DTO
- Normalize monetary values to TON
- Ensure listing_key = "{gift_id}:{id}" (id from StarGiftUnique)
- Resolve variant_id from attributes

2.5 ListingStateTracker
- Maintains in-memory + Redis cache of last-seen listings
- Emits events:
  - market.listing.new (first_seen or relist)
  - market.listing.price_changed (same key, new price)
  - market.listing.removed (not seen N scans + confirmed by backfill)
- Dedupe with TTL to prevent noisy repeats

2.6 ListingEnricher
- Adds all metrics required for PRO trading decision:
  floor/fair/undervalue, liquidity, depth, absorption, pressure, volatility (if history exists)
- Reads historical snapshots from PostgreSQL / Redis caches
- Calculates plan fields:
  target_ton, stop_ton (risk-managed)

2.7 SignalEngine
- Computes:
  Score100
  Conf_pct
  EdgeRank_raw / EdgeRank100 (dynamic weights by market regime)
  reasons[] and risk_flags[] (template-based)
- Produces signal.generated (domain event)

2.8 DecisionEngine
- Converts enriched metrics + edgeRank into action:
  BUY / SELL / WATCH / SKIP
- Adapts thresholds/weights by market regime
- Produces final "signal" object for UI + Telegram

2.9 MarketStatusService
- Computes market-wide aggregates:
  market regime, breadth, global floor/median, totals
- Emits market.status.updated periodically (every 10–60s)

2.10 TelegramNotifier
- Sends signals to channel(s) only when:
  EdgeRank >= 55 AND Conf >= 35 AND ExpectedProfit >= 8%
- Uses consistent PRO templates (reasons/risk_flags)

---------------------------------------------------------------------
3) EVENT FLOWS (EVENT-DRIVEN PIPELINES)
---------------------------------------------------------------------

3.1 Listing pipeline
MTProto snapshot -> Normalized listing -> State event -> Enriched listing -> UI + Signals

Events:
- market.listing.new
- market.listing.price_changed
- market.listing.removed

3.2 Signal pipeline
Enriched listing -> scoring -> decision -> signal

Events:
- signal.generated (internal)
- signal.published (optional if you want separate publishing step)

3.3 Market pipeline
Market snapshots -> regime detection -> market.status.updated

---------------------------------------------------------------------
4) REDIS STREAMS + TOPIC NAMING
---------------------------------------------------------------------

Streams (required):
- stream:listings
- stream:signals
- stream:market

Event envelopes (recommended):
{
  "event": "market.listing.new",
  "ts": "2026-03-04T12:00:00Z",
  "payload": { ... }
}

Event types:
- listing.new
- listing.price_changed
- listing.removed
- signal.generated
- market.status.updated

Retention:
- stream:listings: 24h (or 7d if needed for replay)
- stream:signals: 30d (or 90d)
- stream:market: 7d

Consumer groups:
- cg:enricher
- cg:signal_engine
- cg:api_sse
- cg:telegram

---------------------------------------------------------------------
5) METRICS PIPELINE (HOW METRICS ARE PRODUCED)
---------------------------------------------------------------------

5.1 Input datasets
- Active listings L(t)
- Sales S_w (sales in window w)
- Floor history series for variant and market
- Volume series
- Supply series (active_lots, listed_share)

5.2 Default windows
w_10m, w_30m, w_1h, w_6h, w_24h, w_7d

5.3 Production rule
Frontend never calculates metrics.
Frontend only renders values returned by backend APIs / SSE events.

5.4 Snapshot storage
- metrics_snapshots:
  - market-level snapshots every 1m
  - variant-level snapshots every 1m (or adaptive sampling)

---------------------------------------------------------------------
6) SIGNAL ENGINE PIPELINE (SCORING -> EDGE -> ACTION)
---------------------------------------------------------------------

6.1 Inputs
- Enriched listing metrics
- Market regime
- Risk model (depth/liquidity/pressure)

6.2 Outputs
- Score100, Conf, EdgeRank_raw, EdgeRank100
- Action: BUY/SELL/WATCH/SKIP
- reasons[] and risk_flags[]
- trading plan: target/stop (optional but recommended)

6.3 Gate for Telegram publishing
Publish if:
EdgeRank >= 55 AND Conf >= 35 AND ExpectedProfit >= 8%

6.4 Regime-adaptive EdgeRank weights (Signals / Listings pages)
RISK_ON:
  0.40*EP + 0.25*S + 0.10*L + 0.10*AR + 0.05*D - 0.10*LP
MEAN_REVERT (BASE):
  0.35*EP + 0.25*S + 0.15*L + 0.10*AR + 0.10*D - 0.15*LP
RISK_OFF:
  0.25*EP + 0.20*S + 0.20*L + 0.15*AR + 0.15*D - 0.20*LP
PANIC:
  0.20*EP + 0.20*S + 0.25*L + 0.20*AR + 0.10*D - 0.25*LP

---------------------------------------------------------------------
7) NEW LISTINGS + RACE-MODE ARCHITECTURE
---------------------------------------------------------------------

7.1 New listings feed
- /v1/listings/new
- Items: ListingItemPro
- Dedup by listing_key
- is_relist flag if reappears after TTL

7.2 Race-mode feed (repricing)
- /v1/listings/race
- Items: ListingRaceItemPro
- Target is to detect fast repricing opportunities

7.3 Removed detection
- listing not present in head for N cycles
- confirmed by backfill scan
- then emit listing.removed

7.4 Noise control
- price_changed with abs(delta_pct) < 0.5% => low priority (default hidden)

---------------------------------------------------------------------
8) API + SSE INTEGRATION
---------------------------------------------------------------------

REST endpoints (OpenAPI):
- /v1/signals
- /v1/listings/new
- /v1/listings/race
- /v1/listings/history
- /v1/market/status

SSE endpoints:
- /v1/stream/listings (listing.new / listing.price_changed / listing.removed)

Rule:
SSE payload DTO must match OpenAPI schemas.

---------------------------------------------------------------------
9) FRONTEND (BENTO UI) — CONFIG-DRIVEN UI
---------------------------------------------------------------------

Frontend is built from JSON config files (Bento blocks):
- bento_ui_signals_blocks.json (signals page)
- bento_ui_blocks_new_listings.json (new listings page)
- bento_ui_blocks.json (overview + variant pages)

The UI renders:
- tables with PRO columns
- filters
- row expand with reasons/risk_flags and plan

Frontend never recalculates any metric.

---------------------------------------------------------------------
10) LATENCY + RELIABILITY REQUIREMENTS
---------------------------------------------------------------------

Targets:
- p99 detect latency <= 1000ms
- p95 API <= 300ms
- SSE delivery <= 150ms

Reliability:
- Handle flood-wait (rate-limits) gracefully
- Maintain backfill to prevent missed events
- Monitor miss rate, duplicate rate, SSE disconnect

Observability:
- metrics: latency, qps, errors, flood-wait
- tracing: poll -> normalize -> enrich -> signal -> publish
- logs: structured logs with listing_key and trace_id

---------------------------------------------------------------------
11) SECURITY + SAFETY (PRO)
---------------------------------------------------------------------

- Store MTProto session keys securely (vault/secret manager)
- Limit API keys and internal endpoints
- Rate limit public endpoints
- Validate all payloads (schema validation)
- Dedupe + replay protection on streams

---------------------------------------------------------------------
12) IMPLEMENTATION NOTES FOR AI AGENTS
---------------------------------------------------------------------

Non-negotiable rules:
- Event-driven architecture
- Backend computes all analytics
- EdgeRank formula is exact
- DecisionEngine rules are exact
- UI is config-driven via Bento JSON blocks
- Contracts match OpenAPI schemas

Suggested stack:
- Backend: Node.js (NestJS) or Python (FastAPI), Postgres, Redis, SSE
- Metrics: worker services + scheduled snapshots
- Frontend: React + Bento UI components, SSE client

---------------------------------------------------------------------
END OF DOCUMENT
---------------------------------------------------------------------
