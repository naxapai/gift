import { AnimatePresence, motion } from 'framer-motion'
import { useMemo, useState } from 'react'
import { DecisionTraceCard } from './DecisionTraceCard'
import { pct, signalPercent, signalTypeRu, ton } from '../lib/api'
import type { SignalItem } from '../types/api'

interface SignalDetailsDrawerProps {
  signal: SignalItem | null
  onClose: () => void
}

type TabKey = 'reasons' | 'calc' | 'lots' | 'history'

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: 'reasons', label: 'Причины' },
  { key: 'calc', label: 'Расчёт' },
  { key: 'lots', label: 'Лоты' },
  { key: 'history', label: 'История' },
]

function riskProxy(signal: SignalItem): number {
  const count = Array.isArray(signal.risk_flags) ? signal.risk_flags.length : 0
  return Math.min(1, count / 4)
}

export function SignalDetailsDrawer({ signal, onClose }: SignalDetailsDrawerProps) {
  const [tab, setTab] = useState<TabKey>('reasons')

  const calcRows = useMemo(() => {
    if (!signal) return []
    return [
      ['Тип', signalTypeRu(signal.type)],
      ['Оценка', Number(signal.score100 || 0).toFixed(1)],
      ['Уверенность', `${Number(signal.conf_pct || 0).toFixed(1)}%`],
      ['Цена', `${ton(signal.price_ton)} TON`],
      ['Минимальная цена (floor)', `${ton(signal.floor_ton)} TON`],
      ['Справедливая цена', `${ton(signal.fair_ton)} TON`],
      ['Недооценка', `${signalPercent(signal.undervalue_pct ?? signal.undervalue ?? 0).toFixed(2)}%`],
      ['Ожид. прибыль', `${signalPercent(signal.expected_profit_pct || 0).toFixed(2)}%`],
      ['Прогноз 24ч', `${pct(signal.forecast24h_pct_min ?? signal.forecast_24h_pct_min)}…${pct(signal.forecast24h_pct_max ?? signal.forecast_24h_pct_max)}`],
      ['Риск proxy', riskProxy(signal).toFixed(2)],
    ]
  }, [signal])

  return (
    <AnimatePresence>
      {signal ? (
        <>
          <motion.button
            type="button"
            className="fixed inset-0 z-40 bg-slate-900/40"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />

          <motion.aside
            className="fixed right-0 top-0 z-50 h-full w-full max-w-[560px] overflow-y-auto border-l border-slate-200 bg-white p-4 shadow-2xl"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', stiffness: 280, damping: 30 }}
          >
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h3 className="text-xl font-bold text-slate-900">Детали сигнала</h3>
                <p className="text-xs text-slate-500">{signal.signal_id || signal.variant_id || 'н/д'}</p>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
              >
                Закрыть
              </button>
            </div>

            <div className="mb-4 grid grid-cols-4 gap-2 rounded-xl border border-[var(--line)] bg-[rgba(255,255,255,0.72)] p-2">
              {tabs.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => setTab(t.key)}
                  className={`gmz-btn rounded-lg px-2 py-2 text-xs font-semibold ${
                    tab === t.key ? 'bg-[var(--accent)] text-white' : 'gmz-btn-ghost text-slate-600 hover:bg-white'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {tab === 'reasons' && (
              <section className="space-y-3">
                <div className="rounded-xl border border-slate-200 p-3">
                  <h4 className="mb-2 text-sm font-bold text-slate-800">Причины</h4>
                  {signal.reasons?.length ? (
                    <ul className="space-y-1 text-sm text-slate-700">
                      {signal.reasons.map((reason, i) => (
                        <li key={`${reason}-${i}`}>• {reason}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-slate-500">Нет причин в ответе</p>
                  )}
                </div>

                <div className="rounded-xl border border-slate-200 p-3">
                  <h4 className="mb-2 text-sm font-bold text-slate-800">Риски</h4>
                  {signal.risk_flags?.length ? (
                    <ul className="space-y-1 text-sm text-rose-700">
                      {signal.risk_flags.map((risk, i) => (
                        <li key={`${risk}-${i}`}>• {risk}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-slate-500">Риски не указаны</p>
                  )}
                </div>

                <div className="rounded-xl border border-slate-200 p-3">
                  <h4 className="mb-2 text-sm font-bold text-slate-800">WATCH trigger</h4>
                  <p className="text-sm text-slate-700">{signal.watch_trigger || 'Нет отдельного триггера'}</p>
                </div>

                <DecisionTraceCard trace={signal.decision_trace} />
              </section>
            )}

            {tab === 'calc' && (
              <section className="rounded-xl border border-slate-200 p-3">
                <h4 className="mb-2 text-sm font-bold text-slate-800">Параметры расчёта</h4>
                <div className="grid gap-2 sm:grid-cols-2">
                  {calcRows.map(([k, v]) => (
                    <div key={k} className="rounded-lg border border-dashed border-sky-200 bg-slate-50 px-2 py-2">
                      <div className="text-[11px] text-slate-500">{k}</div>
                      <div className="mt-1 text-sm font-semibold text-slate-900 tabular-nums">{v}</div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {tab === 'lots' && (
              <section className="rounded-xl border border-slate-200 p-3">
                <h4 className="mb-2 text-sm font-bold text-slate-800">Лоты</h4>
                <div className="grid gap-2 sm:grid-cols-2">
                  <div className="rounded-lg border border-dashed border-sky-200 bg-slate-50 px-2 py-2">
                    <div className="text-[11px] text-slate-500">Активные лоты</div>
                    <div className="mt-1 text-sm font-semibold text-slate-900">{Number(signal.active_lots || 0).toLocaleString('ru-RU')}</div>
                  </div>
                  <div className="rounded-lg border border-dashed border-sky-200 bg-slate-50 px-2 py-2">
                    <div className="text-[11px] text-slate-500">Ликвидность 24ч</div>
                    <div className="mt-1 text-sm font-semibold text-slate-900">{Number(signal.liquidity24h || 0).toFixed(2)}</div>
                  </div>
                </div>
              </section>
            )}

            {tab === 'history' && (
              <section className="rounded-xl border border-slate-200 p-3">
                <h4 className="mb-2 text-sm font-bold text-slate-800">История</h4>
                <div className="text-sm text-slate-600">Время сигнала: {signal.ts ? new Date(signal.ts).toLocaleString('ru-RU') : '—'}</div>
                <div className="mt-2 text-xs text-slate-500">Источник: {signal.source || 'н/д'}</div>
              </section>
            )}
          </motion.aside>
        </>
      ) : null}
    </AnimatePresence>
  )
}
