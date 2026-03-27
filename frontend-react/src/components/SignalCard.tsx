import clsx from 'clsx'
import { pct, signalPercent, signalTypeRu, ton, tonToStars } from '../lib/api'
import type { SignalItem } from '../types/api'

interface SignalCardProps {
  signal: SignalItem
  onOpenDetails?: (signal: SignalItem) => void
  onOpenVariant?: (signal: SignalItem) => void
}

function chipClass(type?: string): string {
  const t = String(type || '').toUpperCase()
  if (t === 'BUY') return 'gmz-chip buy'
  if (t === 'SELL') return 'gmz-chip sell'
  if (t === 'WATCH') return 'gmz-chip watch'
  return 'gmz-chip hold'
}

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, value))
}

function finiteOrNull(value: unknown): number | null {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function progressWidth(value: number | null, muted: boolean): number {
  if (value === null) return 0
  const width = clampPercent(value)
  if (!muted) return width
  // Keep sparse bars visible to avoid "disappearing scale" effect during live updates.
  return Math.max(6, width * 0.6)
}

function normalizeQueryToken(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '_')
    .replace(/[^a-z0-9_]/g, '')
}

function resolveGiftSlug(variantId?: string): string {
  const raw = String(variantId || '').trim().toLowerCase()
  if (!raw) return ''

  let m = raw.match(/^([a-z0-9]+)-(\d+)$/)
  if (m) return `${m[1]}-${m[2]}`

  m = raw.match(/^fragment_([a-z0-9]+).*?_(\d+)$/)
  if (m) return `${m[1]}-${m[2]}`

  m = raw.match(/([a-z0-9]+)[_-](\d+)$/)
  if (m) return `${m[1]}-${m[2]}`

  return ''
}

function buildFragmentUrl(signal: SignalItem): string {
  const queryParts = [
    normalizeQueryToken(String(signal.collection_id || signal.collection || '')),
    normalizeQueryToken(String(signal.model || '')),
    normalizeQueryToken(String(signal.background || '')),
    normalizeQueryToken(String(signal.pattern || '')),
  ].filter(Boolean)
  const fallback = String(signal.variant_id || '').replaceAll('|', ' ')
  const query = encodeURIComponent((queryParts.join(' ') || fallback).trim())
  const slug = resolveGiftSlug(signal.variant_id)
  if (slug) {
    return `https://fragment.com/gift/${slug}?collection=all&query=${query}`
  }
  return `https://fragment.com/?collection=all&query=${query}`
}

function starsCompact(stars: number): string {
  if (!Number.isFinite(stars) || stars <= 0) return '0'
  if (stars >= 1000) return `${(stars / 1000).toFixed(1)}k`
  return `${Math.round(stars)}`
}

function pickStars(primary?: number | null, fallbackTon?: number | null): number {
  const direct = Number(primary || 0)
  if (Number.isFinite(direct) && direct > 0) return direct
  return tonToStars(fallbackTon)
}

export function SignalCard({ signal, onOpenDetails, onOpenVariant }: SignalCardProps) {
  const type = String(signal.type || signal.action || 'WATCH').toUpperCase()
  const sparse = String(signal.data_quality || '').toLowerCase() === 'sparse'

  const floor = Number(signal.floor_ton || 0)
  const price = Number(signal.price_ton || floor)
  const fair = Number(signal.fair_ton || 0)
  const undervalue = Number.isFinite(Number(signal.undervalue_pct))
    ? Number(signal.undervalue_pct || 0)
    : signalPercent(signal.undervalue || 0)
  const expected = signalPercent(signal.expected_profit_pct || 0)
  const liq = Number.isFinite(Number(signal.liquidity_score))
    ? Number(signal.liquidity_score || 0)
    : Math.max(0, Math.min(100, Number(signal.liquidity24h || 0) * 100))
  const activeLots = Number(signal.active_lots || 0)
  const scoreRaw = finiteOrNull(signal.score100)
  const confRaw = finiteOrNull(signal.conf_pct)
  const score = scoreRaw === null ? null : clampPercent(scoreRaw)
  const conf = confRaw === null ? null : clampPercent(confRaw)
  const scoreMuted = score === null || sparse
  const confMuted = conf === null || sparse
  const previewUrl = String(signal.preview_url || '').trim()

  const title = signal.variant_label || [signal.model, signal.background, signal.pattern].filter(Boolean).join(' • ') || signal.variant_id || '-'
  const collection = signal.collection || signal.collection_id || '-'
  const forecast = `${pct(signal.forecast24h_pct_min ?? signal.forecast_24h_pct_min)}…${pct(signal.forecast24h_pct_max ?? signal.forecast_24h_pct_max)}`
  const floorStars = pickStars(signal.floor_stars, floor)
  const priceStars = pickStars(signal.price_stars, price)
  const openDetails = () => {
    if (onOpenDetails) {
      onOpenDetails(signal)
      return
    }
    onOpenVariant?.(signal)
  }

  const kpis: Array<[string, string]> = [
    ['Оценка', score === null ? 'н/д' : score.toFixed(1)],
    ['Уверенность', conf === null ? 'н/д' : `${conf.toFixed(1)}%`],
    ['Цена', `${ton(price)} TON / ${starsCompact(priceStars)}⭐`],
    ['Мин. цена', `${ton(floor)} TON / ${starsCompact(floorStars)}⭐`],
  ]

  if (type === 'BUY') {
    kpis.push(
      ['Справедливая цена', fair > 0 ? `${ton(fair)} TON` : 'н/д'],
      ['Недооценка', Number.isFinite(undervalue) ? `${undervalue.toFixed(1)}%` : 'н/д'],
      ['Ожид. прибыль', Number.isFinite(expected) ? `${expected.toFixed(1)}%` : 'н/д'],
    )
  } else if (type === 'SELL') {
    kpis.push(
      ['Прогноз 24ч', forecast],
      ['Активные лоты', String(activeLots)],
      ['Ликвидность 24ч', liq.toFixed(2)],
    )
  }

  return (
    <article className="grid gap-3 rounded-2xl border border-sky-100 bg-gradient-to-b from-white to-slate-50 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="h-12 w-12 shrink-0 overflow-hidden rounded-xl border border-slate-200 bg-slate-100">
            <img
              src={previewUrl || '/favicon.png'}
              alt={title}
              className="h-full w-full object-cover"
              loading="lazy"
              onError={(e) => {
                const img = e.currentTarget
                if (img.dataset.fallbackDone === '1') return
                img.dataset.fallbackDone = '1'
                img.src = '/favicon.png'
              }}
            />
          </div>
          <button
            type="button"
            className="text-left text-sm font-semibold text-slate-900 hover:text-blue-700"
            onClick={() => onOpenVariant?.(signal)}
          >
            {title}
            <div className="mt-1 text-xs font-normal text-slate-500">{collection}</div>
          </button>
        </div>
        <span className={clsx(chipClass(type))}>{signalTypeRu(type)}</span>
      </div>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {kpis.map(([label, value]) => (
          <div key={label} className="rounded-xl border border-dashed border-sky-200 bg-slate-50/60 px-2 py-2">
            <div className="text-[11px] text-slate-500">{label}</div>
            <div className="mt-1 text-sm font-semibold text-slate-900 tabular-nums">{value}</div>
          </div>
        ))}
      </div>

      <div className={clsx('grid gap-2', sparse && 'opacity-70')}>
        <div className="grid grid-cols-[96px_1fr_auto] items-center gap-2 text-xs">
          <span className="text-slate-500">Оценка</span>
          <span className="h-2 overflow-hidden rounded-full bg-slate-200">
            <span
              className={clsx('block h-full rounded-full', scoreMuted ? 'bg-slate-300' : 'bg-gradient-to-r from-blue-500 to-indigo-500')}
              style={{ width: `${progressWidth(score, scoreMuted).toFixed(1)}%` }}
            />
          </span>
          <span className="tabular-nums text-slate-700">
            {score === null ? 'н/д' : sparse ? `~${score.toFixed(1)}%` : `${score.toFixed(1)}%`}
          </span>
        </div>

        <div className="grid grid-cols-[96px_1fr_auto] items-center gap-2 text-xs">
          <span className="text-slate-500">Уверенность</span>
          <span className="h-2 overflow-hidden rounded-full bg-slate-200">
            <span
              className={clsx('block h-full rounded-full', confMuted ? 'bg-slate-300' : 'bg-gradient-to-r from-cyan-500 to-blue-500')}
              style={{ width: `${progressWidth(conf, confMuted).toFixed(1)}%` }}
            />
          </span>
          <span className="tabular-nums text-slate-700">
            {conf === null ? 'н/д' : sparse ? `~${conf.toFixed(1)}%` : `${conf.toFixed(1)}%`}
          </span>
        </div>
      </div>

      <div className="text-sm text-slate-700">
        {type === 'BUY' && (
          <span>
            <strong>КУПИТЬ:</strong> fair {fair > 0 ? `${ton(fair)} TON` : 'н/д'}, недооценка{' '}
            {Number.isFinite(undervalue) ? `${undervalue.toFixed(1)}%` : 'н/д'}, ожидаемая прибыль{' '}
            {Number.isFinite(expected) ? `${expected.toFixed(1)}%` : 'н/д'}
          </span>
        )}
        {type === 'SELL' && (
          <span>
            <strong>ПРОДАТЬ:</strong> прогноз 24ч {forecast}, активные лоты {activeLots}, ликвидность {liq.toFixed(2)}
          </span>
        )}
        {!['BUY', 'SELL'].includes(type) && (
          <span>
            <strong>{signalTypeRu(type)}:</strong> прогноз 24ч {forecast}
          </span>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        {type === 'BUY' && (
          <>
            <a
              href={buildFragmentUrl(signal)}
              target="_blank"
              rel="noreferrer"
              className="gmz-btn gmz-btn-primary px-3 py-2 text-sm"
            >
              Купить
            </a>
            <a
              href={buildFragmentUrl(signal)}
              target="_blank"
              rel="noreferrer"
              className="gmz-btn gmz-btn-ghost px-3 py-2 text-sm"
            >
              Купить+выставить
            </a>
          </>
        )}
        {type === 'SELL' && (
          <a
            href={buildFragmentUrl(signal)}
            target="_blank"
            rel="noreferrer"
            className="gmz-btn rounded-xl border border-rose-200 bg-[#fff8f8] px-3 py-2 text-sm font-semibold text-rose-700"
          >
            Продать
          </a>
        )}
        <button
          type="button"
          onClick={openDetails}
          className="gmz-btn gmz-btn-ghost px-3 py-2 text-sm"
        >
          Подробнее
        </button>
      </div>
    </article>
  )
}
