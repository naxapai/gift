import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import screenersUiRaw from '../../../config/screeners/screeners_page_pro_ui_mapping_unified_v1.json'
import { BentoCard } from '../components/BentoCard'
import { BentoGrid } from '../components/BentoGrid'
import { LoadingBlock } from '../components/LoadingBlock'
import { MetricTile } from '../components/MetricTile'
import { PageHeader } from '../components/PageHeader'
import { getScreenersFeed, pct, subscribeScreenersStream, ton } from '../lib/api'
import { readUiAutoRefreshMinutes, uiAutoRefreshMs } from '../lib/uiSettings'
import type { ScreenerRowPro, SignalType } from '../types/api'

type MarketRegime = 'RISK_ON' | 'MEAN_REVERT' | 'RISK_OFF' | 'PANIC'
type ScreenerType =
  | 'NEW_LISTINGS'
  | 'RACE_MODE'
  | 'UNDERVALUED'
  | 'MOMENTUM_BUY'
  | 'BREAKDOWN_SELL'
  | 'WHALE_ACTIVITY'
  | 'LIQUIDITY_SPIKE'
  | 'VOLATILITY_SURGE'

const SCREENER_TYPE_OPTIONS: Array<{ id: ScreenerType; label: string }> = [
  { id: 'NEW_LISTINGS', label: 'NEW' },
  { id: 'RACE_MODE', label: 'RACE' },
  { id: 'UNDERVALUED', label: 'UNDERVALUED' },
  { id: 'MOMENTUM_BUY', label: 'MOMENTUM' },
  { id: 'BREAKDOWN_SELL', label: 'BREAKDOWN' },
  { id: 'WHALE_ACTIVITY', label: 'WHALE' },
  { id: 'LIQUIDITY_SPIKE', label: 'LIQ SPIKE' },
  { id: 'VOLATILITY_SURGE', label: 'VOL SURGE' },
]

const ACTION_OPTIONS: SignalType[] = ['BUY', 'SELL', 'WATCH', 'SKIP']
const REGIME_OPTIONS: MarketRegime[] = ['RISK_ON', 'MEAN_REVERT', 'RISK_OFF', 'PANIC']

type ScreenersUiMapping = {
  primary_data_source?: string
  realtime_sse?: string
  realtime_event?: string
  actions?: string[]
  columns?: Array<{ id?: string; label?: string }>
  filters?: Array<{ id?: string; default?: number }>
}

const SCREENERS_UI = (screenersUiRaw || {}) as ScreenersUiMapping
const SCREENERS_CACHE_KEY = 'gmz.screeners.cache.v1'

type ScreenersCachePayload = {
  savedAt: number
  items: ScreenerRowPro[]
}

function defaultFilterValue(id: string, fallback: number): number {
  const rows = Array.isArray(SCREENERS_UI.filters) ? SCREENERS_UI.filters : []
  for (const row of rows) {
    if (String(row?.id || '').trim() === id && Number.isFinite(Number(row?.default))) {
      return Number(row?.default)
    }
  }
  return fallback
}

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

export function ScreenersPage() {
  const navigate = useNavigate()
  const autoRefreshMinutes = useMemo(() => readUiAutoRefreshMinutes(), [])
  const autoRefreshMs = useMemo(() => uiAutoRefreshMs(autoRefreshMinutes), [autoRefreshMinutes])
  const [items, setItems] = useState<ScreenerRowPro[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [expandedRow, setExpandedRow] = useState<string>('')
  const [nextRefreshSec, setNextRefreshSec] = useState(Math.ceil(autoRefreshMs / 1000))

  const [screenerTypes, setScreenerTypes] = useState<ScreenerType[]>([])
  const [actions, setActions] = useState<SignalType[]>([])
  const [regimes, setRegimes] = useState<MarketRegime[]>([])
  const [edgeMin, setEdgeMin] = useState<number>(() => defaultFilterValue('edgeRank_min', 55))
  const [confMin, setConfMin] = useState<number>(() => defaultFilterValue('conf_min', 35))
  const [profitMin, setProfitMin] = useState<number>(() => defaultFilterValue('profit_min_pct', 8))
  const [liqMin, setLiqMin] = useState<number>(() => defaultFilterValue('liq_min', 35))
  const [arMin, setArMin] = useState<number>(() => defaultFilterValue('ar_min', 0.9))
  const [lpMax, setLpMax] = useState<number>(() => defaultFilterValue('lp_max', 4))

  const firstLoadRef = useRef(true)
  const nextRefreshAtRef = useRef<number>(Date.now() + autoRefreshMs)
  const actionOptions = useMemo<SignalType[]>(() => {
    const allowed: SignalType[] = ['BUY', 'SELL', 'WATCH', 'SKIP']
    const fromCfg = (Array.isArray(SCREENERS_UI.actions) ? SCREENERS_UI.actions : [])
      .map((x) => String(x || '').trim().toUpperCase())
      .filter((x): x is SignalType => allowed.includes(x as SignalType))
    return fromCfg.length ? fromCfg : ACTION_OPTIONS
  }, [])
  const screenerColumns = useMemo<Array<{ id: string; label: string }>>(() => {
    const fromCfg = Array.isArray(SCREENERS_UI.columns) ? SCREENERS_UI.columns : []
    const cleaned = fromCfg
      .map((c) => ({ id: String(c?.id || '').trim(), label: String(c?.label || '').trim() }))
      .filter((c) => c.id && c.label)
    if (cleaned.length) return cleaned
    return [
      { id: 'age', label: 'Возраст' },
      { id: 'screener_type', label: 'Скринер' },
      { id: 'variant_label', label: 'Вариант' },
      { id: 'price_ton', label: 'Цена' },
      { id: 'floor_ton', label: 'Floor' },
      { id: 'fair_ton', label: 'Fair' },
      { id: 'undervalue_pct', label: 'Недооценка' },
      { id: 'expected_profit_pct', label: 'Профит' },
      { id: 'edgeRank100', label: 'EdgeRank' },
      { id: 'score100', label: 'Score' },
      { id: 'conf_pct', label: 'Conf' },
      { id: 'liquidity_score', label: 'Ликвидность' },
      { id: 'absorption_30m', label: 'Поглощение 30м' },
      { id: 'listing_pressure', label: 'Давление' },
      { id: 'depth_score', label: 'Глубина' },
      { id: 'market_regime', label: 'Режим' },
      { id: 'action', label: 'Действие' },
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
      const feed = await getScreenersFeed({
        screenerType: screenerTypes,
        action: actions,
        marketRegime: regimes,
        edgeRankMin: edgeMin,
        confMin,
        profitMinPct: profitMin,
        liqMin,
        arMin,
        lpMax,
        limit: 200,
        endpoint: SCREENERS_UI.primary_data_source || undefined,
      })
      setItems(feed.items || [])
      const payload: ScreenersCachePayload = { savedAt: Date.now(), items: feed.items || [] }
      sessionStorage.setItem(SCREENERS_CACHE_KEY, JSON.stringify(payload))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки скринеров')
    } finally {
      setLoading(false)
      setRefreshing(false)
      firstLoadRef.current = false
    }
  }, [actions, arMin, confMin, edgeMin, liqMin, lpMax, profitMin, regimes, screenerTypes])

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(SCREENERS_CACHE_KEY)
      if (raw) {
        const payload = JSON.parse(raw) as ScreenersCachePayload
        if (payload && Array.isArray(payload.items) && Number.isFinite(Number(payload.savedAt))) {
          const ageMs = Date.now() - Number(payload.savedAt)
          if (ageMs >= 0 && ageMs < autoRefreshMs) {
            setItems(payload.items)
            setLoading(false)
            firstLoadRef.current = false
            nextRefreshAtRef.current = Number(payload.savedAt) + autoRefreshMs
            setNextRefreshSec(Math.ceil(Math.max(0, nextRefreshAtRef.current - Date.now()) / 1000))
            return
          }
        }
      }
    } catch {
      // session cache is best-effort
    }
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

    const es = subscribeScreenersStream((row) => {
      if (!row || !row.variant_id) return
      setItems((prev) => {
        const idx = prev.findIndex((x) => x.variant_id === row.variant_id && x.screener_type === row.screener_type)
        if (idx === -1) return [row, ...prev].slice(0, 200)
        const next = prev.slice()
        next[idx] = row
        return next
      })
    }, undefined, {
      endpoint: SCREENERS_UI.realtime_sse || undefined,
      event: SCREENERS_UI.realtime_event || undefined,
    })

    return () => {
      es.close()
      window.clearInterval(poll)
      window.clearInterval(tick)
    }
  }, [autoRefreshMs, load, scheduleNextAutoRefresh])

  const stats = useMemo(() => {
    const buy = items.filter((x) => String(x.action || '').toUpperCase() === 'BUY').length
    const sell = items.filter((x) => String(x.action || '').toUpperCase() === 'SELL').length
    return { total: items.length, buy, sell }
  }, [items])

  const toggleSetValue = <T extends string>(setFn: (next: T[]) => void, current: T[], value: T) => {
    if (current.includes(value)) setFn(current.filter((x) => x !== value))
    else setFn([...current, value])
  }

  return (
    <section>
      <PageHeader
        title="Скринеры"
        subtitle="PRO-лента: fixed EdgeRank + decision trace"
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
        <BentoCard title="Фильтры" className="xl:col-span-2 xl:sticky xl:top-4 xl:self-start">
          <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
            <MetricTile label="Сигналов" value={stats.total} />
            <MetricTile label="BUY" value={stats.buy} />
            <MetricTile label="SELL" value={stats.sell} />
          </div>

          <div className="mt-4 space-y-3 text-sm">
            <div>
              <div className="mb-1 text-xs font-semibold text-slate-500">Скринер</div>
              <div className="flex flex-wrap gap-1.5">
                {SCREENER_TYPE_OPTIONS.map((x) => (
                  <button
                    key={x.id}
                    type="button"
                    onClick={() => toggleSetValue<ScreenerType>(setScreenerTypes, screenerTypes, x.id)}
                    className={`rounded-lg border px-2 py-1 text-xs ${screenerTypes.includes(x.id)
                      ? 'border-blue-300 bg-blue-50 text-blue-700'
                      : 'border-slate-200 bg-white text-slate-600'
                    }`}
                  >
                    {x.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="mb-1 text-xs font-semibold text-slate-500">Действие</div>
              <div className="flex flex-wrap gap-1.5">
                {actionOptions.map((x) => (
                  <button
                    key={x}
                    type="button"
                    onClick={() => toggleSetValue<SignalType>(setActions, actions, x)}
                    className={`rounded-lg border px-2 py-1 text-xs ${actions.includes(x)
                      ? 'border-blue-300 bg-blue-50 text-blue-700'
                      : 'border-slate-200 bg-white text-slate-600'
                    }`}
                  >
                    {x}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="mb-1 text-xs font-semibold text-slate-500">Режим</div>
              <div className="flex flex-wrap gap-1.5">
                {REGIME_OPTIONS.map((x) => (
                  <button
                    key={x}
                    type="button"
                    onClick={() => toggleSetValue<MarketRegime>(setRegimes, regimes, x)}
                    className={`rounded-lg border px-2 py-1 text-xs ${regimes.includes(x)
                      ? 'border-blue-300 bg-blue-50 text-blue-700'
                      : 'border-slate-200 bg-white text-slate-600'
                    }`}
                  >
                    {x}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <label className="text-xs text-slate-500">EdgeRank ≥
                <input className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" type="number" value={edgeMin} onChange={(e) => setEdgeMin(Number(e.target.value || 0))} />
              </label>
              <label className="text-xs text-slate-500">Conf ≥
                <input className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" type="number" value={confMin} onChange={(e) => setConfMin(Number(e.target.value || 0))} />
              </label>
              <label className="text-xs text-slate-500">Профит ≥ %
                <input className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" type="number" value={profitMin} onChange={(e) => setProfitMin(Number(e.target.value || 0))} />
              </label>
              <label className="text-xs text-slate-500">Ликвидность ≥
                <input className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" type="number" value={liqMin} onChange={(e) => setLiqMin(Number(e.target.value || 0))} />
              </label>
              <label className="text-xs text-slate-500">Поглощение ≥
                <input className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" type="number" step="0.1" value={arMin} onChange={(e) => setArMin(Number(e.target.value || 0))} />
              </label>
              <label className="text-xs text-slate-500">Давление ≤
                <input className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" type="number" step="0.1" value={lpMax} onChange={(e) => setLpMax(Number(e.target.value || 0))} />
              </label>
            </div>

            <button type="button" onClick={() => void load()} className="gmz-btn gmz-btn-primary w-full px-4 py-2 text-sm">Применить</button>
          </div>
        </BentoCard>

        <BentoCard title="Скринеры (PRO)" className="xl:col-span-4">
          {refreshing ? <div className="mb-2 text-xs font-medium text-slate-500">Обновляем данные…</div> : null}
          {error ? <div className="mb-3 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">Ошибка: {error}</div> : null}
          {loading ? (
            <LoadingBlock className="h-40" />
          ) : items.length ? (
            <div className="gmz-table-wrap">
              <table className="gmz-table">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    {screenerColumns.map((col) => (
                      <th key={col.id} className="pb-2 pr-3">{col.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map((v) => {
                    const rowKey = `${v.variant_id}:${v.screener_type}:${v.ts}`
                    const opened = expandedRow === rowKey
                    return (
                      <Fragment key={rowKey}>
                        <tr className="border-b border-slate-100">
                          {screenerColumns.map((col) => {
                            const id = col.id
                            if (id === 'age') return <td key={id} className="py-2 pr-3 tabular-nums">{formatAge(v.age)}</td>
                            if (id === 'screener_type') return <td key={id} className="py-2 pr-3"><span className="gmz-chip hold">{v.screener_type}</span></td>
                            if (id === 'variant_label') {
                              return (
                                <td key={id} className="py-2 pr-3">
                                  <button
                                    type="button"
                                    onClick={() => navigate(`/variant/${encodeURIComponent(v.variant_id)}`)}
                                    className="gmz-btn gmz-btn-ghost rounded-lg px-2 py-1 text-left text-sm font-medium text-slate-700 hover:text-[var(--accent)]"
                                  >
                                    {v.variant_label || v.variant_id}
                                  </button>
                                </td>
                              )
                            }
                            if (id === 'price_ton') return <td key={id} className="py-2 pr-3 tabular-nums">{ton(v.price_ton)}</td>
                            if (id === 'floor_ton') return <td key={id} className="py-2 pr-3 tabular-nums">{ton(v.floor_ton)}</td>
                            if (id === 'fair_ton') return <td key={id} className="py-2 pr-3 tabular-nums">{ton(v.fair_ton)}</td>
                            if (id === 'undervalue_pct') return <td key={id} className="py-2 pr-3 tabular-nums">{pct(v.undervalue_pct)}</td>
                            if (id === 'expected_profit_pct') return <td key={id} className="py-2 pr-3 tabular-nums">{pct(v.expected_profit_pct)}</td>
                            if (id === 'edgeRank100') return <td key={id} className="py-2 pr-3 tabular-nums">{Number(v.edgeRank100 || 0).toFixed(1)}</td>
                            if (id === 'score100') return <td key={id} className="py-2 pr-3 tabular-nums">{Number(v.score100 || 0).toFixed(1)}</td>
                            if (id === 'conf_pct') return <td key={id} className="py-2 pr-3 tabular-nums">{pct(v.conf_pct)}</td>
                            if (id === 'liquidity_score') return <td key={id} className="py-2 pr-3 tabular-nums">{Number(v.liquidity_score || 0).toFixed(1)}</td>
                            if (id === 'absorption_30m') return <td key={id} className="py-2 pr-3 tabular-nums">{Number(v.absorption_30m || 0).toFixed(2)}</td>
                            if (id === 'listing_pressure') return <td key={id} className="py-2 pr-3 tabular-nums">{Number(v.listing_pressure || 0).toFixed(2)}</td>
                            if (id === 'depth_score') return <td key={id} className="py-2 pr-3 tabular-nums">{Number(v.depth_score || 0).toFixed(2)}</td>
                            if (id === 'market_regime') return <td key={id} className="py-2 pr-3">{regimeRu(v.market_regime)}</td>
                            if (id === 'action') {
                              return (
                                <td key={id} className="py-2 pr-3">
                                  <div className="flex items-center gap-2">
                                    <span className={actionClass(v.action)}>{actionRu(v.action)}</span>
                                    <button type="button" className="text-xs text-slate-500 underline" onClick={() => setExpandedRow(opened ? '' : rowKey)}>
                                      {opened ? 'Скрыть' : 'Детали'}
                                    </button>
                                  </div>
                                </td>
                              )
                            }
                            return <td key={id} className="py-2 pr-3 text-xs text-slate-400">—</td>
                          })}
                        </tr>
                        {opened ? (
                          <tr className="border-b border-slate-100 bg-slate-50/40">
                            <td className="px-2 py-3" colSpan={Math.max(1, screenerColumns.length)}>
                              <div className="grid gap-3 md:grid-cols-3">
                                <div>
                                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Причины</div>
                                  <ul className="space-y-1 text-sm text-slate-700">
                                    {(v.reasons || []).map((x, i) => <li key={i}>• {x}</li>)}
                                  </ul>
                                </div>
                                <div>
                                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Риски</div>
                                  <ul className="space-y-1 text-sm text-slate-700">
                                    {(v.risk_flags || []).map((x, i) => <li key={i}>• {x}</li>)}
                                  </ul>
                                </div>
                                <div>
                                  <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Decision Trace</div>
                                  <pre className="max-h-48 overflow-auto rounded-lg border border-slate-200 bg-white p-2 text-xs text-slate-700">
                                    {JSON.stringify(v.decision_trace || {}, null, 2)}
                                  </pre>
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
            <div className="text-sm text-slate-500">Скринер пуст</div>
          )}
        </BentoCard>
      </BentoGrid>
    </section>
  )
}
