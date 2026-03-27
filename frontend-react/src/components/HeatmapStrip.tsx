import type { MetricPoint } from '../types/api'

interface HeatmapStripProps {
  points?: MetricPoint[]
  label?: string
  maxItems?: number
  cellHeightClass?: string
}

function asNum(v: unknown): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

export function HeatmapStrip({ points = [], label = 'Heatmap', maxItems = 48, cellHeightClass = 'h-4' }: HeatmapStripProps) {
  const values = points
    .slice(-maxItems)
    .map((p) => asNum(p.value))
    .filter((v) => Number.isFinite(v))

  if (!values.length) {
    return (
      <div className="grid h-20 place-items-center rounded-xl border border-dashed border-slate-300 text-sm text-slate-500">
        Нет данных для heatmap
      </div>
    )
  }

  const max = Math.max(1e-9, Math.max(...values))
  return (
    <div className="rounded-xl border border-[var(--line)] bg-[rgba(255,255,255,0.72)] p-2">
      <div className="mb-2 text-xs text-slate-500">{label}</div>
      <div className="grid grid-cols-12 gap-1">
        {values.map((v, i) => {
          const k = Math.max(0, Math.min(1, v / max))
          const bg = `rgba(14,116,144,${(0.08 + k * 0.82).toFixed(3)})`
          return <div key={`${i}-${v}`} className={`${cellHeightClass} rounded-sm`} style={{ backgroundColor: bg }} title={v.toFixed(3)} />
        })}
      </div>
    </div>
  )
}
