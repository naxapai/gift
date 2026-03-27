import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import listingBentoConfigRaw from '../../../config/listing/bento_ui_blocks_new_listings.json'
import listingProfilesRaw from '../../../config/listing/signal_profiles_by_regime.json'
import { BentoCard } from '../components/BentoCard'
import { BentoGrid } from '../components/BentoGrid'
import { GmzSelect } from '../components/GmzSelect'
import { LoadingBlock } from '../components/LoadingBlock'
import { MetricTile } from '../components/MetricTile'
import { PageHeader } from '../components/PageHeader'
import { Sparkline } from '../components/Sparkline'
import { getListingSignals, getListingSourceStatus, getListingsHistory, getListingsNew, getListingsRace, getListingsSummary, getMarketStatus, resolveVariantByTraits, subscribeListingsStream, subscribeSignalsStream, ton } from '../lib/api'
import { readUiAutoRefreshMinutes, uiAutoRefreshMs } from '../lib/uiSettings'
import type { ListingEventItem, ListingItemPro, ListingRaceItemPro, ListingsHistoryResponse, ListingSourceStatusResponse, ListingSummaryResponse, MarketStatusResponse, MetricPoint, SignalItem } from '../types/api'

type ListingBentoBlock = {
  id: string
  type: string
  title?: string
  columns?: string[]
  default_sort?: string[]
  filters?: string[]
  metrics?: string[]
  data_source?: string
  realtime?: string
}

type ListingBentoConfig = {
  version?: string
  blocks?: ListingBentoBlock[]
}

const LISTING_BENTO = (listingBentoConfigRaw || {}) as ListingBentoConfig
type ListingFiltersState = {
  action: string
  regime: string
  edgeRankMin: number
  confMin: number
  profitMin: number
  liqMin: number
  lpMax: number
  arMin: number
  vvMin: number
  onlyProAlerts: boolean
  raceDirection: string
  raceDeltaMin: number
  includeLowPriority: boolean
  q: string
}

type ListingPresetPayload = Omit<ListingFiltersState, 'q'>
type ListingPresetItem = {
  id: string
  label: string
}

const LISTING_DEFAULT_PRESET_ID = 'default_relaxed'

interface ListingCachePayload {
  savedAt: number
  data: {
    windowKey: '10m' | '30m' | '1h' | '6h' | '24h'
    filters: ListingFiltersState
    appliedFilters: ListingFiltersState
    selectedPreset: string
    marketStatus: MarketStatusResponse | null
    listingSourceStatus: ListingSourceStatusResponse | null
    listingSummary: ListingSummaryResponse | null
    newListings: ListingItemPro[]
    raceListings: ListingRaceItemPro[]
    listingSignals: SignalItem[]
    livePulseTs: string
    newSource?: string
    raceSource?: string
    newSourceError?: string
    raceSourceError?: string
    raceEffectiveWindow?: '10m' | '30m' | '1h' | '6h' | '24h'
  }
}

const LISTING_PROFILE_PRESETS: Record<string, Partial<ListingPresetPayload>> = (
  (listingProfilesRaw as { ui_presets?: Record<string, Partial<ListingPresetPayload>> } | undefined)?.ui_presets || {}
)

const PRESET_LABELS: Record<string, string> = {
  default: 'Базовый PRO',
  top_buy: 'Топ BUY',
  anti_slip: 'Анти-скольжение',
  panic_hunt: 'Охота PANIC',
}
const PRIMARY_PRESET_IDS = ['default', 'top_buy', 'anti_slip']
const PRESET_ORDER = ['default', 'top_buy', 'anti_slip', 'panic_hunt']

function listingRelaxedDefaults(): ListingFiltersState {
  return {
    action: '',
    regime: '',
    edgeRankMin: 0,
    confMin: 0,
    profitMin: 0,
    liqMin: 0,
    lpMax: 10,
    arMin: 0,
    vvMin: 0,
    onlyProAlerts: false,
    raceDirection: 'ANY',
    raceDeltaMin: 0,
    includeLowPriority: false,
    q: '',
  }
}

function getBlockByType(type: string): ListingBentoBlock | undefined {
  return (LISTING_BENTO.blocks || []).find((x) => String(x?.type || '') === type)
}

function pageTitleFromBento(): string {
  const explicit = String((LISTING_BENTO as unknown as { title?: string })?.title || '').trim()
  if (explicit) return explicit
  const page = String((LISTING_BENTO as unknown as { page?: string })?.page || '').trim().toLowerCase()
  if (page === 'new_listings') return 'Листинг'
  return 'Листинг'
}

function pageSubtitleFromBento(): string {
  const explicit = String((LISTING_BENTO as unknown as { description?: string })?.description || '').trim()
  if (explicit) return explicit
  return `NEW + RACE Scanner (PRO, config v${String(LISTING_BENTO.version || '1.0')})`
}

function windowFromEndpoint(endpoint: string, fallback: '10m' | '30m' | '1h' | '6h' | '24h' = '30m'): '10m' | '30m' | '1h' | '6h' | '24h' {
  const raw = String(endpoint || '')
  if (!raw.includes('?')) return fallback
  const q = raw.split('?')[1] || ''
  const params = new URLSearchParams(q)
  const w = String(params.get('window') || '').trim()
  if (w === '10m' || w === '30m' || w === '1h' || w === '6h' || w === '24h') return w
  return fallback
}

function normalizeWindowKey(
  raw: unknown,
  fallback: '10m' | '30m' | '1h' | '6h' | '24h' = '30m',
): '10m' | '30m' | '1h' | '6h' | '24h' {
  const w = String(raw || '').trim()
  if (w === '10m' || w === '30m' || w === '1h' || w === '6h' || w === '24h') return w
  return fallback
}

function windowKeyToSec(windowKey: '10m' | '30m' | '1h' | '6h' | '24h'): number {
  if (windowKey === '10m') return 10 * 60
  if (windowKey === '30m') return 30 * 60
  if (windowKey === '1h') return 60 * 60
  if (windowKey === '6h') return 6 * 60 * 60
  return 24 * 60 * 60
}

const MARKET_STATUS_ENDPOINT = String(getBlockByType('MARKET_CONTEXT_HEADER')?.data_source || '/v1/market/status?window=30m')
const LISTINGS_SIGNALS_ENDPOINT = String(getBlockByType('TABLE_LISTING_SIGNALS')?.data_source || '/v1/listings/signals')
const LISTINGS_NEW_ENDPOINT = String(getBlockByType('TABLE_NEW_LISTINGS')?.data_source || '/v1/listings/new')
const LISTINGS_RACE_ENDPOINT = String(getBlockByType('TABLE_RACE_MODE')?.data_source || '/v1/listings/race')
const LISTING_CACHE_KEY = 'gmz.listing.cache.v1'
const LISTINGS_STREAM_EVENTS = Array.from(
  new Set(
    [
      String(getBlockByType('TABLE_LISTING_SIGNALS')?.realtime || '').trim(),
      String(getBlockByType('TABLE_NEW_LISTINGS')?.realtime || '').trim(),
      String(getBlockByType('TABLE_RACE_MODE')?.realtime || '').trim(),
      'listing.removed',
    ].filter(Boolean),
  ),
)

const NEW_DEFAULT_COLUMNS = [
  'age',
  'variant_label',
  'price_ton',
  'floor_ton',
  'fair_ton',
  'undervalue_pct',
  'edgeRank100',
  'score100',
  'conf_pct',
  'expected_profit_pct',
  'market_regime_badge',
  'liquidity_score',
  'absorption_30m',
  'listing_pressure',
  'depth_score',
  'action',
]

const RACE_DEFAULT_COLUMNS = [
  'variant_label',
  'prev_price_ton',
  'price_ton',
  'delta_pct',
  'direction',
  'edgeRank100',
  'market_regime_badge',
  'action',
]

const LISTING_SIGNALS_DEFAULT_COLUMNS = [
  'variant_label',
  'action',
  'score100',
  'conf_pct',
  'floor_ton',
  'fair_ton',
]

const NEW_COLUMN_LABELS: Record<string, string> = {
  age: 'Возраст',
  variant_label: 'Вариант',
  price_ton: 'Цена',
  floor_ton: 'Floor',
  fair_ton: 'Fair',
  undervalue_pct: 'Недооценка',
  edgeRank100: 'EdgeRank',
  score100: 'Score',
  conf_pct: 'Conf',
  expected_profit_pct: 'Профит',
  market_regime_badge: 'Режим',
  liquidity_score: 'Ликвидность',
  absorption_30m: 'Поглощение',
  listing_pressure: 'Давление',
  depth_score: 'Глубина',
  action: 'Действие',
}

const RACE_COLUMN_LABELS: Record<string, string> = {
  variant_label: 'Вариант',
  prev_price_ton: 'Пред.',
  price_ton: 'Цена',
  delta_pct: 'Δ%',
  direction: 'Напр.',
  edgeRank100: 'EdgeRank',
  market_regime_badge: 'Режим',
  action: 'Действие',
}

const LISTING_SIGNALS_COLUMN_LABELS: Record<string, string> = {
  variant_label: 'Вариант',
  action: 'Сигнал',
  score100: 'Score',
  conf_pct: 'Conf',
  floor_ton: 'Floor',
  fair_ton: 'Fair',
}

type SortSpec = {
  field: string
  dir: 'asc' | 'desc'
}

function compact(value: number): string {
  return value.toLocaleString('ru-RU')
}

function ago(ts?: string): string {
  if (!ts) return '—'
  const ms = Date.now() - new Date(ts).getTime()
  if (!Number.isFinite(ms) || ms < 0) return '—'
  const sec = Math.floor(ms / 1000)
  if (sec < 60) return `${sec}с`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}м`
  const h = Math.floor(min / 60)
  if (h < 24) return `${h}ч`
  const d = Math.floor(h / 24)
  return `${d}д`
}

function num(v: unknown, digits = 2): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(digits)
}

function formatCountdown(totalSec: number): string {
  const sec = Math.max(0, Math.floor(totalSec))
  const mm = Math.floor(sec / 60)
  const ss = sec % 60
  return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
}

function parseSortSpec(raw: unknown): SortSpec[] {
  if (!Array.isArray(raw)) return []
  const out: SortSpec[] = []
  for (const row of raw) {
    const src = String(row || '').trim()
    if (!src) continue
    const parts = src.split(/\s+/).filter(Boolean)
    const field = String(parts[0] || '').trim()
    if (!field) continue
    const dir = String(parts[1] || 'desc').toLowerCase() === 'asc' ? 'asc' : 'desc'
    out.push({ field, dir })
  }
  return out
}

function normalizeFilterId(raw: unknown): string {
  return String(raw || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '')
}

function canonicalFilterId(raw: unknown): string {
  const id = normalizeFilterId(raw)
  if (id === 'edgerank100min') return 'edgerankmin'
  if (id === 'marketregimes') return 'marketregime'
  return id
}

function listingSortValue(row: ListingItemPro, field: string, nowMs: number): number | string {
  if (field === 'age') {
    const ts = Date.parse(String(row.ts_detected || ''))
    if (!Number.isFinite(ts)) return Number.MAX_SAFE_INTEGER
    return Math.max(0, nowMs - ts)
  }
  const raw = (row as unknown as Record<string, unknown>)[field]
  const n = Number(raw)
  if (Number.isFinite(n)) return n
  return String(raw || '').toLowerCase()
}

function raceSortValue(row: ListingRaceItemPro, field: string): number | string {
  const raw = (row as unknown as Record<string, unknown>)[field]
  const n = Number(raw)
  if (Number.isFinite(n)) return n
  return String(raw || '').toLowerCase()
}

function listingSignalSortValue(row: SignalItem, field: string): number | string {
  if (field === 'ts') {
    const ts = Date.parse(String(row.ts || ''))
    return Number.isFinite(ts) ? ts : 0
  }
  const raw = (row as unknown as Record<string, unknown>)[field]
  const n = Number(raw)
  if (Number.isFinite(n)) return n
  return String(raw || '').toLowerCase()
}

function listingSignalStableKey(row: SignalItem): string {
  const signalId = String(row.signal_id || '').trim()
  if (signalId) return `signal:${signalId}`
  const variantId = String(row.variant_id || '').trim()
  const action = String(row.type || row.action || '').trim().toUpperCase()
  const ts = String(row.ts || '').trim()
  const source = String(row.source || '').trim()
  const listingId = String(row.listing_id || '').trim()
  if (variantId || ts || action) return `row:${variantId}|${action}|${ts}|${source}|${listingId}`
  const label = String(row.variant_label || '').trim()
  return `fallback:${label}|${source}`
}

function normalizeListingSignalsRows(rows: SignalItem[], limit = 120): SignalItem[] {
  if (!rows.length) return []
  const map = new Map<string, SignalItem>()
  for (const row of rows) {
    const key = listingSignalStableKey(row)
    const prev = map.get(key)
    if (!prev) {
      map.set(key, row)
      continue
    }
    const prevTs = Date.parse(String(prev.ts || ''))
    const rowTs = Date.parse(String(row.ts || ''))
    if (!Number.isFinite(prevTs) || (Number.isFinite(rowTs) && rowTs >= prevTs)) {
      map.set(key, row)
    }
  }
  const out = [...map.values()]
  out.sort((a, b) => {
    const at = Date.parse(String(a.ts || ''))
    const bt = Date.parse(String(b.ts || ''))
    if (Number.isFinite(bt) || Number.isFinite(at)) {
      const delta = (Number.isFinite(bt) ? bt : 0) - (Number.isFinite(at) ? at : 0)
      if (delta !== 0) return delta
    }
    const as = Number(a.score100 || 0)
    const bs = Number(b.score100 || 0)
    if (bs !== as) return bs - as
    return listingSignalStableKey(a).localeCompare(listingSignalStableKey(b), 'ru')
  })
  return out.slice(0, limit)
}

function listingKeyFromRow(row: { listing_key?: unknown; listing_id?: unknown }): string {
  return String(row?.listing_key || row?.listing_id || '').trim()
}

function compareValues(a: number | string, b: number | string, dir: 'asc' | 'desc'): number {
  if (typeof a === 'number' && typeof b === 'number') {
    return dir === 'asc' ? a - b : b - a
  }
  const aa = String(a)
  const bb = String(b)
  if (aa === bb) return 0
  return dir === 'asc' ? (aa < bb ? -1 : 1) : (aa > bb ? -1 : 1)
}

export function ListingPage() {
  const navigate = useNavigate()
  const autoRefreshMinutes = useMemo(() => readUiAutoRefreshMinutes(), [])
  const autoRefreshMs = useMemo(() => uiAutoRefreshMs(autoRefreshMinutes), [autoRefreshMinutes])
  const refreshTimerRef = useRef<number | null>(null)
  const streamBurstRef = useRef(0)
  const firstLoadRef = useRef(true)
  const initDoneRef = useRef(false)
  const nextRefreshAtRef = useRef<number>(Date.now() + autoRefreshMs)
  const lastAutoRefreshAtRef = useRef<number>(0)
  const requestKeyRef = useRef('')
  const skipNextRequestLoadRef = useRef(false)
  const defaultFilters = useMemo(() => listingRelaxedDefaults(), [])
  const [windowKey, setWindowKey] = useState<'10m' | '30m' | '1h' | '6h' | '24h'>(windowFromEndpoint(MARKET_STATUS_ENDPOINT, '30m'))
  const [filters, setFilters] = useState<ListingFiltersState>(() => listingRelaxedDefaults())
  const [appliedFilters, setAppliedFilters] = useState<ListingFiltersState>(() => listingRelaxedDefaults())
  const [marketStatus, setMarketStatus] = useState<MarketStatusResponse | null>(null)
  const [listingSourceStatus, setListingSourceStatus] = useState<ListingSourceStatusResponse | null>(null)
  const [listingSummary, setListingSummary] = useState<ListingSummaryResponse | null>(null)
  const [newListings, setNewListings] = useState<ListingItemPro[]>([])
  const [raceListings, setRaceListings] = useState<ListingRaceItemPro[]>([])
  const [newSource, setNewSource] = useState('')
  const [raceSource, setRaceSource] = useState('')
  const [newSourceError, setNewSourceError] = useState('')
  const [raceSourceError, setRaceSourceError] = useState('')
  const [raceEffectiveWindow, setRaceEffectiveWindow] = useState<'10m' | '30m' | '1h' | '6h' | '24h'>(windowFromEndpoint(MARKET_STATUS_ENDPOINT, '30m'))
  const [listingSignals, setListingSignals] = useState<SignalItem[]>([])
  const [history, setHistory] = useState<ListingsHistoryResponse | null>(null)
  const [selectedVariantId, setSelectedVariantId] = useState('')
  const [livePulseTs, setLivePulseTs] = useState('')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [error, setError] = useState('')
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({})
  const [selectedPreset, setSelectedPreset] = useState<string>(LISTING_DEFAULT_PRESET_ID)
  const [nextRefreshSec, setNextRefreshSec] = useState(Math.ceil(autoRefreshMs / 1000))

  const blockByType = useMemo(() => {
    const map = new Map<string, ListingBentoBlock>()
    for (const block of LISTING_BENTO.blocks || []) {
      if (block?.type) map.set(block.type, block)
    }
    return map
  }, [])

  const newColumns = useMemo(() => {
    const cols = blockByType.get('TABLE_NEW_LISTINGS')?.columns
    return Array.isArray(cols) && cols.length ? cols : NEW_DEFAULT_COLUMNS
  }, [blockByType])

  const raceColumns = useMemo(() => {
    const cols = blockByType.get('TABLE_RACE_MODE')?.columns
    return Array.isArray(cols) && cols.length ? cols : RACE_DEFAULT_COLUMNS
  }, [blockByType])
  const listingSignalColumns = useMemo(() => {
    const cols = blockByType.get('TABLE_LISTING_SIGNALS')?.columns
    return Array.isArray(cols) && cols.length ? cols : LISTING_SIGNALS_DEFAULT_COLUMNS
  }, [blockByType])
  const presetItems = useMemo(() => {
    const keys = Object.keys(LISTING_PROFILE_PRESETS || {})
    if (!keys.length) return []
    return keys
      .filter((id) => id !== LISTING_DEFAULT_PRESET_ID)
      .sort((a, b) => {
        const ai = PRESET_ORDER.indexOf(a)
        const bi = PRESET_ORDER.indexOf(b)
        if (ai === -1 && bi === -1) return a.localeCompare(b, 'ru')
        if (ai === -1) return 1
        if (bi === -1) return -1
        return ai - bi
      })
      .map((id) => ({
        id,
        label: PRESET_LABELS[id] || id.replaceAll('_', ' ').toUpperCase(),
      }))
  }, [])
  const primaryPresetItems = useMemo(() => {
    const byId = new Map(presetItems.map((item) => [item.id, item]))
    return PRIMARY_PRESET_IDS.map((id) => byId.get(id) || { id, label: PRESET_LABELS[id] || id }).filter(Boolean)
  }, [presetItems])

  const newSortSpec = useMemo(
    () => parseSortSpec(blockByType.get('TABLE_NEW_LISTINGS')?.default_sort as unknown[]),
    [blockByType],
  )
  const raceSortSpec = useMemo(
    () => parseSortSpec(blockByType.get('TABLE_RACE_MODE')?.default_sort as unknown[]),
    [blockByType],
  )
  const listingSignalSortSpec = useMemo(
    () => parseSortSpec(blockByType.get('TABLE_LISTING_SIGNALS')?.default_sort as unknown[]),
    [blockByType],
  )
  const proFilterSet = useMemo(() => {
    const src = blockByType.get('FILTER_BAR')?.filters
    const rows = Array.isArray(src) && src.length
      ? src
      : [
          'edgeRank_min',
          'conf_min',
          'profit_min',
          'liq_min',
          'lp_max',
          'ar_min',
          'vv_min',
          'market_regime',
          'action',
          'only_pro_alerts',
        ]
    return new Set(rows.map((x) => canonicalFilterId(x)))
  }, [blockByType])
  const hasProFilter = useCallback(
    (id: string) => proFilterSet.has(canonicalFilterId(id)),
    [proFilterSet],
  )

  const executionHealthMetrics = useMemo(() => {
    const src = blockByType.get('METRICS_PANEL')?.metrics
    const ids = Array.isArray(src) && src.length
      ? src.map((x) => String(x || '').trim()).filter(Boolean)
      : ['detect_latency_p95', 'detect_latency_p99', 'miss_rate', 'duplicate_rate', 'sse_disconnect_rate']
    return ids
  }, [blockByType])
  const pageTitle = useMemo(() => pageTitleFromBento(), [])
  const pageSubtitle = useMemo(() => pageSubtitleFromBento(), [])
  const feedRequestKey = useMemo(() => JSON.stringify({ windowKey, appliedFilters }), [windowKey, appliedFilters])
  const scheduleNextAutoRefresh = useCallback((baseTs: number = Date.now()) => {
    nextRefreshAtRef.current = baseTs + autoRefreshMs
    setNextRefreshSec(Math.ceil(autoRefreshMs / 1000))
  }, [autoRefreshMs])

  const load = useCallback(async (opts?: { includeContext?: boolean }) => {
    const includeContext = opts?.includeContext !== false
    if (firstLoadRef.current) setLoading(true)
    else setRefreshing(true)
    setError('')
    const [statusRes, sourceStatusRes, summaryRes, feedNewRes, feedRaceRes, listingSignalsRes] = await Promise.allSettled([
      includeContext
        ? getMarketStatus(windowKey, MARKET_STATUS_ENDPOINT)
        : Promise.resolve(marketStatus),
      includeContext
        ? getListingSourceStatus()
        : Promise.resolve(listingSourceStatus),
      includeContext
        ? getListingsSummary(windowKeyToSec(windowKey))
        : Promise.resolve(listingSummary),
      getListingsNew({
        window: windowKey,
        limit: 300,
        action: appliedFilters.action ? [appliedFilters.action] : [],
        marketRegime: appliedFilters.regime ? [appliedFilters.regime] : [],
        edgeRankMin: appliedFilters.edgeRankMin,
        confMin: appliedFilters.confMin,
        profitMin: appliedFilters.profitMin,
        liqMin: appliedFilters.liqMin,
        lpMax: appliedFilters.lpMax,
        arMin: appliedFilters.arMin,
        vvMin: appliedFilters.vvMin,
        onlyProAlerts: appliedFilters.onlyProAlerts,
        q: appliedFilters.q.trim(),
        endpoint: LISTINGS_NEW_ENDPOINT,
      }),
      getListingsRace({
        window: windowKey,
        limit: 250,
        direction: appliedFilters.raceDirection,
        deltaPctMin: appliedFilters.raceDeltaMin,
        includeLowPriority: appliedFilters.includeLowPriority,
        onlyProAlerts: appliedFilters.onlyProAlerts,
        q: appliedFilters.q.trim(),
        endpoint: LISTINGS_RACE_ENDPOINT,
      }),
      getListingSignals({
        windowSec: windowKeyToSec(windowKey),
        type: appliedFilters.action ? appliedFilters.action : undefined,
        minScore: appliedFilters.edgeRankMin,
        includeRelisted: true,
        page: 1,
        pageSize: 80,
        sortBy: 'ts',
        sortDir: 'desc',
        endpoint: LISTINGS_SIGNALS_ENDPOINT,
      }),
    ])

    const hardErrors: string[] = []

    if (includeContext) {
      if (statusRes.status === 'fulfilled') {
        setMarketStatus(statusRes.value || null)
      } else {
        hardErrors.push(statusRes.reason instanceof Error ? statusRes.reason.message : 'market_status_failed')
        setMarketStatus((prev) => prev || null)
      }
    }

    if (includeContext) {
      if (sourceStatusRes.status === 'fulfilled') {
        setListingSourceStatus(sourceStatusRes.value || null)
      } else {
        setListingSourceStatus((prev) => prev || null)
      }
    }

    if (includeContext) {
      if (summaryRes.status === 'fulfilled') {
        const payload = summaryRes.value || null
        const sourceErr = String(payload?.source_error || '').trim()
        if (payload || !sourceErr) {
          setListingSummary(payload)
        }
      } else {
        setListingSummary((prev) => prev || null)
      }
    }

    if (feedNewRes.status === 'fulfilled') {
      const payload = feedNewRes.value
      const items = Array.isArray(payload.items) ? payload.items : []
      setNewSource(String(payload.source || ''))
      const sourceErr = String(payload.source_error || '').trim()
      setNewSourceError(sourceErr)
      if (items.length || !sourceErr) setNewListings(items)
      else setNewListings([])
    } else {
      hardErrors.push(feedNewRes.reason instanceof Error ? feedNewRes.reason.message : 'listings_new_failed')
      setNewSource('')
      setNewSourceError('listings_new_failed')
      setNewListings((prev) => prev)
    }

    if (feedRaceRes.status === 'fulfilled') {
      const payload = feedRaceRes.value
      setRaceSource(String(payload.source || ''))
      const items = Array.isArray(payload.items) ? payload.items : []
      const sourceErr = String(payload.source_error || '').trim()
      const effectiveWindow = windowKey
      setRaceSourceError(sourceErr)
      setRaceEffectiveWindow(effectiveWindow)
      if (items.length || !sourceErr) setRaceListings(items)
      else setRaceListings([])
    } else {
      hardErrors.push(feedRaceRes.reason instanceof Error ? feedRaceRes.reason.message : 'listings_race_failed')
      setRaceSource('')
      setRaceSourceError('listings_race_failed')
      setRaceListings((prev) => prev)
    }

    if (listingSignalsRes.status === 'fulfilled') {
      const payload = listingSignalsRes.value
      const items = Array.isArray(payload.items) ? payload.items.slice(0, 120) : []
      const sourceErr = String(payload.source_error || '').trim()
      if (items.length || !sourceErr) setListingSignals(normalizeListingSignalsRows(items, 120))
    } else {
      hardErrors.push(listingSignalsRes.reason instanceof Error ? listingSignalsRes.reason.message : 'listings_signals_failed')
      setListingSignals((prev) => prev)
    }

    if (hardErrors.length >= 3) {
      setError(hardErrors.join(' | '))
    }
    setLoading(false)
    setRefreshing(false)
    firstLoadRef.current = false
  }, [windowKey, appliedFilters, marketStatus, listingSummary])

  const loadHistory = useCallback(async (variantId: string) => {
    if (!variantId) return
    setLoadingHistory(true)
    try {
      const to = new Date()
      const from = new Date(to.getTime() - 6 * 60 * 60 * 1000)
      const payload = await getListingsHistory({
        variantId,
        from: from.toISOString(),
        to: to.toISOString(),
        resolution: '5m',
      })
      setHistory(payload)
    } catch {
      setHistory(null)
    } finally {
      setLoadingHistory(false)
    }
  }, [])

  useEffect(() => {
    if (initDoneRef.current) return
    initDoneRef.current = true

    let hydrated = false
    try {
      const raw = sessionStorage.getItem(LISTING_CACHE_KEY)
      if (raw) {
        const parsed = JSON.parse(raw) as ListingCachePayload
        if (parsed && parsed.data && Number.isFinite(Number(parsed.savedAt))) {
          const d = parsed.data
          setWindowKey(d.windowKey || '30m')
          setFilters(d.filters || defaultFilters)
          setAppliedFilters(d.appliedFilters || defaultFilters)
          setSelectedPreset(String(d.selectedPreset || LISTING_DEFAULT_PRESET_ID))
          setMarketStatus(d.marketStatus || null)
          setListingSourceStatus(d.listingSourceStatus || null)
          setListingSummary(d.listingSummary || null)
          setNewListings(Array.isArray(d.newListings) ? d.newListings : [])
          setRaceListings(Array.isArray(d.raceListings) ? d.raceListings : [])
          setNewSource(String(d.newSource || ''))
          setRaceSource(String(d.raceSource || ''))
          setNewSourceError(String(d.newSourceError || ''))
          setRaceSourceError(String(d.raceSourceError || ''))
          setRaceEffectiveWindow(normalizeWindowKey(d.raceEffectiveWindow || d.windowKey || '30m', '30m'))
          setListingSignals(Array.isArray(d.listingSignals) ? d.listingSignals : [])
          setLivePulseTs(String(d.livePulseTs || ''))
          setLoading(false)
          setRefreshing(false)
          firstLoadRef.current = false
          hydrated = true

          const savedAt = Number(parsed.savedAt || 0)
          const ageMs = Date.now() - savedAt
          if (ageMs > 0 && ageMs < autoRefreshMs) {
            skipNextRequestLoadRef.current = true
            nextRefreshAtRef.current = savedAt + autoRefreshMs
            setNextRefreshSec(Math.ceil(Math.max(0, nextRefreshAtRef.current - Date.now()) / 1000))
          } else {
            requestKeyRef.current = feedRequestKey
            lastAutoRefreshAtRef.current = Date.now()
            scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
            void load({ includeContext: true })
          }
        }
      }
    } catch {
      // cache read is best effort
    }

    if (!hydrated) {
      requestKeyRef.current = feedRequestKey
      lastAutoRefreshAtRef.current = Date.now()
      scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
      void load({ includeContext: true })
      return
    }

    try {
      const raw = sessionStorage.getItem(LISTING_CACHE_KEY)
      if (raw) {
        const parsed = JSON.parse(raw) as ListingCachePayload
        const savedAt = Number(parsed?.savedAt || 0)
        const ageMs = Date.now() - savedAt
        if (ageMs >= autoRefreshMs) {
          requestKeyRef.current = feedRequestKey
          lastAutoRefreshAtRef.current = Date.now()
          scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
          void load({ includeContext: true })
        }
      }
    } catch {
      // ignore stale-cache refresh errors
    }
  }, [autoRefreshMs, defaultFilters, feedRequestKey, load, scheduleNextAutoRefresh])

  useEffect(() => {
    if (!initDoneRef.current) return
    if (skipNextRequestLoadRef.current) {
      skipNextRequestLoadRef.current = false
      requestKeyRef.current = feedRequestKey
      return
    }
    if (requestKeyRef.current === feedRequestKey) return
    const prev = requestKeyRef.current
    requestKeyRef.current = feedRequestKey
    lastAutoRefreshAtRef.current = Date.now()
    scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
    let includeContext = true
    if (prev) {
      try {
        const p = JSON.parse(prev) as { windowKey?: string }
        includeContext = String(p?.windowKey || '') !== String(windowKey || '')
      } catch {
        includeContext = true
      }
    }
    void load({ includeContext })
  }, [feedRequestKey, load, scheduleNextAutoRefresh, windowKey])

  useEffect(() => {
    const poll = window.setInterval(() => {
      lastAutoRefreshAtRef.current = Date.now()
      scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
      void load({ includeContext: true })
    }, autoRefreshMs)
    const tick = window.setInterval(() => {
      const remain = Math.max(0, Math.ceil((nextRefreshAtRef.current - Date.now()) / 1000))
      setNextRefreshSec(remain)
    }, 1000)
    return () => {
      window.clearInterval(poll)
      window.clearInterval(tick)
    }
  }, [autoRefreshMs, load, scheduleNextAutoRefresh])

  useEffect(() => {
    const scheduleRefresh = (delayMs = 1200) => {
      if (refreshTimerRef.current !== null) return
        refreshTimerRef.current = window.setTimeout(() => {
        refreshTimerRef.current = null
        void load({ includeContext: false })
      }, delayMs)
    }

    const es = subscribeListingsStream(
      (evt) => {
        const payload = evt.payload as ListingItemPro & ListingRaceItemPro & ListingEventItem
        const listingKey = listingKeyFromRow(payload)
        const variantId = String(payload?.variant_id || '').trim()

        if (evt.type === 'listing.new' || evt.type === 'listing.price_changed' || evt.type === 'listing.removed') {
          setLivePulseTs(evt.ts || new Date().toISOString())

          if (evt.type === 'listing.new') {
            setNewListings((prev) => {
              const next = [payload as ListingItemPro, ...prev.filter((x) => listingKeyFromRow(x) !== listingKey || !listingKey)]
              return next.slice(0, 300)
            })
          } else if (evt.type === 'listing.price_changed') {
            setRaceListings((prev) => {
              const next = [payload as ListingRaceItemPro, ...prev.filter((x) => listingKeyFromRow(x) !== listingKey || !listingKey)]
              return next.slice(0, 250)
            })
          } else if (evt.type === 'listing.removed') {
            setNewListings((prev) => prev.filter((x) => {
              if (listingKey && listingKeyFromRow(x) === listingKey) return false
              if (variantId && String(x.variant_id || '') === variantId) return false
              return true
            }))
            setRaceListings((prev) => prev.filter((x) => {
              if (listingKey && listingKeyFromRow(x) === listingKey) return false
              if (variantId && String(x.variant_id || '') === variantId) return false
              return true
            }))
            setListingSignals((prev) => prev.filter((x) => {
              if (listingKey && String(x.listing_key || '').trim() === listingKey) return false
              if (variantId && String(x.variant_id || '').trim() === variantId) return false
              return true
            }))
          }

          streamBurstRef.current += 1
          if (evt.type === 'listing.removed') {
            scheduleRefresh(250)
          } else if (streamBurstRef.current % 8 === 0) {
            scheduleRefresh(1200)
          }
        }
      },
      undefined,
      {
        window: windowKey,
        intervalSec: 2.0,
        limit: 200,
        includeLowPriority: appliedFilters.includeLowPriority,
        events: LISTINGS_STREAM_EVENTS,
      },
    )
    return () => {
      es.close()
      if (refreshTimerRef.current !== null) {
        window.clearTimeout(refreshTimerRef.current)
        refreshTimerRef.current = null
      }
    }
  }, [load, windowKey, appliedFilters.includeLowPriority])

  useEffect(() => {
    const actionFilter = String(appliedFilters.action || '').trim().toUpperCase()
    const minScore = Number(appliedFilters.edgeRankMin || 0)
    const query = String(appliedFilters.q || '').trim().toLowerCase()
    const es = subscribeSignalsStream(
      (sig) => {
        const sigAction = String(sig.type || sig.action || '').toUpperCase()
        if (actionFilter && sigAction && sigAction !== actionFilter) return
        const sigScore = Number(sig.score100 || 0)
        if (Number.isFinite(sigScore) && sigScore < minScore) return
        if (query) {
          const hay = [
            sig.collection,
            sig.model,
            sig.background,
            sig.pattern,
            sig.variant_label,
            sig.variant_id,
          ]
            .map((x) => String(x || '').toLowerCase())
            .join(' ')
          if (!hay.includes(query)) return
        }
        setListingSignals((prev) => normalizeListingSignalsRows([sig, ...prev], 120))
        setLivePulseTs(String(sig.ts || new Date().toISOString()))
      },
      undefined,
      {
        mode: 'tz',
        limit: 120,
        dedupeTtlSec: 600,
      },
    )
    return () => {
      es.close()
    }
  }, [appliedFilters.action, appliedFilters.edgeRankMin, appliedFilters.q])

  useEffect(() => {
    if (!selectedVariantId) return
    void loadHistory(selectedVariantId)
  }, [selectedVariantId, loadHistory])

  useEffect(() => {
    if (loading) return
    try {
      const payload: ListingCachePayload = {
        savedAt: Date.now(),
        data: {
          windowKey,
          filters,
          appliedFilters,
          selectedPreset,
          marketStatus,
          listingSourceStatus,
          listingSummary,
          newListings,
          raceListings,
          newSource,
          raceSource,
          newSourceError,
          raceSourceError,
          raceEffectiveWindow,
          listingSignals,
          livePulseTs,
        },
      }
      sessionStorage.setItem(LISTING_CACHE_KEY, JSON.stringify(payload))
    } catch {
      // cache write is best effort
    }
  }, [
    loading,
    windowKey,
    filters,
    appliedFilters,
    selectedPreset,
    marketStatus,
    listingSourceStatus,
    listingSummary,
    newListings,
    raceListings,
    newSource,
    raceSource,
    newSourceError,
    raceSourceError,
    raceEffectiveWindow,
    listingSignals,
    livePulseTs,
  ])

  const scannerCounters = useMemo(() => {
    const buy = newListings.filter((x) => String(x.action || '').toUpperCase() === 'BUY').length
    const sell = newListings.filter((x) => String(x.action || '').toUpperCase() === 'SELL').length
    const watch = newListings.filter((x) => String(x.action || '').toUpperCase() === 'WATCH').length
    const skip = newListings.filter((x) => String(x.action || '').toUpperCase() === 'SKIP').length
    return { buy, sell, watch, skip }
  }, [newListings])

  const signalCounters = useMemo(() => {
    const out = { buy: 0, sell: 0, watch: 0, skip: 0 }
    for (const row of listingSignals) {
      const action = String(row.type || row.action || '').toUpperCase()
      if (action === 'BUY') out.buy += 1
      else if (action === 'SELL') out.sell += 1
      else if (action === 'WATCH') out.watch += 1
      else if (action === 'SKIP') out.skip += 1
    }
    return out
  }, [listingSignals])

  const proFilterCounters = useMemo(() => {
    const market = marketStatus?.signals_1h || {}
    const summaryNew = Number(listingSummary?.new_total || 0)
    const summaryRace = Number(listingSummary?.relisted_total || 0)
    const newCount = newListings.length > 0 ? newListings.length : summaryNew
    const raceCount = raceListings.length > 0 ? raceListings.length : summaryRace
    const buyCount = Number(market.buy || 0) || signalCounters.buy || scannerCounters.buy
    const sellCount = Number(market.sell || 0) || signalCounters.sell || scannerCounters.sell
    const watchCount = Number(market.watch || 0) || signalCounters.watch || scannerCounters.watch
    const skipCount = Number(market.skip || 0) || signalCounters.skip || scannerCounters.skip
    return {
      newCount: Math.max(0, Math.round(newCount)),
      raceCount: Math.max(0, Math.round(raceCount)),
      buyCount: Math.max(0, Math.round(buyCount)),
      sellCount: Math.max(0, Math.round(sellCount)),
      watchCount: Math.max(0, Math.round(watchCount)),
      skipCount: Math.max(0, Math.round(skipCount)),
    }
  }, [marketStatus, listingSummary, newListings.length, raceListings.length, signalCounters, scannerCounters])

  const listingPrimaryRealtimeAvailable = useMemo(() => {
    const src = String(listingSourceStatus?.source || '').trim().toLowerCase()
    if (!src) return false
    return src.startsWith('mtproto')
  }, [listingSourceStatus])

  const newScannerRealtimeAvailable = useMemo(() => {
    if (!listingPrimaryRealtimeAvailable) return false
    const src = String(newSource || '').trim().toLowerCase()
    const err = String(newSourceError || '').trim().toLowerCase()
    if (!src.startsWith('mtproto')) return false
    return !err
  }, [listingPrimaryRealtimeAvailable, newSource, newSourceError])

  const raceScannerRealtimeAvailable = useMemo(() => {
    if (!listingPrimaryRealtimeAvailable) return false
    const src = String(raceSource || '').trim().toLowerCase()
    const err = String(raceSourceError || '').trim().toLowerCase()
    if (!src.startsWith('mtproto')) return false
    return !err
  }, [listingPrimaryRealtimeAvailable, raceSource, raceSourceError])

  const marketSourceWarning = useMemo(() => {
    const sourceError = String(listingSourceStatus?.last_error || listingSourceStatus?.error || '').trim()
    if (!sourceError) return ''
    const normalized = sourceError.toLowerCase()
    if (
      normalized === 'unknown_error'
      || normalized === 'request_failed'
      || normalized === 'failed to fetch'
      || normalized.startsWith('typeerror: failed to fetch')
      || normalized.startsWith('networkerror when attempting to fetch resource')
    ) return ''
    const status = String(listingSourceStatus?.status || '').toLowerCase()
    const degraded = Boolean(listingSourceStatus?.degraded) || status === 'degraded' || listingSourceStatus?.ok === false
    if (degraded) return sourceError
    return ''
  }, [listingSourceStatus])

  const newScannerHint = useMemo(() => {
    if (!listingPrimaryRealtimeAvailable) {
      return 'NEW Scanner требует MTProto источник. Сейчас realtime-источник недоступен.'
    }
    const err = String(newSourceError || '').trim().toLowerCase()
    if (err.includes('source_not_mtproto_api')) return 'NEW Scanner требует MTProto источник. Сейчас realtime-источник недоступен.'
    if (err.includes('http 500') || err.includes('internal server error') || err.includes('runtime_error')) {
      return 'NEW Scanner временно недоступен (ошибка сервера). Обновите страницу через 10-20 секунд.'
    }
    if (err) return `NEW Scanner временно недоступен: ${newSourceError}`
    return `NEW Scanner пуст за окно ${windowKey} (новые лоты не обнаружены).`
  }, [listingPrimaryRealtimeAvailable, newSourceError, windowKey])

  const raceScannerHint = useMemo(() => {
    if (!listingPrimaryRealtimeAvailable) {
      return 'RACE Scanner требует MTProto источник. Сейчас realtime-источник недоступен.'
    }
    const err = String(raceSourceError || '').trim()
    const errNorm = err.toLowerCase()
    if (errNorm.includes('http 500') || errNorm.includes('internal server error') || errNorm.includes('runtime_error')) {
      return 'RACE Scanner временно недоступен (ошибка сервера). Обновите страницу через 10-20 секунд.'
    }
    if (err) return `RACE Scanner временно недоступен: ${raceSourceError}`
    return `RACE Scanner пуст за окно ${windowKey} (изменения цен не зафиксированы).`
  }, [listingPrimaryRealtimeAvailable, raceEffectiveWindow, raceSourceError, windowKey])

  const sortedNewListings = useMemo(() => {
    if (!newListings.length) return []
    const nowMs = Date.now()
    const rows = [...newListings]
    const specs = newSortSpec.length
      ? newSortSpec
      : [
          { field: 'edgeRank100', dir: 'desc' as const },
          { field: 'expected_profit_pct', dir: 'desc' as const },
          { field: 'age', dir: 'asc' as const },
        ]
    rows.sort((a, b) => {
      for (const spec of specs) {
        const av = listingSortValue(a, spec.field, nowMs)
        const bv = listingSortValue(b, spec.field, nowMs)
        const cmp = compareValues(av, bv, spec.dir)
        if (cmp !== 0) return cmp
      }
      return 0
    })
    return rows
  }, [newListings, newSortSpec])

  const sortedRaceListings = useMemo(() => {
    if (!raceListings.length) return []
    const rows = [...raceListings]
    const specs = raceSortSpec.length
      ? raceSortSpec
      : [
          { field: 'delta_pct', dir: 'desc' as const },
          { field: 'edgeRank100', dir: 'desc' as const },
        ]
    rows.sort((a, b) => {
      for (const spec of specs) {
        const av = raceSortValue(a, spec.field)
        const bv = raceSortValue(b, spec.field)
        const cmp = compareValues(av, bv, spec.dir)
        if (cmp !== 0) return cmp
      }
      return 0
    })
    return rows
  }, [raceListings, raceSortSpec])

  const floorSeries: MetricPoint[] = useMemo(
    () => ((history?.series?.floor || []).map((x) => ({ ts: x.ts, value: x.v })) as MetricPoint[]),
    [history],
  )

  const sortedListingSignals = useMemo(() => {
    if (!listingSignals.length) return []
    const rows = [...listingSignals]
    const specs = listingSignalSortSpec.length
      ? listingSignalSortSpec
      : [
          { field: 'ts', dir: 'desc' as const },
          { field: 'score100', dir: 'desc' as const },
        ]
    rows.sort((a, b) => {
      for (const spec of specs) {
        const av = listingSignalSortValue(a, spec.field)
        const bv = listingSignalSortValue(b, spec.field)
        const cmp = compareValues(av, bv, spec.dir)
        if (cmp !== 0) return cmp
      }
      return 0
    })
    return rows
  }, [listingSignals, listingSignalSortSpec])

  const applyPreset = useCallback((preset: string) => {
    setSelectedPreset(preset)
    setFilters((s) => {
      let next: ListingFiltersState
      if (preset === LISTING_DEFAULT_PRESET_ID) {
        next = { ...defaultFilters }
      } else {
        const mapped = LISTING_PROFILE_PRESETS[preset]
        if (!mapped || typeof mapped !== 'object') return s
        next = {
          ...s,
          action: String(mapped.action ?? s.action),
          regime: String(mapped.regime ?? s.regime),
          edgeRankMin: Number.isFinite(Number(mapped.edgeRankMin)) ? Number(mapped.edgeRankMin) : s.edgeRankMin,
          confMin: Number.isFinite(Number(mapped.confMin)) ? Number(mapped.confMin) : s.confMin,
          profitMin: Number.isFinite(Number(mapped.profitMin)) ? Number(mapped.profitMin) : s.profitMin,
          liqMin: Number.isFinite(Number(mapped.liqMin)) ? Number(mapped.liqMin) : s.liqMin,
          lpMax: Number.isFinite(Number(mapped.lpMax)) ? Number(mapped.lpMax) : s.lpMax,
          arMin: Number.isFinite(Number(mapped.arMin)) ? Number(mapped.arMin) : s.arMin,
          vvMin: Number.isFinite(Number(mapped.vvMin)) ? Number(mapped.vvMin) : s.vvMin,
          raceDirection: String(mapped.raceDirection ?? s.raceDirection),
          raceDeltaMin: Number.isFinite(Number(mapped.raceDeltaMin)) ? Number(mapped.raceDeltaMin) : s.raceDeltaMin,
          includeLowPriority: typeof mapped.includeLowPriority === 'boolean' ? mapped.includeLowPriority : s.includeLowPriority,
          onlyProAlerts: typeof mapped.onlyProAlerts === 'boolean' ? mapped.onlyProAlerts : s.onlyProAlerts,
        }
      }
      setAppliedFilters({ ...next })
      return next
    })
  }, [defaultFilters])

  const toggleRow = useCallback((key: string) => {
    if (!key) return
    setExpandedRows((s) => ({ ...s, [key]: !s[key] }))
  }, [])

  const openVariant = useCallback(
    async (row: { variant_id?: string | null; collection_id?: string | null; collection?: string | null; model?: string | null; background?: string | null; pattern?: string | null }) => {
      let variantId = String(row.variant_id || '').trim()
      const fallback = {
        collectionId: String(row.collection_id || '').trim(),
        collection: String(row.collection || '').trim(),
        model: String(row.model || '').trim(),
        background: String(row.background || '').trim(),
        pattern: String(row.pattern || '').trim(),
      }
      if (!variantId && fallback.collection && fallback.model) {
        try {
          const resolved = await resolveVariantByTraits({
            collection: fallback.collection,
            model: fallback.model,
            background: fallback.background || undefined,
            pattern: fallback.pattern || undefined,
            activeOnly: true,
          })
          variantId = String(resolved?.variant_id || '').trim()
        } catch {
          // fallback keeps navigation silent when variant is not resolved
        }
      }
      if (!variantId) return
      navigate(`/variant/${encodeURIComponent(variantId)}`, {
        state: {
          variantFallback: fallback,
        },
      })
    },
    [navigate],
  )

  return (
    <section>
      {/* PageHeader title={pageTitle} subtitle={pageSubtitle} */}
      <PageHeader
        title={pageTitle}
        subtitle={pageSubtitle}
        right={(
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-slate-500">
              Обновление через {formatCountdown(nextRefreshSec)}
            </span>
            <button
              type="button"
              onClick={() => {
                lastAutoRefreshAtRef.current = Date.now()
                scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
                void load()
              }}
              className="gmz-btn gmz-btn-ghost px-3 py-2 text-sm"
            >
              Обновить
            </button>
          </div>
        )}
      />

      <BentoGrid>
        <BentoCard title={blockByType.get('MARKET_CONTEXT_HEADER')?.title || 'Режим рынка и контекст'} className="xl:col-span-12">
          {refreshing ? <div className="mb-2 text-xs font-medium text-slate-500">Обновляем данные блоков…</div> : null}
          {loading ? (
            <LoadingBlock className="h-24" />
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <MetricTile
                  label="Режим"
                  value={`${marketStatus?.market_regime_badge || '🟡'} ${String(marketStatus?.market_regime || 'MEAN_REVERT')}`}
                />
                <MetricTile label="Доверие данным" value={`${Number(marketStatus?.data_conf_pct || 0)}%`} />
                <MetricTile label="Скорость рынка" value={`${Number(marketStatus?.velocity_score || 0)}`} />
                <MetricTile label="Источник" value={String(listingSourceStatus?.source || marketStatus?.source || 'n/a')} />
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <MetricTile label="Скорость объема" value={Number(marketStatus?.flow?.volume_velocity || 0).toFixed(2)} />
                <MetricTile label="Поглощение" value={Number(marketStatus?.flow?.absorption || 0).toFixed(2)} />
                <MetricTile label="Давление листинга" value={Number(marketStatus?.flow?.listing_pressure || 0).toFixed(2)} />
                <MetricTile label="Ликвидность" value={`${Number(marketStatus?.liquidity?.liquidity_score || 0)}`} />
              </div>
              {marketSourceWarning ? (
                <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  Источник работает в degraded режиме: {marketSourceWarning}
                </div>
              ) : null}
            </>
          )}
        </BentoCard>

        <BentoCard title={blockByType.get('FILTER_BAR')?.title || 'PRO Фильтры'} className="xl:col-span-12">
          {loading ? (
            <div className="space-y-3">
              <LoadingBlock className="h-16" />
              <LoadingBlock className="h-16" />
              <LoadingBlock className="h-16" />
            </div>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
                <MetricTile label="NEW" value={newScannerRealtimeAvailable ? compact(proFilterCounters.newCount) : '—'} />
                <MetricTile label="RACE" value={raceScannerRealtimeAvailable ? compact(proFilterCounters.raceCount) : '—'} />
                <MetricTile label="BUY" value={compact(proFilterCounters.buyCount)} />
                <MetricTile label="SELL" value={compact(proFilterCounters.sellCount)} />
                <MetricTile label="WATCH" value={compact(proFilterCounters.watchCount)} />
                <MetricTile label="SKIP" value={compact(proFilterCounters.skipCount)} />
              </div>

              <div className="mt-3 grid grid-cols-4 gap-2">
                <button
                  type="button"
                  className={`gmz-btn w-full px-3 py-2 text-xs ${selectedPreset === LISTING_DEFAULT_PRESET_ID ? 'gmz-btn-primary' : 'gmz-btn-ghost'}`}
                  onClick={() => applyPreset(LISTING_DEFAULT_PRESET_ID)}
                >
                  По умолчанию
                </button>
                {(primaryPresetItems.length ? primaryPresetItems : [{ id: 'default', label: 'Базовый PRO' } as ListingPresetItem]).map((preset) => (
                  <button
                    key={preset.id}
                    type="button"
                    className={`gmz-btn w-full px-3 py-2 text-xs ${selectedPreset === preset.id ? 'gmz-btn-primary' : 'gmz-btn-ghost'}`}
                    onClick={() => applyPreset(preset.id)}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>

              <div className="mt-4 grid gap-3 xl:grid-cols-4">
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Окно</span>
                  <GmzSelect
                    value={windowKey}
                    onChange={(v) => setWindowKey(v as typeof windowKey)}
                    options={[
                      { value: '10m', label: '10m' },
                      { value: '30m', label: '30m' },
                      { value: '1h', label: '1h' },
                      { value: '6h', label: '6h' },
                      { value: '24h', label: '24h' },
                    ]}
                    placeholder="30m"
                  />
                </label>
                {hasProFilter('action') ? (
                  <label className="block">
                    <span className="mb-1 block text-sm font-medium text-slate-700">Действие</span>
                    <GmzSelect
                      value={filters.action}
                      onChange={(v) => setFilters((s) => ({ ...s, action: v }))}
                      options={[
                        { value: '', label: 'Все' },
                        { value: 'BUY', label: 'BUY' },
                        { value: 'SELL', label: 'SELL' },
                        { value: 'WATCH', label: 'WATCH' },
                        { value: 'SKIP', label: 'SKIP' },
                      ]}
                      placeholder="Все"
                    />
                  </label>
                ) : null}
                {hasProFilter('market_regime') ? (
                  <label className="block">
                    <span className="mb-1 block text-sm font-medium text-slate-700">Режим рынка</span>
                    <GmzSelect
                      value={filters.regime}
                      onChange={(v) => setFilters((s) => ({ ...s, regime: v }))}
                      options={[
                        { value: '', label: 'Все' },
                        { value: 'RISK_ON', label: 'RISK_ON' },
                        { value: 'MEAN_REVERT', label: 'MEAN_REVERT' },
                        { value: 'RISK_OFF', label: 'RISK_OFF' },
                        { value: 'PANIC', label: 'PANIC' },
                      ]}
                      placeholder="Все"
                    />
                  </label>
                ) : null}
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Поиск</span>
                  <input
                    value={filters.q}
                    onChange={(e) => setFilters((s) => ({ ...s, q: e.target.value }))}
                    placeholder="Вариант / traits / listing key"
                    className="gmz-input"
                  />
                </label>
              </div>

              <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                {hasProFilter('edgeRank_min') ? (
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-slate-700">Мин. Edge</span>
                    <input type="number" min={0} max={100} value={filters.edgeRankMin} onChange={(e) => setFilters((s) => ({ ...s, edgeRankMin: Number(e.target.value || 0) }))} className="gmz-input" />
                  </label>
                ) : null}
                {hasProFilter('conf_min') ? (
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-slate-700">Мин. Conf</span>
                    <input type="number" min={0} max={100} value={filters.confMin} onChange={(e) => setFilters((s) => ({ ...s, confMin: Number(e.target.value || 0) }))} className="gmz-input" />
                  </label>
                ) : null}
                {hasProFilter('profit_min') ? (
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-slate-700">Мин. Profit %</span>
                    <input type="number" value={filters.profitMin} onChange={(e) => setFilters((s) => ({ ...s, profitMin: Number(e.target.value || 0) }))} className="gmz-input" />
                  </label>
                ) : null}
                {hasProFilter('liq_min') ? (
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-slate-700">Мин. Liquidity</span>
                    <input type="number" min={0} max={100} value={filters.liqMin} onChange={(e) => setFilters((s) => ({ ...s, liqMin: Number(e.target.value || 0) }))} className="gmz-input" />
                  </label>
                ) : null}
                {hasProFilter('lp_max') ? (
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-slate-700">Макс. LP</span>
                    <input type="number" step="0.1" value={filters.lpMax} onChange={(e) => setFilters((s) => ({ ...s, lpMax: Number(e.target.value || 0) }))} className="gmz-input" />
                  </label>
                ) : null}
                {hasProFilter('ar_min') ? (
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-slate-700">Мин. AR</span>
                    <input type="number" step="0.1" value={filters.arMin} onChange={(e) => setFilters((s) => ({ ...s, arMin: Number(e.target.value || 0) }))} className="gmz-input" />
                  </label>
                ) : null}
                {hasProFilter('vv_min') ? (
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium text-slate-700">Мин. VV</span>
                    <input type="number" step="0.1" value={filters.vvMin} onChange={(e) => setFilters((s) => ({ ...s, vvMin: Number(e.target.value || 0) }))} className="gmz-input" />
                  </label>
                ) : null}
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-700">Мин. Race Δ%</span>
                  <input type="number" step="0.1" value={filters.raceDeltaMin} onChange={(e) => setFilters((s) => ({ ...s, raceDeltaMin: Number(e.target.value || 0) }))} className="gmz-input" />
                </label>
              </div>

              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Направление Race</span>
                  <GmzSelect
                    value={filters.raceDirection}
                    onChange={(v) => setFilters((s) => ({ ...s, raceDirection: v }))}
                    options={[
                      { value: 'ANY', label: 'ANY' },
                      { value: 'DOWN', label: 'DOWN' },
                      { value: 'UP', label: 'UP' },
                    ]}
                    placeholder="DOWN"
                  />
                </label>

                {hasProFilter('only_pro_alerts') ? (
                  <label className="flex items-center justify-between gap-3 rounded-xl border border-[var(--line)] bg-[rgba(255,255,255,0.72)] px-3 py-2 text-sm">
                    <span>Только PRO алерты</span>
                    <input type="checkbox" checked={filters.onlyProAlerts} onChange={(e) => setFilters((s) => ({ ...s, onlyProAlerts: e.target.checked }))} className="h-4 w-4" />
                  </label>
                ) : null}

                <label className="flex items-center justify-between gap-3 rounded-xl border border-[var(--line)] bg-[rgba(255,255,255,0.72)] px-3 py-2 text-sm">
                  <span>Показывать race-шум (&lt;0.5%)</span>
                  <input type="checkbox" checked={filters.includeLowPriority} onChange={(e) => setFilters((s) => ({ ...s, includeLowPriority: e.target.checked }))} className="h-4 w-4" />
                </label>
              </div>

              <button type="button" onClick={() => setAppliedFilters({ ...filters })} className="gmz-btn gmz-btn-primary mt-4 w-full px-4 text-sm">
                Применить
              </button>
            </>
          )}
        </BentoCard>

        {error ? <BentoCard className="xl:col-span-12 border-rose-200 bg-rose-50/70 text-sm text-rose-700">Ошибка: {error}</BentoCard> : null}

        <BentoCard title={`${blockByType.get('TABLE_NEW_LISTINGS')?.title || 'NEW Scanner'} ${sortedNewListings.length.toLocaleString('ru-RU')}`} className="xl:col-span-12">
          {loading ? (
            <LoadingBlock className="h-36" />
          ) : sortedNewListings.length ? (
            <div className="gmz-table-wrap">
              <table className="gmz-table">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    {newColumns.map((c) => (
                      <th key={c} className="pb-2 pr-4">
                        {NEW_COLUMN_LABELS[c] || c}
                      </th>
                    ))}
                    <th className="pb-2">Open</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedNewListings.slice(0, 120).map((row) => {
                    const rowKey = String(row.listing_key || row.listing_id || row.variant_id || '')
                    const expanded = !!expandedRows[rowKey]
                    return (
                      <Fragment key={rowKey}>
                        <tr
                          className="cursor-pointer border-b border-slate-100"
                          onClick={() => {
                            toggleRow(rowKey)
                            if (row.variant_id) setSelectedVariantId(String(row.variant_id))
                          }}
                        >
                          {newColumns.map((col) => {
                            if (col === 'age') return <td key={col} className="py-2 pr-4 tabular-nums">{ago(row.ts_detected)}</td>
                            if (col === 'variant_label') {
                              return (
                                <td key={col} className="py-2 pr-4">
                                  <div className="flex items-center gap-2 text-left text-xs text-slate-700">
                                    <img
                                      src={String(row.preview_url || '/favicon.png')}
                                      alt={row.variant_label || 'gift'}
                                      className="h-8 w-8 rounded-lg border border-slate-200 object-cover"
                                      loading="lazy"
                                      onError={(e) => {
                                        const img = e.currentTarget
                                        if (img.dataset.fallbackDone === '1') return
                                        img.dataset.fallbackDone = '1'
                                        img.src = '/favicon.png'
                                      }}
                                    />
                                    <span>{row.variant_label || '—'}</span>
                                  </div>
                                </td>
                              )
                            }
                            if (col === 'price_ton') return <td key={col} className="py-2 pr-4 tabular-nums">{ton(row.price_ton)} TON</td>
                            if (col === 'floor_ton') return <td key={col} className="py-2 pr-4 tabular-nums">{ton(row.floor_ton)} TON</td>
                            if (col === 'fair_ton') return <td key={col} className="py-2 pr-4 tabular-nums">{ton(row.fair_ton)} TON</td>
                            if (col === 'undervalue_pct') return <td key={col} className="py-2 pr-4 tabular-nums">{num(row.undervalue_pct, 1)}%</td>
                            if (col === 'edgeRank100') return <td key={col} className="py-2 pr-4 tabular-nums font-semibold">{num(row.edgeRank100, 1)}</td>
                            if (col === 'score100') return <td key={col} className="py-2 pr-4 tabular-nums">{num(row.score100, 1)}</td>
                            if (col === 'conf_pct') return <td key={col} className="py-2 pr-4 tabular-nums">{num(row.conf_pct, 1)}%</td>
                            if (col === 'expected_profit_pct') return <td key={col} className="py-2 pr-4 tabular-nums">{num(row.expected_profit_pct, 1)}%</td>
                            if (col === 'market_regime_badge') return <td key={col} className="py-2 pr-4">{row.market_regime_badge || '🟡'}</td>
                            if (col === 'liquidity_score') return <td key={col} className="py-2 pr-4 tabular-nums">{num(row.liquidity_score, 0)}</td>
                            if (col === 'absorption_30m') return <td key={col} className="py-2 pr-4 tabular-nums">{num(row.absorption_30m, 2)}</td>
                            if (col === 'listing_pressure') return <td key={col} className="py-2 pr-4 tabular-nums">{num(row.listing_pressure, 2)}</td>
                            if (col === 'depth_score') return <td key={col} className="py-2 pr-4 tabular-nums">{num(row.depth_score, 2)}</td>
                            if (col === 'action') {
                              return (
                                <td key={col} className="py-2 pr-4">
                                  <span className="rounded-full bg-[var(--accent-soft)] px-2 py-1 text-xs font-semibold text-[var(--accent)]">
                                    {row.action || 'WATCH'}{row.strength_tag && row.strength_tag !== 'NONE' ? ` · ${row.strength_tag}` : ''}
                                  </span>
                                </td>
                              )
                            }
                            return <td key={col} className="py-2 pr-4 text-xs text-slate-500">—</td>
                          })}
                          <td className="py-2">
                            <button
                              type="button"
                              className="gmz-btn gmz-btn-ghost rounded-lg px-2 py-1 text-xs font-semibold text-[var(--accent)]"
                              onClick={(e) => {
                                e.stopPropagation()
                                void openVariant(row)
                              }}
                            >
                              Карточка
                            </button>
                          </td>
                        </tr>
                        {expanded ? (
                          <tr className="border-b border-slate-100 bg-slate-50/55">
                            <td colSpan={newColumns.length + 1} className="px-3 py-2 text-xs text-slate-700">
                              <div className="grid gap-2 xl:grid-cols-4">
                                <div>
                                  <div className="font-semibold">План</div>
                                  <div>Target: {row.target_ton ? `${ton(row.target_ton)} TON` : '—'}</div>
                                  <div>Stop: {row.stop_ton ? `${ton(row.stop_ton)} TON` : '—'}</div>
                                  <div>Latency: {row.latency_ms ?? '—'} ms</div>
                                </div>
                                <div>
                                  <div className="font-semibold">Причины</div>
                                  <div>{(row.reasons || []).slice(0, 3).join(' · ') || '—'}</div>
                                  <div className="mt-1 font-semibold">Риски</div>
                                  <div>{(row.risk_flags || []).slice(0, 3).join(' · ') || '—'}</div>
                                </div>
                                <div>
                                  <div className="font-semibold">Decision trace</div>
                                  <div>Mode: {row.decision_trace?.mode || '—'}</div>
                                  <div>Resolved: {row.decision_trace?.resolved_action || row.action || '—'}</div>
                                  <div>Liq/AR/LP: {num(row.decision_trace?.liquidity_norm, 3)} / {num(row.decision_trace?.absorption_30m, 3)} / {num(row.decision_trace?.listing_pressure, 3)}</div>
                                </div>
                                <div>
                                  <div className="font-semibold">Edge math</div>
                                  <div>EP/S/L: {num(row.edge_norms?.EP, 3)} / {num(row.edge_norms?.S, 3)} / {num(row.edge_norms?.L, 3)}</div>
                                  <div>AR/D/LP: {num(row.edge_norms?.AR, 3)} / {num(row.edge_norms?.D, 3)} / {num(row.edge_norms?.LP, 3)}</div>
                                  <div>C: {num(row.edge_norms?.C, 3)}</div>
                                </div>
                              </div>
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-sm text-slate-500">{newScannerHint}</div>
          )}
        </BentoCard>

        <BentoCard title={`${blockByType.get('TABLE_RACE_MODE')?.title || 'RACE Scanner'} ${sortedRaceListings.length.toLocaleString('ru-RU')}${raceEffectiveWindow !== windowKey ? ` · ${raceEffectiveWindow}` : ''}`} className="xl:col-span-12">
          {loading ? (
            <LoadingBlock className="h-28" />
          ) : sortedRaceListings.length ? (
            <div className="gmz-table-wrap">
              <table className="gmz-table">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    {raceColumns.map((c) => (
                      <th key={c} className="pb-2 pr-4">
                        {RACE_COLUMN_LABELS[c] || c}
                      </th>
                    ))}
                    <th className="pb-2">Open</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedRaceListings.slice(0, 120).map((row, idx) => (
                    <tr key={`${row.listing_key || idx}-${row.ts_detected || ''}`} className="border-b border-slate-100">
                      {raceColumns.map((col) => {
                        if (col === 'variant_label') {
                          const label = String(
                            row.variant_label
                            || [row.collection, row.model, row.background, row.pattern].filter(Boolean).join(' • ')
                            || row.variant_id
                            || '—',
                          )
                          return (
                            <td key={col} className="py-2 pr-4">
                              <div className="flex items-center gap-2 text-left text-xs text-slate-700">
                                <img
                                  src={String(row.preview_url || '/favicon.png')}
                                  alt={label}
                                  className="h-8 w-8 rounded-lg border border-slate-200 object-cover"
                                  loading="lazy"
                                  onError={(e) => {
                                    const img = e.currentTarget
                                    if (img.dataset.fallbackDone === '1') return
                                    img.dataset.fallbackDone = '1'
                                    img.src = '/favicon.png'
                                  }}
                                />
                                <span className="truncate">{label}</span>
                              </div>
                            </td>
                          )
                        }
                        if (col === 'prev_price_ton') return <td key={col} className="py-2 pr-4 tabular-nums">{ton(row.prev_price_ton)} TON</td>
                        if (col === 'price_ton') return <td key={col} className="py-2 pr-4 tabular-nums">{ton(row.price_ton)} TON</td>
                        if (col === 'delta_pct') {
                          return (
                            <td key={col} className="py-2 pr-4 tabular-nums">
                              {num(row.delta_pct, 2)}%
                              {row.low_priority ? <span className="ml-1 rounded bg-slate-200 px-1 text-[10px] text-slate-700">noise</span> : null}
                            </td>
                          )
                        }
                        if (col === 'direction') return <td key={col} className="py-2 pr-4">{row.direction || '—'}</td>
                        if (col === 'edgeRank100') return <td key={col} className="py-2 pr-4 tabular-nums">{row.edgeRank100 === null || row.edgeRank100 === undefined ? '—' : Number(row.edgeRank100).toFixed(1)}</td>
                        if (col === 'market_regime_badge') return <td key={col} className="py-2 pr-4">{row.market_regime_badge || '🟡'}</td>
                        if (col === 'action') return <td key={col} className="py-2 pr-4">{row.action || '—'}</td>
                        return <td key={col} className="py-2 pr-4 text-xs text-slate-500">—</td>
                      })}
                      <td className="py-2">
                        <button
                          type="button"
                          className="gmz-btn gmz-btn-ghost rounded-lg px-2 py-1 text-xs font-semibold text-[var(--accent)]"
                          onClick={() => {
                            void openVariant(row)
                          }}
                        >
                          Карточка
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-sm text-slate-500">{raceScannerHint}</div>
          )}
        </BentoCard>

        <BentoCard title={blockByType.get('METRICS_PANEL')?.title || 'Execution Health'} className="xl:col-span-12">
          {loading ? (
            <LoadingBlock className="h-24" />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
              {executionHealthMetrics.map((metricId) => {
                const eh = marketStatus?.execution_health
                if (metricId === 'detect_latency_p95') {
                  return <MetricTile key={metricId} label="Detect p95" value={`${Number(eh?.detect_latency_p95 || 0)} ms`} />
                }
                if (metricId === 'detect_latency_p99') {
                  return <MetricTile key={metricId} label="Detect p99" value={`${Number(eh?.detect_latency_p99 || 0)} ms`} />
                }
                if (metricId === 'miss_rate') {
                  return <MetricTile key={metricId} label="Miss rate" value={`${Number(eh?.miss_rate || 0).toFixed(2)}%`} />
                }
                if (metricId === 'duplicate_rate') {
                  return <MetricTile key={metricId} label="Duplicate rate" value={`${Number(eh?.duplicate_rate || 0).toFixed(2)}%`} />
                }
                if (metricId === 'sse_disconnect_rate') {
                  return (
                    <MetricTile
                      key={metricId}
                      label="SSE disconnect"
                      value={
                        livePulseTs
                          ? `${Number(eh?.sse_disconnect_rate || 0).toFixed(2)}%`
                          : 'n/a'
                      }
                    />
                  )
                }
                return (
                  <MetricTile
                    key={metricId}
                    label={metricId}
                    value="n/a"
                  />
                )
              })}
            </div>
          )}
        </BentoCard>

        <BentoCard title="История выбранного варианта" className="xl:col-span-12">
          {!selectedVariantId ? (
            <div className="text-sm text-slate-500">Выберите строку в NEW scanner, чтобы увидеть историю.</div>
          ) : loadingHistory ? (
            <LoadingBlock className="h-32" />
          ) : history ? (
            <div className="space-y-3">
              <div className="text-xs text-slate-500">
                {history.variant_id} | {history.resolution} | {history.from} - {history.to}
              </div>
              <Sparkline points={floorSeries} color="#2563eb" fill="rgba(37,99,235,0.14)" label="Floor history" />
            </div>
          ) : (
            <div className="text-sm text-slate-500">Не удалось загрузить историю по выбранному варианту.</div>
          )}
        </BentoCard>

        <BentoCard title={`${blockByType.get('TABLE_LISTING_SIGNALS')?.title || 'Сигналы листинга'} ${sortedListingSignals.length.toLocaleString('ru-RU')}`} className="xl:col-span-12">
          {loading ? (
            <LoadingBlock className="h-24" />
          ) : sortedListingSignals.length ? (
            <div className="gmz-table-wrap">
              <table className="gmz-table">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    {listingSignalColumns.map((col) => (
                      <th key={col} className="pb-2 pr-4">{LISTING_SIGNALS_COLUMN_LABELS[col] || col}</th>
                    ))}
                    <th className="pb-2">Open</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedListingSignals.slice(0, 120).map((row) => {
                    const label = String(
                      row.variant_label
                      || [row.collection, row.model, row.background, row.pattern].filter(Boolean).join(' • ')
                      || row.variant_id
                      || '—',
                    )
                    const rowKey = listingSignalStableKey(row)
                    const action = String(row.type || row.action || 'WATCH').toUpperCase()
                    return (
                      <tr
                        key={rowKey}
                        className="cursor-pointer border-b border-slate-100"
                        onClick={() => {
                          if (row.variant_id) setSelectedVariantId(String(row.variant_id))
                          void openVariant(row)
                        }}
                      >
                        {listingSignalColumns.map((col) => {
                          if (col === 'variant_label') {
                            return (
                              <td key={col} className="py-2 pr-4">
                                <div className="flex items-center gap-2 text-left text-xs text-slate-700">
                                  <img
                                    src={String(row.preview_url || '/favicon.png')}
                                    alt={label}
                                    className="h-8 w-8 rounded-lg border border-slate-200 object-cover"
                                    loading="lazy"
                                    onError={(e) => {
                                      const img = e.currentTarget
                                      if (img.dataset.fallbackDone === '1') return
                                      img.dataset.fallbackDone = '1'
                                      img.src = '/favicon.png'
                                    }}
                                  />
                                  <span className="truncate">{label}</span>
                                </div>
                              </td>
                            )
                          }
                          if (col === 'action') {
                            return (
                              <td key={col} className="py-2 pr-4">
                                <span className="rounded-full bg-[var(--accent-soft)] px-2 py-1 text-xs font-semibold text-[var(--accent)]">{action}</span>
                              </td>
                            )
                          }
                          if (col === 'score100') return <td key={col} className="py-2 pr-4 tabular-nums">{num(row.score100, 1)}</td>
                          if (col === 'conf_pct') return <td key={col} className="py-2 pr-4 tabular-nums">{num(row.conf_pct, 1)}%</td>
                          if (col === 'floor_ton') return <td key={col} className="py-2 pr-4 tabular-nums">{ton(row.floor_ton)} TON</td>
                          if (col === 'fair_ton') return <td key={col} className="py-2 pr-4 tabular-nums">{ton(row.fair_ton)} TON</td>
                          return <td key={col} className="py-2 pr-4 text-xs text-slate-500">—</td>
                        })}
                        <td className="py-2">
                          <button
                            type="button"
                            className="gmz-btn gmz-btn-ghost rounded-lg px-2 py-1 text-xs font-semibold text-[var(--accent)]"
                            onClick={(e) => {
                              e.stopPropagation()
                              void openVariant(row)
                            }}
                          >
                            Карточка
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-sm text-slate-500">Сигналы листинга пока отсутствуют по текущим фильтрам.</div>
          )}
        </BentoCard>
      </BentoGrid>
    </section>
  )
}
