import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { BentoCard } from '../components/BentoCard'
import { BentoGrid } from '../components/BentoGrid'
import { HeatmapStrip } from '../components/HeatmapStrip'
import { LoadingBlock } from '../components/LoadingBlock'
import { MetricTile } from '../components/MetricTile'
import { PageHeader } from '../components/PageHeader'
import { Sparkline } from '../components/Sparkline'
import { getMetric, getVariantDetails, getVariants, resolveVariantByTraits, signalTypeRu, subscribeRealtime, ton } from '../lib/api'
import { bentoBlockMetrics, bentoBlockTitle, bentoPageMetrics, bentoPageTitleRu, bentoTimeframes } from '../lib/bentoContracts'
import { fmtByUnit, scalarFromPoints, timeframeConfig, timeframeFromIso, type TimeframeKey } from '../lib/metrics'
import { buildTradesHref } from '../lib/trades'
import { readUiAutoRefreshMinutes, uiAutoRefreshMs } from '../lib/uiSettings'
import type { MetricPoint, VariantDetailsResponse, VariantItem } from '../types/api'

interface Scalar {
  value: number
  unit: string
}

interface VariantCachePayload {
  savedAt: number
  data: {
    details: VariantDetailsResponse | null
    tfFloor: TimeframeKey
    tfVolume: TimeframeKey
    tfLiquidity: TimeframeKey
    tfHeatmap: TimeframeKey
    scalars: Record<string, Scalar>
    floorSeries: MetricPoint[]
    volumeSeries: MetricPoint[]
    liquiditySeries: MetricPoint[]
    supplySeries: MetricPoint[]
    heatSeries: MetricPoint[]
    feedItems: Array<Record<string, unknown>>
  }
}

function lastPoint(points?: MetricPoint[]): MetricPoint | null {
  if (!points?.length) return null
  return points[points.length - 1] || null
}

function getScalar(map: Record<string, Scalar>, metric: string): Scalar {
  return map[metric] || { value: 0, unit: 'RATIO' }
}

type VariantFallback = {
  collectionId?: string
  collection?: string
  model?: string
  background?: string
  pattern?: string
}

function normalizeTraitValue(value: unknown): string {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .replace(/[_-]+/g, ' ')
}

function traitsFromVariant(item: VariantItem): VariantFallback {
  return {
    collectionId: String(item.collection_id || '').trim(),
    collection: String(item.collection_name || '').trim(),
    model: String(item.model || '').trim(),
    background: String(item.background || '').trim(),
    pattern: String(item.pattern || '').trim(),
  }
}

function chartMetricFromVariantBlock(blockId: string, fallback: string): string {
  const metrics = bentoBlockMetrics('variant', blockId, [fallback])
  const chartLike = metrics.find((m) => {
    const key = String(m || '').toUpperCase()
    return key.includes('CHART') || key.includes('HEATMAP') || key.includes('HISTORY') || key.includes('FEED')
  })
  return String(chartLike || metrics[0] || fallback).toUpperCase()
}

export function VariantPage() {
  const { variantId = '' } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const fallbackRef = useRef(false)
  const autoRefreshMinutes = useMemo(() => readUiAutoRefreshMinutes(), [])
  const autoRefreshMs = useMemo(() => uiAutoRefreshMs(autoRefreshMinutes), [autoRefreshMinutes])
  const variantCacheKey = useMemo(() => `gmz.variant.cache.v1:${variantId}`, [variantId])
  const initDoneRef = useRef('')

  const [details, setDetails] = useState<VariantDetailsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailsRefreshing, setDetailsRefreshing] = useState(false)
  const [error, setError] = useState('')

  const [tfFloor, setTfFloor] = useState<TimeframeKey>('24h')
  const [tfVolume, setTfVolume] = useState<TimeframeKey>('24h')
  const [tfLiquidity, setTfLiquidity] = useState<TimeframeKey>('24h')
  const [tfHeatmap, setTfHeatmap] = useState<TimeframeKey>('24h')

  const [metricsLoading, setMetricsLoading] = useState(true)
  const [metricsRefreshing, setMetricsRefreshing] = useState(false)
  const [metricsError, setMetricsError] = useState('')
  const [scalars, setScalars] = useState<Record<string, Scalar>>({})

  const [floorSeries, setFloorSeries] = useState<MetricPoint[]>([])
  const [volumeSeries, setVolumeSeries] = useState<MetricPoint[]>([])
  const [liquiditySeries, setLiquiditySeries] = useState<MetricPoint[]>([])
  const [supplySeries, setSupplySeries] = useState<MetricPoint[]>([])
  const [heatSeries, setHeatSeries] = useState<MetricPoint[]>([])
  const [feedItems, setFeedItems] = useState<Array<Record<string, unknown>>>([])
  const variantTitle = bentoPageTitleRu('variant', 'Подарок')
  const tfVariantFloor = bentoTimeframes('variant', 'floor_history', (['1h', '6h', '24h', '7d'] as TimeframeKey[]))
  const tfVariantVolume = bentoTimeframes('variant', 'volume_variant', (['1h', '6h', '24h'] as TimeframeKey[]))
  const tfVariantLiquidity = bentoTimeframes('variant', 'liquidity_variant', (['1h', '6h', '24h'] as TimeframeKey[]))
  const tfVariantHeatmap = bentoTimeframes('variant', 'heatmap_variant', (['6h', '24h'] as TimeframeKey[]))
  const titlePricing = useMemo(() => bentoBlockTitle('variant', 'pricing', 'Ценообразование'), [])
  const titleRisk = useMemo(() => bentoBlockTitle('variant', 'risk', 'Риск'), [])
  const titleFloorHistory = useMemo(() => bentoBlockTitle('variant', 'floor_history', 'История минимальной цены (floor)'), [])
  const titleVolumeChart = useMemo(() => bentoBlockTitle('variant', 'volume_variant', 'График объема'), [])
  const titleNewListings = useMemo(() => bentoBlockTitle('variant', 'new_listings', 'Новые листинги'), [])
  const titleLiquidityChart = useMemo(() => bentoBlockTitle('variant', 'liquidity_variant', 'График ликвидности'), [])
  const titleDepthWall = useMemo(() => bentoBlockTitle('variant', 'depth_wall', 'Глубина и стенка'), [])
  const titleWhales = useMemo(() => bentoBlockTitle('variant', 'whales_variant', 'Киты'), [])
  const titleRarity = useMemo(() => bentoBlockTitle('variant', 'rarity', 'Редкость'), [])
  const titleHeatmap = useMemo(() => bentoBlockTitle('variant', 'heatmap_variant', 'Тепловая карта ликвидности'), [])
  const titleListingFeed = useMemo(() => bentoBlockTitle('variant', 'listing_feed', 'Лента листингов'), [])
  const variantMetricsFromBento = useMemo(
    () => bentoPageMetrics('variant', []),
    [],
  )
  const metricFloorHistory = useMemo(() => chartMetricFromVariantBlock('floor_history', 'FLOOR_HISTORY'), [])
  const metricVolumeChart = useMemo(() => chartMetricFromVariantBlock('volume_variant', 'VOLUME_CHART'), [])
  const metricLiquidityChart = useMemo(() => chartMetricFromVariantBlock('liquidity_variant', 'LIQUIDITY_CHART'), [])
  const metricHeatmap = useMemo(() => chartMetricFromVariantBlock('heatmap_variant', 'LIQUIDITY_HEATMAP'), [])
  const metricListingFeed = useMemo(() => chartMetricFromVariantBlock('listing_feed', 'LISTING_FEED'), [])

  const timerRef = useRef<number | null>(null)
  const detailsFirstLoadRef = useRef(true)
  const metricsFirstLoadRef = useRef(true)
  const tfFloorRef = useRef<TimeframeKey>(tfFloor)
  const tfVolumeRef = useRef<TimeframeKey>(tfVolume)
  const tfLiquidityRef = useRef<TimeframeKey>(tfLiquidity)
  const tfHeatmapRef = useRef<TimeframeKey>(tfHeatmap)
  const prevTfFloorRef = useRef<TimeframeKey>(tfFloor)
  const prevTfVolumeRef = useRef<TimeframeKey>(tfVolume)
  const prevTfLiquidityRef = useRef<TimeframeKey>(tfLiquidity)
  const prevTfHeatmapRef = useRef<TimeframeKey>(tfHeatmap)

  useEffect(() => {
    tfFloorRef.current = tfFloor
  }, [tfFloor])
  useEffect(() => {
    tfVolumeRef.current = tfVolume
  }, [tfVolume])
  useEffect(() => {
    tfLiquidityRef.current = tfLiquidity
  }, [tfLiquidity])
  useEffect(() => {
    tfHeatmapRef.current = tfHeatmap
  }, [tfHeatmap])

  const resolveVariantByFallback = useCallback(async (hint: VariantFallback): Promise<string> => {
    const normalizedHint = {
      collectionId: String(hint.collectionId || '').trim(),
      collection: normalizeTraitValue(hint.collection),
      model: normalizeTraitValue(hint.model),
      background: normalizeTraitValue(hint.background),
      pattern: normalizeTraitValue(hint.pattern),
    }
    if (!normalizedHint.collectionId && !normalizedHint.collection && !normalizedHint.model) return ''

    const collectionRaw = String(hint.collection || '').trim()
    const modelRaw = String(hint.model || '').trim()
    const backgroundRaw = String(hint.background || '').trim()
    const patternRaw = String(hint.pattern || '').trim()
    if (modelRaw) {
      const resolved = await resolveVariantByTraits({
        collectionId: normalizedHint.collectionId || undefined,
        collection: collectionRaw || undefined,
        model: modelRaw,
        background: backgroundRaw || undefined,
        pattern: patternRaw || undefined,
        activeOnly: true,
      }).catch(() => null)
      const resolvedId = String(resolved?.variant_id || '').trim()
      if (resolvedId) return resolvedId
    }

    const byCollection = normalizedHint.collectionId
      ? await getVariants({ collectionId: normalizedHint.collectionId, sort: 'floor_ton.asc', cap: 4000 }).catch(() => [])
      : []
    const pool = byCollection.length ? byCollection : await getVariants({ sort: 'floor_ton.asc', cap: 4000 }).catch(() => [])
    if (!pool.length) return ''

    const candidates = pool.filter((item) => {
      const t = traitsFromVariant(item)
      const collectionMatch = !normalizedHint.collection || normalizeTraitValue(t.collection) === normalizedHint.collection
      const modelMatch = !normalizedHint.model || normalizeTraitValue(t.model) === normalizedHint.model
      const backgroundMatch = !normalizedHint.background || normalizeTraitValue(t.background) === normalizedHint.background
      const patternMatch = !normalizedHint.pattern || normalizeTraitValue(t.pattern) === normalizedHint.pattern
      return collectionMatch && modelMatch && backgroundMatch && patternMatch
    })
    return String(candidates[0]?.variant_id || '').trim()
  }, [])

  const loadDetails = useCallback(async () => {
    if (!variantId) return
    if (detailsFirstLoadRef.current) setLoading(true)
    else setDetailsRefreshing(true)
    setError('')
    try {
      const d = await getVariantDetails(variantId)
      setDetails(d)
      fallbackRef.current = false
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Ошибка загрузки карточки'
      const notFound = message.includes('variant_not_found_or_not_active')
      const fallback = (location.state as { variantFallback?: VariantFallback } | null)?.variantFallback
      if (notFound && fallback && !fallbackRef.current) {
        fallbackRef.current = true
        const resolvedId = await resolveVariantByFallback(fallback)
        if (resolvedId && resolvedId !== variantId) {
          navigate(`/variant/${encodeURIComponent(resolvedId)}`, {
            replace: true,
            state: { variantFallback: fallback },
          })
          return
        }
      }
      setError(message)
    } finally {
      setLoading(false)
      setDetailsRefreshing(false)
      detailsFirstLoadRef.current = false
    }
  }, [variantId, location.state, navigate, resolveVariantByFallback])

  const loadMetrics = useCallback(async () => {
    if (!variantId) return
    if (metricsFirstLoadRef.current) setMetricsLoading(true)
    else setMetricsRefreshing(true)
    setMetricsError('')
    try {
      const floorCfg = timeframeConfig(tfFloorRef.current)
      const volCfg = timeframeConfig(tfVolumeRef.current)
      const liqCfg = timeframeConfig(tfLiquidityRef.current)
      const heatCfg = timeframeConfig(tfHeatmapRef.current)
      const toDate = new Date()
      const toIso = toDate.toISOString()
      const floorFrom = timeframeFromIso(tfFloorRef.current, toDate)
      const volFrom = timeframeFromIso(tfVolumeRef.current, toDate)
      const liqFrom = timeframeFromIso(tfLiquidityRef.current, toDate)
      const heatFrom = timeframeFromIso(tfHeatmapRef.current, toDate)

      const seriesMetrics = new Set(['FLOOR_HISTORY', 'VOLUME_CHART', 'LIQUIDITY_CHART', 'SUPPLY_CHART', 'LIQUIDITY_HEATMAP', 'LISTING_FEED'])
      const scalarNames = (variantMetricsFromBento.length
        ? variantMetricsFromBento
        : [
            'BUY_SCORE',
            'SELL_SCORE',
            'EDGE_SCORE',
            'EXPECTED_PROFIT',
            'FAIR_PRICE',
            'UNDERVALUE',
            'FLOOR_REALTIME',
            'LISTING_PRESSURE',
            'ABSORPTION_RATE',
            'LIQUIDITY_SCORE',
            'MARKET_DEPTH',
            'BUY_WALL_SCORE',
            'WHALE_RATIO',
            'WHALE_IMPULSE',
            'RARITY_SCORE',
            'VOLATILITY',
            'LISTING_VELOCITY',
            'NEW_LISTINGS_REALTIME',
          ]).filter((metric) => !seriesMetrics.has(String(metric || '').toUpperCase()))

      const scalarResponses = await Promise.all(
        scalarNames.map((metric) =>
          getMetric({ metric, scope: 'VARIANT', variantId }).catch(() => ({ metric, unit: 'RATIO', points: [] })),
        ),
      )

      const scalarMap: Record<string, Scalar> = {}
      for (const row of scalarResponses) {
        const metricName = String(row.metric || '').toUpperCase()
        scalarMap[metricName] = {
          value: scalarFromPoints(row.points),
          unit: String(row.unit || 'RATIO'),
        }
      }
      setScalars(scalarMap)

      const [floorHistory, volumeChart, liquidityChart, supplyChart, heatmap, listingFeed] = await Promise.all([
        getMetric({ metric: metricFloorHistory, scope: 'VARIANT', variantId, from: floorFrom, to: toIso, interval: floorCfg.interval, limit: floorCfg.limit }).catch(() => ({ points: [] })),
        getMetric({ metric: metricVolumeChart, scope: 'VARIANT', variantId, from: volFrom, to: toIso, interval: volCfg.interval, limit: volCfg.limit }).catch(() => ({ points: [] })),
        getMetric({ metric: metricLiquidityChart, scope: 'VARIANT', variantId, from: liqFrom, to: toIso, interval: liqCfg.interval, limit: liqCfg.limit }).catch(() => ({ points: [] })),
        getMetric({ metric: 'SUPPLY_CHART', scope: 'VARIANT', variantId, from: volFrom, to: toIso, interval: volCfg.interval, limit: volCfg.limit }).catch(() => ({ points: [] })),
        getMetric({ metric: metricHeatmap, scope: 'VARIANT', variantId, from: heatFrom, to: toIso, interval: heatCfg.interval, limit: heatCfg.limit }).catch(() => ({ points: [] })),
        getMetric({ metric: metricListingFeed, scope: 'VARIANT', variantId, limit: 1 }).catch(() => ({ points: [] })),
      ])

      setFloorSeries(floorHistory.points || [])
      setVolumeSeries(volumeChart.points || [])
      setLiquiditySeries(liquidityChart.points || [])
      setSupplySeries(supplyChart.points || [])
      setHeatSeries(heatmap.points || [])

      const feedPoint = lastPoint(listingFeed.points)
      const items = ((feedPoint?.extra || {}) as Record<string, unknown>).items
      setFeedItems(Array.isArray(items) ? items.map((x) => (typeof x === 'object' && x ? (x as Record<string, unknown>) : {})) : [])
    } catch (e) {
      setMetricsError(e instanceof Error ? e.message : 'Ошибка загрузки метрик')
    } finally {
      setMetricsLoading(false)
      setMetricsRefreshing(false)
      metricsFirstLoadRef.current = false
    }
  }, [variantId, metricFloorHistory, metricVolumeChart, metricLiquidityChart, metricHeatmap, metricListingFeed, variantMetricsFromBento])

  const loadFloorSeriesOnly = useCallback(async (key: TimeframeKey) => {
    if (!variantId) return
    try {
      const cfg = timeframeConfig(key)
      const toDate = new Date()
      const floorHistory = await getMetric({
        metric: metricFloorHistory,
        scope: 'VARIANT',
        variantId,
        from: timeframeFromIso(key, toDate),
        to: toDate.toISOString(),
        interval: cfg.interval,
        limit: cfg.limit,
      }).catch(() => ({ points: [] }))
      setFloorSeries(floorHistory.points || [])
    } catch {
      // keep previous data on partial refresh errors
    }
  }, [variantId, metricFloorHistory])

  const loadVolumeSeriesOnly = useCallback(async (key: TimeframeKey) => {
    if (!variantId) return
    try {
      const cfg = timeframeConfig(key)
      const toDate = new Date()
      const fromIso = timeframeFromIso(key, toDate)
      const toIso = toDate.toISOString()
      const volumeChart = await getMetric({
        metric: metricVolumeChart,
        scope: 'VARIANT',
        variantId,
        from: fromIso,
        to: toIso,
        interval: cfg.interval,
        limit: cfg.limit,
      }).catch(() => ({ points: [] }))
      const supplyChart = await getMetric({
        metric: 'SUPPLY_CHART',
        scope: 'VARIANT',
        variantId,
        from: fromIso,
        to: toIso,
        interval: cfg.interval,
        limit: cfg.limit,
      }).catch(() => ({ points: [] }))
      setVolumeSeries(volumeChart.points || [])
      setSupplySeries(supplyChart.points || [])
    } catch {
      // keep previous data on partial refresh errors
    }
  }, [variantId, metricVolumeChart])

  const loadLiquiditySeriesOnly = useCallback(async (key: TimeframeKey) => {
    if (!variantId) return
    try {
      const cfg = timeframeConfig(key)
      const toDate = new Date()
      const liquidityChart = await getMetric({
        metric: metricLiquidityChart,
        scope: 'VARIANT',
        variantId,
        from: timeframeFromIso(key, toDate),
        to: toDate.toISOString(),
        interval: cfg.interval,
        limit: cfg.limit,
      }).catch(() => ({ points: [] }))
      setLiquiditySeries(liquidityChart.points || [])
    } catch {
      // keep previous data on partial refresh errors
    }
  }, [variantId, metricLiquidityChart])

  const loadHeatSeriesOnly = useCallback(async (key: TimeframeKey) => {
    if (!variantId) return
    try {
      const cfg = timeframeConfig(key)
      const toDate = new Date()
      const heatmap = await getMetric({
        metric: metricHeatmap,
        scope: 'VARIANT',
        variantId,
        from: timeframeFromIso(key, toDate),
        to: toDate.toISOString(),
        interval: cfg.interval,
        limit: cfg.limit,
      }).catch(() => ({ points: [] }))
      setHeatSeries(heatmap.points || [])
    } catch {
      // keep previous data on partial refresh errors
    }
  }, [variantId, metricHeatmap])

  useEffect(() => {
    if (!variantId) return
    if (initDoneRef.current === variantId) return
    initDoneRef.current = variantId

    let hydrated = false
    setError('')
    setMetricsError('')

    try {
      const raw = sessionStorage.getItem(variantCacheKey)
      if (raw) {
        const parsed = JSON.parse(raw) as VariantCachePayload
        if (parsed && parsed.data && Number.isFinite(Number(parsed.savedAt))) {
          const d = parsed.data
          setDetails(d.details || null)
          setTfFloor(d.tfFloor || '24h')
          setTfVolume(d.tfVolume || '24h')
          setTfLiquidity(d.tfLiquidity || '24h')
          setTfHeatmap(d.tfHeatmap || '24h')
          setScalars(d.scalars || {})
          setFloorSeries(Array.isArray(d.floorSeries) ? d.floorSeries : [])
          setVolumeSeries(Array.isArray(d.volumeSeries) ? d.volumeSeries : [])
          setLiquiditySeries(Array.isArray(d.liquiditySeries) ? d.liquiditySeries : [])
          setSupplySeries(Array.isArray(d.supplySeries) ? d.supplySeries : [])
          setHeatSeries(Array.isArray(d.heatSeries) ? d.heatSeries : [])
          setFeedItems(Array.isArray(d.feedItems) ? d.feedItems : [])
          setLoading(false)
          setMetricsLoading(false)
          setDetailsRefreshing(false)
          setMetricsRefreshing(false)
          detailsFirstLoadRef.current = false
          metricsFirstLoadRef.current = false
          hydrated = true

          const savedAt = Number(parsed.savedAt || 0)
          const ageMs = Date.now() - savedAt
          if (ageMs >= autoRefreshMs) {
            void loadDetails()
            void loadMetrics()
          }
        }
      }
    } catch {
      // cache read is best effort
    }

    if (!hydrated) {
      detailsFirstLoadRef.current = true
      metricsFirstLoadRef.current = true
      setDetails(null)
      setScalars({})
      setFloorSeries([])
      setVolumeSeries([])
      setLiquiditySeries([])
      setSupplySeries([])
      setHeatSeries([])
      setFeedItems([])
      setLoading(true)
      setMetricsLoading(true)
      void loadDetails()
      void loadMetrics()
    }
  }, [variantId, variantCacheKey, autoRefreshMs, loadDetails, loadMetrics])

  useEffect(() => {
    if (prevTfFloorRef.current === tfFloor) return
    prevTfFloorRef.current = tfFloor
    void loadFloorSeriesOnly(tfFloor)
  }, [tfFloor, loadFloorSeriesOnly])

  useEffect(() => {
    if (prevTfVolumeRef.current === tfVolume) return
    prevTfVolumeRef.current = tfVolume
    void loadVolumeSeriesOnly(tfVolume)
  }, [tfVolume, loadVolumeSeriesOnly])

  useEffect(() => {
    if (prevTfLiquidityRef.current === tfLiquidity) return
    prevTfLiquidityRef.current = tfLiquidity
    void loadLiquiditySeriesOnly(tfLiquidity)
  }, [tfLiquidity, loadLiquiditySeriesOnly])

  useEffect(() => {
    if (prevTfHeatmapRef.current === tfHeatmap) return
    prevTfHeatmapRef.current = tfHeatmap
    void loadHeatSeriesOnly(tfHeatmap)
  }, [tfHeatmap, loadHeatSeriesOnly])

  useEffect(() => {
    const es = subscribeRealtime((evt) => {
      if (!['signal.created', 'metric.updated', 'listing.event', 'variant.updated'].includes(String(evt.type || ''))) return
      if (timerRef.current) window.clearTimeout(timerRef.current)
      timerRef.current = window.setTimeout(() => {
        void loadDetails()
        void loadMetrics()
      }, 500)
    })
    return () => {
      es.close()
      if (timerRef.current) window.clearTimeout(timerRef.current)
    }
  }, [loadDetails, loadMetrics])

  useEffect(() => {
    if (!variantId || loading || metricsLoading) return
    try {
      const payload: VariantCachePayload = {
        savedAt: Date.now(),
        data: {
          details,
          tfFloor,
          tfVolume,
          tfLiquidity,
          tfHeatmap,
          scalars,
          floorSeries,
          volumeSeries,
          liquiditySeries,
          supplySeries,
          heatSeries,
          feedItems,
        },
      }
      sessionStorage.setItem(variantCacheKey, JSON.stringify(payload))
    } catch {
      // cache write is best effort
    }
  }, [
    variantId,
    variantCacheKey,
    loading,
    metricsLoading,
    details,
    tfFloor,
    tfVolume,
    tfLiquidity,
    tfHeatmap,
    scalars,
    floorSeries,
    volumeSeries,
    liquiditySeries,
    supplySeries,
    heatSeries,
    feedItems,
  ])

  const variant = details?.variant
  const breakdown = details?.breakdown

  const title = useMemo(
    () => [variant?.collection_name, variant?.model, variant?.background, variant?.pattern].filter(Boolean).join(' • ') || variantId,
    [variant, variantId],
  )
  const tradeBuyHref = useMemo(() => buildTradesHref({
    variantId,
    collectionId: String(variant?.collection_id || '').trim() || undefined,
    collection: variant?.collection_name,
    model: variant?.model,
    background: variant?.background,
    pattern: variant?.pattern,
    intent: 'BUY',
  }), [variantId, variant])
  const tradeBuyListHref = useMemo(() => buildTradesHref({
    variantId,
    collectionId: String(variant?.collection_id || '').trim() || undefined,
    collection: variant?.collection_name,
    model: variant?.model,
    background: variant?.background,
    pattern: variant?.pattern,
    intent: 'BUY_AND_LIST',
  }), [variantId, variant])

  const depthScalar = getScalar(scalars, 'MARKET_DEPTH')
  const depthPoint = lastPoint(floorSeries)
  const signalHint = useMemo(() => {
    const backend = String(variant?.action_hint || breakdown?.action_hint || '').toUpperCase()
    if (backend === 'BUY' || backend === 'SELL' || backend === 'WATCH' || backend === 'SKIP') return backend
    return 'WATCH'
  }, [breakdown?.action_hint, variant?.action_hint])

  const tradeTiles = [
    ['Оценка BUY', fmtByUnit(getScalar(scalars, 'BUY_SCORE').value, getScalar(scalars, 'BUY_SCORE').unit)],
    ['Оценка SELL', fmtByUnit(getScalar(scalars, 'SELL_SCORE').value, getScalar(scalars, 'SELL_SCORE').unit)],
    ['Индекс преимущества', fmtByUnit(getScalar(scalars, 'EDGE_SCORE').value, getScalar(scalars, 'EDGE_SCORE').unit)],
    ['Сигнал', signalTypeRu(signalHint)],
  ]

  return (
    <section>
      <PageHeader
        title={variantTitle}
        subtitle={variantId}
        right={
          <div className="flex flex-wrap gap-2">
            <Link to={tradeBuyHref} className="gmz-btn gmz-btn-primary px-3 py-2 text-sm">
              Купить
            </Link>
            <Link to={tradeBuyListHref} className="gmz-btn gmz-btn-ghost px-3 py-2 text-sm">
              Купить+выставить
            </Link>
            <Link to="/signals" className="gmz-btn gmz-btn-ghost px-3 py-2 text-sm">
              Назад к сигналам
            </Link>
          </div>
        }
      />

      {error ? <BentoCard className="mb-4 border-rose-200 bg-rose-50/70 text-sm text-rose-700">Ошибка: {error}</BentoCard> : null}
      {metricsError ? <BentoCard className="mb-4 border-rose-200 bg-rose-50/70 text-sm text-rose-700">Ошибка метрик: {metricsError}</BentoCard> : null}
      {detailsRefreshing || metricsRefreshing ? (
        <div className="mb-3 text-xs font-medium text-slate-500">Обновляем блоки карточки…</div>
      ) : null}

      <BentoGrid>
        <BentoCard title={title} className="xl:col-span-3">
          {loading ? (
            <div className="space-y-3">
              <LoadingBlock className="h-10" />
              <LoadingBlock className="h-20" />
            </div>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                {tradeTiles.map(([label, value]) => (
                  <MetricTile key={label} label={label} value={value} />
                ))}
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <MetricTile label="Минимальная цена (floor)" value={`${ton(variant?.floor_ton)} TON`} />
              <MetricTile label="Справедливая цена" value={fmtByUnit(getScalar(scalars, 'FAIR_PRICE').value, getScalar(scalars, 'FAIR_PRICE').unit)} />
              <MetricTile label="Недооценка" value={fmtByUnit(getScalar(scalars, 'UNDERVALUE').value, getScalar(scalars, 'UNDERVALUE').unit)} />
              <MetricTile label="Ожидаемая прибыль" value={fmtByUnit(getScalar(scalars, 'EXPECTED_PROFIT').value, getScalar(scalars, 'EXPECTED_PROFIT').unit)} />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Link to={tradeBuyHref} className="gmz-btn gmz-btn-primary px-3 py-2 text-sm">
                  Купить
                </Link>
                <Link to={tradeBuyListHref} className="gmz-btn gmz-btn-ghost px-3 py-2 text-sm">
                  Купить+выставить
                </Link>
              </div>
            </>
          )}
        </BentoCard>

        <BentoCard title={titlePricing} className="xl:col-span-2">
          {metricsLoading ? (
            <LoadingBlock className="h-24" />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              <MetricTile label="Реалтайм floor" value={fmtByUnit(getScalar(scalars, 'FLOOR_REALTIME').value, getScalar(scalars, 'FLOOR_REALTIME').unit)} />
              <MetricTile label="Справедливая цена" value={fmtByUnit(getScalar(scalars, 'FAIR_PRICE').value, getScalar(scalars, 'FAIR_PRICE').unit)} />
              <MetricTile label="Недооценка" value={fmtByUnit(getScalar(scalars, 'UNDERVALUE').value, getScalar(scalars, 'UNDERVALUE').unit)} />
              <MetricTile label="Ожидаемая прибыль" value={fmtByUnit(getScalar(scalars, 'EXPECTED_PROFIT').value, getScalar(scalars, 'EXPECTED_PROFIT').unit)} />
            </div>
          )}
        </BentoCard>

        <BentoCard title={titleRisk} className="xl:col-span-1">
          {metricsLoading ? (
            <LoadingBlock className="h-24" />
          ) : (
            <div className="grid gap-2">
              <MetricTile label="Давление листинга" value={fmtByUnit(getScalar(scalars, 'LISTING_PRESSURE').value, getScalar(scalars, 'LISTING_PRESSURE').unit)} />
              <MetricTile label="Поглощение" value={fmtByUnit(getScalar(scalars, 'ABSORPTION_RATE').value, getScalar(scalars, 'ABSORPTION_RATE').unit)} />
              <MetricTile label="Ликвидность" value={fmtByUnit(getScalar(scalars, 'LIQUIDITY_SCORE').value, getScalar(scalars, 'LIQUIDITY_SCORE').unit)} />
              <MetricTile label="Глубина рынка" value={fmtByUnit(getScalar(scalars, 'MARKET_DEPTH').value, getScalar(scalars, 'MARKET_DEPTH').unit)} />
              <MetricTile label="Волатильность" value={fmtByUnit(getScalar(scalars, 'VOLATILITY').value, getScalar(scalars, 'VOLATILITY').unit)} />
            </div>
          )}
        </BentoCard>
      </BentoGrid>

      <BentoGrid className="mt-4">
        <BentoCard
          className="xl:col-span-3"
          title={titleFloorHistory}
          right={
            <div className="flex gap-1">
              {tfVariantFloor.map((tf) => (
                <button key={tf} type="button" onClick={() => setTfFloor(tf)} className={`rounded-lg border px-2 py-1 text-xs font-semibold ${tfFloor === tf ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-slate-200 text-slate-600'}`}>
                  {tf}
                </button>
              ))}
            </div>
          }
        >
          {metricsLoading ? <LoadingBlock className="h-[240px]" /> : <Sparkline points={floorSeries} label="Минимальная цена, TON" color="#0f6ad8" fill="rgba(14,116,144,0.12)" />}
        </BentoCard>

        <BentoCard
          className="xl:col-span-3"
          title={titleVolumeChart}
          right={
            <div className="flex gap-1">
              {tfVariantVolume.map((tf) => (
                <button key={tf} type="button" onClick={() => setTfVolume(tf)} className={`rounded-lg border px-2 py-1 text-xs font-semibold ${tfVolume === tf ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-slate-200 text-slate-600'}`}>
                  {tf}
                </button>
              ))}
            </div>
          }
        >
          {metricsLoading ? <LoadingBlock className="h-[240px]" /> : <Sparkline points={volumeSeries} label="Объем" color="#0284c7" fill="rgba(2,132,199,0.12)" />}
        </BentoCard>
      </BentoGrid>

      <BentoGrid className="mt-4">
        <BentoCard title={titleNewListings} className="xl:col-span-2">
          {metricsLoading ? (
            <LoadingBlock className="h-[240px]" />
          ) : (
            <div className="space-y-3">
              <MetricTile label="Новые листинги (реалтайм)" value={fmtByUnit(getScalar(scalars, 'NEW_LISTINGS_REALTIME').value, getScalar(scalars, 'NEW_LISTINGS_REALTIME').unit)} />
              <MetricTile label="Скорость листинга" value={fmtByUnit(getScalar(scalars, 'LISTING_VELOCITY').value, getScalar(scalars, 'LISTING_VELOCITY').unit)} />
              <MetricTile label="Лотов в карточке" value={Number(details?.listings?.length || 0).toLocaleString('ru-RU')} />
            </div>
          )}
        </BentoCard>

        <BentoCard
          className="xl:col-span-2"
          title={titleLiquidityChart}
          right={
            <div className="flex gap-1">
              {tfVariantLiquidity.map((tf) => (
                <button key={tf} type="button" onClick={() => setTfLiquidity(tf)} className={`rounded-lg border px-2 py-1 text-xs font-semibold ${tfLiquidity === tf ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-slate-200 text-slate-600'}`}>
                  {tf}
                </button>
              ))}
            </div>
          }
        >
          {metricsLoading ? <LoadingBlock className="h-[240px]" /> : <Sparkline points={liquiditySeries} label="Ликвидность" color="#0f766e" fill="rgba(15,118,110,0.12)" />}
        </BentoCard>

        <BentoCard title="График предложения" className="xl:col-span-1">
          {metricsLoading ? <LoadingBlock className="h-[240px]" /> : <Sparkline points={supplySeries} label="Предложение" color="#1d4ed8" fill="rgba(29,78,216,0.12)" />}
        </BentoCard>

        <BentoCard title={titleDepthWall} className="xl:col-span-1">
          {metricsLoading ? (
            <LoadingBlock className="h-[240px]" />
          ) : (
            <div className="space-y-3">
              <MetricTile label="Глубина рынка" value={fmtByUnit(depthScalar.value, depthScalar.unit)} />
              <MetricTile label="Сила стенки BUY" value={fmtByUnit(getScalar(scalars, 'BUY_WALL_SCORE').value, getScalar(scalars, 'BUY_WALL_SCORE').unit)} />
              <MetricTile label="Последний минимум" value={depthPoint ? `${Number(depthPoint.value || 0).toFixed(1)} TON` : 'н/д'} />
            </div>
          )}
        </BentoCard>
      </BentoGrid>

      <BentoGrid className="mt-4">
        <BentoCard title={titleWhales} className="xl:col-span-2">
          {metricsLoading ? (
            <LoadingBlock className="h-24" />
          ) : (
            <div className="grid gap-3">
              <MetricTile label="Доля китов" value={fmtByUnit(getScalar(scalars, 'WHALE_RATIO').value, getScalar(scalars, 'WHALE_RATIO').unit)} />
              <MetricTile label="Импульс китов" value={fmtByUnit(getScalar(scalars, 'WHALE_IMPULSE').value, getScalar(scalars, 'WHALE_IMPULSE').unit)} />
            </div>
          )}
        </BentoCard>

        <BentoCard title={titleRarity} className="xl:col-span-2">
          {metricsLoading ? (
            <LoadingBlock className="h-24" />
          ) : (
            <div className="grid gap-3">
              <MetricTile label="Индекс редкости" value={fmtByUnit(getScalar(scalars, 'RARITY_SCORE').value, getScalar(scalars, 'RARITY_SCORE').unit)} />
            </div>
          )}
        </BentoCard>

        <BentoCard
          className="xl:col-span-2"
          title={titleHeatmap}
          right={
            <div className="flex gap-1">
              {tfVariantHeatmap.map((tf) => (
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
          {metricsLoading ? <LoadingBlock className="h-24" /> : <HeatmapStrip points={heatSeries} label="Ликвидность" maxItems={48} cellHeightClass="h-12" />}
        </BentoCard>
      </BentoGrid>

      <BentoCard title={titleListingFeed} className="mt-4">
        {metricsLoading ? (
          <LoadingBlock className="h-24" />
        ) : feedItems.length ? (
          <div className="gmz-table-wrap">
            <table className="gmz-table">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="pb-2 pr-4">Время</th>
                  <th className="pb-2 pr-4">Ключ листинга</th>
                  <th className="pb-2 pr-4">TON</th>
                  <th className="pb-2 pr-4">Модель</th>
                  <th className="pb-2">Источник</th>
                </tr>
              </thead>
              <tbody>
                {feedItems.slice(0, 30).map((row, i) => {
                  const attrs = (row.attributes || {}) as Record<string, unknown>
                  return (
                    <tr key={`${row.listing_key || 'lk'}-${i}`} className="border-b border-slate-100">
                      <td className="py-2 pr-4 text-xs text-slate-500">{String(row.ts || '—')}</td>
                      <td className="py-2 pr-4 text-xs text-slate-600">{String(row.listing_key || row.variant_id || '—')}</td>
                      <td className="py-2 pr-4 tabular-nums">{Number((row.resell_amount as number) || 0).toFixed(1)}</td>
                      <td className="py-2 pr-4">{String(attrs.model || '—')}</td>
                      <td className="py-2">{String(row.source || '—')}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-sm text-slate-500">Для этого варианта нет событий в ленте листингов</div>
        )}
      </BentoCard>

      <BentoCard title="Лоты и рекомендации" className="mt-4">
        {loading ? (
          <LoadingBlock className="h-24" />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            <MetricTile label="Лотов в ответе" value={Number(details?.listings?.length || 0)} />
            <MetricTile label="Прогноз 24ч" value={`${Number(breakdown?.forecast24h_pct_min || variant?.forecast24h_pct_min || 0).toFixed(1)}%…${Number(breakdown?.forecast24h_pct_max || variant?.forecast24h_pct_max || 0).toFixed(1)}%`} />
          </div>
        )}
        {!!details?.listings?.length && (
          <div className="gmz-table-wrap mt-3">
            <table className="gmz-table">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="pb-2 pr-4">ID листинга</th>
                  <th className="pb-2 pr-4">Тип</th>
                  <th className="pb-2 pr-4">Статус</th>
                  <th className="pb-2 pr-4">TON</th>
                  <th className="pb-2">⭐</th>
                </tr>
              </thead>
              <tbody>
                {details.listings.slice(0, 30).map((lot) => (
                  <tr key={lot.listing_id || `${lot.sale_type}-${lot.price_ton}`} className="border-b border-slate-100">
                    <td className="py-2 pr-4 text-xs text-slate-600">{lot.listing_id || '—'}</td>
                    <td className="py-2 pr-4">{lot.sale_type || '—'}</td>
                    <td className="py-2 pr-4">{lot.status || '—'}</td>
                    <td className="py-2 pr-4 tabular-nums">{ton(lot.price_ton)}</td>
                    <td className="py-2 tabular-nums">{Number(lot.price_stars || 0).toLocaleString('ru-RU')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </BentoCard>
    </section>
  )
}
