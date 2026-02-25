# GiftMarketZone Formula Lock (TZ / V1)

Last updated: 2026-02-26

This document freezes the current production formula set for `mode=tz` in `/v1/*`.
All formula changes must be made by explicit PR with calibration notes.

## Scope

- Engine: `tz` (`mode=tz` on `/v1/overview`, `/v1/variants`, `/v1/signals`)
- Source implementation: `core.py`, method `GiftAnalyticsService._tz_signal_math`
- Output contracts: `_v1_variant_summary`, `_v1_signal`

## Metric Matrix

1. `price_ton`
- Formula: `variant_floor_ton if >0 else collection_floor_ton`
- Code: `core.py` in `_tz_signal_math`
- Status: locked

2. `floor_ton`
- Formula: `collection_floor_ton if >0 else variant_floor_ton`
- Code: `core.py` in `_tz_signal_math`
- Status: locked

3. `median_ton` (`m`)
- Formula priority:
  - `median_ton_24h` if `sales24h >= 10`
  - else `vwap_ton_24h` if `sales24h >= 10`
  - else `median_ton_7d` if available
  - else `floor_ton`
- Code: `core.py` in `_tz_signal_math`
- Status: locked

4. `fair_ton`
- Formula:
  - `base = 0.7 * m + 0.3 * floor_ton`
  - `prem_rarity` by `active_lots` bands (`<=1`, `<=3`, `<=10`)
  - `pen_liq = clamp((0.5 - liq6h)/0.5, 0, 0.25)`
  - `fair_ton = base * (1 + prem_rarity) * (1 - pen_liq)`
- Code: `core.py` in `_tz_signal_math`
- Status: locked

5. `undervalue`
- Formula: `(fair_ton - price_ton) / fair_ton`
- Code: `core.py` in `_tz_signal_math`
- Status: locked

6. `liq_score`
- Formula: `clamp(sales24h / lots_scale, 0, 1)`, where `lots_scale=max(1, supply/1000)`
- Code: `core.py` in `_tz_signal_math`
- Status: locked

7. `trend_t`
- Formula:
  - `d_f = floor_change_pct_1h / 200`
  - `trend_raw = clamp(0.6*d_f + 0.4*log1p(vol30m)/log1p(20), -1, 1)`
  - `trend_t = (trend_raw + 1)/2`
- Code: `core.py` in `_tz_signal_math`
- Status: locked

8. `risk_pen` and `risk_flags`
- Formula bands:
  - synthetic floor, thin liquidity, provider degraded, pump risk
- Code: `core.py` in `_tz_signal_math`
- Status: locked

9. `score` / `score100`
- Formula:
  - `u = clamp(undervalue/0.6, 0, 1)`
  - `r = clamp(prem_rarity/0.8, 0, 1)`
  - `score = clamp(0.45*u + 0.25*r + 0.20*trend_t + 0.10*liq_score - risk_pen_eff, 0, 1)`
  - sparse uplift for low sales and positive undervalue
- Code: `core.py` in `_tz_signal_math`
- Status: locked

10. `conf_pct`
- Formula:
  - baseline `confidence = clamp(0.3 + 0.7*min(1, sales24h/30), 0, 1)`
  - sparse undervalue uplift for low-sales positive setups
  - `conf_pct = round(confidence*100, 1)`
- Code: `core.py` in `_tz_signal_math`
- Status: locked

11. `expected_profit_pct`
- Formula:
  - `target_sell = max(fair_ton*0.98, floor_ton)`
  - `gross_profit = (target_sell - price_ton)/price_ton`
  - `expected_profit_pct = max(0, gross_profit - 0.03)`
- Code: `core.py` in `_tz_signal_math`
- Status: locked

12. `forecast24h_pct_min` / `forecast24h_pct_max`
- Formula:
  - linear combination of supply/sales/floor deltas (`x1`,`x2`,`d_f_6h`,`d_f_24h`)
  - sparse damping + adaptive volatility cap
  - bounded by `[-volatility_cap, +volatility_cap]`
- Code: `core.py` in `_tz_signal_math`
- Status: locked

13. `action_hint` (`BUY/SELL/WATCH/SKIP`)
- Formula:
  - hard `BUY` rule
  - hard `SELL` block (`hard_sell`, guarded by `neutral_zone`)
  - soft `BUY` bands
  - `WATCH` bands including low-confidence neutral corridor
  - fallback `SKIP`
- Code: `core.py` in `_tz_signal_math`
- Status: locked

## Compatibility Rules

1. `legacy` and `tz` must not mix fields in one signal payload.
2. `engine_mode` must always be present in `/v1` responses.
3. Any threshold edits require calibration evidence (distribution delta and quality delta).

## Current Calibration Target (Top-100 `/v1/signals?mode=tz`)

- `BUY`: 5-12
- `SELL`: 5-12
- `WATCH`: 25-40
- `SKIP`: 45-60

## Phase Status (1-5)

1. Formula lock: done
2. Remove output post-layer and keep logic in TZ math: done
3. Backtest harness and gates: done (script-based; requires remote data availability for prod-grade calibration)
4. Default mode switch to TZ: done (`V1_SIGNAL_ENGINE_MODE=tz`)
5. Contract/invariant tests: done

## Backtest Workflow

1. Run:
`python3 scripts/backtest_tz_signals.py --horizon-hours 24 --mode tz --limit 2000`
2. Ensure `"source": "remote"` (if `local_fallback`, treat result as diagnostic only).
3. Accept formula changes only if:
- `gates_passed == true`
- and distribution remains within target corridor.
