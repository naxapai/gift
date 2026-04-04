import type { ReactNode } from 'react'

type TraceLike = Record<string, unknown> | null | undefined

function num(value: unknown, digits = 2): string {
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(digits) : '—'
}

function list(value: unknown): string[] {
  return Array.isArray(value) ? value.map((x) => String(x || '').trim()).filter(Boolean) : []
}

function kv(value: unknown): Array<[string, string]> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return []
  return Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, typeof v === 'number' ? num(v, 3) : String(v ?? '—')])
}

export function DecisionTraceCard({ trace, title = 'Decision Trace' }: { trace: TraceLike; title?: string }) {
  const payload = trace && typeof trace === 'object' && !Array.isArray(trace) ? trace as Record<string, unknown> : {}
  const thresholds = kv(payload.thresholds)
  const normalized = kv(payload.normalized)
  const gates = Array.isArray(payload.gates) ? payload.gates.filter((x) => x && typeof x === 'object') as Array<Record<string, unknown>> : []
  const missing = list(payload.missing_for_buy)

  const sections: ReactNode[] = []
  if (payload.regime) sections.push(<div key="regime"><strong>Режим:</strong> {String(payload.regime)}</div>)
  if (thresholds.length) sections.push(<div key="thresholds"><strong>Пороги:</strong> {thresholds.map(([k, v]) => `${k}=${v}`).join(' • ')}</div>)
  if (normalized.length) sections.push(<div key="normalized"><strong>Нормализованные:</strong> {normalized.map(([k, v]) => `${k}=${v}`).join(' • ')}</div>)
  if (gates.length) sections.push(<div key="gates"><strong>Gates:</strong> {gates.map((g) => `${String(g.name || 'gate')}:${Boolean(g.ok) ? 'ok' : 'fail'}${g.reason ? ` (${String(g.reason)})` : ''}`).join(' • ')}</div>)
  if (missing.length) sections.push(<div key="missing"><strong>Не хватает до BUY:</strong> {missing.join(', ')}</div>)
  if (payload.boost !== undefined) sections.push(<div key="boost"><strong>Boost:</strong> {String(payload.boost)}</div>)

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-700">
      <div className="mb-2 text-sm font-bold text-slate-800">{title}</div>
      {sections.length ? <div className="space-y-1">{sections}</div> : <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-2">{JSON.stringify(payload, null, 2)}</pre>}
    </div>
  )
}
