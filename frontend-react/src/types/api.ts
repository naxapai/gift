export type SignalType = 'BUY' | 'SELL' | 'WATCH' | 'SKIP'
export type ScreenerType =
  | 'NEW_LISTINGS'
  | 'RACE_MODE'
  | 'UNDERVALUED'
  | 'MOMENTUM_BUY'
  | 'BREAKDOWN_SELL'
  | 'WHALE_ACTIVITY'
  | 'LIQUIDITY_SPIKE'
  | 'VOLATILITY_SURGE'

export interface OverviewResponse {
  engine_mode?: string
  market_state?: string
  stale?: boolean
  counts?: {
    gifts?: number
    collections?: number
    models?: number
    backdrops?: number
    symbols?: number
  }
  key_metrics?: Record<string, number | null>
  provider_health?: ProviderHealth[]
  top_signals?: SignalItem[]
}

export interface ProviderHealth {
  provider?: string
  p95_ms?: number
  err_pct?: number
  degraded?: boolean
  ts?: string
}

export interface SignalsResponse {
  items: SignalItem[]
  next_cursor?: string | null
  engine_mode?: string
  total_count?: number
}

export interface ScreenerRowPro {
  ts: string
  age?: number
  screener_type: ScreenerType | string
  variant_id: string
  variant_label: string
  collection?: string
  model?: string
  background?: string
  pattern?: string
  price_ton?: number | null
  floor_ton?: number | null
  fair_ton?: number | null
  undervalue_pct?: number | null
  expected_profit_pct?: number | null
  liquidity_score?: number | null
  absorption_30m?: number | null
  listing_pressure?: number | null
  depth_score?: number | null
  score100?: number | null
  conf_pct?: number | null
  edgeRank_raw?: number | null
  edgeRank100?: number | null
  market_regime?: 'RISK_ON' | 'MEAN_REVERT' | 'RISK_OFF' | 'PANIC' | string
  action?: SignalType | string
  reasons?: string[]
  risk_flags?: string[]
  decision_trace?: Record<string, unknown>
}

export interface ScreenersFeedResponse {
  items: ScreenerRowPro[]
  next_cursor?: string | null
}

export interface CatalogRowPro {
  variant_id: string
  variant_label: string
  collection?: string
  model?: string
  background?: string
  pattern?: string
  price_ton?: number | null
  floor_ton?: number | null
  fair_ton?: number | null
  median_24h_ton?: number | null
  undervalue_pct?: number | null
  expected_profit_pct?: number | null
  active_lots?: number | null
  listed_share?: number | null
  liquidity_score?: number | null
  absorption_30m?: number | null
  listing_pressure?: number | null
  depth_score?: number | null
  score100?: number | null
  conf_pct?: number | null
  edgeRank_raw?: number | null
  edgeRank100?: number | null
  market_regime?: 'RISK_ON' | 'MEAN_REVERT' | 'RISK_OFF' | 'PANIC' | string
  action?: SignalType | string
  reasons?: string[]
  risk_flags?: string[]
  decision_trace?: Record<string, unknown>
  sort_key?: number | null
  updated_at?: string
  age_sec?: number | null
  listings_10m?: number | null
  volume_24h_ton?: number | null
  floor_history?: Array<{ ts?: string; value?: number }>
}

export interface CatalogFeedResponse {
  items: CatalogRowPro[]
  next_cursor?: string | null
}

export interface SignalItem {
  signal_id?: string
  ts?: string
  type?: SignalType | string
  action?: SignalType | string
  strength_tag?: 'NONE' | 'STRONG_BUY' | 'STRONG_SELL' | string
  variant_id?: string
  variant_label?: string
  collection_id?: string
  collection?: string
  model?: string
  background?: string
  pattern?: string
  market_regime?: 'RISK_ON' | 'MEAN_REVERT' | 'RISK_OFF' | 'PANIC' | string
  market_regime_badge?: string
  edgeRank_profile?: string
  edgeRank_raw?: number
  edgeRank100?: number
  score100?: number
  conf_pct?: number
  price_ton?: number | null
  price_stars?: number | null
  floor_ton?: number | null
  floor_stars?: number | null
  fair_ton?: number | null
  undervalue?: number | null
  undervalue_pct?: number | null
  expected_profit_pct?: number | null
  forecast24h_pct_min?: number | null
  forecast24h_pct_max?: number | null
  forecast_24h_pct_min?: number | null
  forecast_24h_pct_max?: number | null
  target_ton?: number | null
  stop_ton?: number | null
  liquidity24h?: number | null
  liquidity_score?: number | null
  absorption_30m?: number | null
  listing_pressure?: number | null
  volume_velocity?: number | null
  depth_5pct_count?: number | null
  depth_5pct_ton?: number | null
  watch_trigger?: string | null
  active_lots?: number | null
  preview_url?: string
  reasons?: string[]
  risk_flags?: string[]
  data_quality?: string
  listing_id?: string
  listing_key?: string
  source?: string
}

export interface CollectionItem {
  collection_id: string
  name?: string
  preview_url?: string
  floor_ton?: number
  delta_1h?: number
  delta_12h?: number
  delta_24h?: number
  active_lots_total?: number
}

export interface AuthUser {
  id?: number
  username?: string
  first_name?: string
  last_name?: string
  photo_url?: string
  auth_date?: number
}

export interface OwnedGiftItem {
  gift_id?: string
  variant_id?: string | null
  collection?: string | null
  model?: string | null
  background?: string | null
  pattern?: string | null
  variant_label?: string
  preview_url?: string
  fragment_url?: string
  status?: string
  floor_ton?: number | null
  fair_ton?: number | null
  acquired_at?: string
  meta?: Record<string, unknown>
}

export type TradeStatus = 'PENDING_SIGNATURE' | 'SIGNED' | 'BROADCAST' | 'CONFIRMED' | 'FAILED' | 'EXPIRED' | 'REPLACED'
export type TradeIntentType = 'BUY' | 'BUY_AND_LIST' | 'SELL' | 'LIST' | 'CANCEL_LISTING' | 'TRANSFER'

export interface BuyQuoteResponse {
  buy_quote_token: string
  expires_at: string
  quote: {
    variant_id: string
    listing_id?: string | null
    max_price_ton: number
    slippage_bps: number
    fee_budget_ton: number
    wallet_address_hash?: string | null
    nonce: string
  }
}

export interface TradeIntent {
  intent_id: string
  intent_type: TradeIntentType | string
  variant_id: string
  wallet_address: string
  listing_id?: string | null
  gift_unique_id?: string | null
  status: TradeStatus | string
  created_at: string
  expires_at: string
  tx_hash?: string | null
  source?: 'STANDARD' | 'FAST_BUY' | string
  chain_id?: string | null
  parent_intent_id?: string | null
  step_index?: number | null
  chain_policy?: 'MANUAL' | 'BUY_THEN_LIST' | string | null
  post_action?: Record<string, unknown> | null
  reasons?: string[] | null
  risk_flags?: string[] | null
  decision_trace?: Record<string, unknown> | null
}

export interface PositionPro {
  position_id: string
  wallet_address: string
  variant_id: string
  qty: number
  avg_buy_price_ton: number
  mark_price_ton: number
  fees_paid_ton: number
  realized_pnl_ton: number
  realized_pnl_pct: number
  unrealized_pnl_ton: number
  unrealized_pnl_pct: number
  edgeRank100?: number | null
  conf_pct?: number | null
  action?: string | null
  risk_flags?: string[]
  opened_at?: string | null
  updated_at: string
}

export interface HoldingPro {
  holding_id: string
  wallet_address: string
  gift_unique_id: string
  variant_id: string
  acquired_price_ton: number
  acquired_at: string
  status: 'OWNED' | 'LISTED' | 'TRANSFER_PENDING' | 'SOLD' | string
  marketplace_listing_id?: string | null
  listed_price_ton?: number | null
  updated_at?: string | null
}

export interface PnlSummaryPro {
  pnl_today_ton: number
  pnl_today_pct: number
  pnl_7d_ton: number
  pnl_30d_ton: number
  win_rate: number
  avg_hold_min: number
  best_trade_ton: number
  worst_trade_ton: number
  exposure_ton: number
  market_regime: 'RISK_ON' | 'MEAN_REVERT' | 'RISK_OFF' | 'PANIC' | string
}

export interface AutoSellRule {
  rule_id: string
  wallet_address: string
  enabled: boolean
  scope: string
  trigger_type: 'TAKE_PROFIT' | 'STOP_LOSS' | 'TRAILING_STOP' | 'TIME_EXIT' | 'REGIME_EXIT' | 'SIGNAL_EXIT' | string
  params: Record<string, unknown>
  mode: 'NOTIFY_ONLY' | 'AUTO_LIST' | 'AUTO_SELL_NOW' | string
  list_price_strategy?: 'FAIR_PLUS_X' | 'FLOOR_MINUS_X' | 'FIXED' | string | null
  cooldown_sec: number
  priority: number
  updated_at?: string
}

export interface WalletActivityItem {
  ts: string
  direction: 'IN' | 'OUT' | string
  amount_ton: number
  counterparty?: string | null
  tx_hash: string
}

export interface CollectionsResponse {
  items: CollectionItem[]
  next_cursor?: string | null
}

export interface VariantItem {
  variant_id: string
  collection_id?: string
  collection_name?: string
  model?: string
  background?: string
  pattern?: string
  preview_url?: string
  floor_ton?: number
  delta_1h?: number
  delta_12h?: number
  delta_24h?: number
  active_lots?: number
  score100?: number
  conf_pct?: number
  action_hint?: string
  fair_ton?: number
  undervalue?: number
  expected_profit_pct?: number
  liquidity24h?: number
  forecast24h_pct_min?: number
  forecast24h_pct_max?: number
}

export interface VariantsResponse {
  items: VariantItem[]
  next_cursor?: string | null
}

export interface VariantResolveResponse {
  variant_id: string
  collection_id?: string
  collection?: string
  model?: string
  background?: string
  pattern?: string
  preview_url?: string
  active_lots?: number
  floor_ton?: number
  matched_by?: string
  active_only?: boolean
}

export interface ListingSummaryResponse {
  source?: string
  source_error?: string
  active_total?: number
  new_total?: number
  relisted_total?: number
  collections_active?: number
}

export interface ListingSourceStatusResponse {
  source?: string
  degraded?: boolean
  ok?: boolean
  status?: string
  last_error?: string
  error?: string
  strict_primary?: boolean
  effective_mode?: string
}

export interface MarketStatusResponse {
  ts?: string
  window?: string
  market_regime?: 'RISK_ON' | 'MEAN_REVERT' | 'RISK_OFF' | 'PANIC' | string
  market_regime_badge?: string
  data_health?: 'OK' | 'DEGRADED' | string
  data_conf_pct?: number
  trend?: string
  velocity_score?: number
  vol_level?: 'LOW' | 'MED' | 'HIGH' | string
  flow?: {
    volume_velocity?: number
    absorption?: number
    listing_pressure?: number
  }
  liquidity?: {
    liquidity_score?: number
    depth_5pct?: {
      lots?: number
      ton?: number
    }
  }
  supply?: {
    active_lots?: number
    delta_lots_1h?: number
    listing_velocity_10m?: number
    listing_velocity_norm?: number
  }
  whales?: {
    whale_ratio_pct?: number
    whale_impulse?: number | null
  }
  signals_1h?: {
    buy?: number
    sell?: number
    watch?: number
    skip?: number
  }
  provider_health?: {
    provider?: string
    p95_ms?: number
    err_pct?: number
    degraded?: boolean
    ts?: string
  }
  execution_health?: {
    detect_latency_p95?: number
    detect_latency_p99?: number
    miss_rate?: number
    duplicate_rate?: number
    sse_disconnect_rate?: number
  }
  source?: string
  source_error?: string
}

export interface ListingItemPro {
  listing_key?: string
  gift_id?: string | number
  listing_id?: number | null
  unique_id?: string
  variant_id?: string
  collection?: string
  model?: string
  background?: string
  pattern?: string
  variant_label?: string
  price_ton?: number
  floor_ton?: number | null
  fair_ton?: number | null
  undervalue_pct?: number | null
  expected_profit_pct?: number | null
  score100?: number | null
  conf_pct?: number | null
  market_regime?: string | null
  market_regime_badge?: string | null
  edgeRank_profile?: string | null
  edgeRank_raw?: number | null
  edgeRank100?: number | null
  action?: SignalType | string | null
  strength_tag?: 'NONE' | 'STRONG_BUY' | 'STRONG_SELL' | string
  target_ton?: number | null
  stop_ton?: number | null
  liquidity_score?: number | null
  absorption_30m?: number | null
  listing_pressure?: number | null
  volume_velocity?: number | null
  depth_5pct_count?: number | null
  depth_5pct_ton?: number | null
  depth_score?: number | null
  edge_norms?: {
    C?: number
    S?: number
    EP?: number
    L?: number
    AR?: number
    LP?: number
    D?: number
  }
  decision_trace?: {
    mode?: string
    edgeRank100?: number
    conf_pct?: number
    expected_profit_pct?: number
    liquidity_norm?: number
    absorption_30m?: number
    listing_pressure?: number
    resolved_action?: string
  }
  reasons?: string[]
  risk_flags?: string[]
  ts_source?: string | null
  ts_detected?: string
  latency_ms?: number | null
  is_relist?: boolean
  premium_required?: boolean | null
  resale_ton_only?: boolean | null
  preview_url?: string
  source?: string
}

export interface ListingsFeedResponse {
  items: ListingItemPro[]
  next_cursor?: string | null
  server_ts?: string
  source?: string
  source_error?: string
}

export interface ListingRaceItemPro {
  listing_key?: string
  variant_id?: string | null
  collection_id?: string | null
  collection?: string | null
  model?: string | null
  background?: string | null
  pattern?: string | null
  variant_label?: string | null
  preview_url?: string
  prev_price_ton?: number | null
  price_ton?: number
  delta_ton?: number | null
  delta_pct?: number | null
  direction?: 'UP' | 'DOWN' | string | null
  low_priority?: boolean
  market_regime?: string | null
  market_regime_badge?: string | null
  edgeRank100?: number | null
  action?: SignalType | string | null
  reasons?: string[]
  risk_flags?: string[]
  ts_detected?: string
  source?: string
}

export interface ListingsRaceFeedResponse {
  items: ListingRaceItemPro[]
  next_cursor?: string | null
  server_ts?: string
  source?: string
  source_error?: string
}

export interface ListingEventItem {
  ts?: string
  type?: 'listing.new' | 'listing.price_changed' | 'listing.removed' | string
  listing_key?: string
  price_ton?: number | null
  meta?: Record<string, unknown>
}

export interface TimePoint {
  ts?: string
  v?: number
}

export interface ListingsHistoryResponse {
  variant_id?: string
  from?: string
  to?: string
  resolution?: string
  series?: {
    floor?: TimePoint[]
    active_lots?: TimePoint[]
    sales_count?: TimePoint[]
    volume_ton?: TimePoint[]
  }
  events?: ListingEventItem[]
  server_ts?: string
}

export interface ListingRow {
  variant_id?: string
  collection?: string
  slug?: string
  gift_id?: string
  attributes?: {
    model?: string
    background?: string
    pattern?: string
  }
  preview_url?: string
  listing_id?: string
  listing_key?: string
  is_new?: boolean
  resell_amount_ton?: number
  resell_amount_stars_est?: number
  first_seen_at?: string
  last_seen_at?: string
}

export interface ListingsResponse {
  source?: string
  items: ListingRow[]
  next_cursor?: string | null
}

export interface ListingSignalsResponse {
  source?: string
  source_error?: string
  total?: number
  total_pages?: number
  items: SignalItem[]
}

export interface FavoriteItem {
  variant_id?: string
  note?: string
  added_at?: string
}

export interface FavoritesResponse {
  items: FavoriteItem[]
}

export interface VariantDetailsResponse {
  variant?: VariantItem
  listings?: Array<{
    listing_id?: string
    sale_type?: string
    status?: string
    price_ton?: number
    price_stars?: number
  }>
  breakdown?: {
    action_hint?: string
    score100?: number
    conf_pct?: number
    reasons?: string[]
    risk_flags?: string[]
    forecast24h_pct_min?: number
    forecast24h_pct_max?: number
  }
}

export interface MetricPoint {
  ts?: string
  value?: number
  extra?: Record<string, unknown>
}

export interface MetricResponse {
  metric?: string
  scope?: string
  variant_id?: string
  unit?: string
  points?: MetricPoint[]
  stale?: boolean
  engine_mode?: string
}

export interface StreamEnvelope {
  type?: string
  ts?: string
  payload?: Record<string, unknown>
}
