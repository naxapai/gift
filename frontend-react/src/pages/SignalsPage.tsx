import { Fragment, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import signalsBentoRaw from '../../../config/signals/bento_ui_signals_blocks.json'
import signalsUiRaw from '../../../config/signals/frontend_signals_ui_mapping.json'
import signalsProUiRaw from '../../../config/signals/signals_page_pro_ui_mapping.json'
import { BentoCard } from '../components/BentoCard'
import { BentoGrid } from '../components/BentoGrid'
import { GmzSelect } from '../components/GmzSelect'
import { LoadingBlock } from '../components/LoadingBlock'
import { MetricTile } from '../components/MetricTile'
import { PageHeader } from '../components/PageHeader'
import { getMarketStatus, getSignalsPage, signalPercent, signalTypeRu, subscribeSignalsStream, ton } from '../lib/api'
import { readUiAutoRefreshMinutes, uiAutoRefreshMs } from '../lib/uiSettings'
import type { MarketStatusResponse, SignalItem } from '../types/api'
import { SignalDetailsDrawer } from '../components/SignalDetailsDrawer'

type SignalAction = 'BUY' | 'SELL' | 'WATCH' | 'SKIP'
type MarketRegime = 'RISK_ON' | 'MEAN_REVERT' | 'RISK_OFF' | 'PANIC'

type UiFilter = {
  id?: string
  ui?: string
  type?: string
  min?: number
  max?: number
  step?: number
  fields?: string[]
  default?: number | boolean | string | string[]
  options?: string[]
}

type UiColumn = {
  id?: string
  ui?: string
  width?: number
  sticky?: string
}

type UiPreset = {
  id?: string
  ui?: string
  expr?: string
}

type UiSort = {
  field?: string
  dir?: 'asc' | 'desc' | string
}

type UiDefaults = {
  window?: string
  sort?: UiSort[]
  autoRefresh?: boolean
  realtime?: boolean
  filters?: Record<string, unknown>
}

type UiMapping = {
  page?: string
  filters?: UiFilter[]
  columns?: UiColumn[]
}

type SignalsProUi = {
  title?: string
  description?: string
  defaults?: UiDefaults
  data?: {
    http?: {
      feed?: { method?: string; url?: string }
      market?: { method?: string; url?: string }
    }
    realtime?: { transport?: string; endpoint?: string; event?: string }
  }
  columns?: UiColumn[]
  filters?: UiFilter[]
  presets?: UiPreset[]
  row_expand?: {
    sections?: Array<{ id?: string; ui?: string; type?: string; path?: string; maxItems?: number; items?: Array<{ k?: string; path?: string }> }>
  }
}
type RowSection = NonNullable<NonNullable<SignalsProUi['row_expand']>['sections']>[number]

type BentoBlock = {
  id?: string
  type?: string
  title?: string
}

type BentoMapping = {
  title?: string
  description?: string
  blocks?: BentoBlock[]
}

type AppliedFilters = {
  actions: SignalAction[]
  regimes: MarketRegime[]
  minScore?: number
  edgeRankMin: number
  confMin: number
  profitMin: number
  liqMin: number
  lpMax: number
  arMin: number
  vvMin: number
  q: string
  onlyProAlerts: boolean
  onlyNew: boolean
  minUndervalue?: number
  maxRisk?: number
}

interface SignalsCachePayload {
  savedAt: number
  data: {
    rows: SignalItem[]
    totalCount: number | null
    hasMore: boolean
    nextCursor: string | null
    marketStatus: MarketStatusResponse | null
    applied: AppliedFilters
    filtersUi: {
      actions: SignalAction[]
      regimes: MarketRegime[]
      minScore: string
      edgeRankMin: number
      confMin: number
      profitMin: number
      liqMin: number
      lpMax: number
      arMin: number
      vvMin: number
      searchQ: string
      onlyNew: boolean
      onlyProAlerts: boolean
      minUndervalue: string
      maxRisk: string
      presetId: string
    }
  }
}

const SIGNALS_UI = (signalsUiRaw || {}) as UiMapping
const SIGNALS_BENTO = (signalsBentoRaw || {}) as BentoMapping
const SIGNALS_PRO_UI = (signalsProUiRaw || {}) as SignalsProUi
const SIGNALS_PRO_FILTER_DEFAULTS = (SIGNALS_PRO_UI.defaults?.filters || {}) as Record<string, unknown>
const RELAXED_PRESET_ID = 'default_relaxed'
const STRICT_PRESET_ID = 'pro_alerts'
const DEFAULT_PRESET_ID = String(SIGNALS_PRO_FILTER_DEFAULTS.preset_id || RELAXED_PRESET_ID).trim() || RELAXED_PRESET_ID
const USE_RELAXED_DEFAULT = DEFAULT_PRESET_ID === RELAXED_PRESET_ID

function bentoBlockTitle(type: string, fallback: string): string {
  const rows = Array.isArray(SIGNALS_BENTO.blocks) ? SIGNALS_BENTO.blocks : []
  const found = rows.find((x) => String(x?.type || '') === type)
  const title = String(found?.title || '').trim()
  return title || fallback
}

const DEFAULT_WINDOW = String(SIGNALS_PRO_UI.defaults?.window || '30m')
const DEFAULT_SORT = (Array.isArray(SIGNALS_PRO_UI.defaults?.sort) ? SIGNALS_PRO_UI.defaults?.sort : []) as UiSort[]
const DEFAULT_SORT_BY = String(DEFAULT_SORT[0]?.field || 'edgeRank100')
const DEFAULT_SORT_DIR = (String(DEFAULT_SORT[0]?.dir || 'desc').toLowerCase() === 'asc' ? 'asc' : 'desc') as 'asc' | 'desc'
const DEFAULT_AUTO_REFRESH = SIGNALS_PRO_UI.defaults?.autoRefresh !== false
const DEFAULT_REALTIME = SIGNALS_PRO_UI.defaults?.realtime !== false
const SIGNALS_CACHE_KEY = 'gmz.signals.cache.v3'
const FEED_ENDPOINT = String(SIGNALS_PRO_UI.data?.http?.feed?.url || '/v1/signals')
const MARKET_ENDPOINT_RAW = String(SIGNALS_PRO_UI.data?.http?.market?.url || '')
const MARKET_ENDPOINT = (() => {
  const raw = MARKET_ENDPOINT_RAW.trim()
  if (!raw) return '/v1/market/status'
  return raw.includes('?') ? (raw.split('?')[0] || '/v1/market/status') : raw
})()
const MARKET_WINDOW = (() => {
  if (!MARKET_ENDPOINT_RAW.includes('?')) return DEFAULT_WINDOW
  const query = MARKET_ENDPOINT_RAW.split('?')[1] || ''
  const params = new URLSearchParams(query)
  const windowValue = String(params.get('window') || '').trim()
  return windowValue || DEFAULT_WINDOW
})()
const REALTIME_ENDPOINT = String(SIGNALS_PRO_UI.data?.realtime?.endpoint || '/v1/stream/signals')
const REALTIME_EVENT = String(SIGNALS_PRO_UI.data?.realtime?.event || 'signal.created')
const SEARCH_FIELDS = (() => {
  const row = (SIGNALS_PRO_UI.filters || []).find((x) => String(x?.id || '') === 'search')
  const fields = Array.isArray(row?.fields) ? row.fields : ['collection', 'model', 'background', 'pattern', 'variant_id', 'variant_label']
  return fields.map((x) => String(x || '').trim()).filter(Boolean)
})()

const DEFAULT_COLUMNS: UiColumn[] = [
  { id: 'action', ui: 'Действие', width: 92, sticky: 'left' },
  { id: 'market_regime_badge', ui: 'Режим', width: 72, sticky: 'left' },
  { id: 'edgeRank100', ui: 'EdgeRank', width: 92 },
  { id: 'edgeRank_profile', ui: 'Профиль', width: 96 },
  { id: 'score100', ui: 'Score', width: 78 },
  { id: 'conf_pct', ui: 'Conf%', width: 74 },
  { id: 'expected_profit_pct', ui: 'Profit%', width: 86 },
  { id: 'undervalue_pct', ui: 'Δ%', width: 68 },
  { id: 'price_ton', ui: 'Цена', width: 78 },
  { id: 'floor_ton', ui: 'Floor', width: 78 },
  { id: 'fair_ton', ui: 'Fair', width: 78 },
  { id: 'target_ton', ui: 'Target', width: 84 },
  { id: 'stop_ton', ui: 'Stop', width: 78 },
  { id: 'liquidity_score', ui: 'Liq', width: 64 },
  { id: 'absorption_30m', ui: 'AR', width: 64 },
  { id: 'listing_pressure', ui: 'LP', width: 64 },
  { id: 'volume_velocity', ui: 'VV', width: 64 },
  { id: 'depth_5pct_count', ui: 'Depth', width: 74 },
  { id: 'variant_label', ui: 'Подарок', width: 300 },
  { id: 'ts', ui: 'Время', width: 170 },
]

const DEFAULT_ROW_SECTIONS: RowSection[] = [
  { id: 'reasons', ui: 'Почему', type: 'list', path: 'reasons', maxItems: 3 },
  { id: 'risks', ui: 'Риски', type: 'list', path: 'risk_flags', maxItems: 3 },
  { id: 'watch_trigger', ui: 'Триггер (WATCH)', type: 'text', path: 'watch_trigger' },
  {
    id: 'edge_math',
    ui: 'EdgeRank математика',
    type: 'kv',
    items: [
      { k: 'EdgeRaw', path: 'edgeRank_raw' },
      { k: 'EdgeRank100', path: 'edgeRank100' },
      { k: 'Профиль', path: 'edgeRank_profile' },
    ],
  },
]

const ROW_HEIGHT = 52
const OVERSCAN = 12
const ACTION_COL_MIN_WIDTH = 128
const REGIME_COL_MIN_WIDTH = 132

function resolveColumnWidth(columnId: string, width: number): number {
  if (columnId === 'action') return Math.max(ACTION_COL_MIN_WIDTH, width)
  if (columnId === 'market_regime_badge') return Math.max(REGIME_COL_MIN_WIDTH, width)
  return width
}

function isCenterColumn(columnId: string): boolean {
  return columnId === 'edgeRank100'
}

function inLastHour(ts?: string): boolean {
  if (!ts) return false
  const t = Date.parse(ts)
  if (!Number.isFinite(t)) return false
  return Date.now() - t <= 60 * 60 * 1000
}

function numOrUndefined(value: string): number | undefined {
  const n = Number(value)
  return Number.isFinite(n) ? n : undefined
}

function cfgDefaultNumber(filterId: string): number | undefined {
  const raw = SIGNALS_PRO_FILTER_DEFAULTS[filterId]
  const n = Number(raw)
  return Number.isFinite(n) ? n : undefined
}

function cfgDefaultBool(filterId: string): boolean | undefined {
  const raw = SIGNALS_PRO_FILTER_DEFAULTS[filterId]
  return typeof raw === 'boolean' ? raw : undefined
}

function cfgDefaultArray<T extends string>(filterId: string): T[] {
  const altId = filterId === 'market_regime' ? 'market_regimes' : filterId
  const raw = SIGNALS_PRO_FILTER_DEFAULTS[filterId] ?? SIGNALS_PRO_FILTER_DEFAULTS[altId]
  if (!Array.isArray(raw)) return []
  return raw.map((x) => String(x || '').toUpperCase()).filter(Boolean) as T[]
}

function filterDefaultNumber(filterId: string, fallback: number): number {
  const fromCfg = cfgDefaultNumber(filterId)
  if (fromCfg !== undefined) return fromCfg
  const f = (SIGNALS_UI.filters || []).find((x) => String(x?.id || '') === filterId)
  const n = Number(f?.default)
  return Number.isFinite(n) ? n : fallback
}

function filterDefaultNumberOptional(filterId: string): number | undefined {
  const fromCfg = cfgDefaultNumber(filterId)
  if (fromCfg !== undefined) return fromCfg
  const f = (SIGNALS_UI.filters || []).find((x) => String(x?.id || '') === filterId)
  const n = Number(f?.default)
  return Number.isFinite(n) ? n : undefined
}

function filterDefaultBool(filterId: string, fallback: boolean): boolean {
  const fromCfg = cfgDefaultBool(filterId)
  if (fromCfg !== undefined) return fromCfg
  const f = (SIGNALS_UI.filters || []).find((x) => String(x?.id || '') === filterId)
  return typeof f?.default === 'boolean' ? f.default : fallback
}

function filterDefaultArray<T extends string>(filterId: string, fallback: T[]): T[] {
  const fromCfg = cfgDefaultArray<T>(filterId)
  if (fromCfg.length) return fromCfg
  const f = (SIGNALS_UI.filters || []).find((x) => String(x?.id || '') === filterId)
  const raw = Array.isArray(f?.default) ? f.default : []
  const out = raw.map((x) => String(x || '').toUpperCase()).filter(Boolean) as T[]
  return out.length ? out : fallback
}

function getFilterDef(filterId: string): UiFilter | undefined {
  const pro = (SIGNALS_PRO_UI.filters || []).find((x) => String(x?.id || '') === filterId)
  if (pro) return pro
  return (SIGNALS_UI.filters || []).find((x) => String(x?.id || '') === filterId)
}

function filterUiLabel(filterId: string, fallback: string): string {
  const ui = String(getFilterDef(filterId)?.ui || '').trim()
  return ui || fallback
}

function filterNumMeta(filterId: string, fallback: { min?: number; max?: number; step?: number }) {
  const f = getFilterDef(filterId)
  const min = Number(f?.min)
  const max = Number(f?.max)
  const step = Number(f?.step)
  return {
    min: Number.isFinite(min) ? min : fallback.min,
    max: Number.isFinite(max) ? max : fallback.max,
    step: Number.isFinite(step) ? step : fallback.step,
  }
}

function byPath(row: SignalItem, path?: string): unknown {
  const p = String(path || '').trim()
  if (!p) return undefined
  const key = p as keyof SignalItem
  return row[key]
}

function toggleValue<T extends string>(rows: T[], value: T): T[] {
  return rows.includes(value) ? rows.filter((x) => x !== value) : [...rows, value]
}

function signalKey(row: SignalItem): string {
  return row.signal_id || `${row.variant_id || ''}|${row.type || row.action || ''}|${row.ts || ''}`
}

function sortFieldValue(row: SignalItem, field: string): number | string {
  if (field === 'ts') {
    const ts = Date.parse(String(row.ts || ''))
    return Number.isFinite(ts) ? ts : 0
  }
  const raw = row[field as keyof SignalItem]
  const n = Number(raw)
  if (Number.isFinite(n)) return n
  return String(raw || '')
}

function sortSignals(rows: SignalItem[], sorts: UiSort[]): SignalItem[] {
  const chain = (Array.isArray(sorts) ? sorts : []).filter((x) => String(x?.field || '').trim())
  return [...rows].sort((a, b) => {
    for (const rule of chain) {
      const field = String(rule.field || '').trim()
      if (!field) continue
      const desc = String(rule.dir || 'desc').toLowerCase() !== 'asc'
      const av = sortFieldValue(a, field)
      const bv = sortFieldValue(b, field)
      if (typeof av === 'number' && typeof bv === 'number') {
        const delta = desc ? (bv - av) : (av - bv)
        if (Math.abs(delta) > 1e-9) return delta
      } else {
        const cmp = String(av).localeCompare(String(bv), 'ru')
        if (cmp !== 0) return desc ? -cmp : cmp
      }
    }
    return String(b.ts || '').localeCompare(String(a.ts || ''))
  })
}

function mergeSignals(prev: SignalItem[], nextRows: SignalItem[], sorts: UiSort[]): SignalItem[] {
  const map = new Map<string, SignalItem>()
  for (const row of prev) {
    const key = signalKey(row)
    if (key) map.set(key, row)
  }
  for (const row of nextRows) {
    const key = signalKey(row)
    if (key) map.set(key, row)
  }
  return sortSignals([...map.values()], sorts)
}

function expectedProfitPct(row: SignalItem): number {
  return signalPercent(row.expected_profit_pct || 0)
}

function undervaluePct(row: SignalItem): number {
  if (Number.isFinite(Number(row.undervalue_pct))) return Number(row.undervalue_pct || 0)
  return signalPercent(row.undervalue || 0)
}

function marketTactics(status: MarketStatusResponse | null): string[] {
  if (!status) return ['Ожидаем контекст рынка…', 'Проверьте качество данных', 'Используйте пресет PRO-алерты']
  const regime = String(status.market_regime || 'MEAN_REVERT').toUpperCase()
  const health = String(status.data_health || 'OK').toUpperCase()
  const flow = status.flow || {}
  const tactics: string[] = []
  if (regime === 'PANIC') tactics.push('PANIC: приоритет защите капитала, подтверждать вход только при росте AR/VV.')
  else if (regime === 'RISK_OFF') tactics.push('RISK_OFF: фокус на SELL/WATCH, отслеживайте LP и глубину.')
  else if (regime === 'RISK_ON') tactics.push('RISK_ON: приоритет BUY c EdgeRank/Conf выше порогов.')
  else tactics.push('MEAN_REVERT: работать от отклонений к справедливой цене.')
  if (health === 'DEGRADED') tactics.push('Качество данных DEGRADED: увеличьте фильтры Conf и Liquidity.')
  else tactics.push('Качество данных OK: можно использовать базовые PRO-пороги.')
  tactics.push(`Поток: VV ${Number(flow.volume_velocity || 0).toFixed(2)} • AR ${Number(flow.absorption || 0).toFixed(2)} • LP ${Number(flow.listing_pressure || 0).toFixed(2)}`)
  return tactics.slice(0, 3)
}

function formatDate(ts?: string): string {
  if (!ts) return '—'
  const t = Date.parse(ts)
  if (!Number.isFinite(t)) return '—'
  return new Date(t).toLocaleString('ru-RU')
}

function fmtNum(value: unknown, digits = 1): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(digits)
}

function clamp100(value: unknown): number {
  const n = Number(value)
  if (!Number.isFinite(n)) return 0
  if (n < 0) return 0
  if (n > 100) return 100
  return n
}

function formatCountdown(totalSec: number): string {
  const sec = Math.max(0, Math.floor(totalSec))
  const mm = Math.floor(sec / 60)
  const ss = sec % 60
  return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
}

function qualityCell(value: unknown, tone: 'score' | 'conf'): ReactNode {
  const raw = Number(value)
  const hasValue = Number.isFinite(raw)
  const pct = hasValue ? clamp100(raw) : 0
  const width = hasValue ? Math.max(6, pct) : 6
  const fillClass = hasValue
    ? (tone === 'score' ? 'bg-blue-500' : 'bg-emerald-500')
    : 'bg-slate-300'
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <span className="truncate tabular-nums text-[12px] leading-none">{hasValue ? Math.round(pct) : 'н/д'}</span>
      <span className="h-1.5 w-full rounded-full bg-slate-200/90">
        <span className={`block h-1.5 rounded-full transition-[width] duration-200 ease-out ${fillClass}`} style={{ width: `${width}%` }} />
      </span>
    </div>
  )
}

function cellText(row: SignalItem, columnId: string): string {
  switch (columnId) {
    case 'edgeRank100':
      return fmtNum(row.edgeRank100, 0)
    case 'score100':
      return fmtNum(row.score100, 0)
    case 'conf_pct':
      return fmtNum(row.conf_pct, 0)
    case 'expected_profit_pct':
      return fmtNum(expectedProfitPct(row), 1)
    case 'undervalue_pct':
      return fmtNum(undervaluePct(row), 1)
    case 'price_ton':
      return ton(row.price_ton)
    case 'floor_ton':
      return ton(row.floor_ton)
    case 'fair_ton':
      return ton(row.fair_ton)
    case 'target_ton':
      return ton(row.target_ton)
    case 'stop_ton':
      return ton(row.stop_ton)
    case 'liquidity_score':
      return fmtNum(row.liquidity_score ?? (Number(row.liquidity24h || 0) * 100), 0)
    case 'absorption_30m':
      return fmtNum(row.absorption_30m, 2)
    case 'listing_pressure':
      return fmtNum(row.listing_pressure, 2)
    case 'volume_velocity':
      return fmtNum(row.volume_velocity, 2)
    case 'depth_5pct_count':
      return fmtNum(row.depth_5pct_count, 0)
    case 'variant_label':
      return row.variant_label || [row.collection, row.model, row.background, row.pattern].filter(Boolean).join(' • ') || (row.variant_id || '—')
    case 'edgeRank_profile':
      return String(row.edgeRank_profile || row.market_regime || 'MEAN_REVERT')
    case 'ts':
      return formatDate(row.ts)
    default:
      return '—'
  }
}

function isStickyColumn(columnId: string): boolean {
  return columnId === 'action' || columnId === 'market_regime_badge'
}

function stickyLeft(columnId: string): number {
  if (columnId === 'action') return 0
  if (columnId === 'market_regime_badge') return ACTION_COL_MIN_WIDTH
  return 0
}

function signalChip(type?: string): string {
  const t = String(type || '').toUpperCase()
  if (t === 'BUY') return 'gmz-chip buy'
  if (t === 'SELL') return 'gmz-chip sell'
  if (t === 'WATCH') return 'gmz-chip watch'
  return 'gmz-chip hold'
}

function matchesApplied(row: SignalItem, applied: AppliedFilters): boolean {
  const action = String(row.type || row.action || '').toUpperCase() as SignalAction
  const regime = String(row.market_regime || '').toUpperCase() as MarketRegime
  if (applied.actions.length && !applied.actions.includes(action)) return false
  if (applied.regimes.length && !applied.regimes.includes(regime)) return false
  if ((Number(row.edgeRank100 || 0)) < applied.edgeRankMin) return false
  if ((Number(row.conf_pct || 0)) < applied.confMin) return false
  if (expectedProfitPct(row) < applied.profitMin) return false
  const liq = Number((row.liquidity_score ?? (Number(row.liquidity24h || 0) * 100)) || 0)
  if (liq < applied.liqMin) return false
  if (Number(row.listing_pressure || 0) > applied.lpMax) return false
  if (Number(row.absorption_30m || 0) < applied.arMin) return false
  if (Number(row.volume_velocity || 0) < applied.vvMin) return false
  if (applied.onlyProAlerts) {
    if (Number(row.edgeRank100 || 0) < 55 || Number(row.conf_pct || 0) < 35 || expectedProfitPct(row) < 8) return false
  }
  if (applied.q) {
    const hay = SEARCH_FIELDS.map((f) => String(byPath(row, f) || '')).join(' ').toLowerCase()
    if (!hay.includes(applied.q.toLowerCase())) return false
  }
  if (applied.onlyNew && !inLastHour(row.ts)) return false
  if (applied.minUndervalue !== undefined && undervaluePct(row) < applied.minUndervalue) return false
  if (applied.maxRisk !== undefined) {
    const riskProxy = Math.min(1, (Array.isArray(row.risk_flags) ? row.risk_flags.length : 0) / 4)
    if (riskProxy > applied.maxRisk) return false
  }
  if (applied.minScore !== undefined && Number(row.score100 || 0) < applied.minScore) return false
  return true
}

function renderRowSection(row: SignalItem, section: RowSection, onDetails: () => void): ReactNode {
  const title = String(section.ui || section.id || 'Детали')
  const sectionId = String(section.id || '')
  const sectionType = String(section.type || '').toLowerCase()
  const cardBase = 'rounded-xl border border-slate-200 bg-white p-3 text-sm'

  if (sectionType === 'list') {
    const src = byPath(row, section.path)
    const arr = Array.isArray(src) ? src.map((x) => String(x || '').trim()).filter(Boolean) : []
    const maxItems = Math.max(1, Number(section.maxItems || 3))
    return (
      <div className={cardBase}>
        <div className="mb-2 text-xs font-semibold text-slate-500">{title}</div>
        {arr.length ? arr.slice(0, maxItems).map((x) => <div key={x}>• {x}</div>) : <div className="text-slate-500">нет данных</div>}
      </div>
    )
  }

  if (sectionType === 'kv') {
    const items = Array.isArray(section.items) ? section.items : []
    return (
      <div className={cardBase}>
        <div className="mb-2 text-xs font-semibold text-slate-500">{title}</div>
        {items.length ? (
          items.map((it) => {
            const k = String(it?.k || '')
            const raw = byPath(row, it?.path)
            const value = raw === undefined || raw === null || raw === '' ? '—' : String(raw)
            return <div key={`${k}:${String(it?.path || '')}`}>{k}: {value}</div>
          })
        ) : (
          <div className="text-slate-500">нет данных</div>
        )}
        {sectionId === 'edge_math' ? (
          <button type="button" className="gmz-btn gmz-btn-ghost mt-2 px-2 text-xs" onClick={onDetails}>Подробнее</button>
        ) : null}
      </div>
    )
  }

  const raw = byPath(row, section.path)
  const text = raw === undefined || raw === null || raw === '' ? '—' : String(raw)
  return (
    <div className={cardBase}>
      <div className="mb-2 text-xs font-semibold text-slate-500">{title}</div>
      <div>{text}</div>
      {sectionId === 'edge_math' ? (
        <button type="button" className="gmz-btn gmz-btn-ghost mt-2 px-2 text-xs" onClick={onDetails}>Подробнее</button>
      ) : null}
    </div>
  )
}

function parsePresetExpr(expr: string): {
  actions?: SignalAction[]
  regimes?: MarketRegime[]
  edgeRankMin?: number
  confMin?: number
  profitMin?: number
  liqMin?: number
  lpMax?: number
  arMin?: number
  vvMin?: number
  minScore?: number
  minUndervalue?: number
  maxRisk?: number
  onlyNew?: boolean
  unsupportedLpMin?: boolean
  unsupportedArMax?: boolean
} {
  const src = String(expr || '')
  const out: {
    actions?: SignalAction[]
    regimes?: MarketRegime[]
    edgeRankMin?: number
    confMin?: number
    profitMin?: number
    liqMin?: number
    lpMax?: number
    arMin?: number
    vvMin?: number
    minScore?: number
    minUndervalue?: number
    maxRisk?: number
    onlyNew?: boolean
    unsupportedLpMin?: boolean
    unsupportedArMax?: boolean
  } = {}
  const parseNum = (re: RegExp): number | undefined => {
    const m = src.match(re)
    if (!m) return undefined
    const n = Number(m[1])
    return Number.isFinite(n) ? n : undefined
  }
  const inMatch = src.match(/action\s+in\s*\(([^)]*)\)/i)
  if (inMatch) {
    const rows = String(inMatch[1] || '')
      .split(',')
      .map((x) => x.replace(/['"\s]/g, '').toUpperCase())
      .filter(Boolean) as SignalAction[]
    if (rows.length) out.actions = rows
  }
  const actionEq = src.match(/action\s*==\s*['"]([A-Z_]+)['"]/i)
  if (actionEq) out.actions = [String(actionEq[1] || '').toUpperCase() as SignalAction]
  const regimeEq = src.match(/market_regime\s*==\s*['"]([A-Z_]+)['"]/i)
  if (regimeEq) out.regimes = [String(regimeEq[1] || '').toUpperCase() as MarketRegime]

  out.edgeRankMin = parseNum(/edgeRank100\s*>=\s*([0-9.]+)/i)
  out.confMin = parseNum(/conf_pct\s*>=\s*([0-9.]+)/i)
  out.profitMin = parseNum(/expected_profit_pct\s*>=\s*([0-9.]+)/i)
  out.liqMin = parseNum(/liquidity_score\s*>=\s*([0-9.]+)/i)
  out.vvMin = parseNum(/volume_velocity\s*>=\s*([0-9.]+)/i)
  out.lpMax = parseNum(/listing_pressure\s*<=\s*([0-9.]+)/i)
  out.arMin = parseNum(/absorption_30m\s*>=\s*([0-9.]+)/i)
  out.minScore = parseNum(/score100\s*>=\s*([0-9.]+)/i)
  out.minUndervalue = parseNum(/undervalue_pct\s*>=\s*([0-9.]+)/i)
  out.maxRisk = parseNum(/risk\s*<=\s*([0-9.]+)/i)
  if (/only_new_1h\s*==\s*true/i.test(src)) out.onlyNew = true
  if (/only_new_1h\s*==\s*false/i.test(src)) out.onlyNew = false
  out.unsupportedLpMin = /listing_pressure\s*>=\s*([0-9.]+)/i.test(src)
  out.unsupportedArMax = /absorption_30m\s*<=\s*([0-9.]+)/i.test(src)
  return out
}

export function SignalsPage() {
  const navigate = useNavigate()
  const autoRefreshMinutes = useMemo(() => readUiAutoRefreshMinutes(), [])
  const autoRefreshMs = useMemo(() => uiAutoRefreshMs(autoRefreshMinutes), [autoRefreshMinutes])

  const columns = useMemo(() => {
    const cols = ((SIGNALS_PRO_UI.columns || SIGNALS_UI.columns || []).filter((x) => x?.id)) as UiColumn[]
    return cols.length ? cols : DEFAULT_COLUMNS
  }, [])

  const actionOptions = useMemo(() => {
    const row = getFilterDef('action')
    const opts = (row?.options || []).map((x) => String(x).toUpperCase()).filter(Boolean)
    return (opts.length ? opts : ['BUY', 'SELL', 'WATCH', 'SKIP']) as SignalAction[]
  }, [])

  const regimeOptions = useMemo(() => {
    const row = getFilterDef('market_regime')
    const opts = (row?.options || []).map((x) => String(x).toUpperCase()).filter(Boolean)
    return (opts.length ? opts : ['RISK_ON', 'MEAN_REVERT', 'RISK_OFF', 'PANIC']) as MarketRegime[]
  }, [])

  const presets = useMemo(() => {
    const src = (SIGNALS_PRO_UI.presets || []).filter((x) => x?.id && x?.ui) as Array<{ id: string; ui: string; expr?: string }>
    const hasRelaxed = src.some((x) => String(x.id) === RELAXED_PRESET_ID)
    const hasStrict = src.some((x) => String(x.id) === STRICT_PRESET_ID)
    const out = [...src]
    if (!hasRelaxed) {
      out.unshift({
        id: RELAXED_PRESET_ID,
        ui: 'По умолчанию',
        expr: 'action in (BUY,SELL,WATCH) && edgeRank100>=0 && conf_pct>=0 && expected_profit_pct>=0',
      })
    }
    if (!hasStrict) {
      out.push({
        id: STRICT_PRESET_ID,
        ui: 'PRO-алерты',
        expr: 'edgeRank100>=55 && conf_pct>=35 && expected_profit_pct>=8 && action in (BUY,SELL,WATCH)',
      })
    }
    return out
  }, [])

  const rowSections = useMemo(() => {
    const src = SIGNALS_PRO_UI.row_expand?.sections || []
    const out = src.filter((x) => x?.id || x?.ui)
    return out.length ? out : DEFAULT_ROW_SECTIONS
  }, [])

  const filterIdSet = useMemo(() => {
    const ids = new Set<string>()
    for (const row of SIGNALS_PRO_UI.filters || []) {
      const id = String(row?.id || '').trim()
      if (id) ids.add(id)
    }
    for (const row of SIGNALS_UI.filters || []) {
      const id = String(row?.id || '').trim()
      if (id) ids.add(id)
    }
    return ids
  }, [])
  const hasFilter = useCallback((id: string) => filterIdSet.has(id), [filterIdSet])

  const edgeRankMeta = useMemo(() => filterNumMeta('edgeRank100_min', { min: 0, max: 100, step: 1 }), [])
  const confMeta = useMemo(() => filterNumMeta('conf_min', { min: 0, max: 100, step: 1 }), [])
  const profitMeta = useMemo(() => filterNumMeta('profit_min', { min: 0, max: 50, step: 0.5 }), [])
  const liqMeta = useMemo(() => filterNumMeta('liq_min', { min: 0, max: 100, step: 1 }), [])
  const lpMeta = useMemo(() => filterNumMeta('lp_max', { min: 0, max: 10, step: 0.1 }), [])
  const arMeta = useMemo(() => filterNumMeta('ar_min', { min: 0, max: 3, step: 0.05 }), [])
  const vvMeta = useMemo(() => filterNumMeta('vv_min', { min: 0, max: 3, step: 0.05 }), [])

  const minScoreDefault = useMemo(() => filterDefaultNumberOptional('min_score'), [])
  const minUndervalueDefault = useMemo(() => filterDefaultNumberOptional('min_undervalue_pct'), [])
  const maxRiskDefault = useMemo(() => filterDefaultNumberOptional('max_risk'), [])
  const [actions, setActions] = useState<SignalAction[]>(filterDefaultArray<SignalAction>('action', ['BUY', 'SELL', 'WATCH']))
  const [regimes, setRegimes] = useState<MarketRegime[]>(filterDefaultArray<MarketRegime>('market_regime', ['RISK_ON', 'MEAN_REVERT', 'RISK_OFF', 'PANIC']))
  const [minScore, setMinScore] = useState(USE_RELAXED_DEFAULT ? '' : (Number.isFinite(minScoreDefault) ? String(minScoreDefault) : ''))
  const [edgeRankMin, setEdgeRankMin] = useState<number>(USE_RELAXED_DEFAULT ? 0 : filterDefaultNumber('edgeRank100_min', 55))
  const [confMin, setConfMin] = useState<number>(USE_RELAXED_DEFAULT ? 0 : filterDefaultNumber('conf_min', 35))
  const [profitMin, setProfitMin] = useState<number>(USE_RELAXED_DEFAULT ? 0 : filterDefaultNumber('profit_min', 8))
  const [liqMin, setLiqMin] = useState<number>(USE_RELAXED_DEFAULT ? 0 : filterDefaultNumber('liq_min', 35))
  const [lpMax, setLpMax] = useState<number>(USE_RELAXED_DEFAULT ? 10 : filterDefaultNumber('lp_max', 4))
  const [arMin, setArMin] = useState<number>(USE_RELAXED_DEFAULT ? 0 : filterDefaultNumber('ar_min', 0.9))
  const [vvMin, setVvMin] = useState<number>(USE_RELAXED_DEFAULT ? 0 : filterDefaultNumber('vv_min', 1.0))
  const [searchQ, setSearchQ] = useState('')
  const [onlyNew, setOnlyNew] = useState<boolean>(filterDefaultBool('only_new_1h', false))
  const [onlyProAlerts, setOnlyProAlerts] = useState<boolean>(USE_RELAXED_DEFAULT ? false : filterDefaultBool('only_pro_alerts', true))
  const [minUndervalue, setMinUndervalue] = useState(USE_RELAXED_DEFAULT ? '' : (Number.isFinite(minUndervalueDefault) ? String(minUndervalueDefault) : ''))
  const [maxRisk, setMaxRisk] = useState(USE_RELAXED_DEFAULT ? '' : (Number.isFinite(maxRiskDefault) ? String(maxRiskDefault) : ''))
  const [presetId, setPresetId] = useState(USE_RELAXED_DEFAULT ? RELAXED_PRESET_ID : '')

  const [applied, setApplied] = useState<AppliedFilters>({
    actions,
    regimes,
    minScore: hasFilter('min_score') ? numOrUndefined(minScore) : undefined,
    edgeRankMin,
    confMin,
    profitMin,
    liqMin,
    lpMax,
    arMin,
    vvMin,
    q: hasFilter('search') ? searchQ : '',
    onlyProAlerts: hasFilter('only_pro_alerts') ? onlyProAlerts : false,
    onlyNew: hasFilter('only_new_1h') ? onlyNew : false,
    minUndervalue: hasFilter('min_undervalue_pct') ? numOrUndefined(minUndervalue) : undefined,
    maxRisk: hasFilter('max_risk') ? numOrUndefined(maxRisk) : undefined,
  })

  const [rows, setRows] = useState<SignalItem[]>([])
  const [totalCount, setTotalCount] = useState<number | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [marketStatus, setMarketStatus] = useState<MarketStatusResponse | null>(null)
  const [selected, setSelected] = useState<SignalItem | null>(null)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [nextRefreshSec, setNextRefreshSec] = useState(Math.ceil(autoRefreshMs / 1000))

  const firstLoadRef = useRef(true)
  const streamDedupRef = useRef<Map<string, number>>(new Map())
  const loadInFlightRef = useRef(false)
  const nextCursorRef = useRef<string | null>(null)
  const tableWrapRef = useRef<HTMLDivElement | null>(null)
  const initDoneRef = useRef(false)
  const presetInitDoneRef = useRef(false)
  const nextRefreshAtRef = useRef<number>(Date.now() + autoRefreshMs)
  const lastAutoRefreshAtRef = useRef<number>(0)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewportHeight, setViewportHeight] = useState(640)
  const appliedRequestKey = useMemo(() => JSON.stringify(applied), [applied])
  const appliedRequestKeyRef = useRef('')

  const scheduleNextAutoRefresh = useCallback((baseTs: number = Date.now()) => {
    nextRefreshAtRef.current = baseTs + autoRefreshMs
    setNextRefreshSec(Math.ceil(autoRefreshMs / 1000))
  }, [autoRefreshMs])

  const fetchPage = useCallback(async (reset: boolean) => {
    if (loadInFlightRef.current) return
    loadInFlightRef.current = true
    if (reset) {
      if (firstLoadRef.current) setLoading(true)
      else setRefreshing(true)
    } else {
      setLoadingMore(true)
    }
    setError('')
    try {
      const requestParams = {
        actions: applied.actions,
        marketRegimes: applied.regimes,
        minScore: applied.minScore,
        edgeRankMin: applied.edgeRankMin,
        confMin: applied.confMin,
        profitMin: applied.profitMin,
        liqMin: applied.liqMin,
        lpMax: applied.lpMax,
        arMin: applied.arMin,
        vvMin: applied.vvMin,
        minUndervaluePct: applied.minUndervalue,
        maxRisk: applied.maxRisk,
        onlyNew1h: applied.onlyNew,
        onlyProAlerts: applied.onlyProAlerts,
        q: applied.q,
        sortBy: DEFAULT_SORT_BY,
        sortDir: DEFAULT_SORT_DIR,
        limit: 200,
        cursor: reset ? undefined : (nextCursorRef.current || undefined),
        endpoint: FEED_ENDPOINT,
      }
      let payload = await getSignalsPage(requestParams)
      let incoming = Array.isArray(payload.items) ? payload.items : []
      const total = Number(payload.total_count)
      setTotalCount(Number.isFinite(total) ? total : null)
      setRows((prev) => (reset ? sortSignals(incoming, DEFAULT_SORT) : mergeSignals(prev, incoming, DEFAULT_SORT)))
      const cursor = String(payload.next_cursor || '')
      nextCursorRef.current = cursor || null
      setHasMore(Boolean(cursor))
      if (reset) {
        setExpanded({})
        setScrollTop(0)
        setHasMore(Boolean(cursor))
        if (tableWrapRef.current) tableWrapRef.current.scrollTop = 0
      }
      firstLoadRef.current = false
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки сигналов')
    } finally {
      setLoading(false)
      setRefreshing(false)
      setLoadingMore(false)
      loadInFlightRef.current = false
    }
  }, [applied])

  const refreshMarket = useCallback(async () => {
    const status = await getMarketStatus(MARKET_WINDOW, MARKET_ENDPOINT).catch(() => null)
    setMarketStatus(status)
  }, [])

  useEffect(() => {
    if (initDoneRef.current) return
    initDoneRef.current = true

    let hydrated = false
    try {
      const raw = sessionStorage.getItem(SIGNALS_CACHE_KEY)
      if (raw) {
        const parsed = JSON.parse(raw) as SignalsCachePayload
        if (parsed && parsed.data && Number.isFinite(Number(parsed.savedAt))) {
          const d = parsed.data
          setRows(Array.isArray(d.rows) ? d.rows : [])
          if (d.totalCount === null) setTotalCount(null)
          else setTotalCount(Number.isFinite(Number(d.totalCount)) ? Number(d.totalCount) : null)
          setHasMore(Boolean(d.hasMore))
          nextCursorRef.current = typeof d.nextCursor === 'string' ? d.nextCursor : null
          setMarketStatus(d.marketStatus || null)

          const cachedApplied = d.applied
          if (cachedApplied) {
            setApplied({
              actions: Array.isArray(cachedApplied.actions) ? cachedApplied.actions : [],
              regimes: Array.isArray(cachedApplied.regimes) ? cachedApplied.regimes : [],
              minScore: Number.isFinite(Number(cachedApplied.minScore)) ? Number(cachedApplied.minScore) : undefined,
              edgeRankMin: Number(cachedApplied.edgeRankMin || 0),
              confMin: Number(cachedApplied.confMin || 0),
              profitMin: Number(cachedApplied.profitMin || 0),
              liqMin: Number(cachedApplied.liqMin || 0),
              lpMax: Number(cachedApplied.lpMax || 10),
              arMin: Number(cachedApplied.arMin || 0),
              vvMin: Number(cachedApplied.vvMin || 0),
              q: String(cachedApplied.q || ''),
              onlyProAlerts: Boolean(cachedApplied.onlyProAlerts),
              onlyNew: Boolean(cachedApplied.onlyNew),
              minUndervalue: Number.isFinite(Number(cachedApplied.minUndervalue)) ? Number(cachedApplied.minUndervalue) : undefined,
              maxRisk: Number.isFinite(Number(cachedApplied.maxRisk)) ? Number(cachedApplied.maxRisk) : undefined,
            })
          }

          const ui = d.filtersUi
          if (ui) {
            setActions(Array.isArray(ui.actions) ? ui.actions : [])
            setRegimes(Array.isArray(ui.regimes) ? ui.regimes : [])
            setMinScore(String(ui.minScore || ''))
            setEdgeRankMin(Number(ui.edgeRankMin || 0))
            setConfMin(Number(ui.confMin || 0))
            setProfitMin(Number(ui.profitMin || 0))
            setLiqMin(Number(ui.liqMin || 0))
            setLpMax(Number(ui.lpMax || 10))
            setArMin(Number(ui.arMin || 0))
            setVvMin(Number(ui.vvMin || 0))
            setSearchQ(String(ui.searchQ || ''))
            setOnlyNew(Boolean(ui.onlyNew))
            setOnlyProAlerts(Boolean(ui.onlyProAlerts))
            setMinUndervalue(String(ui.minUndervalue || ''))
            setMaxRisk(String(ui.maxRisk || ''))
            setPresetId(String(ui.presetId || ''))
          }

          setLoading(false)
          setRefreshing(false)
          setLoadingMore(false)
          firstLoadRef.current = false
          hydrated = true

          const savedAt = Number(parsed.savedAt || 0)
          const ageMs = Date.now() - savedAt
          appliedRequestKeyRef.current = JSON.stringify(cachedApplied || d.applied || {})
          if (ageMs > 0 && ageMs < autoRefreshMs) {
            nextRefreshAtRef.current = savedAt + autoRefreshMs
            setNextRefreshSec(Math.ceil(Math.max(0, nextRefreshAtRef.current - Date.now()) / 1000))
          } else {
            scheduleNextAutoRefresh()
          }
          if (ageMs >= autoRefreshMs) {
            lastAutoRefreshAtRef.current = Date.now()
            scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
            void fetchPage(true)
            void refreshMarket()
          }
        }
      }
    } catch {
      // cache read is best effort
    }

    if (!hydrated) {
      appliedRequestKeyRef.current = appliedRequestKey
      lastAutoRefreshAtRef.current = Date.now()
      scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
      void fetchPage(true)
      void refreshMarket()
    }
  }, [appliedRequestKey, fetchPage, refreshMarket, scheduleNextAutoRefresh, autoRefreshMs])

  useEffect(() => {
    if (!initDoneRef.current) return
    if (appliedRequestKeyRef.current === appliedRequestKey) return
    appliedRequestKeyRef.current = appliedRequestKey
    lastAutoRefreshAtRef.current = Date.now()
    scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
    void fetchPage(true)
  }, [appliedRequestKey, fetchPage, scheduleNextAutoRefresh])

  useEffect(() => {
    if (!DEFAULT_REALTIME) return
    const es = subscribeSignalsStream((incoming) => {
      const sid = String(incoming.signal_id || '').trim()
      if (!sid) return
      const now = Date.now()
      const dedupe = streamDedupRef.current
      for (const [k, ts] of dedupe.entries()) {
        if (now - ts > 10 * 60 * 1000) dedupe.delete(k)
      }
      const prev = dedupe.get(sid)
      if (prev && now - prev <= 10 * 60 * 1000) return
      dedupe.set(sid, now)
      if (!matchesApplied(incoming, applied)) return
      setTotalCount((prev) => (prev === null ? null : prev + 1))
      setRows((prevRows) => mergeSignals(prevRows, [incoming], DEFAULT_SORT).slice(0, 10000))
    }, undefined, { endpoint: REALTIME_ENDPOINT, event: REALTIME_EVENT })
    return () => es.close()
  }, [applied])

  useEffect(() => {
    if (!DEFAULT_AUTO_REFRESH) return
    const poll = window.setInterval(() => {
      lastAutoRefreshAtRef.current = Date.now()
      scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
      void fetchPage(true)
      void refreshMarket()
    }, autoRefreshMs)
    const tick = window.setInterval(() => {
      const remain = Math.max(0, Math.ceil((nextRefreshAtRef.current - Date.now()) / 1000))
      setNextRefreshSec(remain)
    }, 1000)
    return () => {
      window.clearInterval(poll)
      window.clearInterval(tick)
    }
  }, [autoRefreshMs, fetchPage, refreshMarket, scheduleNextAutoRefresh])

  useEffect(() => {
    if (loading) return
    try {
      const payload: SignalsCachePayload = {
        savedAt: Date.now(),
        data: {
          rows,
          totalCount,
          hasMore,
          nextCursor: nextCursorRef.current,
          marketStatus,
          applied,
          filtersUi: {
            actions,
            regimes,
            minScore,
            edgeRankMin,
            confMin,
            profitMin,
            liqMin,
            lpMax,
            arMin,
            vvMin,
            searchQ,
            onlyNew,
            onlyProAlerts,
            minUndervalue,
            maxRisk,
            presetId,
          },
        },
      }
      sessionStorage.setItem(SIGNALS_CACHE_KEY, JSON.stringify(payload))
    } catch {
      // cache write is best effort
    }
  }, [
    loading,
    rows,
    totalCount,
    hasMore,
    marketStatus,
    applied,
    actions,
    regimes,
    minScore,
    edgeRankMin,
    confMin,
    profitMin,
    liqMin,
    lpMax,
    arMin,
    vvMin,
    searchQ,
    onlyNew,
    onlyProAlerts,
    minUndervalue,
    maxRisk,
    presetId,
  ])

  const onApply = useCallback(() => {
    setApplied({
      actions: hasFilter('action') ? actions : [],
      regimes: hasFilter('market_regime') ? regimes : [],
      minScore: hasFilter('min_score') ? numOrUndefined(minScore) : undefined,
      edgeRankMin: hasFilter('edgeRank100_min') ? edgeRankMin : 0,
      confMin: hasFilter('conf_min') ? confMin : 0,
      profitMin: hasFilter('profit_min') ? profitMin : 0,
      liqMin: hasFilter('liq_min') ? liqMin : 0,
      lpMax: hasFilter('lp_max') ? lpMax : 10,
      arMin: hasFilter('ar_min') ? arMin : 0,
      vvMin: hasFilter('vv_min') ? vvMin : 0,
      q: hasFilter('search') ? searchQ : '',
      onlyProAlerts: hasFilter('only_pro_alerts') ? onlyProAlerts : false,
      onlyNew: hasFilter('only_new_1h') ? onlyNew : false,
      minUndervalue: hasFilter('min_undervalue_pct') ? numOrUndefined(minUndervalue) : undefined,
      maxRisk: hasFilter('max_risk') ? numOrUndefined(maxRisk) : undefined,
    })
    setTotalCount(null)
    nextCursorRef.current = null
    setHasMore(false)
  }, [actions, regimes, minScore, edgeRankMin, confMin, profitMin, liqMin, lpMax, arMin, vvMin, searchQ, onlyProAlerts, onlyNew, minUndervalue, maxRisk, hasFilter])

  const applyPreset = useCallback((id: string) => {
    setPresetId(id)
    const strictBaseline = () => ({
      actions: filterDefaultArray<SignalAction>('action', ['BUY', 'SELL', 'WATCH']),
      regimes: filterDefaultArray<MarketRegime>('market_regime', ['RISK_ON', 'MEAN_REVERT', 'RISK_OFF', 'PANIC']),
      edgeRankMin: 55,
      confMin: 35,
      profitMin: 8,
      liqMin: 35,
      lpMax: 4,
      arMin: 0.9,
      vvMin: 1.0,
      minScore: '30',
      minUndervalue: '5',
      maxRisk: '0.4',
      onlyProAlerts: true,
      onlyNew: filterDefaultBool('only_new_1h', false),
    })

    const applyRuntime = (next: {
      actions: SignalAction[]
      regimes: MarketRegime[]
      edgeRankMin: number
      confMin: number
      profitMin: number
      liqMin: number
      lpMax: number
      arMin: number
      vvMin: number
      minScore: string
      minUndervalue: string
      maxRisk: string
      onlyProAlerts: boolean
      onlyNew: boolean
    }) => {
      setActions(next.actions)
      setRegimes(next.regimes)
      setEdgeRankMin(next.edgeRankMin)
      setConfMin(next.confMin)
      setProfitMin(next.profitMin)
      setLiqMin(next.liqMin)
      setLpMax(next.lpMax)
      setArMin(next.arMin)
      setVvMin(next.vvMin)
      setMinScore(next.minScore)
      setMinUndervalue(next.minUndervalue)
      setMaxRisk(next.maxRisk)
      setOnlyProAlerts(next.onlyProAlerts)
      setOnlyNew(next.onlyNew)
      setApplied({
        actions: hasFilter('action') ? next.actions : [],
        regimes: hasFilter('market_regime') ? next.regimes : [],
        minScore: hasFilter('min_score') ? numOrUndefined(next.minScore) : undefined,
        edgeRankMin: hasFilter('edgeRank100_min') ? next.edgeRankMin : 0,
        confMin: hasFilter('conf_min') ? next.confMin : 0,
        profitMin: hasFilter('profit_min') ? next.profitMin : 0,
        liqMin: hasFilter('liq_min') ? next.liqMin : 0,
        lpMax: hasFilter('lp_max') ? next.lpMax : 10,
        arMin: hasFilter('ar_min') ? next.arMin : 0,
        vvMin: hasFilter('vv_min') ? next.vvMin : 0,
        q: hasFilter('search') ? searchQ : '',
        onlyProAlerts: hasFilter('only_pro_alerts') ? next.onlyProAlerts : false,
        onlyNew: hasFilter('only_new_1h') ? next.onlyNew : false,
        minUndervalue: hasFilter('min_undervalue_pct') ? numOrUndefined(next.minUndervalue) : undefined,
        maxRisk: hasFilter('max_risk') ? numOrUndefined(next.maxRisk) : undefined,
      })
      setTotalCount(null)
      nextCursorRef.current = null
      setHasMore(false)
    }

    if (id === RELAXED_PRESET_ID) {
      applyRuntime({
        ...strictBaseline(),
        edgeRankMin: 0,
        confMin: 0,
        profitMin: 0,
        liqMin: 0,
        lpMax: 10,
        arMin: 0,
        vvMin: 0,
        minScore: '',
        minUndervalue: '',
        maxRisk: '',
        onlyProAlerts: false,
      })
      return
    }

    if (!id || id === STRICT_PRESET_ID) {
      applyRuntime(strictBaseline())
      return
    }

    const preset = presets.find((x) => x.id === id)
    const expr = String(preset?.expr || '')
    if (!expr) {
      applyRuntime(strictBaseline())
      return
    }

    const parsed = parsePresetExpr(expr)
    const next = strictBaseline()
    if (parsed.actions?.length) next.actions = parsed.actions
    if (parsed.regimes?.length) next.regimes = parsed.regimes
    if (parsed.edgeRankMin !== undefined) next.edgeRankMin = parsed.edgeRankMin
    if (parsed.confMin !== undefined) next.confMin = parsed.confMin
    if (parsed.profitMin !== undefined) next.profitMin = parsed.profitMin
    if (parsed.liqMin !== undefined) next.liqMin = parsed.liqMin
    if (parsed.vvMin !== undefined) next.vvMin = parsed.vvMin
    if (parsed.lpMax !== undefined) next.lpMax = parsed.lpMax
    if (parsed.arMin !== undefined) next.arMin = parsed.arMin
    if (parsed.minScore !== undefined) next.minScore = String(parsed.minScore)
    if (parsed.minUndervalue !== undefined) next.minUndervalue = String(parsed.minUndervalue)
    if (parsed.maxRisk !== undefined) next.maxRisk = String(parsed.maxRisk)
    if (parsed.onlyNew !== undefined) next.onlyNew = parsed.onlyNew
    if (parsed.unsupportedLpMin) next.lpMax = 10
    if (parsed.unsupportedArMax) next.arMin = 0
    next.onlyProAlerts = id === STRICT_PRESET_ID || id === 'top_buy'
    applyRuntime(next)
  }, [hasFilter, presets, searchQ])

  useEffect(() => {
    // Always start from configured default preset after hydration.
    // This prevents stale session filters from pinning feed to a tiny subset.
    if (presetInitDoneRef.current) return
    presetInitDoneRef.current = true
    if (!DEFAULT_PRESET_ID) return
    applyPreset(DEFAULT_PRESET_ID)
  }, [applyPreset])

  const filtered = useMemo(() => rows.filter((x) => matchesApplied(x, applied)), [rows, applied])

  const stats = useMemo(() => {
    return {
      total: totalCount ?? filtered.length,
      buy: filtered.filter((x) => String(x.type || x.action || '').toUpperCase() === 'BUY').length,
      sell: filtered.filter((x) => String(x.type || x.action || '').toUpperCase() === 'SELL').length,
      shown: filtered.length,
    }
  }, [filtered, totalCount])

  useEffect(() => {
    const el = tableWrapRef.current
    if (!el) return
    const update = () => setViewportHeight(el.clientHeight || 640)
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [loading])

  const visibleRange = useMemo(() => {
    const start = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN)
    const count = Math.ceil(viewportHeight / ROW_HEIGHT) + OVERSCAN * 2
    const end = Math.min(filtered.length, start + count)
    return { start, end }
  }, [filtered.length, scrollTop, viewportHeight])

  const visibleRows = useMemo(() => filtered.slice(visibleRange.start, visibleRange.end), [filtered, visibleRange])
  const topPad = visibleRange.start * ROW_HEIGHT
  const bottomPad = Math.max(0, (filtered.length - visibleRange.end) * ROW_HEIGHT)

  const onTableScroll = useCallback(() => {
    const el = tableWrapRef.current
    if (!el) return
    setScrollTop(el.scrollTop)
    const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 280
    if (nearBottom && hasMore && !loadingMore) {
      void fetchPage(false)
    }
  }, [hasMore, loadingMore, fetchPage])

  const tactics = useMemo(() => marketTactics(marketStatus), [marketStatus])
  const titleMarket = useMemo(() => bentoBlockTitle('HEADER_MARKET_CONTEXT', 'Контекст рынка'), [])
  const titleFilters = useMemo(() => bentoBlockTitle('FILTER_BAR', 'Фильтры'), [])
  const titleTable = useMemo(() => bentoBlockTitle('TABLE_SIGNALS_PRO', 'Сигналы'), [])
  const pageTitle = useMemo(() => String(SIGNALS_BENTO.title || SIGNALS_PRO_UI.title || 'Лента сигналов (PRO)'), [])
  const pageSubtitle = useMemo(
    () => String(SIGNALS_PRO_UI.description || SIGNALS_BENTO.description || 'Операционный терминал: EdgeRank, режим рынка, realtime'),
    [],
  )
  const triggerManualRefresh = useCallback(() => {
    lastAutoRefreshAtRef.current = Date.now()
    scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
    void fetchPage(true)
    void refreshMarket()
  }, [fetchPage, refreshMarket, scheduleNextAutoRefresh])

  return (
    <section>
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
              onClick={triggerManualRefresh}
              className="gmz-btn gmz-btn-ghost px-3 py-2 text-sm"
            >
              Обновить
            </button>
          </div>
        )}
      />

      <BentoGrid className="signals-layout-grid">
        <BentoCard title={titleMarket} className="xl:col-span-2">
          {marketStatus ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <MetricTile label="Режим" value={`${marketStatus.market_regime_badge || '🟡'} ${marketStatus.market_regime || 'MEAN_REVERT'}`} />
                <MetricTile label="Data health" value={String(marketStatus.data_health || 'OK')} />
                <MetricTile label="Conf рынка" value={`${Number(marketStatus.data_conf_pct || 0)}%`} />
                <MetricTile label="Сигналы 1ч" value={`${Number(marketStatus.signals_1h?.buy || 0) + Number(marketStatus.signals_1h?.sell || 0) + Number(marketStatus.signals_1h?.watch || 0)}`} />
              </div>
              <div className="mt-3 space-y-2 text-sm text-slate-700">
                {tactics.map((line) => (
                  <div key={line}>• {line}</div>
                ))}
              </div>
            </>
          ) : (
            <LoadingBlock className="h-28" />
          )}
        </BentoCard>

        <BentoCard title={titleFilters} className="gmz-filters-panel h-fit self-start xl:col-span-1 xl:sticky xl:top-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
            <MetricTile label="Сигналов" value={stats.total} />
            <MetricTile label="BUY" value={stats.buy} />
            <MetricTile label="SELL" value={stats.sell} />
            <MetricTile label="Показано" value={stats.shown} />
          </div>

          <div className="mt-4 space-y-3">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-slate-700">Пресет</span>
              <GmzSelect
                value={presetId}
                onChange={applyPreset}
                options={presets.map((x) => ({ value: x.id, label: x.ui }))}
                placeholder="Выберите пресет"
              />
            </label>

            {hasFilter('action') ? (
              <div>
                <div className="mb-1 text-sm font-medium text-slate-700">{filterUiLabel('action', 'Тип сигнала')}</div>
                <div className="grid grid-cols-2 gap-2">
                  {actionOptions.map((opt) => (
                    <label key={opt} className="flex items-center gap-2 rounded-xl border border-[var(--line)] bg-white/70 px-2 py-2 text-xs">
                      <input type="checkbox" checked={actions.includes(opt)} onChange={() => setActions((s) => toggleValue(s, opt))} className="h-4 w-4" />
                      <span>{opt}</span>
                    </label>
                  ))}
                </div>
              </div>
            ) : null}

            {hasFilter('market_regime') ? (
              <div>
                <div className="mb-1 text-sm font-medium text-slate-700">{filterUiLabel('market_regime', 'Режим рынка')}</div>
                <div className="grid grid-cols-2 gap-2">
                  {regimeOptions.map((opt) => (
                    <label key={opt} className="flex items-center gap-2 rounded-xl border border-[var(--line)] bg-white/70 px-2 py-2 text-xs">
                      <input type="checkbox" checked={regimes.includes(opt)} onChange={() => setRegimes((s) => toggleValue(s, opt))} className="h-4 w-4" />
                      <span>{opt}</span>
                    </label>
                  ))}
                </div>
              </div>
            ) : null}

            {hasFilter('search') ? (
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-slate-700">{filterUiLabel('search', 'Поиск')}</span>
                <input value={searchQ} onChange={(e) => setSearchQ(e.target.value)} className="gmz-input" placeholder="Коллекция / модель / фон / узор" />
              </label>
            ) : null}

            <div className="grid gap-3 sm:grid-cols-2">
              {hasFilter('edgeRank100_min') ? (
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">{filterUiLabel('edgeRank100_min', 'EdgeRank ≥')}</span>
                  <input value={String(edgeRankMin)} onChange={(e) => setEdgeRankMin(Number(e.target.value || 0))} type="number" min={edgeRankMeta.min} max={edgeRankMeta.max} step={edgeRankMeta.step} className="gmz-input" />
                </label>
              ) : null}

              {hasFilter('conf_min') ? (
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">{filterUiLabel('conf_min', 'Conf ≥')}</span>
                  <input value={String(confMin)} onChange={(e) => setConfMin(Number(e.target.value || 0))} type="number" min={confMeta.min} max={confMeta.max} step={confMeta.step} className="gmz-input" />
                </label>
              ) : null}

              {hasFilter('profit_min') ? (
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">{filterUiLabel('profit_min', 'Profit% ≥')}</span>
                  <input value={String(profitMin)} onChange={(e) => setProfitMin(Number(e.target.value || 0))} type="number" min={profitMeta.min} max={profitMeta.max} step={profitMeta.step} className="gmz-input" />
                </label>
              ) : null}

              {hasFilter('liq_min') ? (
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">{filterUiLabel('liq_min', 'Liquidity ≥')}</span>
                  <input value={String(liqMin)} onChange={(e) => setLiqMin(Number(e.target.value || 0))} type="number" min={liqMeta.min} max={liqMeta.max} step={liqMeta.step} className="gmz-input" />
                </label>
              ) : null}

              {hasFilter('lp_max') ? (
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">{filterUiLabel('lp_max', 'LP ≤')}</span>
                  <input value={String(lpMax)} onChange={(e) => setLpMax(Number(e.target.value || 0))} type="number" min={lpMeta.min} max={lpMeta.max} step={lpMeta.step} className="gmz-input" />
                </label>
              ) : null}

              {hasFilter('ar_min') ? (
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">{filterUiLabel('ar_min', 'AR ≥')}</span>
                  <input value={String(arMin)} onChange={(e) => setArMin(Number(e.target.value || 0))} type="number" min={arMeta.min} max={arMeta.max} step={arMeta.step} className="gmz-input" />
                </label>
              ) : null}

              {hasFilter('vv_min') ? (
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">{filterUiLabel('vv_min', 'VV ≥')}</span>
                  <input value={String(vvMin)} onChange={(e) => setVvMin(Number(e.target.value || 0))} type="number" min={vvMeta.min} max={vvMeta.max} step={vvMeta.step} className="gmz-input" />
                </label>
              ) : null}

              {hasFilter('min_score') ? (
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Мин. score (0..100)</span>
                  <input value={minScore} onChange={(e) => setMinScore(e.target.value)} type="number" min={0} max={100} placeholder="Например: 30" className="gmz-input" />
                </label>
              ) : null}

              {hasFilter('min_undervalue_pct') ? (
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Мин. недооценка (%)</span>
                  <input value={minUndervalue} onChange={(e) => setMinUndervalue(e.target.value)} type="number" placeholder="Например: 5" className="gmz-input" />
                </label>
              ) : null}

              {hasFilter('max_risk') ? (
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Макс. риск (0..1)</span>
                  <input value={maxRisk} onChange={(e) => setMaxRisk(e.target.value)} type="number" min={0} max={1} step="0.01" placeholder="Например: 0.4" className="gmz-input" />
                </label>
              ) : null}
            </div>

            {hasFilter('only_pro_alerts') ? (
              <label className="flex items-center justify-between gap-3 rounded-xl border border-[var(--line)] bg-[rgba(255,255,255,0.72)] px-3 py-2 text-sm">
                <span>{filterUiLabel('only_pro_alerts', 'Только PRO-алерты')}</span>
                <input type="checkbox" checked={onlyProAlerts} onChange={(e) => setOnlyProAlerts(e.target.checked)} className="h-4 w-4" />
              </label>
            ) : null}

            {hasFilter('only_new_1h') ? (
              <label className="flex items-center justify-between gap-3 rounded-xl border border-[var(--line)] bg-[rgba(255,255,255,0.72)] px-3 py-2 text-sm">
                <span>{filterUiLabel('only_new_1h', 'Только новые (1ч)')}</span>
                <input type="checkbox" checked={onlyNew} onChange={(e) => setOnlyNew(e.target.checked)} className="h-4 w-4" />
              </label>
            ) : null}

            <button type="button" onClick={onApply} className="gmz-btn gmz-btn-primary w-full px-4 text-sm">Применить</button>
          </div>
        </BentoCard>

        <BentoCard title={titleTable} className="xl:col-span-1 w-full">
          {error ? <div className="mb-3 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">Ошибка: {error}</div> : null}
          {refreshing ? <div className="mb-3 text-xs font-medium text-slate-500">Обновляем данные…</div> : null}
          {loading ? (
            <div className="grid gap-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <LoadingBlock key={i} className="h-14" />
              ))}
            </div>
          ) : filtered.length ? (
            <div ref={tableWrapRef} className="gmz-table-wrap xl:h-[calc(100vh-120px)] xl:max-h-[calc(100vh-200px)]" onScroll={onTableScroll}>
              <table className="gmz-table gmz-signals-table">
                <thead>
                  <tr>
                    {columns.map((col) => {
                      const colId = String(col.id || '')
                      const width = resolveColumnWidth(colId, Number(col.width || 80))
                      const sticky = isStickyColumn(colId)
                      const centered = isCenterColumn(colId)
                      return (
                        <th
                          key={colId}
                          style={{
                            width,
                            minWidth: width,
                            maxWidth: width,
                            textAlign: centered ? 'center' : 'left',
                            ...(sticky ? { position: 'sticky', left: stickyLeft(colId), zIndex: 3 } : {}),
                          }}
                        >
                          {String(col.ui || colId)}
                        </th>
                      )
                    })}
                  </tr>
                </thead>
                <tbody>
                  {topPad > 0 ? (
                    <tr>
                      <td colSpan={columns.length} style={{ height: topPad, padding: 0, borderBottom: 0 }} />
                    </tr>
                  ) : null}
                  {visibleRows.map((row) => {
                    const key = signalKey(row)
                    const isExpanded = !!expanded[key]
                    const action = String(row.type || row.action || '').toUpperCase()
                    return (
                      <Fragment key={key}>
                        <tr style={{ height: ROW_HEIGHT }} onClick={() => setExpanded((s) => ({ ...s, [key]: !s[key] }))}>
                          {columns.map((col) => {
                            const colId = String(col.id || '')
                            const width = resolveColumnWidth(colId, Number(col.width || 80))
                            const sticky = isStickyColumn(colId)
                            const centered = isCenterColumn(colId)
                            let content: string | number | ReactNode
                            if (colId === 'action') {
                              content = <span className={signalChip(action)}>{signalTypeRu(action)}</span>
                            } else if (colId === 'market_regime_badge') {
                              content = `${row.market_regime_badge || '🟡'} ${String(row.market_regime || '')}`
                            } else if (colId === 'score100') {
                              content = qualityCell(row.score100, 'score')
                            } else if (colId === 'conf_pct') {
                              content = qualityCell(row.conf_pct, 'conf')
                            } else if (colId === 'variant_label') {
                              const title = cellText(row, colId)
                              content = (
                                <button
                                  type="button"
                                  className="flex w-full items-center gap-2 text-left hover:text-blue-700"
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    const variantId = String(row.variant_id || '')
                                    if (variantId) {
                                      navigate(`/variant/${encodeURIComponent(variantId)}`, {
                                        state: {
                                          variantFallback: {
                                            collectionId: String(row.collection_id || '').trim(),
                                            collection: String(row.collection || '').trim(),
                                            model: String(row.model || '').trim(),
                                            background: String(row.background || '').trim(),
                                            pattern: String(row.pattern || '').trim(),
                                          },
                                        },
                                      })
                                    }
                                  }}
                                >
                                  <img
                                    src={String(row.preview_url || '/favicon.png')}
                                    alt={title}
                                    className="h-7 w-7 shrink-0 rounded-lg border border-slate-200 object-cover"
                                    loading="lazy"
                                    onError={(e) => {
                                      const img = e.currentTarget
                                      if (img.dataset.fallbackDone === '1') return
                                      img.dataset.fallbackDone = '1'
                                      img.src = '/favicon.png'
                                    }}
                                  />
                                  <span className="truncate font-semibold text-slate-800">{title}</span>
                                </button>
                              )
                            } else if (colId === 'ts') {
                              content = <span className="text-xs text-slate-600">{cellText(row, colId)}</span>
                            } else {
                              content = <span className="tabular-nums">{cellText(row, colId)}</span>
                            }
                            return (
                              <td
                                key={colId}
                                style={{
                                  width,
                                  minWidth: width,
                                  maxWidth: width,
                                  textAlign: centered ? 'center' : 'left',
                                  whiteSpace: colId === 'action' || colId === 'market_regime_badge' ? 'nowrap' : undefined,
                                  ...(sticky ? { position: 'sticky', left: stickyLeft(colId), zIndex: 2, background: '#fff' } : {}),
                                }}
                              >
                                {content}
                              </td>
                            )
                          })}
                        </tr>
                        {isExpanded ? (
                          <tr>
                            <td colSpan={columns.length} className="bg-slate-50/80 p-3">
                              <div className="grid gap-3 xl:grid-cols-4">
                                {rowSections.map((section) => (
                                  <Fragment key={`${key}:${String(section.id || section.ui || 'sec')}`}>
                                    {renderRowSection(row, section, () => setSelected(row))}
                                  </Fragment>
                                ))}
                              </div>
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    )
                  })}
                  {bottomPad > 0 ? (
                    <tr>
                      <td colSpan={columns.length} style={{ height: bottomPad, padding: 0, borderBottom: 0 }} />
                    </tr>
                  ) : null}
                </tbody>
              </table>
              <div className="sticky bottom-0 border-t border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">
                {loadingMore ? 'Загружаем следующую страницу…' : hasMore ? 'Прокрутите вниз для догрузки' : 'Конец ленты'}
              </div>
            </div>
          ) : (
            <div className="text-sm text-slate-500">Сигналы не найдены по текущим фильтрам</div>
          )}
        </BentoCard>
      </BentoGrid>

      {selected ? <SignalDetailsDrawer signal={selected} onClose={() => setSelected(null)} /> : null}
    </section>
  )
}
