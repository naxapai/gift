
# GiftMarketZone — AI Agent System Context (v5 ENTERPRISE)
Version: 5.0
Purpose: Full enterprise-grade AI development context for Codex / GPT / autonomous developer agents.

This document aggregates ALL technical specifications of the GiftMarketZone platform discussed in project documentation.
It enables AI agents to implement the entire system (backend, analytics engine, signals engine, frontend mapping)
with minimal additional instructions.

====================================================================
1. PROJECT OVERVIEW
====================================================================

GiftMarketZone is a professional analytics and trading platform
for the Telegram Gifts resale marketplace.

Core goals:

• Detect new gift listings with ultra-low latency
• Analyze the Telegram gifts market structure
• Calculate professional trading metrics
• Generate automated BUY / SELL / WATCH / SKIP signals
• Provide real-time dashboards for professional traders

Main application:

https://giftmarketzone.com

Main UI sections:

Overview — global market analytics
Variant — analytics for specific gift
Signals — professional signal feed
New Listings — high‑speed listing scanner

====================================================================
2. DOMAIN MODEL
====================================================================

variant
= (collection + model + background + pattern)

Example:

collection: snakebox
model: Bluebell
background: Cobalt Blue
pattern: Hourglass

variant_id:

snakebox_bluebell_cobalt_hourglass


listing
active listing on marketplace

sale
completed purchase event

market
aggregate of all variants

====================================================================
3. DATA SOURCE
====================================================================

Primary source:

Telegram MTProto API

Method:

payments.getResaleStarGifts

Polling architecture:

Head polling:
interval 300–800 ms

Backfill scan:
interval 5–10 seconds

Head polling detects listings instantly.
Backfill prevents missed events.

====================================================================
4. SYSTEM ARCHITECTURE
====================================================================

Core backend services:

GiftTypesSyncService
sync gift metadata

ResaleHeadPoller
poll Telegram API

ListingNormalizer
normalize MTProto payloads

ListingStateTracker
detect:

new listings
price changes
listing removals

ListingEnricher
calculate analytics metrics

SignalEngine
calculate trading metrics

DecisionEngine
determine signal type

RedisStreamPublisher
publish realtime events

APIGateway
REST endpoints

SSEGateway
realtime streaming

====================================================================
5. EVENT STREAMS
====================================================================

Redis streams:

stream:listings
stream:signals
stream:market

Event types:

market.listing.new
market.listing.price_changed
market.listing.removed
signal.generated
market.status.updated

Example event:

{
  "event": "market.listing.new",
  "listing_key": "12345:777",
  "variant_id": "snakebox_bluebell_cobalt_hourglass",
  "price_ton": 5.4,
  "ts": 1712222222
}

====================================================================
6. CORE ANALYTICS METRICS
====================================================================

Realtime Floor

F(t) = min(P_i(t))

where

P_i = price of listing i


Listing Velocity

LV_w = count(new_listings in window w)


Volume Velocity

VV = sales_volume_w / avg_sales_volume


Liquidity Score

L = clamp(volume_24h / supply , 0 , 1)


Absorption Rate

AR = sales_30m / listings_30m


Listing Pressure

LP = new_listings_30m / sales_30m


Market Depth

D = listings_within_5pct_floor / total_listings


Undervalue

U = (fair_price − listing_price) / fair_price


Expected Profit

EP = (target_price − entry_price) / entry_price


Volatility

V = std(price_history)


Rarity Score

RS = rarity_weight / supply

====================================================================
7. EDGERANK MODEL
====================================================================

Normalization variables:

C  = conf_pct / 100
S  = score100 / 100
EP = clamp(expected_profit_pct / 0.30,0,1)
L  = clamp(liquidity_score / 100,0,1)
AR = clamp(absorption_30m / 2.0,0,1)
LP = clamp(listing_pressure / 8.0,0,1)
D  = clamp(depth_score,0,1)

EdgeRank_raw =

0.35*EP
+0.25*S
+0.15*L
+0.10*AR
+0.10*D
−0.15*LP

EdgeRank = clamp(EdgeRank_raw,0,1) * C

EdgeRank100 = round(EdgeRank * 100)

====================================================================
8. MARKET REGIME MODEL
====================================================================

Market regimes:

RISK_ON
bullish expansion

MEAN_REVERT
balanced market

RISK_OFF
bearish market

PANIC
high volatility crash

Regime affects signal thresholds and scoring weights.

====================================================================
9. DECISION ENGINE
====================================================================

BUY

EdgeRank ≥ 60
Conf ≥ 35
ExpectedProfit ≥ 8%
Liquidity ≥ 0.35
AbsorptionRate ≥ 0.9

SELL

ListingPressure ≥ 4
AbsorptionRate ≤ 0.8

WATCH

EdgeRank ∈ [55..60]

SKIP

otherwise

====================================================================
10. SIGNAL PIPELINE
====================================================================

Pipeline:

Listings → Metrics → EdgeRank → Decision Engine → Signal → Telegram

Signals emitted when:

EdgeRank ≥ 55
Conf ≥ 35
ExpectedProfit ≥ 8%

====================================================================
11. API ENDPOINTS
====================================================================

GET /v1/signals

GET /v1/listings/new

GET /v1/listings/race

GET /v1/listings/history

GET /v1/market/status

SSE /v1/stream/listings

====================================================================
12. DATABASE STRUCTURE
====================================================================

PostgreSQL tables

variants
listings
sales
metrics_snapshots
signals

Redis

stream:listings
stream:signals
stream:market

====================================================================
13. FRONTEND ARCHITECTURE
====================================================================

UI framework

Bento UI

Layout config:

bento_ui_blocks.json

Pages:

Overview
Variant
Signals
New Listings

Frontend must be configuration‑driven.

====================================================================
14. PERFORMANCE TARGETS
====================================================================

Detection latency

p99 ≤ 1000 ms

API latency

p95 ≤ 300 ms

Realtime latency

≤ 150 ms

====================================================================
15. AI DEVELOPMENT RULES
====================================================================

AI agents must:

use event‑driven architecture
compute analytics only in backend
keep EdgeRank formula exact
follow Decision Engine rules
render UI via Bento configuration
respect API contracts

====================================================================
END OF FILE
====================================================================
