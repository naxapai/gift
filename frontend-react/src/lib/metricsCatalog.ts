import mappingRaw from '../../../config/contracts/frontend_metrics_mapping.json'

type MetricMappingPayload = {
  version?: string
  overview_metrics?: string[]
  variant_metrics?: string[]
}

export type MetricScope = 'MARKET' | 'COLLECTION' | 'VARIANT'

const payload = (mappingRaw || {}) as MetricMappingPayload

function normalizeMetric(metric: string): string {
  return String(metric || '').trim().toUpperCase()
}

function dedupeMetrics(items: string[]): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const item of items) {
    const metric = normalizeMetric(item)
    if (!metric || seen.has(metric)) continue
    seen.add(metric)
    out.push(metric)
  }
  return out
}

export const FRONTEND_METRICS_MAPPING_VERSION = String(payload.version || '1.0')
export const OVERVIEW_METRICS = Object.freeze(dedupeMetrics(Array.isArray(payload.overview_metrics) ? payload.overview_metrics : []))
export const VARIANT_METRICS = Object.freeze(dedupeMetrics(Array.isArray(payload.variant_metrics) ? payload.variant_metrics : []))
export const METRIC_NAMES = Object.freeze(dedupeMetrics([...OVERVIEW_METRICS, ...VARIANT_METRICS]))
export const METRIC_SET = new Set<string>(METRIC_NAMES)
export const METRIC_ENUM = Object.freeze(
  METRIC_NAMES.reduce<Record<string, string>>((acc, metric) => {
    acc[metric] = metric
    return acc
  }, {}),
)

export function normalizeMetricName(metric: string): string {
  return normalizeMetric(metric)
}

export function isKnownMetric(metric: string): boolean {
  return METRIC_SET.has(normalizeMetric(metric))
}

export function isMetricAllowedByMapping(metric: string, scope: MetricScope): boolean {
  const normalized = normalizeMetric(metric)
  if (!normalized || !METRIC_SET.has(normalized)) return false
  if (scope === 'MARKET') return OVERVIEW_METRICS.includes(normalized)
  if (scope === 'VARIANT') return VARIANT_METRICS.includes(normalized)
  return true
}

export function assertMetricAllowedByMapping(metric: string, scope: MetricScope): void {
  const normalized = normalizeMetric(metric)
  if (!isKnownMetric(normalized)) {
    throw new Error(`unsupported_metric_in_frontend_mapping:${normalized}`)
  }
  if (!isMetricAllowedByMapping(normalized, scope)) {
    throw new Error(`metric_scope_mismatch_in_frontend_mapping:${normalized}:${scope}`)
  }
}

