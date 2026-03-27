import type { MetricPoint } from '../types/api'

interface SparklineProps {
  points?: MetricPoint[]
  color?: string
  fill?: string
  height?: number
  label?: string
}

function toFinite(value: unknown, fallback = 0): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

export function Sparkline({
  points = [],
  color = '#2563eb',
  fill = 'rgba(37,99,235,0.12)',
  height = 190,
  label = 'Метрика',
}: SparklineProps) {
  const safe = points
    .map((p) => ({ ts: String(p.ts || ''), value: toFinite(p.value, Number.NaN) }))
    .filter((p) => Number.isFinite(p.value))

  if (safe.length < 2) {
    return (
      <div className="grid h-[220px] place-items-center rounded-xl border border-dashed border-slate-300 text-sm text-slate-500">
        Недостаточно данных для графика
      </div>
    )
  }

  const width = 860
  const padL = 36
  const padR = 10
  const padT = 14
  const padB = 26
  const min = Math.min(...safe.map((p) => p.value))
  const max = Math.max(...safe.map((p) => p.value))
  const span = Math.max(1e-9, max - min)

  const x = (i: number) => padL + (i / (safe.length - 1)) * (width - padL - padR)
  const y = (v: number) => padT + ((max - v) / span) * (height - padT - padB)

  const line = safe.map((p, i) => `${x(i).toFixed(2)},${y(p.value).toFixed(2)}`).join(' ')
  const area = `${line} ${x(safe.length - 1).toFixed(2)},${(height - padB).toFixed(2)} ${x(0).toFixed(2)},${(height - padB).toFixed(2)}`

  const ticks = [0, 0.5, 1].map((t) => {
    const value = max - (max - min) * t
    return {
      y: y(value),
      label: value.toFixed(Math.abs(value) < 10 ? 2 : 1),
    }
  })

  return (
    <div className="overflow-hidden rounded-xl border border-[var(--line)] bg-[rgba(255,255,255,0.72)] p-2">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[220px] w-full" role="img" aria-label={label}>
        {ticks.map((tick) => (
          <g key={tick.label}>
            <line x1={padL} y1={tick.y} x2={width - padR} y2={tick.y} stroke="#cbd5e1" strokeDasharray="4 4" />
            <text x={4} y={tick.y + 4} fontSize="11" fill="#64748b">
              {tick.label}
            </text>
          </g>
        ))}
        <polygon points={area} fill={fill} />
        <polyline points={line} fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" />
        <text x={padL} y={12} fontSize="11" fill="#64748b">
          {label}
        </text>
        <text x={padL} y={height - 6} fontSize="11" fill="#64748b">
          {safe[0]?.ts ? 'Старт' : ''}
        </text>
        <text x={width - 54} y={height - 6} fontSize="11" fill="#64748b">
          Сейчас
        </text>
      </svg>
    </div>
  )
}
