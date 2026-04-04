import type {
  CatalogFeedResponse,
  CatalogRowPro,
  CollectionItem,
  CollectionsResponse,
  ListingEventItem,
  ListingItemPro,
  ListingRaceItemPro,
  ListingSignalsResponse,
  ListingsFeedResponse,
  ListingsHistoryResponse,
  ListingsRaceFeedResponse,
  ListingsResponse,
  ListingSourceStatusResponse,
  ListingSummaryResponse,
  MarketStatusResponse,
  MetricResponse,
  OverviewResponse,
  FavoritesResponse,
  SignalItem,
  TradeIntent,
  PositionPro,
  HoldingPro,
  PnlSummaryPro,
  AutoSellRule,
  WalletActivityItem,
  BuyQuoteResponse,
  ScreenerRowPro,
  ScreenersFeedResponse,
  SignalsResponse,
  StreamEnvelope,
  VariantDetailsResponse,
  VariantResolveResponse,
  VariantItem,
  VariantsResponse,
} from '../types/api'

import { OPENAPI_V1, variantDetailsPath, withMode, withQuery } from './openapi'
import { assertMetricAllowedByMapping, normalizeMetricName, type MetricScope } from './metricsCatalog'

const API_BASE = import.meta.env.VITE_API_BASE || ''
const API_TIMEOUT_MS = Math.max(1000, Number(import.meta.env.VITE_API_TIMEOUT_MS || 15000))
const API_RETRY_COUNT = Math.max(0, Number(import.meta.env.VITE_API_RETRY_COUNT || 1))
const ENABLE_LEGACY_MARKET_OVERVIEW_FALLBACK = String(import.meta.env.VITE_ENABLE_LEGACY_MARKET_OVERVIEW_FALLBACK || '').trim().toLowerCase() === 'true'
const TRANSIENT_HTTP_CODES = new Set([408, 429, 500, 502, 503, 504])

function withBase(path: string): string {
  if (!API_BASE) return path
  return `${API_BASE}${path}`
}

function withEndpointQuery(endpoint: string, params: URLSearchParams): string {
  const raw = String(endpoint || '').trim()
  const fallback = '/'
  const [basePathRaw, endpointQueryRaw] = (raw || fallback).split('?', 2)
  const basePath = basePathRaw || fallback
  const merged = new URLSearchParams(endpointQueryRaw || '')
  const overrideKeys = new Set<string>()
  for (const key of params.keys()) overrideKeys.add(key)
  for (const key of overrideKeys) merged.delete(key)
  for (const [key, value] of params.entries()) merged.append(key, value)
  return withQuery(basePath, merged)
}

async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const url = withBase(path)
  let lastError: Error | null = null

  for (let attempt = 0; attempt <= API_RETRY_COUNT; attempt += 1) {
    const controller = new AbortController()
    const timeoutId = globalThis.setTimeout(() => controller.abort('timeout'), API_TIMEOUT_MS)
    try {
      const res = await fetch(url, {
        credentials: 'same-origin',
        cache: 'no-store',
        ...init,
        signal: controller.signal,
      })
      const payload = await res.json().catch(() => ({}))
      if (!res.ok) {
        const reason = String(payload?.error || payload?.reason || payload?.message || res.statusText)
        const err = new Error(`HTTP ${res.status}: ${reason}`) as Error & { retryable?: boolean }
        const transient = TRANSIENT_HTTP_CODES.has(res.status)
        err.retryable = transient
        if (transient && attempt < API_RETRY_COUNT) {
          await new Promise((resolve) => globalThis.setTimeout(resolve, 180 * (attempt + 1)))
          continue
        }
        throw err
      }
      return payload as T
    } catch (e) {
      const isAbort = e instanceof DOMException && e.name === 'AbortError'
      const retryable = isAbort || !!((e as { retryable?: boolean } | null)?.retryable)
      const msg = isAbort ? `HTTP timeout after ${API_TIMEOUT_MS}ms` : (e instanceof Error ? e.message : 'request_failed')
      lastError = new Error(msg)
      if (retryable && attempt < API_RETRY_COUNT) {
        await new Promise((resolve) => globalThis.setTimeout(resolve, 180 * (attempt + 1)))
        continue
      }
    } finally {
      globalThis.clearTimeout(timeoutId)
    }
  }
  throw lastError || new Error('request_failed')
}

function sanitizeSourceError(raw: unknown): string {
  const v = String(raw || '').trim()
  if (!v) return ''
  const normalized = v.toLowerCase()
  if (normalized === 'unknown_error' || normalized === 'request_failed') return ''
  if (normalized === 'failed to fetch' || normalized === 'networkerror when attempting to fetch resource.') return ''
  if (normalized.startsWith('typeerror: failed to fetch')) return ''
  return v
}

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function normalizeListingsFeed(payload: unknown, fallbackSource: string): ListingsFeedResponse {
  const src = asObject(payload)
  return {
    items: (Array.isArray(src.items) ? src.items : []) as ListingItemPro[],
    next_cursor: src.next_cursor == null ? null : String(src.next_cursor),
    server_ts: String(src.server_ts || new Date().toISOString()),
    source: String(src.source || fallbackSource),
    source_error: sanitizeSourceError(src.source_error),
  }
}

function normalizeListingsRaceFeed(payload: unknown, fallbackSource: string): ListingsRaceFeedResponse {
  const src = asObject(payload)
  return {
    items: (Array.isArray(src.items) ? src.items : []) as ListingRaceItemPro[],
    next_cursor: src.next_cursor == null ? null : String(src.next_cursor),
    server_ts: String(src.server_ts || new Date().toISOString()),
    source: String(src.source || fallbackSource),
    source_error: sanitizeSourceError(src.source_error),
  }
}

function normalizeListingSignals(payload: unknown, fallbackSource: string): ListingSignalsResponse {
  const src = asObject(payload)
  const items = (Array.isArray(src.items) ? src.items : []) as SignalItem[]
  const total = Number.isFinite(Number(src.total)) ? Number(src.total) : items.length
  const totalPages = Number.isFinite(Number(src.total_pages)) ? Number(src.total_pages) : 1
  return {
    source: String(src.source || fallbackSource),
    source_error: sanitizeSourceError(src.source_error),
    total,
    total_pages: totalPages,
    items,
  }
}

function normalizeListingsHistory(variantId: string, payload: unknown): ListingsHistoryResponse {
  const src = asObject(payload)
  const series = asObject(src.series)
  const safePoints = (value: unknown): Array<{ ts?: string; v?: number }> => (
    Array.isArray(value) ? value.filter((x) => x && typeof x === 'object') as Array<{ ts?: string; v?: number }> : []
  )
  return {
    variant_id: String(src.variant_id || variantId),
    from: src.from ? String(src.from) : undefined,
    to: src.to ? String(src.to) : undefined,
    resolution: src.resolution ? String(src.resolution) : undefined,
    series: {
      floor: safePoints(series.floor),
      active_lots: safePoints(series.active_lots),
      sales_count: safePoints(series.sales_count),
      volume_ton: safePoints(series.volume_ton),
    },
    events: Array.isArray(src.events) ? (src.events as ListingsHistoryResponse['events']) : [],
    server_ts: String(src.server_ts || new Date().toISOString()),
  }
}

function normalizeScreenersFeed(payload: unknown): ScreenersFeedResponse {
  const src = asObject(payload)
  return {
    items: (Array.isArray(src.items) ? src.items : []) as ScreenerRowPro[],
    next_cursor: src.next_cursor == null ? null : String(src.next_cursor),
  }
}

function marketStateToRegime(value: unknown): 'RISK_ON' | 'MEAN_REVERT' | 'RISK_OFF' | 'PANIC' {
  const raw = String(value || '').trim().toLowerCase()
  if (raw === 'рост') return 'RISK_ON'
  if (raw === 'падение') return 'RISK_OFF'
  if (raw === 'panic') return 'PANIC'
  return 'MEAN_REVERT'
}

function marketStateToBadge(value: unknown): string {
  const raw = String(value || '').trim().toLowerCase()
  if (raw === 'рост') return '🟢'
  if (raw === 'падение') return '🔴'
  if (raw === 'panic') return '🟥'
  return '🟡'
}

function mapLegacyOverviewToMarketStatus(window: string, payload: Record<string, unknown>): MarketStatusResponse {
  const activeLots = Number(payload.active_listings || 0)
  const sold = Number(payload.total_sold || payload.sell_signals || 0)
  const listingPressure = activeLots / Math.max(1, sold)
  const stale = Boolean(payload.data_stale)
  const state = String(payload.market_state || 'Боковик')
  const source = String(payload.runtime_source || payload.source || 'legacy_overview')
  const sourceError = String(payload.last_error || '')
  return {
    ts: String(payload.updated_at || new Date().toISOString()),
    window,
    market_regime: marketStateToRegime(state),
    market_regime_badge: marketStateToBadge(state),
    data_health: stale || !!sourceError ? 'DEGRADED' : 'OK',
    data_conf_pct: stale || !!sourceError ? 45 : 82,
    trend: state,
    velocity_score: 0,
    vol_level: 'MED',
    flow: {
      volume_velocity: 0,
      absorption: 0,
      listing_pressure: Number.isFinite(listingPressure) ? listingPressure : 0,
    },
    liquidity: {
      liquidity_score: 0,
      depth_5pct: {
        lots: 0,
        ton: 0,
      },
    },
    supply: {
      active_lots: activeLots,
      delta_lots_1h: 0,
      listing_velocity_10m: 0,
      listing_velocity_norm: 0,
    },
    whales: {
      whale_ratio_pct: 0,
      whale_impulse: 0,
    },
    signals_1h: {
      buy: Number(payload.buy_signals || 0),
      sell: Number(payload.sell_signals || 0),
      watch: 0,
      skip: 0,
    },
    provider_health: {
      provider: source,
      p95_ms: 0,
      err_pct: sourceError ? 100 : 0,
      degraded: stale || !!sourceError,
      ts: String(payload.updated_at || new Date().toISOString()),
    },
    execution_health: {
      detect_latency_p95: 0,
      detect_latency_p99: 0,
      miss_rate: 0,
      duplicate_rate: 0,
      sse_disconnect_rate: 0,
    },
    source,
    source_error: sourceError,
  }
}

function mapV1OverviewToMarketStatus(window: string, payload: Record<string, unknown>): MarketStatusResponse {
  const state = String(payload.market_state || 'флет')
  const stale = Boolean(payload.stale)
  const keyMetrics = (payload.key_metrics || {}) as Record<string, unknown>
  const counts = (payload.counts || {}) as Record<string, unknown>
  const buySignals = Number(keyMetrics.buy_signals || 0)
  const sellSignals = Number(keyMetrics.sell_signals || 0)
  const activeLots = Number(counts.gifts || 0)
  return {
    ts: new Date().toISOString(),
    window,
    market_regime: marketStateToRegime(state),
    market_regime_badge: marketStateToBadge(state),
    data_health: stale ? 'DEGRADED' : 'OK',
    data_conf_pct: stale ? 45 : 78,
    trend: state,
    velocity_score: 0,
    vol_level: 'MED',
    flow: {
      volume_velocity: 0,
      absorption: 0,
      listing_pressure: activeLots / Math.max(1, sellSignals),
    },
    liquidity: {
      liquidity_score: 0,
      depth_5pct: {
        lots: 0,
        ton: 0,
      },
    },
    supply: {
      active_lots: activeLots,
      delta_lots_1h: 0,
      listing_velocity_10m: 0,
      listing_velocity_norm: 0,
    },
    whales: {
      whale_ratio_pct: 0,
      whale_impulse: 0,
    },
    signals_1h: {
      buy: buySignals,
      sell: sellSignals,
      watch: 0,
      skip: 0,
    },
    provider_health: {
      provider: 'v1_overview_fallback',
      p95_ms: 0,
      err_pct: 0,
      degraded: stale,
      ts: new Date().toISOString(),
    },
    execution_health: {
      detect_latency_p95: 0,
      detect_latency_p99: 0,
      miss_rate: 0,
      duplicate_rate: 0,
      sse_disconnect_rate: 0,
    },
    source: 'v1_overview_fallback',
    source_error: '',
  }
}

async function fetchAllByCursor<T extends { next_cursor?: string | null; items?: unknown[] }>(
  path: string,
  limit = 200,
  cap = 5000,
): Promise<unknown[]> {
  const out: unknown[] = []
  let cursor = ''
  let guard = 0
  while (out.length < cap && guard < 200) {
    const url = new URL(path, 'http://local')
    const q = url.searchParams
    q.set('limit', String(Math.min(limit, cap - out.length)))
    if (cursor) q.set('cursor', cursor)
    const queryPath = `${url.pathname}?${q.toString()}`
    const page = await apiGet<T>(queryPath)
    const chunk = Array.isArray(page.items) ? page.items : []
    out.push(...chunk)
    cursor = String(page.next_cursor || '')
    if (!cursor || chunk.length === 0) break
    guard += 1
  }
  return out
}

export function tonToStars(ton?: number | null): number {
  const n = Number(ton || 0)
  if (!Number.isFinite(n) || n <= 0) return 0
  return Math.round(n * 500)
}

export function pct(value?: number | null): string {
  const n = Number(value || 0)
  if (!Number.isFinite(n)) return '0.0%'
  return `${n > 0 ? '+' : ''}${n.toFixed(1)}%`
}

export function ton(value?: number | null): string {
  const n = Number(value || 0)
  if (!Number.isFinite(n)) return '0.0'
  return n.toFixed(1)
}

export function signalPercent(value?: number | null): number {
  const n = Number(value || 0)
  if (!Number.isFinite(n)) return 0
  return Math.abs(n) <= 1 ? n * 100 : n
}

export function signalTypeRu(type?: string): string {
  const t = String(type || '').toUpperCase()
  if (t === 'BUY') return 'КУПИТЬ'
  if (t === 'SELL') return 'ПРОДАТЬ'
  if (t === 'WATCH') return 'НАБЛЮДАТЬ'
  if (t === 'SKIP') return 'ПРОПУСТИТЬ'
  return t || 'Н/Д'
}

export async function getOverview(): Promise<OverviewResponse> {
  return apiGet<OverviewResponse>(withMode(OPENAPI_V1.overview))
}

export async function getMarketStatus(window = '30m', endpoint?: string): Promise<MarketStatusResponse> {
  const raw = String(endpoint || OPENAPI_V1.marketStatus || '').trim() || OPENAPI_V1.marketStatus
  const [basePath, rawQuery] = raw.split('?', 2)
  const q = new URLSearchParams(rawQuery || '')
  if (window) q.set('window', window)
  const resolvedWindow = String(window || q.get('window') || '30m')
  try {
    return await apiGet<MarketStatusResponse>(withQuery(basePath || OPENAPI_V1.marketStatus, q))
  } catch (e) {
    // Main compatibility fallback: derive market status from v1 overview.
    const v1Overview = (await apiGet<Record<string, unknown>>(withMode(OPENAPI_V1.overview)).catch(() => null)) || null
    if (v1Overview) {
      return mapV1OverviewToMarketStatus(resolvedWindow, v1Overview)
    }
    // Optional legacy fallback for older backends. Disabled by default to avoid noisy 401s in local/dev.
    if (ENABLE_LEGACY_MARKET_OVERVIEW_FALLBACK) {
      const legacy = (await apiGet<Record<string, unknown>>('/api/market/overview').catch(() => null)) || null
      if (legacy) {
        return mapLegacyOverviewToMarketStatus(resolvedWindow, legacy)
      }
    }
    throw e
  }
}

export async function getSignals(params?: {
  type?: string
  actions?: string[]
  marketRegimes?: string[]
  minScore?: number
  edgeRankMin?: number
  confMin?: number
  profitMin?: number
  liqMin?: number
  lpMax?: number
  arMin?: number
  vvMin?: number
  minUndervaluePct?: number
  maxRisk?: number
  onlyNew1h?: boolean
  onlyProAlerts?: boolean
  q?: string
  sortBy?: string
  sortDir?: 'asc' | 'desc'
  limit?: number
  maxPages?: number
}): Promise<SignalItem[]> {
  const q = buildSignalsQuery(params)
  const limit = Math.max(25, Math.min(200, Number(params?.limit || 200)))
  q.set('limit', String(limit))
  const maxPages = Math.max(1, Math.min(50, Number(params?.maxPages || 10)))

  const out: SignalItem[] = []
  let cursor = ''
  let page = 0
  while (page < maxPages) {
    const rq = new URLSearchParams(q)
    if (cursor) rq.set('cursor', cursor)
    const payload = await apiGet<SignalsResponse>(withQuery(OPENAPI_V1.signals, rq))
    const items = Array.isArray(payload.items) ? payload.items : []
    out.push(...items)
    cursor = String(payload.next_cursor || '')
    if (!cursor || items.length === 0) break
    page += 1
  }
  const dedupe = new Map<string, SignalItem>()
  for (const item of out) {
    const key = item.signal_id || `${item.variant_id || ''}|${item.type || ''}|${item.ts || ''}`
    if (!key) continue
    if (!dedupe.has(key)) dedupe.set(key, item)
  }
  return [...dedupe.values()]
}

function buildSignalsQuery(params?: {
  type?: string
  actions?: string[]
  marketRegimes?: string[]
  minScore?: number
  edgeRankMin?: number
  confMin?: number
  profitMin?: number
  liqMin?: number
  lpMax?: number
  arMin?: number
  vvMin?: number
  minUndervaluePct?: number
  maxRisk?: number
  onlyNew1h?: boolean
  onlyProAlerts?: boolean
  q?: string
  sortBy?: string
  sortDir?: 'asc' | 'desc'
}): URLSearchParams {
  const q = new URLSearchParams({ mode: 'tz' })
  if (params?.type) q.set('type', params.type)
  ;(params?.actions || []).forEach((v) => {
    if (v) q.append('action', v)
  })
  ;(params?.marketRegimes || []).forEach((v) => {
    if (v) q.append('market_regime', v)
  })
  if (Number.isFinite(params?.minScore)) {
    const norm = Math.max(0, Math.min(1, Number(params?.minScore) / 100))
    q.set('min_score', String(norm))
  }
  if (Number.isFinite(params?.edgeRankMin)) q.set('edgeRank_min', String(params?.edgeRankMin))
  if (Number.isFinite(params?.confMin)) q.set('conf_min', String(params?.confMin))
  if (Number.isFinite(params?.profitMin)) q.set('profit_min', String(params?.profitMin))
  if (Number.isFinite(params?.liqMin)) q.set('liq_min', String(params?.liqMin))
  if (Number.isFinite(params?.lpMax)) q.set('lp_max', String(params?.lpMax))
  if (Number.isFinite(params?.arMin)) q.set('ar_min', String(params?.arMin))
  if (Number.isFinite(params?.vvMin)) q.set('vv_min', String(params?.vvMin))
  if (Number.isFinite(params?.minUndervaluePct)) q.set('min_undervalue_pct', String(params?.minUndervaluePct))
  if (Number.isFinite(params?.maxRisk)) q.set('max_risk', String(params?.maxRisk))
  if (params?.onlyNew1h !== undefined) q.set('only_new_1h', params.onlyNew1h ? 'true' : 'false')
  if (params?.onlyProAlerts !== undefined) q.set('only_pro_alerts', params.onlyProAlerts ? 'true' : 'false')
  if (params?.q) q.set('q', params.q.trim())
  if (params?.sortBy) q.set('sort_by', params.sortBy)
  if (params?.sortDir) q.set('sort_dir', params.sortDir)
  return q
}

export async function getSignalsPage(params?: {
  type?: string
  actions?: string[]
  marketRegimes?: string[]
  minScore?: number
  edgeRankMin?: number
  confMin?: number
  profitMin?: number
  liqMin?: number
  lpMax?: number
  arMin?: number
  vvMin?: number
  minUndervaluePct?: number
  maxRisk?: number
  onlyNew1h?: boolean
  onlyProAlerts?: boolean
  q?: string
  sortBy?: string
  sortDir?: 'asc' | 'desc'
  limit?: number
  cursor?: string
  endpoint?: string
}): Promise<SignalsResponse> {
  const q = buildSignalsQuery(params)
  q.set('limit', String(Math.max(25, Math.min(200, Number(params?.limit || 200)))))
  if (params?.cursor) q.set('cursor', params.cursor)
  const endpoint = String(params?.endpoint || OPENAPI_V1.signals || '').trim() || OPENAPI_V1.signals
  return apiGet<SignalsResponse>(withQuery(endpoint, q))
}

function mapSignalCreatedEnvelope(env: StreamEnvelope): SignalItem | null {
  const payload = env?.payload as Record<string, unknown> | undefined
  if (!payload || typeof payload !== 'object') return null
  const pickNum = (...keys: string[]): number | null => {
    for (const key of keys) {
      if (!Object.prototype.hasOwnProperty.call(payload, key)) continue
      const raw = payload[key]
      if (raw === null || raw === undefined || raw === '') continue
      const n = Number(raw)
      if (Number.isFinite(n)) return n
    }
    return null
  }
  const pickStr = (...keys: string[]): string => {
    for (const key of keys) {
      if (!Object.prototype.hasOwnProperty.call(payload, key)) continue
      const raw = String(payload[key] ?? '').trim()
      if (raw) return raw
    }
    return ''
  }
  const action = String(payload.action || payload.type || '').toUpperCase() || 'WATCH'
  const ts = String(payload.ts || env.ts || '')
  const confRaw = pickNum('conf_pct', 'confidence_pct', 'confidence')
  const confPct = confRaw === null ? null : (confRaw <= 1 ? confRaw * 100 : confRaw)
  const scoreRaw = pickNum('score100', 'score_pct', 'score')
  const score100 = scoreRaw === null ? null : (scoreRaw <= 1 ? scoreRaw * 100 : scoreRaw)
  const forecastMinRaw = pickNum('forecast_24h_pct_min', 'forecast24h_pct_min')
  const forecastMaxRaw = pickNum('forecast_24h_pct_max', 'forecast24h_pct_max')
  const forecastMin = forecastMinRaw === null ? 0 : forecastMinRaw
  const forecastMax = forecastMaxRaw === null ? 0 : forecastMaxRaw
  const collection = pickStr('collection', 'collection_name', 'base_name')
  const model = pickStr('model', 'model_name')
  const background = pickStr('background', 'backdrop', 'bg')
  const pattern = pickStr('pattern', 'symbol')
  const floorTon = pickNum('floor_ton', 'floor', 'floor_price_ton')
  const priceTon = pickNum('price_ton', 'price', 'listing_price_ton', 'last_price_ton')
  const fairTon = pickNum('fair_ton', 'fair_price_ton')
  const undervaluePct = pickNum('undervalue_pct', 'undervalue')
  const liquidityScore = pickNum('liquidity_score', 'liq_score')
  const depthCount = pickNum('depth_5pct_count', 'depth_count')
  const depthTon = pickNum('depth_5pct_ton', 'depth_ton')
  const out: SignalItem = {
    signal_id: String(payload.signal_id || ''),
    ts,
    type: action,
    action,
    variant_id: String(payload.variant_id || ''),
    collection_id: String(payload.collection_id || ''),
    collection,
    model,
    background,
    pattern,
    variant_label: [collection, model, background, pattern].filter(Boolean).join(' • '),
    market_regime: pickStr('market_regime'),
    edgeRank_profile: pickStr('edgeRank_profile'),
    edgeRank_raw: pickNum('edgeRank_raw') ?? undefined,
    edgeRank100: pickNum('edgeRank100') ?? undefined,
    score100: score100 ?? undefined,
    conf_pct: confPct ?? undefined,
    price_ton: priceTon ?? undefined,
    floor_ton: floorTon ?? undefined,
    fair_ton: fairTon ?? undefined,
    undervalue_pct: undervaluePct ?? undefined,
    undervalue: undervaluePct === null ? undefined : undervaluePct / 100,
    expected_profit_pct: pickNum('expected_profit_pct') ?? undefined,
    forecast24h_pct_min: forecastMin,
    forecast24h_pct_max: forecastMax,
    forecast_24h_pct_min: forecastMin,
    forecast_24h_pct_max: forecastMax,
    target_ton: pickNum('target_ton') ?? undefined,
    stop_ton: pickNum('stop_ton') ?? undefined,
    liquidity_score: liquidityScore ?? undefined,
    absorption_30m: pickNum('absorption_30m') ?? undefined,
    listing_pressure: pickNum('listing_pressure') ?? undefined,
    volume_velocity: pickNum('volume_velocity') ?? undefined,
    depth_5pct_count: depthCount === null ? undefined : Math.round(depthCount),
    depth_5pct_ton: depthTon ?? undefined,
    watch_trigger: pickStr('watch_trigger'),
    floor_stars: pickNum('floor_stars', 'floor_price_stars') ?? undefined,
    price_stars: pickNum('price_stars', 'listing_price_stars') ?? undefined,
    active_lots: pickNum('active_lots') ?? undefined,
    data_quality: pickStr('data_quality'),
    preview_url: pickStr('preview_url', 'image_url'),
    reasons: Array.isArray(payload.reasons) ? payload.reasons.map(String) : [],
    risk_flags: Array.isArray(payload.risk_flags) ? payload.risk_flags.map(String) : [],
  }
  if (!out.signal_id || !out.variant_id) return null
  return out
}

export function subscribeSignalsStream(
  onSignal: (signal: SignalItem) => void,
  onError?: (error: Event) => void,
  params?: { mode?: string; heartbeatMs?: number; limit?: number; dedupeTtlSec?: number; endpoint?: string; event?: string },
): EventSource {
  const q = new URLSearchParams()
  q.set('mode', params?.mode || 'tz')
  q.set('heartbeat', String(params?.heartbeatMs || 15000))
  q.set('limit', String(params?.limit || 100))
  q.set('dedupe_ttl_sec', String(params?.dedupeTtlSec || 600))
  const endpoint = String(params?.endpoint || OPENAPI_V1.signalsStream || '').trim() || OPENAPI_V1.signalsStream
  const eventName = String(params?.event || 'signal.created').trim() || 'signal.created'
  const es = new EventSource(withBase(withQuery(endpoint, q)), { withCredentials: true })
  const handler = (ev: MessageEvent<string>) => {
    try {
      const parsed = JSON.parse(ev.data || '{}') as StreamEnvelope
      const sig = mapSignalCreatedEnvelope(parsed)
      if (sig) onSignal(sig)
    } catch {
      // noop
    }
  }
  es.addEventListener(eventName, handler as EventListener)
  if (onError) es.onerror = onError
  return es
}

export async function getCollections(cap = 1000): Promise<CollectionItem[]> {
  const rows = await fetchAllByCursor<CollectionsResponse>(OPENAPI_V1.collections, 200, cap)
  return rows as CollectionItem[]
}

export async function getVariants(params?: {
  collectionId?: string
  sort?: string
  cap?: number
}): Promise<VariantItem[]> {
  const q = new URLSearchParams({ mode: 'tz' })
  if (params?.collectionId) q.set('collection_id', params.collectionId)
  if (params?.sort) q.set('sort', params.sort)
  const rows = await fetchAllByCursor<VariantsResponse>(withQuery(OPENAPI_V1.variants, q), 200, params?.cap || 5000)
  return rows as VariantItem[]
}

export async function getScreenersFeed(params?: {
  screenerType?: string[]
  marketRegime?: string[]
  action?: string[]
  edgeRankMin?: number
  confMin?: number
  profitMinPct?: number
  liqMin?: number
  arMin?: number
  lpMax?: number
  limit?: number
  cursor?: string
  endpoint?: string
}): Promise<ScreenersFeedResponse> {
  const q = new URLSearchParams()
  ;(params?.screenerType || []).forEach((v) => q.append('screener_type', v))
  ;(params?.marketRegime || []).forEach((v) => q.append('market_regime', v))
  ;(params?.action || []).forEach((v) => q.append('action', v))
  if (Number.isFinite(params?.edgeRankMin)) q.set('edgeRank_min', String(params?.edgeRankMin))
  if (Number.isFinite(params?.confMin)) q.set('conf_min', String(params?.confMin))
  if (Number.isFinite(params?.profitMinPct)) q.set('profit_min_pct', String(params?.profitMinPct))
  if (Number.isFinite(params?.liqMin)) q.set('liq_min', String(params?.liqMin))
  if (Number.isFinite(params?.arMin)) q.set('ar_min', String(params?.arMin))
  if (Number.isFinite(params?.lpMax)) q.set('lp_max', String(params?.lpMax))
  if (Number.isFinite(params?.limit)) q.set('limit', String(params?.limit))
  if (params?.cursor) q.set('cursor', params.cursor)
  const endpoint = String(params?.endpoint || OPENAPI_V1.screenersFeed || '').trim() || OPENAPI_V1.screenersFeed
  const payload = await apiGet<unknown>(withEndpointQuery(endpoint, q))
  return normalizeScreenersFeed(payload)
}

export function subscribeScreenersStream(
  onRow: (row: ScreenerRowPro) => void,
  onError?: (error: Event) => void,
  params?: { heartbeatMs?: number; limit?: number; dedupeTtlSec?: number; endpoint?: string; event?: string },
): EventSource {
  const q = new URLSearchParams()
  q.set('heartbeat', String(params?.heartbeatMs || 15000))
  q.set('limit', String(params?.limit || 100))
  q.set('dedupe_ttl_sec', String(params?.dedupeTtlSec || 600))
  const endpoint = String(params?.endpoint || OPENAPI_V1.screenersStream || '').trim() || OPENAPI_V1.screenersStream
  const eventName = String(params?.event || 'screener.row').trim() || 'screener.row'
  const es = new EventSource(withBase(withQuery(endpoint, q)), { withCredentials: true })
  const handler = (ev: MessageEvent<string>) => {
    try {
      const parsed = JSON.parse(ev.data || '{}') as { payload?: unknown }
      const rowObj = asObject(parsed.payload || parsed)
      const row = rowObj as unknown as ScreenerRowPro
      if (typeof row.variant_id === 'string' && typeof row.screener_type === 'string') onRow(row)
    } catch {
      // noop
    }
  }
  es.addEventListener(eventName, handler as EventListener)
  if (onError) es.onerror = onError
  return es
}

export async function getCatalogFeed(params?: {
  q?: string
  action?: string[]
  marketRegime?: string[]
  edgeRankMin?: number
  confMin?: number
  profitMinPct?: number
  liqMin?: number
  depthMin?: number
  arMin?: number
  lpMax?: number
  activeLotsMin?: number
  activeLotsMax?: number
  listedShareMin?: number
  listedShareMax?: number
  preset?: string
  sort?: 'edgerank' | 'profit' | 'liquidity' | 'undervalue' | 'updated'
  dir?: 'asc' | 'desc'
  limit?: number
  cursor?: string
  endpoint?: string
}): Promise<CatalogFeedResponse> {
  const q = new URLSearchParams()
  if (params?.q) q.set('q', String(params.q))
  ;(params?.action || []).forEach((v) => q.append('action', v))
  ;(params?.marketRegime || []).forEach((v) => q.append('market_regime', v))
  if (Number.isFinite(params?.edgeRankMin)) q.set('edgeRank_min', String(params?.edgeRankMin))
  if (Number.isFinite(params?.confMin)) q.set('conf_min', String(params?.confMin))
  if (Number.isFinite(params?.profitMinPct)) q.set('profit_min_pct', String(params?.profitMinPct))
  if (Number.isFinite(params?.liqMin)) q.set('liq_min', String(params?.liqMin))
  if (Number.isFinite(params?.depthMin)) q.set('depth_min', String(params?.depthMin))
  if (Number.isFinite(params?.arMin)) q.set('ar_min', String(params?.arMin))
  if (Number.isFinite(params?.lpMax)) q.set('lp_max', String(params?.lpMax))
  if (Number.isFinite(params?.activeLotsMin)) q.set('active_lots_min', String(params?.activeLotsMin))
  if (Number.isFinite(params?.activeLotsMax)) q.set('active_lots_max', String(params?.activeLotsMax))
  if (Number.isFinite(params?.listedShareMin)) q.set('listed_share_min', String(params?.listedShareMin))
  if (Number.isFinite(params?.listedShareMax)) q.set('listed_share_max', String(params?.listedShareMax))
  if (params?.preset) q.set('preset', params.preset)
  if (params?.sort) q.set('sort', params.sort)
  if (params?.dir) q.set('dir', params.dir)
  if (Number.isFinite(params?.limit)) q.set('limit', String(params?.limit))
  if (params?.cursor) q.set('cursor', params.cursor)
  const endpoint = String(params?.endpoint || OPENAPI_V1.catalogFeed || '').trim() || OPENAPI_V1.catalogFeed
  return apiGet<CatalogFeedResponse>(withEndpointQuery(endpoint, q))
}

export async function getCatalogVariant(variantId: string, params?: { endpoint?: string }): Promise<CatalogRowPro> {
  const id = encodeURIComponent(String(variantId || '').trim())
  const endpoint = String(params?.endpoint || OPENAPI_V1.catalogVariant || '').trim() || OPENAPI_V1.catalogVariant
  const path = endpoint.endsWith('/') ? `${endpoint}${id}` : `${endpoint}/${id}`
  return apiGet<CatalogRowPro>(path)
}

export function subscribeCatalogStream(
  onRow: (row: CatalogRowPro) => void,
  onError?: (error: Event) => void,
  params?: { heartbeatMs?: number; limit?: number; dedupeTtlSec?: number; endpoint?: string; event?: string },
): EventSource {
  const q = new URLSearchParams()
  q.set('heartbeat', String(params?.heartbeatMs || 15000))
  q.set('limit', String(params?.limit || 200))
  q.set('dedupe_ttl_sec', String(params?.dedupeTtlSec || 600))
  const endpoint = String(params?.endpoint || OPENAPI_V1.catalogStream || '').trim() || OPENAPI_V1.catalogStream
  const eventName = String(params?.event || 'catalog.row').trim() || 'catalog.row'
  const es = new EventSource(withBase(withQuery(endpoint, q)), { withCredentials: true })
  const handler = (ev: MessageEvent<string>) => {
    try {
      const parsed = JSON.parse(ev.data || '{}') as { payload?: unknown }
      const rowObj = asObject(parsed.payload || parsed)
      const row = rowObj as unknown as CatalogRowPro
      if (typeof row.variant_id === 'string') onRow(row)
    } catch {
      // noop
    }
  }
  es.addEventListener(eventName, handler as EventListener)
  if (onError) es.onerror = onError
  return es
}

export async function getVariantDetails(variantId: string): Promise<VariantDetailsResponse> {
  return apiGet<VariantDetailsResponse>(variantDetailsPath(variantId))
}

export async function resolveVariantByTraits(params: {
  collectionId?: string
  collection?: string
  model: string
  background?: string
  pattern?: string
  activeOnly?: boolean
  mode?: string
}): Promise<VariantResolveResponse> {
  const q = new URLSearchParams()
  if (params.collectionId) q.set('collection_id', params.collectionId)
  if (params.collection) q.set('collection', params.collection)
  q.set('model', params.model)
  if (params.background) q.set('background', params.background)
  if (params.pattern) q.set('pattern', params.pattern)
  q.set('active_only', (params.activeOnly ?? true) ? 'true' : 'false')
  if (params.mode) q.set('mode', params.mode)
  return apiGet<VariantResolveResponse>(withQuery(OPENAPI_V1.variantsResolve, q))
}

export async function getMetric(params: {
  metric: string
  scope: MetricScope
  variantId?: string
  collectionId?: string
  from?: string
  to?: string
  interval?: string
  limit?: number
}): Promise<MetricResponse> {
  const metricName = normalizeMetricName(params.metric)
  assertMetricAllowedByMapping(metricName, params.scope)
  const q = new URLSearchParams({
    mode: 'tz',
    metric: metricName,
    scope: params.scope,
  })
  if (params.variantId) q.set('variant_id', params.variantId)
  if (params.collectionId) q.set('collection_id', params.collectionId)
  if (params.from) q.set('from', params.from)
  if (params.to) q.set('to', params.to)
  if (params.interval) q.set('interval', params.interval)
  if (params.limit) q.set('limit', String(params.limit))
  return apiGet<MetricResponse>(withQuery(OPENAPI_V1.metrics, q))
}

export async function getListingsSummary(windowSec = 120): Promise<ListingSummaryResponse> {
  const q = new URLSearchParams()
  q.set('new_window_sec', String(windowSec))
  return apiGet<ListingSummaryResponse>(withQuery(OPENAPI_V1.listingsSummary, q))
}

export async function getListingSourceStatus(): Promise<ListingSourceStatusResponse> {
  try {
    return await apiGet<ListingSourceStatusResponse>(OPENAPI_V1.listingsSourceStatus)
  } catch {
    return apiGet<ListingSourceStatusResponse>('/api/listing/source-status')
  }
}

export async function getListingsNew(params?: {
  window?: '10m' | '30m' | '1h' | '6h' | '24h' | string
  cursor?: string
  limit?: number
  marketRegime?: string[]
  action?: string[]
  edgeRankMin?: number
  confMin?: number
  profitMin?: number
  undervalueMin?: number
  liqMin?: number
  lpMax?: number
  arMin?: number
  vvMin?: number
  onlyProAlerts?: boolean
  collection?: string
  model?: string
  background?: string
  pattern?: string
  variantId?: string
  q?: string
  endpoint?: string
}): Promise<ListingsFeedResponse> {
  const q = new URLSearchParams()
  q.set('window', params?.window || '30m')
  q.set('limit', String(params?.limit || 200))
  if (params?.cursor) q.set('cursor', params.cursor)
  ;(params?.marketRegime || []).forEach((v) => q.append('market_regime', v))
  ;(params?.action || []).forEach((v) => q.append('action', v))
  if (Number.isFinite(params?.edgeRankMin)) q.set('edgeRank_min', String(params?.edgeRankMin))
  if (Number.isFinite(params?.confMin)) q.set('conf_min', String(params?.confMin))
  if (Number.isFinite(params?.profitMin)) q.set('profit_min', String(params?.profitMin))
  if (Number.isFinite(params?.undervalueMin)) q.set('undervalue_min', String(params?.undervalueMin))
  if (Number.isFinite(params?.liqMin)) q.set('liq_min', String(params?.liqMin))
  if (Number.isFinite(params?.lpMax)) q.set('lp_max', String(params?.lpMax))
  if (Number.isFinite(params?.arMin)) q.set('ar_min', String(params?.arMin))
  if (Number.isFinite(params?.vvMin)) q.set('vv_min', String(params?.vvMin))
  if (params?.onlyProAlerts !== undefined) q.set('only_pro_alerts', params.onlyProAlerts ? 'true' : 'false')
  if (params?.collection) q.set('collection', params.collection)
  if (params?.model) q.set('model', params.model)
  if (params?.background) q.set('background', params.background)
  if (params?.pattern) q.set('pattern', params.pattern)
  if (params?.variantId) q.set('variant_id', params.variantId)
  if (params?.q) q.set('q', params.q)
  const endpoint = String(params?.endpoint || OPENAPI_V1.listingsNew || '').trim() || OPENAPI_V1.listingsNew
  try {
    const payload = await apiGet<unknown>(withEndpointQuery(endpoint, q))
    return normalizeListingsFeed(payload, endpoint)
  } catch (e) {
    throw e
  }
}

export async function getListingsRace(params?: {
  window?: '10m' | '30m' | '1h' | '6h' | '24h' | string
  cursor?: string
  limit?: number
  direction?: 'UP' | 'DOWN' | 'ANY' | string
  deltaPctMin?: number
  onlyProAlerts?: boolean
  includeLowPriority?: boolean
  q?: string
  endpoint?: string
}): Promise<ListingsRaceFeedResponse> {
  const q = new URLSearchParams()
  q.set('window', params?.window || '30m')
  q.set('limit', String(params?.limit || 200))
  if (params?.cursor) q.set('cursor', params.cursor)
  q.set('direction', params?.direction || 'ANY')
  if (Number.isFinite(params?.deltaPctMin)) q.set('delta_pct_min', String(params?.deltaPctMin))
  if (params?.onlyProAlerts !== undefined) q.set('only_pro_alerts', params.onlyProAlerts ? 'true' : 'false')
  if (params?.includeLowPriority !== undefined) q.set('include_low_priority', params.includeLowPriority ? 'true' : 'false')
  if (params?.q) q.set('q', params.q)
  const endpoint = String(params?.endpoint || OPENAPI_V1.listingsRace || '').trim() || OPENAPI_V1.listingsRace
  try {
    const payload = await apiGet<unknown>(withEndpointQuery(endpoint, q))
    return normalizeListingsRaceFeed(payload, endpoint)
  } catch (e) {
    throw e
  }
}

export async function getListingsHistory(params: {
  variantId: string
  from?: string
  to?: string
  resolution?: '1m' | '5m' | '15m' | '1h' | string
}): Promise<ListingsHistoryResponse> {
  const q = new URLSearchParams()
  q.set('variant_id', params.variantId)
  if (params.from) q.set('from', params.from)
  if (params.to) q.set('to', params.to)
  if (params.resolution) q.set('resolution', params.resolution)
  try {
    const payload = await apiGet<unknown>(withQuery(OPENAPI_V1.listingsHistory, q))
    return normalizeListingsHistory(params.variantId, payload)
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    if (msg.includes('404')) {
      return normalizeListingsHistory(params.variantId, {})
    }
    throw e
  }
}

export function subscribeListingsStream(
  onEvent: (event: { type: string; ts?: string; payload: ListingItemPro | ListingRaceItemPro | ListingEventItem }) => void,
  onError?: (error: Event) => void,
  params?: {
    window?: '10m' | '30m' | '1h' | '6h' | '24h' | string
    since?: string
    intervalSec?: number
    limit?: number
    includeLowPriority?: boolean
    endpoint?: string
    events?: string[]
  },
): EventSource {
  const q = new URLSearchParams()
  q.set('window', params?.window || '30m')
  if (params?.since) q.set('since', params.since)
  if (Number.isFinite(params?.intervalSec)) q.set('interval_sec', String(params?.intervalSec))
  if (Number.isFinite(params?.limit)) q.set('limit', String(params?.limit))
  if (params?.includeLowPriority !== undefined) q.set('include_low_priority', params.includeLowPriority ? 'true' : 'false')
  const endpoint = String(params?.endpoint || OPENAPI_V1.listingsStream || '').trim() || OPENAPI_V1.listingsStream
  const es = new EventSource(withBase(withEndpointQuery(endpoint, q)), { withCredentials: true })
  const namesRaw = Array.isArray(params?.events) ? params?.events : []
  const names = (namesRaw.length ? namesRaw : ['listing.new', 'listing.price_changed', 'listing.removed'])
    .map((x) => String(x || '').trim())
    .filter(Boolean)
  names.forEach((name) =>
    es.addEventListener(name, (ev) => {
      const msg = ev as MessageEvent<string>
      try {
        const parsed = JSON.parse(msg.data || '{}') as ListingItemPro | ListingRaceItemPro | ListingEventItem
        onEvent({ type: name, ts: String((parsed as { ts_detected?: string; ts?: string }).ts_detected || (parsed as { ts?: string }).ts || ''), payload: parsed })
      } catch {
        // noop
      }
    }),
  )
  if (onError) es.onerror = onError
  return es
}

export async function getListings(params?: {
  windowSec?: number
  onlyNew?: boolean
  collectionQ?: string
  modelQ?: string
  limit?: number
}): Promise<ListingsResponse> {
  const q = new URLSearchParams()
  q.set('new_window_sec', String(params?.windowSec || 120))
  q.set('limit', String(params?.limit || 500))
  if (params?.onlyNew) q.set('only_new', '1')
  if (params?.collectionQ) q.set('collection_q', params.collectionQ)
  if (params?.modelQ) q.set('model_q', params.modelQ)
  return apiGet<ListingsResponse>(withQuery(OPENAPI_V1.listings, q))
}

export async function getListingSignals(params?: {
  windowSec?: number
  type?: string
  minScore?: number
  includeRelisted?: boolean
  page?: number
  pageSize?: number
  sortBy?: string
  sortDir?: 'asc' | 'desc'
  endpoint?: string
}): Promise<ListingSignalsResponse> {
  const endpoint = String(params?.endpoint || OPENAPI_V1.listingSignals || '').trim() || OPENAPI_V1.listingSignals
  const pageSize = Math.max(10, Math.min(250, Number(params?.pageSize || 50)))
  const q = new URLSearchParams()
  q.set('new_window_sec', String(params?.windowSec || 120))
  q.set('limit', String(pageSize))
  q.set('page', String(params?.page || 1))
  q.set('page_size', String(pageSize))
  q.set('sort_by', params?.sortBy || 'ts')
  q.set('sort_dir', params?.sortDir || 'desc')
  q.set('include_relisted', params?.includeRelisted === false ? '0' : '1')
  if (params?.type) q.set('type', params.type)
  if (!endpoint.includes('mode=')) q.set('mode', 'tz')
  if (Number.isFinite(params?.minScore)) {
    const norm = Math.max(0, Math.min(1, Number(params?.minScore) / 100))
    q.set('min_score', String(norm))
  }
  try {
    const payload = await apiGet<unknown>(withEndpointQuery(endpoint, q))
    return normalizeListingSignals(payload, endpoint)
  } catch (e) {
    throw e
  }
}

export async function getFavorites(): Promise<FavoritesResponse> {
  return apiGet<FavoritesResponse>(OPENAPI_V1.favorites)
}

export async function upsertFavorite(variantId: string, note = ''): Promise<{ ok?: boolean }> {
  return apiGet<{ ok?: boolean }>(OPENAPI_V1.favorites, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ variant_id: variantId, note }),
  })
}

export async function removeFavorite(variantId: string): Promise<{ ok?: boolean }> {
  const q = new URLSearchParams()
  q.set('variant_id', variantId)
  return apiGet<{ ok?: boolean }>(withQuery(OPENAPI_V1.favorites, q), {
    method: 'DELETE',
  })
}

export async function getAdminAccess(): Promise<{ ok?: boolean; authenticated?: boolean; is_admin?: boolean; user_id?: number | null }> {
  return apiGet('/api/admin/access')
}

export async function getAdminSignalEngineConfig(): Promise<{
  defaults?: Record<string, unknown>
  overrides?: Record<string, unknown>
  effective?: Record<string, unknown>
}> {
  return apiGet('/api/admin/signal-engine/config')
}

export async function saveAdminSignalEngineConfig(overrides: Record<string, unknown>): Promise<{ ok?: boolean }> {
  return apiGet('/api/admin/signal-engine/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(overrides || {}),
  })
}

export async function resetAdminSignalEngineConfig(): Promise<{ ok?: boolean }> {
  return apiGet('/api/admin/signal-engine/config/reset', {
    method: 'POST',
  })
}

export interface TelegramDeliverySettingsResponse {
  ok?: boolean
  defaults?: Record<string, unknown>
  overrides?: Record<string, unknown>
  effective?: Record<string, unknown>
}

export interface TelegramDeliveryStatusResponse {
  ok?: boolean
  configured?: boolean
  worker_alive?: boolean
  queue_size?: number
  effective?: Record<string, unknown>
  stats?: Record<string, unknown>
}

export interface TelegramDeliveryJournalResponse {
  ok?: boolean
  sent?: Array<Record<string, unknown>>
  failed?: Array<Record<string, unknown>>
}

export interface TelegramDeliveryTestResponse {
  ok?: boolean
  kind?: string
  preview?: string
  sent?: boolean
  error?: string
}

export async function getAdminTelegramDeliveryConfig(): Promise<TelegramDeliverySettingsResponse> {
  return apiGet('/api/admin/telegram-delivery/config')
}

export async function saveAdminTelegramDeliveryConfig(overrides: Record<string, unknown>): Promise<TelegramDeliverySettingsResponse> {
  return apiGet('/api/admin/telegram-delivery/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(overrides || {}),
  })
}

export async function resetAdminTelegramDeliveryConfig(): Promise<TelegramDeliverySettingsResponse> {
  return apiGet('/api/admin/telegram-delivery/config/reset', {
    method: 'POST',
  })
}

export async function getAdminTelegramDeliveryStatus(): Promise<TelegramDeliveryStatusResponse> {
  return apiGet('/api/admin/telegram-delivery/status')
}

export async function getAdminTelegramDeliveryJournal(limit = 20): Promise<TelegramDeliveryJournalResponse> {
  return apiGet(withQuery('/api/admin/telegram-delivery/journal', new URLSearchParams({ limit: String(limit) })))
}

export async function getAdminTelegramDeliveryRecommendation(): Promise<{ ok?: boolean; recommended?: Record<string, unknown>; current?: Record<string, unknown>; current_pass_count?: number; recommended_pass_count?: number; stats?: Record<string, unknown>; reason?: string }> {
  return apiGet('/api/admin/telegram-delivery/recommendation')
}

export async function applyAdminTelegramDeliveryRecommendation(): Promise<{ ok?: boolean; recommended?: Record<string, unknown>; effective?: Record<string, unknown>; current_pass_count?: number; recommended_pass_count?: number }> {
  return apiGet('/api/admin/telegram-delivery/recommendation/apply', { method: 'POST' })
}

export async function postAdminTelegramDeliveryTest(kind: 'gift_signal' | 'market_status'): Promise<TelegramDeliveryTestResponse> {
  return apiGet('/api/admin/telegram-delivery/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind }),
  })
}

export async function getAdminSignalPreview(limit = 120): Promise<{ items?: SignalItem[] }> {
  return apiGet(withQuery('/api/admin/signal-engine/signals', new URLSearchParams({ limit: String(limit) })))
}

export async function triggerAdminRefresh(): Promise<Record<string, unknown>> {
  return apiGet('/api/admin/refresh', { method: 'POST' })
}

export async function getAdminRefreshStatus(): Promise<Record<string, unknown>> {
  return apiGet('/api/admin/refresh/status')
}

export async function getAdminFormulaGatesStatus(): Promise<Record<string, unknown>> {
  return apiGet('/api/admin/formula-gates/status')
}

export async function getAdminRuntimeHttpMetrics(): Promise<Record<string, unknown>> {
  return apiGet('/api/admin/runtime/http-metrics')
}

export async function resetAdminRuntimeHttpMetrics(): Promise<Record<string, unknown>> {
  return apiGet('/api/admin/runtime/http-metrics/reset', { method: 'POST' })
}

export async function getTelegramAuthConfig(): Promise<{ ok?: boolean; enabled?: boolean; required?: boolean; bot_username?: string; session_ttl_sec?: number; max_auth_age_sec?: number; public_base_url?: string }> {
  return apiGet('/api/auth/config')
}

export async function getTelegramAuthBootstrap(): Promise<{ ok?: boolean; enabled?: boolean; required?: boolean; bot_username?: string; session_ttl_sec?: number; max_auth_age_sec?: number; authenticated?: boolean; user?: { id?: number; username?: string; first_name?: string; last_name?: string; photo_url?: string; auth_date?: number } | null }> {
  return apiGet('/api/auth/bootstrap')
}

export async function getTelegramAuthMe(): Promise<{ ok?: boolean; authenticated?: boolean; enabled?: boolean; required?: boolean; user?: { id?: number; username?: string; first_name?: string; last_name?: string; photo_url?: string; auth_date?: number } | null }> {
  return apiGet('/api/auth/me')
}

export async function postTelegramAuthVerify(payload: Record<string, unknown>): Promise<{ ok?: boolean; authenticated?: boolean; user?: Record<string, unknown> | null }> {
  return apiGet('/api/auth/telegram/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  })
}

export async function postTelegramWebAppVerify(initDataRaw: string): Promise<{ ok?: boolean; authenticated?: boolean; user?: Record<string, unknown> | null }> {
  return apiGet('/api/auth/telegram/webapp/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ init_data: initDataRaw }),
  })
}

export async function postTelegramLogout(): Promise<{ ok?: boolean; authenticated?: boolean }> {
  return apiGet('/api/auth/logout', { method: 'POST' })
}

export async function getTelegramOwnedGifts(): Promise<{ ok?: boolean; authenticated?: boolean; items?: Array<Record<string, unknown>>; source?: string; message?: string }> {
  return apiGet('/api/auth/telegram/owned-gifts')
}

export type TonWalletInfo = {
  address?: string
  chain?: string
  public_key?: string
  domain?: string
  verified_at?: number
  proof_timestamp?: number | null
  verification_level?: string
  verification_status?: string
}

export async function getTonAuthConfig(): Promise<{ ok?: boolean; required?: boolean; challenge_ttl_sec?: number; proof_max_age_sec?: number }> {
  return apiGet('/api/auth/ton/config')
}

export async function getTonAuthMe(): Promise<{ ok?: boolean; connected?: boolean; required?: boolean; wallet?: TonWalletInfo | null }> {
  return apiGet('/api/auth/ton/me')
}

export async function postTonChallenge(): Promise<{ ok?: boolean; challenge?: string; expires_at?: number; ttl_sec?: number }> {
  return apiGet('/api/auth/ton/challenge', {
    method: 'POST',
  })
}

export async function postTonVerify(payload: {
  account: { address?: string; chain?: string; publicKey?: string; [key: string]: unknown }
  ton_proof?: Record<string, unknown> | null
}): Promise<{ ok?: boolean; connected?: boolean; wallet?: TonWalletInfo | null }> {
  return apiGet('/api/auth/ton/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  })
}

export async function postTonLogout(): Promise<{ ok?: boolean; connected?: boolean }> {
  return apiGet('/api/auth/ton/logout', {
    method: 'POST',
  })
}

export async function getTonBalance(): Promise<{ ok?: boolean; ton_balance?: number | null; reason?: string; address?: string }> {
  return apiGet('/api/auth/ton/balance')
}

export async function getTradingAccess(): Promise<{ ok?: boolean; allowed?: boolean; telegram_user_id?: string | null; wallet_address?: string | null; reason?: string | null }> {
  return apiGet('/api/trades/access')
}

export async function getBuyQuote(params: { variantId: string; maxPriceTon: number; slippageBps?: number; walletAddress?: string }): Promise<BuyQuoteResponse> {
  const q = new URLSearchParams({
    variant_id: params.variantId,
    max_price_ton: String(params.maxPriceTon),
    slippage_bps: String(params.slippageBps ?? 100),
  })
  if (params.walletAddress) q.set('wallet_address', params.walletAddress)
  return apiGet(`/v1/trades/quotes/buy?${q.toString()}`)
}

export async function postFastBuyConfirm(payload: { buy_quote_token: string; tx_hash: string; wallet_address: string; client_meta?: Record<string, unknown> }): Promise<TradeIntent> {
  return apiGet('/v1/trades/fast/confirm', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
}

export async function getTradeIntents(walletAddress: string, status?: string): Promise<{ items: TradeIntent[]; next_cursor?: string | null }> {
  const q = new URLSearchParams({ wallet_address: walletAddress })
  if (status) q.set('status', status)
  return apiGet(`/v1/trades/intents?${q.toString()}`)
}

export async function postTradeIntent(payload: Record<string, unknown>): Promise<{ intent: TradeIntent; wallet_tx: Record<string, unknown> }> {
  return apiGet('/v1/trades/intents', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload || {}) })
}

export async function postTradeIntentConfirm(intentId: string, payload: Record<string, unknown>): Promise<TradeIntent> {
  return apiGet(`/v1/trades/intents/${encodeURIComponent(intentId)}/confirm_signature`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload || {}) })
}

export async function postRetryListIntent(parentIntentId: string): Promise<TradeIntent> {
  return apiGet(`/v1/trades/intents/${encodeURIComponent(parentIntentId)}/retry_list`, { method: 'POST' })
}

export async function getTradePositions(walletAddress: string): Promise<{ items: PositionPro[] }> {
  return apiGet(`/v1/trades/positions?wallet_address=${encodeURIComponent(walletAddress)}`)
}

export async function getTradesWorkspace(walletAddress: string): Promise<{ wallet_address: string; market_regime?: string; pnl: PnlSummaryPro; positions: PositionPro[]; holdings: HoldingPro[]; history: TradeIntent[]; wallet_activity: WalletActivityItem[]; autosell_rules: AutoSellRule[] }> {
  return apiGet(`/v1/trades/workspace?wallet_address=${encodeURIComponent(walletAddress)}`)
}

export async function getTradeHoldings(walletAddress: string): Promise<{ items: HoldingPro[] }> {
  return apiGet(`/v1/trades/holdings?wallet_address=${encodeURIComponent(walletAddress)}`)
}

export async function getTradePnl(walletAddress: string): Promise<PnlSummaryPro> {
  return apiGet(`/v1/trades/pnl?wallet_address=${encodeURIComponent(walletAddress)}`)
}

export async function getAutoSellRules(walletAddress: string): Promise<{ items: AutoSellRule[] }> {
  return apiGet(`/v1/trades/autosell/rules?wallet_address=${encodeURIComponent(walletAddress)}`)
}

export async function upsertAutoSellRule(payload: AutoSellRule): Promise<AutoSellRule> {
  return apiGet('/v1/trades/autosell/rules', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
}

export async function getWalletActivity(address: string): Promise<{ items: WalletActivityItem[]; next_cursor?: string | null }> {
  return apiGet(`/v1/wallet/activity?address=${encodeURIComponent(address)}`)
}

export function subscribeTradesStream(
  walletAddress: string,
  onEvent: (event: { event?: string; ts?: string; payload?: Record<string, unknown> }) => void,
  onError?: (error: Event) => void,
  params?: { heartbeatMs?: number; limit?: number },
): EventSource {
  const q = new URLSearchParams({
    wallet_address: walletAddress,
    heartbeat: String(params?.heartbeatMs || 15000),
    limit: String(params?.limit || 100),
  })
  const es = new EventSource(withBase(`/v1/stream/trades?${q.toString()}`), { withCredentials: true })
  const handler = (ev: MessageEvent<string>) => {
    try {
      onEvent(JSON.parse(ev.data || '{}') as { event?: string; ts?: string; payload?: Record<string, unknown> })
    } catch {
      // noop
    }
  }
  ;['trade.intent.created', 'trade.intent.signed', 'trade.intent.broadcast', 'trade.intent.confirmed', 'position.updated', 'holding.updated', 'wallet.activity.updated', 'autosell.triggered', 'message']
    .forEach((name) => es.addEventListener(name, handler as EventListener))
  if (onError) es.onerror = onError
  return es
}

export function subscribePnlStream(
  walletAddress: string,
  onEvent: (event: { event?: string; ts?: string; payload?: Record<string, unknown> }) => void,
  onError?: (error: Event) => void,
  params?: { heartbeatMs?: number; limit?: number },
): EventSource {
  const q = new URLSearchParams({
    wallet_address: walletAddress,
    heartbeat: String(params?.heartbeatMs || 15000),
    limit: String(params?.limit || 100),
  })
  const es = new EventSource(withBase(`/v1/stream/pnl?${q.toString()}`), { withCredentials: true })
  const handler = (ev: MessageEvent<string>) => {
    try {
      onEvent(JSON.parse(ev.data || '{}') as { event?: string; ts?: string; payload?: Record<string, unknown> })
    } catch {
      // noop
    }
  }
  ;['pnl.updated', 'message'].forEach((name) => es.addEventListener(name, handler as EventListener))
  if (onError) es.onerror = onError
  return es
}

export async function getAlertsV1(): Promise<{ items?: Array<{ rule_id?: string; name?: string; enabled?: boolean }> }> {
  return apiGet('/v1/alerts')
}

export async function postAlertTestV1(ruleId: string): Promise<{ ok?: boolean }> {
  return apiGet('/v1/alerts/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rule_id: ruleId }),
  })
}

export async function upsertAlertV1(payload: {
  rule_id?: string
  name: string
  enabled?: boolean
  rule_json: Record<string, unknown>
}): Promise<{ ok?: boolean }> {
  return apiGet('/v1/alerts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  })
}

export function subscribeRealtime(
  onMessage: (event: StreamEnvelope) => void,
  onError?: (error: Event) => void,
  params?: { types?: string[]; heartbeatMs?: number; mode?: string },
): EventSource {
  const defaultTypes = ['signal.created', 'metric.updated', 'listing.event', 'variant.updated', 'collection.updated', 'provider.health']
  const eventTypes = (Array.isArray(params?.types) && params?.types.length ? params.types : defaultTypes)
    .map((x) => String(x || '').trim())
    .filter(Boolean)
  const types = eventTypes.join(',')
  const q = new URLSearchParams({ mode: String(params?.mode || 'tz'), types, heartbeat: String(params?.heartbeatMs || 15000) })
  const url = withBase(withQuery(OPENAPI_V1.stream, q))
  const es = new EventSource(url, { withCredentials: true })
  const handler = (ev: MessageEvent<string>) => {
    try {
      const parsed = JSON.parse(ev.data) as StreamEnvelope
      onMessage(parsed)
    } catch {
      // noop
    }
  }
  ;[...eventTypes, 'message']
    .forEach((t) => es.addEventListener(t, handler as EventListener))
  if (onError) es.onerror = onError
  return es
}
