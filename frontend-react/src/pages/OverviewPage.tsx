import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BentoCard } from '../components/BentoCard'
import { BentoGrid } from '../components/BentoGrid'
import { HeatmapStrip } from '../components/HeatmapStrip'
import { LoadingBlock } from '../components/LoadingBlock'
import { MetricTile } from '../components/MetricTile'
import { PageHeader } from '../components/PageHeader'
import { SignalCard } from '../components/SignalCard'
import { Sparkline } from '../components/Sparkline'
import { getMarketStatus, getMetric, getOverview, getSignals, getVariants, pct, subscribeRealtime } from '../lib/api'
import { bentoBlockControlNumber, bentoBlockMetrics, bentoBlockSource, bentoBlockTitle, bentoPageMetrics, bentoPageTitleRu, bentoTimeframes } from '../lib/bentoContracts'
import { fmtByUnit, scalarFromPoints, timeframeConfig, timeframeFromIso, type TimeframeKey } from '../lib/metrics'
import { readUiAutoRefreshMinutes, uiAutoRefreshMs } from '../lib/uiSettings'
import type { MetricPoint, OverviewResponse, SignalItem, VariantItem } from '../types/api'

interface ScalarMetric {
  label: string
  value: number
  unit: string
}

interface OverviewCachePayload {
  savedAt: number
  data: {
    overview: OverviewResponse | null
    topSignals: SignalItem[]
    buySignals: SignalItem[]
    sellSignals: SignalItem[]
    marketStatusSnapshot: {
      liquidityScore?: number
      whaleRatioPct?: number
      whaleImpulse?: number
    } | null
    tfVolume: TimeframeKey
    tfLiquidity: TimeframeKey
    tfHeatmap: TimeframeKey
    volumeSeries: MetricPoint[]
    liquiditySeries: MetricPoint[]
    heatmapSeries: MetricPoint[]
    supplySeries: MetricPoint[]
    floorSeries: MetricPoint[]
    marketIndexMetric: ScalarMetric | null
    floorRealtimeMetric: ScalarMetric | null
    volatilityMetric: ScalarMetric | null
    marketFlowMetrics: ScalarMetric[]
    whaleMetrics: ScalarMetric[]
    depthCount: number
    depthTon: number
    leaderItems: VariantItem[]
    shockItems: VariantItem[]
    overheatItems: VariantItem[]
  }
}

const OVERVIEW_CACHE_KEY = 'gmz.overview.cache.v3'

function asNumber(value: unknown, fallback = 0): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

function lastPoint(points?: MetricPoint[]): MetricPoint | null {
  if (!points?.length) return null
  return points[points.length - 1] || null
}

function metricNum(row: ScalarMetric | null | undefined): string {
  if (!row) return 'н/д'
  return fmtByUnit(row.value, row.unit, 2)
}

function normalizeHeatmapPoints(points: MetricPoint[], tf: TimeframeKey): MetricPoint[] {
  const last = points[points.length - 1]
  const extra = (last?.extra || {}) as { heat?: Array<{ bucket?: unknown; value?: unknown; sales?: unknown }> }
  const heatRaw = Array.isArray(extra.heat) ? extra.heat : []
  if (!heatRaw.length) return points

  const allowedBuckets =
    tf === '1h'
      ? new Set(['1h'])
      : tf === '6h'
        ? new Set(['1h', '6h'])
        : new Set(['1h', '6h', '24h'])

  const mapped = heatRaw
    .map((row, idx) => {
      const bucket = String(row?.bucket || `b${idx}`).trim().toLowerCase()
      const value = Number(row?.value || 0)
      const sales = Number(row?.sales || 0)
      return {
        ts: bucket || `b${idx}`,
        value: Number.isFinite(value) ? value : 0,
        extra: {
          bucket: bucket || `b${idx}`,
          sales: Number.isFinite(sales) ? sales : 0,
        },
      } as MetricPoint
    })
    .filter((row) => allowedBuckets.has(String(row.ts || '').toLowerCase()))

  return mapped.length ? mapped : points
}

function variantTitle(v: VariantItem): string {
  return [v.collection_name, v.model, v.background, v.pattern].filter(Boolean).join(' • ') || v.variant_id
}

function chartMetricFromBlock(pageId: string, blockId: string, fallback: string): string {
  const metrics = bentoBlockMetrics(pageId, blockId, [fallback])
  const chartLike = metrics.find((x) => String(x || '').toUpperCase().includes('CHART') || String(x || '').toUpperCase().includes('HEATMAP'))
  return String(chartLike || metrics[0] || fallback).toUpperCase()
}

function signalTypeFromSource(source: string, fallback: 'BUY' | 'SELL'): 'BUY' | 'SELL' {
  const src = String(source || '').trim()
  if (!src.includes('?')) return fallback
  const q = src.split('?')[1] || ''
  const params = new URLSearchParams(q)
  const t = String(params.get('type') || '').trim().toUpperCase()
  return t === 'SELL' ? 'SELL' : (t === 'BUY' ? 'BUY' : fallback)
}

function formatCountdown(totalSec: number): string {
  const sec = Math.max(0, Math.floor(totalSec))
  const mm = Math.floor(sec / 60)
  const ss = sec % 60
  return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
}

export function OverviewPage() {
  const navigate = useNavigate()
  const autoRefreshMinutes = useMemo(() => readUiAutoRefreshMinutes(), [])
  const autoRefreshMs = useMemo(() => uiAutoRefreshMs(autoRefreshMinutes), [autoRefreshMinutes])
  const [overview, setOverview] = useState<OverviewResponse | null>(null)
  const [topSignals, setTopSignals] = useState<SignalItem[]>([])
  const [buySignals, setBuySignals] = useState<SignalItem[]>([])
  const [sellSignals, setSellSignals] = useState<SignalItem[]>([])
  const [marketStatusSnapshot, setMarketStatusSnapshot] = useState<{
    liquidityScore?: number
    whaleRatioPct?: number
    whaleImpulse?: number
  } | null>(null)
  const [loading, setLoading] = useState(true)
  const [coreRefreshing, setCoreRefreshing] = useState(false)
  const [error, setError] = useState('')

  const [tfVolume, setTfVolume] = useState<TimeframeKey>('1h')
  const [tfLiquidity, setTfLiquidity] = useState<TimeframeKey>('1h')
  const [tfHeatmap, setTfHeatmap] = useState<TimeframeKey>('24h')
  const [metricsLoading, setMetricsLoading] = useState(true)
  const [metricsRefreshing, setMetricsRefreshing] = useState(false)
  const [metricsError, setMetricsError] = useState('')
  const [volumeChartLoading, setVolumeChartLoading] = useState(false)
  const [liquidityChartLoading, setLiquidityChartLoading] = useState(false)
  const [heatmapChartLoading, setHeatmapChartLoading] = useState(false)

  const [volumeSeries, setVolumeSeries] = useState<MetricPoint[]>([])
  const [liquiditySeries, setLiquiditySeries] = useState<MetricPoint[]>([])
  const [heatmapSeries, setHeatmapSeries] = useState<MetricPoint[]>([])
  const [supplySeries, setSupplySeries] = useState<MetricPoint[]>([])
  const [floorSeries, setFloorSeries] = useState<MetricPoint[]>([])

  const [marketIndexMetric, setMarketIndexMetric] = useState<ScalarMetric | null>(null)
  const [floorRealtimeMetric, setFloorRealtimeMetric] = useState<ScalarMetric | null>(null)
  const [volatilityMetric, setVolatilityMetric] = useState<ScalarMetric | null>(null)
  const [marketFlowMetrics, setMarketFlowMetrics] = useState<ScalarMetric[]>([])
  const [whaleMetrics, setWhaleMetrics] = useState<ScalarMetric[]>([])
  const [depthCount, setDepthCount] = useState(0)
  const [depthTon, setDepthTon] = useState(0)

  const [leaderItems, setLeaderItems] = useState<VariantItem[]>([])
  const [shockItems, setShockItems] = useState<VariantItem[]>([])
  const [overheatItems, setOverheatItems] = useState<VariantItem[]>([])
  const [nextRefreshSec, setNextRefreshSec] = useState(Math.ceil(autoRefreshMs / 1000))
  const overviewTitle = bentoPageTitleRu('overview', 'Обзор рынка')
  const tfOverviewVolume = bentoTimeframes('overview', 'volume_chart', (['1h', '6h', '24h'] as TimeframeKey[]))
  const tfOverviewLiquidity = bentoTimeframes('overview', 'liquidity_chart', (['1h', '6h', '24h'] as TimeframeKey[]))
  const tfOverviewHeatmap = bentoTimeframes('overview', 'liquidity_heatmap', (['6h', '24h'] as TimeframeKey[]))
  const overviewMarketIndexMetrics = useMemo(
    () => bentoBlockMetrics('overview', 'market_index', ['MARKET_INDEX', 'VELOCITY_SCORE', 'VOLATILITY', 'FLOOR_REALTIME']),
    [],
  )
  const overviewMarketFlowMetrics = useMemo(
    () => bentoBlockMetrics('overview', 'market_flow', ['LISTING_VELOCITY', 'VOLUME_VELOCITY', 'ABSORPTION_RATE', 'LISTING_PRESSURE']),
    [],
  )
  const overviewWhalesMetrics = useMemo(
    () => bentoBlockMetrics('overview', 'whales', ['WHALE_RATIO', 'WHALE_IMPULSE']),
    [],
  )
  const overviewDepthMetrics = useMemo(
    () => bentoBlockMetrics('overview', 'depth', ['MARKET_DEPTH']),
    [],
  )
  const overviewMetricsFromBento = useMemo(
    () => bentoPageMetrics('overview', []),
    [],
  )
  const metricVolumeChart = useMemo(() => chartMetricFromBlock('overview', 'volume_chart', 'VOLUME_CHART'), [])
  const metricLiquidityChart = useMemo(() => chartMetricFromBlock('overview', 'liquidity_chart', 'LIQUIDITY_CHART'), [])
  const metricLiquidityHeatmap = useMemo(() => chartMetricFromBlock('overview', 'liquidity_heatmap', 'LIQUIDITY_HEATMAP'), [])
  const metricSupplyChart = useMemo(() => chartMetricFromBlock('overview', 'supply', 'SUPPLY_CHART'), [])
  const titleMarketIndex = useMemo(() => bentoBlockTitle('overview', 'market_index', 'Индекс рынка'), [])
  const titleMarketFlow = useMemo(() => bentoBlockTitle('overview', 'market_flow', 'Поток рынка'), [])
  const titleWhales = useMemo(() => bentoBlockTitle('overview', 'whales', 'Киты и глубина'), [])
  const titleVolumeChart = useMemo(() => bentoBlockTitle('overview', 'volume_chart', 'График объема'), [])
  const titleLiquidityChart = useMemo(() => bentoBlockTitle('overview', 'liquidity_chart', 'График ликвидности'), [])
  const titleLiquidityHeatmap = useMemo(() => bentoBlockTitle('overview', 'liquidity_heatmap', 'Тепловая карта ликвидности'), [])
  const titleSupply = useMemo(() => bentoBlockTitle('overview', 'supply', 'Предложение'), [])
  const titleDepth = useMemo(() => bentoBlockTitle('overview', 'depth', 'История минимальной цены (floor)'), [])
  const topBuyTitle = useMemo(() => bentoBlockTitle('overview', 'top_buy', 'Топ BUY сигналы'), [])
  const topSellTitle = useMemo(() => bentoBlockTitle('overview', 'top_sell', 'Топ SELL сигналы'), [])
  const topBuySource = useMemo(() => bentoBlockSource('overview', 'top_buy', '/v1/signals?type=BUY'), [])
  const topSellSource = useMemo(() => bentoBlockSource('overview', 'top_sell', '/v1/signals?type=SELL'), [])
  const topBuyType = useMemo(() => signalTypeFromSource(topBuySource, 'BUY'), [topBuySource])
  const topSellType = useMemo(() => signalTypeFromSource(topSellSource, 'SELL'), [topSellSource])
  const topBuyLimit = useMemo(() => bentoBlockControlNumber('overview', 'top_buy', 'limit', 10), [])
  const topSellLimit = useMemo(() => bentoBlockControlNumber('overview', 'top_sell', 'limit', 10), [])

  const timerRef = useRef<number | null>(null)
  const initDoneRef = useRef(false)
  const nextRefreshAtRef = useRef<number>(Date.now() + autoRefreshMs)
  const lastAutoRefreshAtRef = useRef<number>(0)
  const coreFirstLoadRef = useRef(true)
  const metricsFirstLoadRef = useRef(true)
  const tfVolumeRef = useRef<TimeframeKey>(tfVolume)
  const tfLiquidityRef = useRef<TimeframeKey>(tfLiquidity)
  const tfHeatmapRef = useRef<TimeframeKey>(tfHeatmap)
  const prevTfVolumeRef = useRef<TimeframeKey>(tfVolume)
  const prevTfLiquidityRef = useRef<TimeframeKey>(tfLiquidity)
  const prevTfHeatmapRef = useRef<TimeframeKey>(tfHeatmap)

  useEffect(() => {
    tfVolumeRef.current = tfVolume
  }, [tfVolume])
  useEffect(() => {
    tfLiquidityRef.current = tfLiquidity
  }, [tfLiquidity])
  useEffect(() => {
    tfHeatmapRef.current = tfHeatmap
  }, [tfHeatmap])

  const scheduleNextAutoRefresh = useCallback((baseTs: number = Date.now()) => {
    nextRefreshAtRef.current = baseTs + autoRefreshMs
    setNextRefreshSec(Math.ceil(autoRefreshMs / 1000))
  }, [autoRefreshMs])

  const openVariant = useCallback(
    (
      variantId?: string,
      traits?: {
        collectionId?: string
        collection?: string
        model?: string
        background?: string
        pattern?: string
      },
    ) => {
      const id = String(variantId || '').trim()
      if (!id) return
      navigate(`/variant/${encodeURIComponent(id)}`, {
        state: {
          variantFallback: {
            collectionId: String(traits?.collectionId || '').trim(),
            collection: String(traits?.collection || '').trim(),
            model: String(traits?.model || '').trim(),
            background: String(traits?.background || '').trim(),
            pattern: String(traits?.pattern || '').trim(),
          },
        },
      })
    },
    [navigate],
  )

  const loadCore = useCallback(async () => {
    if (coreFirstLoadRef.current) setLoading(true)
    else setCoreRefreshing(true)
    setError('')
    try {
      const [ov, signals, buy, sell, market] = await Promise.all([
        getOverview(),
        getSignals({ limit: 200, maxPages: 2 }).catch(() => []),
        getSignals({ type: topBuyType, limit: topBuyLimit, maxPages: 1 }).catch(() => []),
        getSignals({ type: topSellType, limit: topSellLimit, maxPages: 1 }).catch(() => []),
        getMarketStatus('30m').catch(() => null),
      ])
      setOverview(ov)
      setTopSignals((ov.top_signals || signals).slice(0, 8))
      setBuySignals(buy.slice(0, topBuyLimit))
      setSellSignals(sell.slice(0, topSellLimit))
      if (market) {
        setMarketStatusSnapshot({
          liquidityScore: asNumber(market.liquidity?.liquidity_score, 0),
          whaleRatioPct: asNumber(market.whales?.whale_ratio_pct, 0),
          whaleImpulse: asNumber(market.whales?.whale_impulse, 0),
        })
      } else {
        setMarketStatusSnapshot(null)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки обзора')
    } finally {
      setLoading(false)
      setCoreRefreshing(false)
      coreFirstLoadRef.current = false
    }
  }, [topBuyType, topBuyLimit, topSellType, topSellLimit])

  const loadVolumeChartOnly = useCallback(async (key: TimeframeKey) => {
    setVolumeChartLoading(true)
    try {
      const cfg = timeframeConfig(key)
      const toDate = new Date()
      const volumeChart = await getMetric({
        metric: metricVolumeChart,
        scope: 'MARKET',
        from: timeframeFromIso(key, toDate),
        to: toDate.toISOString(),
        interval: cfg.interval,
        limit: cfg.limit,
      }).catch(() => ({ unit: 'JSON', points: [] }))
      setVolumeSeries(volumeChart.points || [])
    } catch {
      // keep previous data on partial refresh errors
    } finally {
      setVolumeChartLoading(false)
    }
  }, [metricVolumeChart])

  const loadLiquidityChartOnly = useCallback(async (key: TimeframeKey) => {
    setLiquidityChartLoading(true)
    try {
      const cfg = timeframeConfig(key)
      const toDate = new Date()
      const liquidityChart = await getMetric({
        metric: metricLiquidityChart,
        scope: 'MARKET',
        from: timeframeFromIso(key, toDate),
        to: toDate.toISOString(),
        interval: cfg.interval,
        limit: cfg.limit,
      }).catch(() => ({ unit: 'JSON', points: [] }))
      setLiquiditySeries(liquidityChart.points || [])
    } catch {
      // keep previous data on partial refresh errors
    } finally {
      setLiquidityChartLoading(false)
    }
  }, [metricLiquidityChart])

  const loadHeatmapOnly = useCallback(async (key: TimeframeKey) => {
    setHeatmapChartLoading(true)
    try {
      const cfg = timeframeConfig(key)
      const toDate = new Date()
      const liquidityHeatmap = await getMetric({
        metric: metricLiquidityHeatmap,
        scope: 'MARKET',
        from: timeframeFromIso(key, toDate),
        to: toDate.toISOString(),
        interval: cfg.interval,
        limit: cfg.limit,
      }).catch(() => ({ unit: 'JSON', points: [] }))
      setHeatmapSeries(normalizeHeatmapPoints(liquidityHeatmap.points || [], key))
    } catch {
      // keep previous data on partial refresh errors
    } finally {
      setHeatmapChartLoading(false)
    }
  }, [metricLiquidityHeatmap])

  const loadAdvanced = useCallback(async () => {
    if (metricsFirstLoadRef.current) setMetricsLoading(true)
    else setMetricsRefreshing(true)
    setMetricsError('')
    try {
      const vCfg = timeframeConfig(tfVolumeRef.current)
      const lCfg = timeframeConfig(tfLiquidityRef.current)
      const hCfg = timeframeConfig(tfHeatmapRef.current)
      const toDate = new Date()
      const toIso = toDate.toISOString()
      const vFrom = timeframeFromIso(tfVolumeRef.current, toDate)
      const lFrom = timeframeFromIso(tfLiquidityRef.current, toDate)
      const hFrom = timeframeFromIso(tfHeatmapRef.current, toDate)

      const [
        scalarRows,
        volumeChart,
        liquidityChart,
        liquidityHeatmap,
        supplyChart,
        floorHistory,
        leaders,
        supplyShock,
        overheat,
      ] = await Promise.all([
        Promise.all(
          Array.from(new Set([
            ...overviewMetricsFromBento,
            ...overviewMarketIndexMetrics,
            ...overviewMarketFlowMetrics,
            ...overviewWhalesMetrics,
            ...overviewDepthMetrics,
            'TREND_SCORE',
            'LIQUIDITY_SCORE',
          ])).map((metric) => getMetric({ metric, scope: 'MARKET' }).catch(() => ({ metric, unit: 'RATIO', points: [] }))),
        ),
        getMetric({ metric: metricVolumeChart, scope: 'MARKET', from: vFrom, to: toIso, interval: vCfg.interval, limit: vCfg.limit }).catch(() => ({ unit: 'JSON', points: [] })),
        getMetric({ metric: metricLiquidityChart, scope: 'MARKET', from: lFrom, to: toIso, interval: lCfg.interval, limit: lCfg.limit }).catch(() => ({ unit: 'JSON', points: [] })),
        getMetric({ metric: metricLiquidityHeatmap, scope: 'MARKET', from: hFrom, to: toIso, interval: hCfg.interval, limit: hCfg.limit }).catch(() => ({ unit: 'JSON', points: [] })),
        getMetric({ metric: metricSupplyChart, scope: 'MARKET', from: vFrom, to: toIso, interval: vCfg.interval, limit: vCfg.limit }).catch(() => ({ unit: 'JSON', points: [] })),
        getMetric({ metric: 'FLOOR_HISTORY', scope: 'MARKET', from: vFrom, to: toIso, interval: vCfg.interval, limit: vCfg.limit }).catch(() => ({ unit: 'TON', points: [] })),
        getVariants({ sort: 'floor_change_24h_desc', cap: 8 }).catch(() => []),
        getVariants({ sort: 'lots_desc', cap: 8 }).catch(() => []),
        getVariants({ sort: 'trend_desc', cap: 8 }).catch(() => []),
      ])
      const scalarMap = new Map<string, { unit: string; points: MetricPoint[] }>()
      for (const row of scalarRows || []) {
        const key = String((row as { metric?: string }).metric || '').toUpperCase()
        if (!key) continue
        scalarMap.set(key, {
          unit: String((row as { unit?: string }).unit || 'RATIO'),
          points: ((row as { points?: MetricPoint[] }).points || []) as MetricPoint[],
        })
      }
      const metricScalar = (name: string, fallbackUnit = 'RATIO') => {
        const hit = scalarMap.get(name.toUpperCase())
        if (!hit) return { value: 0, unit: fallbackUnit }
        return {
          value: scalarFromPoints(hit.points),
          unit: String(hit.unit || fallbackUnit),
        }
      }

      const marketIndex = metricScalar('MARKET_INDEX', 'SCORE_0_100')
      const floorRealtime = metricScalar('FLOOR_REALTIME', 'TON')
      const volatility = metricScalar('VOLATILITY', 'RATIO')
      const velocityScore = metricScalar('VELOCITY_SCORE', 'SCORE_0_100')
      const trendScore = metricScalar('TREND_SCORE', 'RATIO')
      const listingVelocity = metricScalar('LISTING_VELOCITY', 'RATIO')
      const listingPressure = metricScalar('LISTING_PRESSURE', 'RATIO')
      const volumeVelocity = metricScalar('VOLUME_VELOCITY', 'RATIO')
      const absorptionRate = metricScalar('ABSORPTION_RATE', 'RATIO')
      const liquidityScore = metricScalar('LIQUIDITY_SCORE', 'SCORE_0_1')
      const whaleRatio = metricScalar('WHALE_RATIO', 'RATIO')
      const whaleImpulse = metricScalar('WHALE_IMPULSE', 'RATIO')
      const depth = scalarMap.get('MARKET_DEPTH') || { unit: 'JSON', points: [] as MetricPoint[] }

      setMarketIndexMetric({ label: 'Индекс рынка', value: marketIndex.value, unit: marketIndex.unit })
      setFloorRealtimeMetric({ label: 'Реалтайм floor', value: floorRealtime.value, unit: floorRealtime.unit })
      setVolatilityMetric({ label: 'Волатильность', value: volatility.value, unit: volatility.unit })
      setMarketFlowMetrics([
        { label: 'Индекс скорости', value: velocityScore.value, unit: velocityScore.unit },
        { label: 'Тренд', value: trendScore.value, unit: trendScore.unit },
        { label: 'Скорость листингов', value: listingVelocity.value, unit: listingVelocity.unit },
        { label: 'Давление листинга', value: listingPressure.value, unit: listingPressure.unit },
        { label: 'Скорость объема', value: volumeVelocity.value, unit: volumeVelocity.unit },
        { label: 'Поглощение', value: absorptionRate.value, unit: absorptionRate.unit },
      ])
      const liqSeriesValue = liquidityScore.value
      const whaleRatioSeriesValue = whaleRatio.value
      const whaleImpulseSeriesValue = whaleImpulse.value
      const liqValue = liqSeriesValue || asNumber(marketStatusSnapshot?.liquidityScore, 0)
      const whaleRatioValue = whaleRatioSeriesValue || ((asNumber(marketStatusSnapshot?.whaleRatioPct, 0)) / 100.0)
      const whaleImpulseValue = whaleImpulseSeriesValue || asNumber(marketStatusSnapshot?.whaleImpulse, 0)

      setWhaleMetrics([
        { label: 'Ликвидность', value: liqValue, unit: String(liquidityScore.unit || 'SCORE_0_1') },
        { label: 'Доля китов', value: whaleRatioValue, unit: String(whaleRatio.unit || 'RATIO') },
        { label: 'Импульс китов', value: whaleImpulseValue, unit: String(whaleImpulse.unit || 'RATIO') },
      ])

      const dPoint = lastPoint(depth.points || [])
      const dExtra = (dPoint?.extra || {}) as Record<string, unknown>
      setDepthCount(asNumber(dExtra.depth_count, asNumber(dPoint?.value, 0)))
      setDepthTon(asNumber(dExtra.depth_ton, 0))

      setVolumeSeries(volumeChart.points || [])
      setLiquiditySeries(liquidityChart.points || [])
      setHeatmapSeries(normalizeHeatmapPoints(liquidityHeatmap.points || [], tfHeatmapRef.current))
      setSupplySeries(supplyChart.points || [])
      setFloorSeries(floorHistory.points || [])

      setLeaderItems((leaders || []).filter((x) => Number(x.delta_24h || 0) > 0).slice(0, 6))
      setShockItems((supplyShock || []).slice(0, 6))
      setOverheatItems((overheat || []).filter((x) => Number(x.delta_24h || 0) > 0 || Number(x.liquidity24h || 0) > 0).slice(0, 6))
    } catch (e) {
      setMetricsError(e instanceof Error ? e.message : 'Ошибка загрузки метрик обзора')
    } finally {
      setMetricsLoading(false)
      setMetricsRefreshing(false)
      metricsFirstLoadRef.current = false
    }
  }, [marketStatusSnapshot, overviewMetricsFromBento, overviewMarketIndexMetrics, overviewMarketFlowMetrics, overviewWhalesMetrics, overviewDepthMetrics, metricVolumeChart, metricLiquidityChart, metricLiquidityHeatmap, metricSupplyChart])

  useEffect(() => {
    if (initDoneRef.current) return
    initDoneRef.current = true

    let hydrated = false
    try {
      const raw = sessionStorage.getItem(OVERVIEW_CACHE_KEY)
      if (raw) {
        const parsed = JSON.parse(raw) as OverviewCachePayload
        if (parsed && parsed.data && Number.isFinite(Number(parsed.savedAt))) {
          const d = parsed.data
          setOverview(d.overview || null)
          setTopSignals(Array.isArray(d.topSignals) ? d.topSignals : [])
          setBuySignals(Array.isArray(d.buySignals) ? d.buySignals : [])
          setSellSignals(Array.isArray(d.sellSignals) ? d.sellSignals : [])
          setMarketStatusSnapshot(d.marketStatusSnapshot || null)
          setTfVolume((d.tfVolume || '1h') as TimeframeKey)
          setTfLiquidity((d.tfLiquidity || '1h') as TimeframeKey)
          setTfHeatmap((d.tfHeatmap || '24h') as TimeframeKey)
          setVolumeSeries(Array.isArray(d.volumeSeries) ? d.volumeSeries : [])
          setLiquiditySeries(Array.isArray(d.liquiditySeries) ? d.liquiditySeries : [])
          setHeatmapSeries(Array.isArray(d.heatmapSeries) ? d.heatmapSeries : [])
          setSupplySeries(Array.isArray(d.supplySeries) ? d.supplySeries : [])
          setFloorSeries(Array.isArray(d.floorSeries) ? d.floorSeries : [])
          setMarketIndexMetric(d.marketIndexMetric || null)
          setFloorRealtimeMetric(d.floorRealtimeMetric || null)
          setVolatilityMetric(d.volatilityMetric || null)
          setMarketFlowMetrics(Array.isArray(d.marketFlowMetrics) ? d.marketFlowMetrics : [])
          setWhaleMetrics(Array.isArray(d.whaleMetrics) ? d.whaleMetrics : [])
          setDepthCount(Number(d.depthCount || 0))
          setDepthTon(Number(d.depthTon || 0))
          setLeaderItems(Array.isArray(d.leaderItems) ? d.leaderItems : [])
          setShockItems(Array.isArray(d.shockItems) ? d.shockItems : [])
          setOverheatItems(Array.isArray(d.overheatItems) ? d.overheatItems : [])

          setLoading(false)
          setMetricsLoading(false)
          coreFirstLoadRef.current = false
          metricsFirstLoadRef.current = false
          hydrated = true

          const ageMs = Date.now() - Number(parsed.savedAt || 0)
          if (ageMs > 0 && ageMs < autoRefreshMs) {
            nextRefreshAtRef.current = Number(parsed.savedAt || 0) + autoRefreshMs
            setNextRefreshSec(Math.ceil(Math.max(0, nextRefreshAtRef.current - Date.now()) / 1000))
          } else {
            scheduleNextAutoRefresh()
          }
          if (ageMs >= autoRefreshMs) {
            lastAutoRefreshAtRef.current = Date.now()
            scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
            void loadCore()
            void loadAdvanced()
          }
        }
      }
    } catch {
      // cache is best effort
    }

    if (!hydrated) {
      lastAutoRefreshAtRef.current = Date.now()
      scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
      void loadCore()
      void loadAdvanced()
    }
  }, [loadCore, loadAdvanced, scheduleNextAutoRefresh])

  useEffect(() => {
    if (prevTfVolumeRef.current === tfVolume) return
    prevTfVolumeRef.current = tfVolume
    void loadVolumeChartOnly(tfVolume)
  }, [tfVolume, loadVolumeChartOnly])

  useEffect(() => {
    if (prevTfLiquidityRef.current === tfLiquidity) return
    prevTfLiquidityRef.current = tfLiquidity
    void loadLiquidityChartOnly(tfLiquidity)
  }, [tfLiquidity, loadLiquidityChartOnly])

  useEffect(() => {
    if (prevTfHeatmapRef.current === tfHeatmap) return
    prevTfHeatmapRef.current = tfHeatmap
    void loadHeatmapOnly(tfHeatmap)
  }, [tfHeatmap, loadHeatmapOnly])

  useEffect(() => {
    const es = subscribeRealtime(() => {
      if ((Date.now() - lastAutoRefreshAtRef.current) < autoRefreshMs) return
      if (timerRef.current) window.clearTimeout(timerRef.current)
      timerRef.current = window.setTimeout(() => {
        lastAutoRefreshAtRef.current = Date.now()
        scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
        void loadCore()
        void loadAdvanced()
      }, 500)
    })

    const poll = window.setInterval(() => {
      lastAutoRefreshAtRef.current = Date.now()
      scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
      void loadCore()
      void loadAdvanced()
    }, autoRefreshMs)

    const tick = window.setInterval(() => {
      const remain = Math.max(0, Math.ceil((nextRefreshAtRef.current - Date.now()) / 1000))
      setNextRefreshSec(remain)
    }, 1000)

    return () => {
      es.close()
      window.clearInterval(poll)
      window.clearInterval(tick)
      if (timerRef.current) window.clearTimeout(timerRef.current)
    }
  }, [autoRefreshMs, loadCore, loadAdvanced, scheduleNextAutoRefresh])

  useEffect(() => {
    if (loading || metricsLoading) return
    try {
      const payload: OverviewCachePayload = {
        savedAt: Date.now(),
        data: {
          overview,
          topSignals,
          buySignals,
          sellSignals,
          marketStatusSnapshot,
          tfVolume,
          tfLiquidity,
          tfHeatmap,
          volumeSeries,
          liquiditySeries,
          heatmapSeries,
          supplySeries,
          floorSeries,
          marketIndexMetric,
          floorRealtimeMetric,
          volatilityMetric,
          marketFlowMetrics,
          whaleMetrics,
          depthCount,
          depthTon,
          leaderItems,
          shockItems,
          overheatItems,
        },
      }
      sessionStorage.setItem(OVERVIEW_CACHE_KEY, JSON.stringify(payload))
    } catch {
      // ignore cache write errors
    }
  }, [
    loading,
    metricsLoading,
    overview,
    topSignals,
    buySignals,
    sellSignals,
    marketStatusSnapshot,
    tfVolume,
    tfLiquidity,
    tfHeatmap,
    volumeSeries,
    liquiditySeries,
    heatmapSeries,
    supplySeries,
    floorSeries,
    marketIndexMetric,
    floorRealtimeMetric,
    volatilityMetric,
    marketFlowMetrics,
    whaleMetrics,
    depthCount,
    depthTon,
    leaderItems,
    shockItems,
    overheatItems,
  ])

  const counts = useMemo(() => {
    const c = overview?.counts
    return {
      gifts: asNumber(c?.gifts),
      collections: asNumber(c?.collections),
      models: asNumber(c?.models),
      backdrops: asNumber(c?.backdrops),
      patterns: asNumber(c?.symbols),
    }
  }, [overview])

  const keyMetrics = useMemo(() => {
    const km = overview?.key_metrics || {}
    return {
      forSale: asNumber(km.total_for_sale),
      sold: asNumber(km.total_sold),
      buySignals: asNumber(km.buy_signals),
      sellSignals: asNumber(km.sell_signals),
    }
  }, [overview])

  return (
    <section>
      <PageHeader
        title={overviewTitle}
        subtitle="Дашборд рынка на v1 API (режим tz)"
        right={
          <div className="flex items-center gap-2">
            {overview?.stale ? (
              <span className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-700">
                Данные устарели
              </span>
            ) : null}
            <span className="text-xs font-medium text-slate-500">
              Обновление через {formatCountdown(nextRefreshSec)}
            </span>
            <button
              type="button"
              onClick={() => {
                lastAutoRefreshAtRef.current = Date.now()
                scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
                void loadCore()
                void loadAdvanced()
              }}
              className="gmz-btn gmz-btn-ghost px-3 py-2 text-sm"
            >
              Обновить
            </button>
          </div>
        }
      />
      {coreRefreshing || metricsRefreshing ? (
        <div className="mb-3 text-xs font-medium text-slate-500">Обновляем данные виджетов…</div>
      ) : null}

      {error ? (
        <BentoCard className="mb-4 border-rose-200 bg-rose-50/60">
          <div className="text-sm font-medium text-rose-700">Ошибка: {error}</div>
        </BentoCard>
      ) : null}
      {metricsError ? (
        <BentoCard className="mb-4 border-rose-200 bg-rose-50/60">
          <div className="text-sm font-medium text-rose-700">Ошибка метрик: {metricsError}</div>
        </BentoCard>
      ) : null}

      <BentoGrid>
        <BentoCard title={titleMarketIndex} className="xl:col-span-3 min-h-[260px]">
          {loading || metricsLoading ? (
            <div className="grid gap-3 sm:grid-cols-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <LoadingBlock key={i} className="h-20" />
              ))}
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              <MetricTile label="Состояние" value={String(overview?.market_state || 'н/д')} />
              <MetricTile label="Индекс" value={metricNum(marketIndexMetric)} />
              <MetricTile label="Реалтайм floor" value={metricNum(floorRealtimeMetric)} />
              <MetricTile label="Волатильность" value={metricNum(volatilityMetric)} />
              <MetricTile label="Подарков" value={counts.gifts.toLocaleString('ru-RU')} />
              <MetricTile label="Коллекций" value={counts.collections.toLocaleString('ru-RU')} />
              <MetricTile label="Моделей" value={counts.models.toLocaleString('ru-RU')} />
              <MetricTile label="Фонов / Узоров" value={`${counts.backdrops.toLocaleString('ru-RU')} / ${counts.patterns.toLocaleString('ru-RU')}`} />
            </div>
          )}
        </BentoCard>

        <BentoCard title={titleMarketFlow} className="xl:col-span-2 min-h-[260px]">
          {metricsLoading ? (
            <div className="grid gap-2 sm:grid-cols-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <LoadingBlock key={i} className="h-16" />
              ))}
            </div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              {marketFlowMetrics.map((row) => (
                <div key={row.label} className="rounded-xl border border-dashed border-sky-200 bg-slate-50/70 p-2">
                  <div className="text-xs text-slate-500">{row.label}</div>
                  <div className="mt-1 text-base font-semibold text-slate-900 tabular-nums">{fmtByUnit(row.value, row.unit, 2)}</div>
                </div>
              ))}
            </div>
          )}
        </BentoCard>

        <BentoCard title={titleWhales} className="xl:col-span-1 min-h-[260px]">
          {metricsLoading ? (
            <div className="space-y-2">
              <LoadingBlock className="h-16" />
              <LoadingBlock className="h-16" />
            </div>
          ) : (
            <div className="grid gap-2">
              {whaleMetrics.map((row) => (
                <div key={row.label} className="rounded-xl border border-dashed border-sky-200 bg-slate-50/70 p-2">
                  <div className="text-xs text-slate-500">{row.label}</div>
                  <div className="mt-1 text-base font-semibold text-slate-900 tabular-nums">{fmtByUnit(row.value, row.unit, 2)}</div>
                </div>
              ))}
              <div className="rounded-xl border border-dashed border-sky-200 bg-slate-50/70 p-2">
                <div className="text-xs text-slate-500">Глубина рынка</div>
                <div className="mt-1 text-base font-semibold text-slate-900 tabular-nums">{depthCount.toLocaleString('ru-RU')} лотов / {depthTon.toFixed(1)} TON</div>
              </div>
            </div>
          )}
        </BentoCard>
      </BentoGrid>

      <BentoGrid className="mt-4">
        <BentoCard
          className="xl:col-span-3"
          title={titleVolumeChart}
          right={
            <div className="flex gap-1">
              {tfOverviewVolume.map((tf) => (
                <button
                  key={tf}
                  type="button"
                  onClick={() => setTfVolume(tf)}
                  className={`rounded-lg border px-2 py-1 text-xs font-semibold ${tfVolume === tf ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-slate-200 text-slate-600'}`}
                >
                  {tf}
                </button>
              ))}
            </div>
          }
        >
          {(metricsLoading || volumeChartLoading) ? <LoadingBlock className="h-[240px]" /> : <Sparkline key={`vol-${tfVolume}`} points={volumeSeries} label="Объем" color="#0284c7" fill="rgba(2,132,199,0.12)" />}
        </BentoCard>

        <BentoCard
          className="xl:col-span-3"
          title={titleLiquidityChart}
          right={
            <div className="flex gap-1">
              {tfOverviewLiquidity.map((tf) => (
                <button
                  key={tf}
                  type="button"
                  onClick={() => setTfLiquidity(tf)}
                  className={`rounded-lg border px-2 py-1 text-xs font-semibold ${tfLiquidity === tf ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-slate-200 text-slate-600'}`}
                >
                  {tf}
                </button>
              ))}
            </div>
          }
        >
          {(metricsLoading || liquidityChartLoading) ? <LoadingBlock className="h-[240px]" /> : <Sparkline key={`liq-${tfLiquidity}`} points={liquiditySeries} label="Ликвидность" color="#0f766e" fill="rgba(15,118,110,0.12)" />}
        </BentoCard>
      </BentoGrid>

      <BentoGrid className="mt-4">
        <BentoCard
          className="xl:col-span-3"
          title={titleLiquidityHeatmap}
          right={
            <div className="flex gap-1">
              {tfOverviewHeatmap.map((tf) => (
                <button
                  key={tf}
                  type="button"
                  onClick={() => setTfHeatmap(tf)}
                  className={`rounded-lg border px-2 py-1 text-xs font-semibold ${tfHeatmap === tf ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-slate-200 text-slate-600'}`}
                >
                  {tf}
                </button>
              ))}
            </div>
          }
        >
          {(metricsLoading || heatmapChartLoading) ? <LoadingBlock className="h-20" /> : <HeatmapStrip key={`heat-${tfHeatmap}`} points={heatmapSeries} label="Ликвидность" maxItems={12} cellHeightClass="h-48" />}
        </BentoCard>
        <BentoCard title={titleSupply} className="xl:col-span-2">
          {metricsLoading ? <LoadingBlock className="h-[220px]" /> : <Sparkline points={supplySeries} label="Активные лоты" color="#1d4ed8" fill="rgba(37,99,235,0.12)" />}
        </BentoCard>
        <BentoCard title={titleDepth} className="xl:col-span-1">
          {metricsLoading ? <LoadingBlock className="h-[220px]" /> : <Sparkline points={floorSeries} label="Минимальная цена, TON" color="#7c3aed" fill="rgba(124,58,237,0.12)" />}
        </BentoCard>
      </BentoGrid>

      <BentoGrid className="mt-4">
        <BentoCard title={topBuyTitle} className="xl:col-span-3">
          {loading ? (
            <LoadingBlock className="h-24" />
          ) : buySignals.length ? (
            <div className="space-y-2">
              {buySignals.map((s) => (
                <button
                  type="button"
                  key={s.signal_id || `${s.variant_id}-${s.ts}`}
                  onClick={() => s.variant_id && navigate(`/variant/${encodeURIComponent(s.variant_id)}`)}
                  className="flex w-full items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-2 text-left hover:border-blue-300"
                >
                  <span className="text-sm text-slate-700">{[s.collection, s.model, s.background, s.pattern].filter(Boolean).join(' • ') || s.variant_id}</span>
                  <span className="text-xs font-semibold text-emerald-700">{Number(s.score100 || 0).toFixed(1)}</span>
                </button>
              ))}
            </div>
          ) : (
            <div className="text-sm text-slate-500">Нет BUY сигналов</div>
          )}
        </BentoCard>

        <BentoCard title={topSellTitle} className="xl:col-span-3">
          {loading ? (
            <LoadingBlock className="h-24" />
          ) : sellSignals.length ? (
            <div className="space-y-2">
              {sellSignals.map((s) => (
                <button
                  type="button"
                  key={s.signal_id || `${s.variant_id}-${s.ts}`}
                  onClick={() =>
                    openVariant(s.variant_id, {
                      collectionId: s.collection_id,
                      collection: s.collection,
                      model: s.model,
                      background: s.background,
                      pattern: s.pattern,
                    })
                  }
                  className="flex w-full items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-2 text-left hover:border-rose-300"
                >
                  <span className="text-sm text-slate-700">{[s.collection, s.model, s.background, s.pattern].filter(Boolean).join(' • ') || s.variant_id}</span>
                  <span className="text-xs font-semibold text-rose-700">{pct(s.forecast24h_pct_max)}</span>
                </button>
              ))}
            </div>
          ) : (
            <div className="text-sm text-slate-500">Нет SELL сигналов</div>
          )}
        </BentoCard>
      </BentoGrid>

      <BentoGrid className="mt-4">
        <BentoCard title="Лидеры движения" className="xl:col-span-2">
          {metricsLoading ? <LoadingBlock className="h-24" /> : leaderItems.length ? (
            <div className="space-y-2">
              {leaderItems.map((v) => (
                <button key={v.variant_id} type="button" onClick={() => openVariant(v.variant_id, { collectionId: v.collection_id, collection: v.collection_name, model: v.model, background: v.background, pattern: v.pattern })} className="flex w-full items-center justify-between rounded-xl border border-slate-200 px-3 py-2 text-left hover:border-blue-300">
                  <span className="text-sm text-slate-700 truncate">{variantTitle(v)}</span>
                  <span className="text-xs font-semibold text-emerald-700">{pct(v.delta_24h)}</span>
                </button>
              ))}
            </div>
          ) : <div className="text-sm text-slate-500">Нет данных</div>}
        </BentoCard>

        <BentoCard title="Шок предложения" className="xl:col-span-2">
          {metricsLoading ? <LoadingBlock className="h-24" /> : shockItems.length ? (
            <div className="space-y-2">
              {shockItems.map((v) => (
                <button key={v.variant_id} type="button" onClick={() => openVariant(v.variant_id, { collectionId: v.collection_id, collection: v.collection_name, model: v.model, background: v.background, pattern: v.pattern })} className="flex w-full items-center justify-between rounded-xl border border-slate-200 px-3 py-2 text-left hover:border-blue-300">
                  <span className="text-sm text-slate-700 truncate">{variantTitle(v)}</span>
                  <span className="text-xs font-semibold text-slate-700">{Number(v.active_lots || 0).toLocaleString('ru-RU')} лотов</span>
                </button>
              ))}
            </div>
          ) : <div className="text-sm text-slate-500">Нет данных</div>}
        </BentoCard>

        <BentoCard title="Перегрев" className="xl:col-span-2">
          {metricsLoading ? <LoadingBlock className="h-24" /> : overheatItems.length ? (
            <div className="space-y-2">
              {overheatItems.map((v) => (
                <button key={v.variant_id} type="button" onClick={() => openVariant(v.variant_id, { collectionId: v.collection_id, collection: v.collection_name, model: v.model, background: v.background, pattern: v.pattern })} className="flex w-full items-center justify-between rounded-xl border border-slate-200 px-3 py-2 text-left hover:border-blue-300">
                  <span className="text-sm text-slate-700 truncate">{variantTitle(v)}</span>
                  <span className="text-xs font-semibold text-amber-700">{pct(v.delta_24h)}</span>
                </button>
              ))}
            </div>
          ) : <div className="text-sm text-slate-500">Нет данных</div>}
        </BentoCard>
      </BentoGrid>

      <BentoCard title="Рекомендация дня" className="mt-4">
        {topSignals[0] ? (
          <SignalCard
            signal={topSignals[0]}
            onOpenDetails={(signal) =>
              openVariant(signal.variant_id, {
                collectionId: signal.collection_id,
                collection: signal.collection,
                model: signal.model,
                background: signal.background,
                pattern: signal.pattern,
              })
            }
            onOpenVariant={(signal) =>
              openVariant(signal.variant_id, {
                collectionId: signal.collection_id,
                collection: signal.collection,
                model: signal.model,
                background: signal.background,
                pattern: signal.pattern,
              })
            }
          />
        ) : (
          <div className="text-sm text-slate-500">Нет сигнала для рекомендации</div>
        )}
      </BentoCard>

      <BentoCard title="Провайдеры данных" className="mt-4">
        {loading ? (
          <LoadingBlock className="h-24" />
        ) : overview?.provider_health?.length ? (
          <div className="gmz-table-wrap">
            <table className="gmz-table">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="pb-2 pr-4">Источник</th>
                  <th className="pb-2 pr-4">p95 (мс)</th>
                  <th className="pb-2 pr-4">Ошибки (%)</th>
                  <th className="pb-2 pr-4">Статус</th>
                  <th className="pb-2">Время</th>
                </tr>
              </thead>
              <tbody>
                {overview.provider_health.map((p) => (
                  <tr key={`${p.provider || 'src'}-${p.ts || ''}`} className="border-b border-slate-100">
                    <td className="py-2 pr-4 font-medium text-slate-700">{p.provider || 'н/д'}</td>
                    <td className="py-2 pr-4 tabular-nums">{asNumber(p.p95_ms).toFixed(0)}</td>
                    <td className="py-2 pr-4 tabular-nums">{asNumber(p.err_pct).toFixed(2)}</td>
                    <td className="py-2 pr-4">
                      <span className={p.degraded ? 'text-rose-600' : 'text-emerald-600'}>{p.degraded ? 'Деградация' : 'ОК'}</span>
                    </td>
                    <td className="py-2 text-slate-500">{p.ts ? new Date(p.ts).toLocaleString('ru-RU') : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-sm text-slate-500">Нет данных по провайдерам</div>
        )}
      </BentoCard>

      <BentoCard title="Ключевые метрики" className="mt-4">
        {loading ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <LoadingBlock key={i} className="h-20" />
            ))}
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            <MetricTile label="Всего в продаже" value={keyMetrics.forSale.toLocaleString('ru-RU')} />
            <MetricTile label="Всего продано" value={keyMetrics.sold.toLocaleString('ru-RU')} />
            <MetricTile label="Сигналы BUY" value={keyMetrics.buySignals.toLocaleString('ru-RU')} />
            <MetricTile label="Сигналы SELL" value={keyMetrics.sellSignals.toLocaleString('ru-RU')} />
          </div>
        )}
      </BentoCard>
    </section>
  )
}
