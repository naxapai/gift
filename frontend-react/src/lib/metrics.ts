export type TimeframeKey = '1h' | '6h' | '24h' | '7d'

export interface TimeframeConfig {
  interval: '1m' | '5m' | '15m' | '1h' | '6h' | '24h'
  limit: number
}

export function timeframeConfig(tf: TimeframeKey): TimeframeConfig {
  if (tf === '1h') return { interval: '1m', limit: 60 }
  if (tf === '6h') return { interval: '5m', limit: 72 }
  if (tf === '7d') return { interval: '1h', limit: 168 }
  return { interval: '15m', limit: 96 }
}

export function timeframeWindowMs(tf: TimeframeKey): number {
  if (tf === '1h') return 60 * 60 * 1000
  if (tf === '6h') return 6 * 60 * 60 * 1000
  if (tf === '7d') return 7 * 24 * 60 * 60 * 1000
  return 24 * 60 * 60 * 1000
}

export function timeframeFromIso(tf: TimeframeKey, toDate: Date = new Date()): string {
  return new Date(toDate.getTime() - timeframeWindowMs(tf)).toISOString()
}

export function normalizeUnitValue(value: number, unit?: string): number {
  const u = String(unit || '').toUpperCase()
  if (u === 'SCORE_0_100' && Math.abs(value) <= 1) {
    return value * 100
  }
  if ((u === 'SCORE_0_1' || u === 'RATIO') && Math.abs(value) <= 1) {
    return value * 100
  }
  return value
}

export function fmtByUnit(value: number, unit?: string, digits = 2): string {
  const u = String(unit || '').toUpperCase()
  const v = normalizeUnitValue(value, u)
  if (u === 'TON') return `${v.toFixed(digits)} TON`
  if (u === 'COUNT') return `${Math.round(v).toLocaleString('ru-RU')}`
  if (u === 'SCORE_0_100') return `${v.toFixed(1)}`
  if (u === 'SCORE_0_1' || u === 'RATIO') return `${v.toFixed(1)}%`
  return `${v.toFixed(digits)}`
}

export function scalarFromPoints(points?: Array<{ value?: number }>): number {
  if (!points?.length) return 0
  return Number(points[points.length - 1]?.value || 0)
}
