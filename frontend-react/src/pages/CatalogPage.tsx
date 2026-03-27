import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import catalogUiRaw from '../../../config/catalog/catalog_page_pro_ui_mapping_v1.json'
import catalogBentoRaw from '../../../config/catalog/bento_ui_catalog_blocks_v1.json'
import { BentoCard } from '../components/BentoCard'
import { BentoGrid } from '../components/BentoGrid'
import { GmzSelect } from '../components/GmzSelect'
import { LoadingBlock } from '../components/LoadingBlock'
import { MetricTile } from '../components/MetricTile'
import { PageHeader } from '../components/PageHeader'
import { getCatalogFeed, getCatalogVariant, getMarketStatus, pct, subscribeCatalogStream, subscribeRealtime, ton } from '../lib/api'
import { readUiAutoRefreshMinutes, uiAutoRefreshMs } from '../lib/uiSettings'
import type { CatalogRowPro, MarketStatusResponse, SignalType } from '../types/api'

type MarketRegime = 'RISK_ON' | 'MEAN_REVERT' | 'RISK_OFF' | 'PANIC'

type CatalogUiMapping = {
  primary_data_source?: string
  realtime_sse?: string
  realtime_event?: string
  actions?: string[]
  columns?: Array<{ id?: string; label?: string }>
  filters?: Array<{ id?: string; default?: number }>
  side_panel?: {
    data_source?: string
  }
}

const CATALOG_UI = (catalogUiRaw || {}) as CatalogUiMapping
const CATALOG_BENTO = catalogBentoRaw as Record<string, unknown>

const REGIME_OPTIONS: MarketRegime[] = ['RISK_ON', 'MEAN_REVERT', 'RISK_OFF', 'PANIC']

function actionRu(value?: string): string {
  const v = String(value || '').toUpperCase()
  if (v === 'BUY') return 'КУПИТЬ'
  if (v === 'SELL') return 'ПРОДАТЬ'
  if (v === 'WATCH') return 'НАБЛЮДАТЬ'
  if (v === 'SKIP') return 'ПРОПУСТИТЬ'
  return 'Н/Д'
}

function actionClass(value?: string): string {
  const v = String(value || '').toUpperCase()
  if (v === 'BUY') return 'gmz-chip buy'
  if (v === 'SELL') return 'gmz-chip sell'
  if (v === 'WATCH') return 'gmz-chip watch'
  return 'gmz-chip hold'
}

function regimeRu(value?: string): string {
  const v = String(value || '').toUpperCase()
  if (v === 'RISK_ON') return 'Рост'
  if (v === 'MEAN_REVERT') return 'Флет'
  if (v === 'RISK_OFF') return 'Снижение'
  if (v === 'PANIC') return 'Паника'
  return 'Н/Д'
}

function formatAge(secRaw: unknown): string {
  const sec = Math.max(0, Number(secRaw || 0))
  if (sec < 60) return `${Math.floor(sec)}с`
  if (sec < 3600) return `${Math.floor(sec / 60)}м`
  if (sec < 86400) return `${Math.floor(sec / 3600)}ч`
  return `${Math.floor(sec / 86400)}д`
}

function formatCountdown(totalSec: number): string {
  const sec = Math.max(0, Math.floor(totalSec))
  const mm = Math.floor(sec / 60)
  const ss = sec % 60
  return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
}

function fmtDateTime(value?: string): string {
  const raw = String(value || '').trim()
  if (!raw) return 'н/д'
  const dt = new Date(raw)
  if (Number.isNaN(dt.getTime())) return raw
  return dt.toLocaleString('ru-RU')
}

function defaultFilterValue(id: string, fallback: number): number {
  const rows = Array.isArray(CATALOG_UI.filters) ? CATALOG_UI.filters : []
  for (const row of rows) {
    if (String(row?.id || '').trim() === id && Number.isFinite(Number(row?.default))) {
      return Number(row?.default)
    }
  }
  return fallback
}

export function CatalogPage() {
  const autoRefreshMinutes = useMemo(() => readUiAutoRefreshMinutes(), [])
  const autoRefreshMs = useMemo(() => uiAutoRefreshMs(autoRefreshMinutes), [autoRefreshMinutes])

  const [items, setItems] = useState<CatalogRowPro[]>([])
  const [selected, setSelected] = useState<CatalogRowPro | null>(null)
  const [selectedDetails, setSelectedDetails] = useState<CatalogRowPro | null>(null)
  const [marketStatus, setMarketStatus] = useState<MarketStatusResponse | null>(null)

  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [expandedRow, setExpandedRow] = useState<string>('')
  const [nextRefreshSec, setNextRefreshSec] = useState(Math.ceil(autoRefreshMs / 1000))

  const [q, setQ] = useState('')
  const [actions, setActions] = useState<SignalType[]>([])
  const [regimes, setRegimes] = useState<MarketRegime[]>([])
  const [preset, setPreset] = useState('')
  const [sortBy, setSortBy] = useState<'edgerank' | 'profit' | 'liquidity' | 'undervalue' | 'updated'>('edgerank')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [edgeMin, setEdgeMin] = useState<number>(() => defaultFilterValue('edgeRank_min', 55))
  const [confMin, setConfMin] = useState<number>(() => defaultFilterValue('conf_min', 35))
  const [profitMin, setProfitMin] = useState<number>(() => defaultFilterValue('profit_min_pct', 8))
  const [liqMin, setLiqMin] = useState<number>(() => defaultFilterValue('liq_min', 35))
  const [depthMin, setDepthMin] = useState<number>(() => defaultFilterValue('depth_min', 0.2))
  const [arMin, setArMin] = useState<number>(() => defaultFilterValue('ar_min', 0.9))
  const [lpMax, setLpMax] = useState<number>(() => defaultFilterValue('lp_max', 4.0))
  const [activeLotsMin, setActiveLotsMin] = useState<number>(() => defaultFilterValue('active_lots_min', 0))
  const [activeLotsMax, setActiveLotsMax] = useState<number>(() => defaultFilterValue('active_lots_max', 9999))
  const [listedShareMin, setListedShareMin] = useState<number>(() => defaultFilterValue('listed_share_min', 0) / 100)
  const [listedShareMax, setListedShareMax] = useState<number>(() => defaultFilterValue('listed_share_max', 100) / 100)

  const firstLoadRef = useRef(true)
  const nextRefreshAtRef = useRef<number>(Date.now() + autoRefreshMs)
  const [flashRows, setFlashRows] = useState<Record<string, number>>({})
  const actionOptions = useMemo<SignalType[]>(() => {
    const allowed: SignalType[] = ['BUY', 'SELL', 'WATCH', 'SKIP']
    const fromCfg = (Array.isArray(CATALOG_UI.actions) ? CATALOG_UI.actions : [])
      .map((x) => String(x || '').trim().toUpperCase())
      .filter((x): x is SignalType => allowed.includes(x as SignalType))
    return fromCfg.length ? fromCfg : allowed
  }, [])
  const presetOptions = useMemo<Array<{ id: string; label: string }>>(() => {
    const presets = (Array.isArray(CATALOG_UI.filters) ? CATALOG_UI.filters : [])
      .find((f) => String(f?.id || '').trim() === 'preset')
    const values = Array.isArray((presets as { values?: unknown[] } | undefined)?.values)
      ? ((presets as { values?: unknown[] }).values || [])
      : []
    const cleaned = values
      .map((x) => String(x || '').trim().toUpperCase())
      .filter(Boolean)
    const uniq = Array.from(new Set(cleaned))
    return [{ id: '', label: 'Без пресета' }, ...uniq.map((id) => ({ id, label: id.replaceAll('_', ' ') }))]
  }, [])
  const sidePanelVariantEndpoint = useMemo(() => {
    const dataSource = String(CATALOG_UI.side_panel?.data_source || '').trim()
    if (!dataSource) return undefined
    if (dataSource.includes('{variant_id}')) {
      return dataSource.replace(/\/?\{variant_id\}/g, '')
    }
    return dataSource
  }, [])
  const catalogColumns = useMemo<Array<{ id: string; label: string }>>(() => {
    const fromCfg = Array.isArray(CATALOG_UI.columns) ? CATALOG_UI.columns : []
    const cleaned = fromCfg
      .map((c) => ({
        id: String(c?.id || '').trim(),
        label: String(c?.label || '').trim(),
      }))
      .filter((c) => c.id.length > 0 && c.label.length > 0)
    if (cleaned.length) return cleaned
    return [
      { id: 'variant_label', label: 'Вариант' },
      { id: 'floor_ton', label: 'Floor' },
      { id: 'fair_ton', label: 'Fair' },
      { id: 'undervalue_pct', label: 'Недооценка' },
      { id: 'expected_profit_pct', label: 'Профит' },
      { id: 'edgeRank100', label: 'EdgeRank' },
      { id: 'conf_pct', label: 'Conf' },
      { id: 'liquidity_score', label: 'Ликвидность' },
      { id: 'absorption_30m', label: 'Поглощение 30м' },
      { id: 'listing_pressure', label: 'Давление (LP)' },
      { id: 'depth_score', label: 'Глубина' },
      { id: 'active_lots', label: 'Активные лоты' },
      { id: 'listed_share', label: 'Доля в продаже' },
      { id: 'market_regime', label: 'Режим' },
      { id: 'action', label: 'Действие' },
      { id: 'updated_at', label: 'Обновлено' },
      { id: 'age_sec', label: 'Возраст' },
    ]
  }, [])

  const scheduleNextAutoRefresh = useCallback((baseTs: number = Date.now()) => {
    nextRefreshAtRef.current = baseTs + autoRefreshMs
    setNextRefreshSec(Math.ceil(autoRefreshMs / 1000))
  }, [autoRefreshMs])

  const load = useCallback(async () => {
    if (firstLoadRef.current) setLoading(true)
    else setRefreshing(true)
    setError('')
    try {
      const [feed, market] = await Promise.all([
        getCatalogFeed({
          q,
          action: actions,
          marketRegime: regimes,
          edgeRankMin: edgeMin,
          confMin,
          profitMinPct: profitMin,
          liqMin,
          depthMin,
          arMin,
          lpMax,
          activeLotsMin,
          activeLotsMax,
          listedShareMin,
          listedShareMax,
          preset,
          sort: sortBy,
          dir: sortDir,
          limit: 300,
          endpoint: CATALOG_UI.primary_data_source || undefined,
        }),
        getMarketStatus('30m'),
      ])
      setItems(feed.items || [])
      setNextCursor(feed.next_cursor || null)
      setMarketStatus(market)
      if (!selected && (feed.items || []).length) {
        setSelected(feed.items[0])
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки каталога')
    } finally {
      setLoading(false)
      setRefreshing(false)
      firstLoadRef.current = false
    }
  }, [q, actions, regimes, edgeMin, confMin, profitMin, liqMin, depthMin, arMin, lpMax, activeLotsMin, activeLotsMax, listedShareMin, listedShareMax, preset, sortBy, sortDir, selected])

  useEffect(() => {
    scheduleNextAutoRefresh(Date.now())
    void load()
  }, [load, scheduleNextAutoRefresh])

  useEffect(() => {
    const poll = window.setInterval(() => {
      scheduleNextAutoRefresh(Date.now())
      void load()
    }, autoRefreshMs)
    const tick = window.setInterval(() => {
      const remain = Math.max(0, Math.ceil((nextRefreshAtRef.current - Date.now()) / 1000))
      setNextRefreshSec(remain)
    }, 1000)

    const es = subscribeCatalogStream((row) => {
      if (!row || !row.variant_id) return
      const now = Date.now()
      setItems((prev) => {
        const idx = prev.findIndex((x) => x.variant_id === row.variant_id)
        if (idx === -1) return [row, ...prev].slice(0, 300)
        const next = prev.slice()
        next[idx] = row
        return next
      })
      setFlashRows((prev) => ({ ...prev, [row.variant_id]: now + 3000 }))
      setSelected((prev) => (prev && prev.variant_id === row.variant_id ? row : prev))
    }, undefined, {
      endpoint: CATALOG_UI.realtime_sse || undefined,
      event: CATALOG_UI.realtime_event || undefined,
      limit: 300,
    })

    return () => {
      es.close()
      window.clearInterval(poll)
      window.clearInterval(tick)
    }
  }, [autoRefreshMs, load, scheduleNextAutoRefresh])

  useEffect(() => {
    const es = subscribeRealtime((evt) => {
      if (String(evt.type || '').trim() !== 'market.status') return
      const payload = evt.payload
      if (!payload || typeof payload !== 'object') return
      setMarketStatus(payload as unknown as MarketStatusResponse)
    }, undefined, {
      types: ['market.status'],
      heartbeatMs: 15000,
      mode: 'tz',
    })
    return () => es.close()
  }, [])

  useEffect(() => {
    const id = window.setInterval(() => {
      const now = Date.now()
      setFlashRows((prev) => {
        const next: Record<string, number> = {}
        for (const [k, v] of Object.entries(prev)) {
          if (v > now) next[k] = v
        }
        return Object.keys(next).length === Object.keys(prev).length ? prev : next
      })
    }, 400)
    return () => window.clearInterval(id)
  }, [])

  useEffect(() => {
    const id = String(selected?.variant_id || '').trim()
    if (!id) {
      setSelectedDetails(null)
      return
    }
    let closed = false
    void getCatalogVariant(id, { endpoint: sidePanelVariantEndpoint }).then((row) => {
      if (closed) return
      setSelectedDetails(row)
    }).catch(() => {
      if (closed) return
      setSelectedDetails(null)
    })
    return () => {
      closed = true
    }
  }, [selected?.variant_id, sidePanelVariantEndpoint])

  const stats = useMemo(() => {
    const buy = items.filter((x) => String(x.action || '').toUpperCase() === 'BUY').length
    const sell = items.filter((x) => String(x.action || '').toUpperCase() === 'SELL').length
    const watch = items.filter((x) => String(x.action || '').toUpperCase() === 'WATCH').length
    return { total: items.length, buy, sell, watch }
  }, [items])

  const toggleSetValue = <T extends string>(setFn: (next: T[]) => void, current: T[], value: T) => {
    if (current.includes(value)) setFn(current.filter((x) => x !== value))
    else setFn([...current, value])
  }

  return (
    <section>
      <PageHeader
        title="Каталог (PRO)"
        subtitle={`Bento: ${(CATALOG_BENTO as { version?: string })?.version || 'v1'}`}
        right={(
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-slate-500">
              Обновление через {formatCountdown(nextRefreshSec)}
            </span>
            <button
              type="button"
              onClick={() => {
                scheduleNextAutoRefresh(Date.now())
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
        <BentoCard title="Режим рынка и контекст" className="xl:col-span-6">
          <div className="grid gap-3 sm:grid-cols-4">
            <MetricTile label="Режим" value={regimeRu(marketStatus?.market_regime)} />
            <MetricTile label="Data health" value={String(marketStatus?.data_health || 'N/A')} />
            <MetricTile label="Conf рынка" value={pct(marketStatus?.data_conf_pct)} />
            <MetricTile label="Источник" value={String(marketStatus?.source || 'n/a')} />
          </div>
        </BentoCard>

        <BentoCard title="Фильтры и пресеты" className="xl:col-span-6">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricTile label="Строк" value={stats.total} />
            <MetricTile label="BUY" value={stats.buy} />
            <MetricTile label="SELL" value={stats.sell} />
            <MetricTile label="WATCH" value={stats.watch} />
          </div>

          <div className="mt-3 grid gap-2 lg:grid-cols-4">
            <label className="text-xs text-slate-500">Поиск
              <input className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" value={q} onChange={(e) => setQ(e.target.value)} placeholder="collection / model / background / pattern" />
              <span className="mt-1 block text-[11px] text-slate-400">Коллекция / Модель / Фон / Узор</span>
            </label>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-500">Пресет</div>
              <div className="flex flex-wrap gap-1.5">
                {presetOptions.map((x) => (
                  <button
                    key={x.id || 'NONE'}
                    type="button"
                    onClick={() => setPreset(x.id)}
                    className={`rounded-lg border px-2 py-1 text-xs ${preset === x.id
                      ? 'border-blue-300 bg-blue-50 text-blue-700'
                      : 'border-slate-200 bg-white text-slate-600'
                    }`}
                  >
                    {x.label}
                  </button>
                ))}
              </div>
            </div>
            <label className="text-xs text-slate-500">Сортировка
              <div className="mt-1">
                <GmzSelect
                  value={sortBy}
                  onChange={(v) => setSortBy((v as typeof sortBy) || 'edgerank')}
                  options={[
                    { value: 'edgerank', label: 'EdgeRank' },
                    { value: 'profit', label: 'Профит' },
                    { value: 'liquidity', label: 'Ликвидность' },
                    { value: 'undervalue', label: 'Недооценка' },
                    { value: 'updated', label: 'Обновлено' },
                  ]}
                />
              </div>
            </label>
            <label className="text-xs text-slate-500">Направление
              <div className="mt-1">
                <GmzSelect
                  value={sortDir}
                  onChange={(v) => setSortDir((v as typeof sortDir) || 'desc')}
                  options={[
                    { value: 'desc', label: 'DESC' },
                    { value: 'asc', label: 'ASC' },
                  ]}
                />
              </div>
            </label>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-500">Действие</div>
              <div className="flex flex-wrap gap-1.5">
                {actionOptions.map((x) => (
                  <button key={x} type="button" onClick={() => toggleSetValue<SignalType>(setActions, actions, x)} className={`rounded-lg border px-2 py-1 text-xs ${actions.includes(x) ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-slate-200 bg-white text-slate-600'}`}>
                    {x}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-500">Режим</div>
              <div className="flex flex-wrap gap-1.5">
                {REGIME_OPTIONS.map((x) => (
                  <button key={x} type="button" onClick={() => toggleSetValue<MarketRegime>(setRegimes, regimes, x)} className={`rounded-lg border px-2 py-1 text-xs ${regimes.includes(x) ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-slate-200 bg-white text-slate-600'}`}>
                    {x}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-xs text-slate-500">EdgeRank ≥<input className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" type="number" value={edgeMin} onChange={(e) => setEdgeMin(Number(e.target.value || 0))} /></label>
            <label className="text-xs text-slate-500">Conf ≥<input className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" type="number" value={confMin} onChange={(e) => setConfMin(Number(e.target.value || 0))} /></label>
            <label className="text-xs text-slate-500">Profit ≥ %<input className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" type="number" value={profitMin} onChange={(e) => setProfitMin(Number(e.target.value || 0))} /></label>
            <label className="text-xs text-slate-500">Liquidity ≥<input className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" type="number" value={liqMin} onChange={(e) => setLiqMin(Number(e.target.value || 0))} /></label>
            <label className="text-xs text-slate-500">Depth ≥<input className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" type="number" step="0.01" value={depthMin} onChange={(e) => setDepthMin(Number(e.target.value || 0))} /></label>
            <label className="text-xs text-slate-500">Поглощение ≥<input className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" type="number" step="0.1" value={arMin} onChange={(e) => setArMin(Number(e.target.value || 0))} /></label>
            <label className="text-xs text-slate-500">LP ≤<input className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" type="number" step="0.1" value={lpMax} onChange={(e) => setLpMax(Number(e.target.value || 0))} /></label>
            <label className="text-xs text-slate-500">Лоты от/до
              <div className="mt-1 grid grid-cols-2 gap-1">
                <input className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" type="number" value={activeLotsMin} onChange={(e) => setActiveLotsMin(Number(e.target.value || 0))} />
                <input className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" type="number" value={activeLotsMax} onChange={(e) => setActiveLotsMax(Number(e.target.value || 0))} />
              </div>
            </label>
            <label className="text-xs text-slate-500">Доля listed от/до %
              <div className="mt-1 grid grid-cols-2 gap-1">
                <input className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" type="number" min={0} max={100} value={Math.round(listedShareMin * 100)} onChange={(e) => setListedShareMin(Math.max(0, Math.min(1, Number(e.target.value || 0) / 100)))} />
                <input className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" type="number" min={0} max={100} value={Math.round(listedShareMax * 100)} onChange={(e) => setListedShareMax(Math.max(0, Math.min(1, Number(e.target.value || 0) / 100)))} />
              </div>
            </label>
          </div>

          <button type="button" onClick={() => void load()} className="mt-3 gmz-btn gmz-btn-primary w-full px-4 py-2 text-sm">Применить</button>
        </BentoCard>

        <BentoCard title={`Каталог (PRO) • ${items.length.toLocaleString('ru-RU')}`} className="xl:col-span-4">
          {refreshing ? <div className="mb-2 text-xs font-medium text-slate-500">Обновляем данные…</div> : null}
          {error ? <div className="mb-3 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">Ошибка: {error}</div> : null}
          {loading ? (
            <LoadingBlock className="h-48" />
          ) : items.length ? (
            <div className="gmz-table-wrap">
              <table className="gmz-table">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    {catalogColumns.map((col) => (
                      <th key={col.id} className="pb-2 pr-3">{col.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map((row) => {
                    const key = `${row.variant_id}:${row.updated_at || ''}`
                    const opened = expandedRow === key
                    return (
                      <Fragment key={key}>
                        <tr className={`border-b border-slate-100 transition-colors ${flashRows[row.variant_id] ? 'bg-blue-50/70' : ''}`}>
                          {catalogColumns.map((col) => {
                            const id = col.id
                            if (id === 'variant_label') {
                              return (
                                <td key={id} className="py-2 pr-3">
                                  <button type="button" onClick={() => setSelected(row)} className="gmz-btn gmz-btn-ghost rounded-lg px-2 py-1 text-left text-sm font-medium text-slate-700 hover:text-[var(--accent)]">
                                    {row.variant_label || row.variant_id}
                                  </button>
                                </td>
                              )
                            }
                            if (id === 'floor_ton') return <td key={id} className="py-2 pr-3 tabular-nums">{ton(row.floor_ton)}</td>
                            if (id === 'fair_ton') return <td key={id} className="py-2 pr-3 tabular-nums">{ton(row.fair_ton)}</td>
                            if (id === 'undervalue_pct') return <td key={id} className="py-2 pr-3 tabular-nums">{pct(row.undervalue_pct)}</td>
                            if (id === 'expected_profit_pct') return <td key={id} className="py-2 pr-3 tabular-nums">{pct(row.expected_profit_pct)}</td>
                            if (id === 'edgeRank100') return <td key={id} className="py-2 pr-3 tabular-nums">{Number(row.edgeRank100 || 0).toFixed(1)}</td>
                            if (id === 'conf_pct') return <td key={id} className="py-2 pr-3 tabular-nums">{pct(row.conf_pct)}</td>
                            if (id === 'liquidity_score') return <td key={id} className="py-2 pr-3 tabular-nums">{Number(row.liquidity_score || 0).toFixed(1)}</td>
                            if (id === 'absorption_30m') return <td key={id} className="py-2 pr-3 tabular-nums">{Number(row.absorption_30m || 0).toFixed(2)}</td>
                            if (id === 'listing_pressure') return <td key={id} className="py-2 pr-3 tabular-nums">{Number(row.listing_pressure || 0).toFixed(2)}</td>
                            if (id === 'depth_score') return <td key={id} className="py-2 pr-3 tabular-nums">{Number(row.depth_score || 0).toFixed(2)}</td>
                            if (id === 'active_lots') return <td key={id} className="py-2 pr-3 tabular-nums">{Number(row.active_lots || 0).toLocaleString('ru-RU')}</td>
                            if (id === 'listed_share') return <td key={id} className="py-2 pr-3 tabular-nums">{pct(Number(row.listed_share || 0) * 100)}</td>
                            if (id === 'market_regime') return <td key={id} className="py-2 pr-3">{regimeRu(row.market_regime)}</td>
                            if (id === 'action') {
                              return (
                                <td key={id} className="py-2 pr-3">
                                  <div className="flex items-center gap-2">
                                    <span className={actionClass(row.action)}>{actionRu(row.action)}</span>
                                    <button type="button" className="text-xs text-slate-500 underline" onClick={() => setExpandedRow(opened ? '' : key)}>
                                      {opened ? 'Скрыть' : 'Детали'}
                                    </button>
                                  </div>
                                </td>
                              )
                            }
                            if (id === 'updated_at') return <td key={id} className="py-2 pr-3 text-xs text-slate-500">{fmtDateTime(row.updated_at)}</td>
                            if (id === 'age_sec') return <td key={id} className="py-2 pr-3 text-xs text-slate-500">{formatAge(row.age_sec)} назад</td>
                            return <td key={id} className="py-2 pr-3 text-xs text-slate-400">—</td>
                          })}
                        </tr>
                        {opened ? (
                          <tr className="border-b border-slate-100 bg-slate-50/40">
                            <td className="px-2 py-3" colSpan={Math.max(1, catalogColumns.length)}>
                              <div className="grid gap-3 md:grid-cols-3">
                                <div>
                                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Причины</div>
                                  <ul className="space-y-1 text-sm text-slate-700">
                                    {(row.reasons || []).map((x, i) => <li key={i}>• {x}</li>)}
                                  </ul>
                                </div>
                                <div>
                                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Риски</div>
                                  <ul className="space-y-1 text-sm text-slate-700">
                                    {(row.risk_flags || []).map((x, i) => <li key={i}>• {x}</li>)}
                                  </ul>
                                </div>
                                <div>
                                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Decision Trace</div>
                                  <pre className="max-h-48 overflow-auto rounded-lg border border-slate-200 bg-white p-2 text-xs text-slate-700">{JSON.stringify(row.decision_trace || {}, null, 2)}</pre>
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
              {nextCursor ? <div className="mt-2 text-xs text-slate-500">Есть еще строки (cursor: {nextCursor})</div> : null}
            </div>
          ) : (
            <div className="text-sm text-slate-500">Каталог пуст по выбранным фильтрам</div>
          )}
        </BentoCard>

        <BentoCard title="Быстрый просмотр варианта" className="xl:col-span-2">
          {!selected ? (
            <div className="text-sm text-slate-500">Выберите строку в таблице каталога.</div>
          ) : (
            <div className="space-y-2 text-sm">
              <div className="text-base font-semibold text-slate-900">{selected.variant_label || selected.variant_id}</div>
              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
                <MetricTile label="Floor" value={ton(selectedDetails?.floor_ton ?? selected.floor_ton)} />
                <MetricTile label="Fair" value={ton(selectedDetails?.fair_ton ?? selected.fair_ton)} />
                <MetricTile label="Недооценка" value={pct(selectedDetails?.undervalue_pct ?? selected.undervalue_pct)} />
                <MetricTile label="Профит" value={pct(selectedDetails?.expected_profit_pct ?? selected.expected_profit_pct)} />
                <MetricTile label="EdgeRank" value={Number(selectedDetails?.edgeRank100 ?? selected.edgeRank100 ?? 0).toFixed(1)} />
                <MetricTile label="Conf" value={pct(selectedDetails?.conf_pct ?? selected.conf_pct)} />
                <MetricTile label="Ликвидность" value={Number(selectedDetails?.liquidity_score ?? selected.liquidity_score ?? 0).toFixed(1)} />
                <MetricTile label="Поглощение 30м" value={Number(selectedDetails?.absorption_30m ?? selected.absorption_30m ?? 0).toFixed(2)} />
                <MetricTile label="Давление (LP)" value={Number(selectedDetails?.listing_pressure ?? selected.listing_pressure ?? 0).toFixed(2)} />
                <MetricTile label="Глубина" value={Number(selectedDetails?.depth_score ?? selected.depth_score ?? 0).toFixed(2)} />
                <MetricTile label="Активные лоты" value={Number(selectedDetails?.active_lots ?? selected.active_lots ?? 0).toLocaleString('ru-RU')} />
                <MetricTile label="Доля в продаже" value={pct(Number(selectedDetails?.listed_share ?? selected.listed_share ?? 0) * 100)} />
                <MetricTile label="Режим" value={regimeRu(selectedDetails?.market_regime ?? selected.market_regime)} />
                <MetricTile label="Действие" value={actionRu(selectedDetails?.action ?? selected.action)} />
                <MetricTile label="Листинги 10м" value={Number(selectedDetails?.listings_10m || 0).toLocaleString('ru-RU')} />
                <MetricTile label="Объем 24ч (TON)" value={Number(selectedDetails?.volume_24h_ton || 0).toLocaleString('ru-RU')} />
              </div>
            </div>
          )}
        </BentoCard>

        <BentoCard title="Как читать Catalog" className="xl:col-span-6">
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
            <li><strong>EdgeRank</strong> — фиксированный скор силы идеи.</li>
            <li>Режим рынка влияет на пороги <strong>BUY/SELL/WATCH/SKIP</strong> и приоритизацию.</li>
            <li>Раскройте строку, чтобы увидеть <strong>Причины / Риски / Decision Trace</strong>.</li>
          </ul>
        </BentoCard>
      </BentoGrid>
    </section>
  )
}
