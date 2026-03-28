import { useCallback, useEffect, useState } from 'react'
import { BentoCard } from '../components/BentoCard'
import { BentoGrid } from '../components/BentoGrid'
import { MetricTile } from '../components/MetricTile'
import { PageHeader } from '../components/PageHeader'
import {
  getAdminTelegramDeliveryConfig,
  getAdminTelegramDeliveryJournal,
  getAdminTelegramDeliveryStatus,
  getTelegramAuthMe,
  getAlertsV1,
  getOverview,
  postAdminTelegramDeliveryTest,
  resetAdminTelegramDeliveryConfig,
  saveAdminTelegramDeliveryConfig,
  upsertAlertV1,
} from '../lib/api'
import { readUiAutoRefreshMinutes, uiAutoRefreshBounds, writeUiAutoRefreshMinutes } from '../lib/uiSettings'

const LS = {
  realtime: 'gmz:settings:realtime',
  animations: 'gmz:settings:animations',
  compact: 'gmz:settings:compact',
}

type TelegramFormState = {
  enabled: boolean
  marketEnabled: boolean
  marketIntervalSec: number
  giftEnabled: boolean
  includeImage: boolean
  edgeRankMin: number
  confMin: number
  profitMin: number
  rateLimitPerMinute: number
  maxRetries: number
  retryBackoffSec: number
}

function readBool(key: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(key)
    if (raw == null) return fallback
    return raw === '1'
  } catch {
    return fallback
  }
}

function writeBool(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? '1' : '0')
  } catch {
    // ignore
  }
}

function parseTelegramForm(effective?: Record<string, unknown> | null): TelegramFormState {
  const market = effective?.market_status && typeof effective.market_status === 'object' ? effective.market_status as Record<string, unknown> : {}
  const gift = effective?.gift_signal && typeof effective.gift_signal === 'object' ? effective.gift_signal as Record<string, unknown> : {}
  const gatesRoot = effective?.publish_gates && typeof effective.publish_gates === 'object' ? effective.publish_gates as Record<string, unknown> : {}
  const gates = gatesRoot.gift_signal_channel && typeof gatesRoot.gift_signal_channel === 'object' ? gatesRoot.gift_signal_channel as Record<string, unknown> : {}
  const transport = effective?.transport && typeof effective.transport === 'object' ? effective.transport as Record<string, unknown> : {}
  return {
    enabled: Boolean(effective?.enabled),
    marketEnabled: Boolean(market.enabled),
    marketIntervalSec: Number(market.min_interval_sec || 900),
    giftEnabled: Boolean(gift.enabled),
    includeImage: gift.include_image !== false,
    edgeRankMin: Number(gates.edgeRank100_gte || 55),
    confMin: Number(gates.conf_pct_gte || 35),
    profitMin: Number(gates.expected_profit_pct_gte || 8),
    rateLimitPerMinute: Number(transport.rate_limit_per_minute || 20),
    maxRetries: Number(transport.max_retries || 3),
    retryBackoffSec: Number(transport.retry_backoff_sec || 1.5),
  }
}

export function SettingsPage() {
  const refreshBounds = uiAutoRefreshBounds()
  const [realtime, setRealtime] = useState(() => readBool(LS.realtime, true))
  const [animations, setAnimations] = useState(() => readBool(LS.animations, true))
  const [compact, setCompact] = useState(() => readBool(LS.compact, false))
  const [autoRefreshMinutes, setAutoRefreshMinutes] = useState(() => readUiAutoRefreshMinutes())

  const [engineMode, setEngineMode] = useState('н/д')
  const [marketState, setMarketState] = useState('н/д')
  const [gifts, setGifts] = useState(0)
  const [collections, setCollections] = useState(0)
  const [alertsLoading, setAlertsLoading] = useState(false)
  const [alertsError, setAlertsError] = useState('')
  const [alerts, setAlerts] = useState<Array<{ rule_id?: string; name?: string; enabled?: boolean }>>([])
  const [alertRuleId, setAlertRuleId] = useState('')
  const [alertName, setAlertName] = useState('')
  const [alertEnabled, setAlertEnabled] = useState(true)
  const [alertRuleJson, setAlertRuleJson] = useState(`{
  "scope": "variant"
}`)
  const [alertSaving, setAlertSaving] = useState(false)

  const [telegramAuthed, setTelegramAuthed] = useState(false)
  const [tgLoading, setTgLoading] = useState(false)
  const [tgSaving, setTgSaving] = useState(false)
  const [tgError, setTgError] = useState('')
  const [tgToast, setTgToast] = useState('')
  const [tgPreview, setTgPreview] = useState('')
  const [tgConfigured, setTgConfigured] = useState(false)
  const [tgWorkerAlive, setTgWorkerAlive] = useState(false)
  const [tgQueueSize, setTgQueueSize] = useState(0)
  const [tgSentTotal, setTgSentTotal] = useState(0)
  const [tgFailedTotal, setTgFailedTotal] = useState(0)
  const [tgLastError, setTgLastError] = useState('')
  const [tgJournal, setTgJournal] = useState<{ sent: Array<Record<string, unknown>>; failed: Array<Record<string, unknown>> }>({ sent: [], failed: [] })
  const [tgForm, setTgForm] = useState<TelegramFormState>(() => parseTelegramForm(null))

  useEffect(() => {
    writeBool(LS.realtime, realtime)
  }, [realtime])
  useEffect(() => {
    writeBool(LS.animations, animations)
  }, [animations])
  useEffect(() => {
    writeBool(LS.compact, compact)
  }, [compact])
  useEffect(() => {
    setAutoRefreshMinutes(writeUiAutoRefreshMinutes(autoRefreshMinutes))
  }, [autoRefreshMinutes])

  const loadTelegramSettings = useCallback(async () => {
    setTgLoading(true)
    setTgError('')
    try {
      const [cfg, status, journal] = await Promise.all([
        getAdminTelegramDeliveryConfig(),
        getAdminTelegramDeliveryStatus(),
        getAdminTelegramDeliveryJournal(10),
      ])
      setTgForm(parseTelegramForm(cfg.effective || null))
      setTgConfigured(Boolean(status.configured))
      setTgWorkerAlive(Boolean(status.worker_alive))
      setTgQueueSize(Number(status.queue_size || 0))
      const stats = status.stats && typeof status.stats === 'object' ? status.stats : {}
      setTgSentTotal(Number(stats.sent_total || 0))
      setTgFailedTotal(Number(stats.failed_total || 0))
      setTgLastError(String(stats.last_error || ''))
      setTgJournal({
        sent: Array.isArray(journal.sent) ? journal.sent : [],
        failed: Array.isArray(journal.failed) ? journal.failed : [],
      })
    } catch (e) {
      setTgError(e instanceof Error ? e.message : 'Не удалось загрузить telegram delivery')
    } finally {
      setTgLoading(false)
    }
  }, [])

  useEffect(() => {
    void (async () => {
      try {
        const [ov, auth] = await Promise.all([
          getOverview(),
          getTelegramAuthMe().catch(() => ({ authenticated: false })),
        ])
        setEngineMode(String(ov.engine_mode || 'н/д'))
        setMarketState(String(ov.market_state || 'н/д'))
        setGifts(Number(ov.counts?.gifts || 0))
        setCollections(Number(ov.counts?.collections || 0))
        const nextTelegramAuthed = Boolean(auth?.authenticated)
        setTelegramAuthed(nextTelegramAuthed)
        if (nextTelegramAuthed) {
          await loadTelegramSettings()
        }
      } catch {
        // ignore in settings
      }
    })()
  }, [loadTelegramSettings])

  useEffect(() => {
    void (async () => {
      setAlertsLoading(true)
      setAlertsError('')
      try {
        const payload = await getAlertsV1()
        const items = Array.isArray(payload.items) ? payload.items : []
        setAlerts(items)
        if (items.length && !alertRuleId) {
          const first = items.find((x) => String(x?.rule_id || '').trim())
          if (first?.rule_id) setAlertRuleId(String(first.rule_id))
          if (first?.name) setAlertName(String(first.name))
          if (typeof first?.enabled === 'boolean') setAlertEnabled(Boolean(first.enabled))
        }
      } catch (e) {
        setAlertsError(e instanceof Error ? e.message : 'Не удалось загрузить alerts')
      } finally {
        setAlertsLoading(false)
      }
    })()
  }, [alertRuleId])

  const saveTelegramSettings = useCallback(async () => {
    setTgSaving(true)
    setTgError('')
    setTgToast('')
    try {
      await saveAdminTelegramDeliveryConfig({
        enabled: tgForm.enabled,
        market_status: {
          enabled: tgForm.marketEnabled,
          min_interval_sec: tgForm.marketIntervalSec,
        },
        gift_signal: {
          enabled: tgForm.giftEnabled,
          include_image: tgForm.includeImage,
        },
        publish_gates: {
          gift_signal_channel: {
            edgeRank100_gte: tgForm.edgeRankMin,
            conf_pct_gte: tgForm.confMin,
            expected_profit_pct_gte: tgForm.profitMin,
          },
        },
        transport: {
          rate_limit_per_minute: tgForm.rateLimitPerMinute,
          max_retries: tgForm.maxRetries,
          retry_backoff_sec: tgForm.retryBackoffSec,
        },
      })
      setTgToast('Telegram delivery настройки сохранены')
      await loadTelegramSettings()
    } catch (e) {
      setTgError(e instanceof Error ? e.message : 'Ошибка сохранения Telegram delivery')
    } finally {
      setTgSaving(false)
    }
  }, [loadTelegramSettings, tgForm])

  const resetTelegramSettings = useCallback(async () => {
    setTgSaving(true)
    setTgError('')
    setTgToast('')
    try {
      const payload = await resetAdminTelegramDeliveryConfig()
      setTgForm(parseTelegramForm(payload.effective || null))
      setTgToast('Telegram delivery настройки сброшены')
      await loadTelegramSettings()
    } catch (e) {
      setTgError(e instanceof Error ? e.message : 'Ошибка сброса Telegram delivery')
    } finally {
      setTgSaving(false)
    }
  }, [loadTelegramSettings])

  const runTelegramTest = useCallback(async (kind: 'gift_signal' | 'market_status') => {
    setTgError('')
    setTgToast('')
    try {
      const payload = await postAdminTelegramDeliveryTest(kind)
      setTgPreview(String(payload.preview || ''))
      if (payload.ok) {
        setTgToast(kind === 'gift_signal' ? 'Тестовый сигнал отправлен в Telegram' : 'Тестовый статус рынка отправлен в Telegram')
      } else {
        setTgError(String(payload.error || 'telegram_test_failed'))
      }
      await loadTelegramSettings()
    } catch (e) {
      setTgError(e instanceof Error ? e.message : 'Ошибка тестовой отправки Telegram')
    }
  }, [loadTelegramSettings])

  return (
    <section>
      <PageHeader title="Настройки" subtitle="Локальные параметры интерфейса, серверные alerts и управление Telegram delivery" />

      <BentoGrid>
        <BentoCard title="Параметры интерфейса" className="xl:col-span-4">
          <div className="space-y-3">
            <label className="flex items-center justify-between rounded-xl border border-[var(--line)] bg-[rgba(255,255,255,0.72)] px-3 py-2 text-sm">
              <span>Обновление в реальном времени (SSE)</span>
              <input type="checkbox" checked={realtime} onChange={(e) => setRealtime(e.target.checked)} className="h-4 w-4" />
            </label>

            <label className="flex items-center justify-between rounded-xl border border-[var(--line)] bg-[rgba(255,255,255,0.72)] px-3 py-2 text-sm">
              <span>Плавные анимации интерфейса</span>
              <input type="checkbox" checked={animations} onChange={(e) => setAnimations(e.target.checked)} className="h-4 w-4" />
            </label>

            <label className="flex items-center justify-between rounded-xl border border-[var(--line)] bg-[rgba(255,255,255,0.72)] px-3 py-2 text-sm">
              <span>Компактный режим карточек</span>
              <input type="checkbox" checked={compact} onChange={(e) => setCompact(e.target.checked)} className="h-4 w-4" />
            </label>

            <div className="rounded-xl border border-[var(--line)] bg-[rgba(255,255,255,0.72)] px-3 py-3">
              <div className="flex items-center justify-between gap-2 text-sm">
                <span>Интервал автообновления данных</span>
                <strong>{autoRefreshMinutes} мин</strong>
              </div>
              <input
                type="range"
                min={refreshBounds.min}
                max={refreshBounds.max}
                step={1}
                value={autoRefreshMinutes}
                onChange={(e) => setAutoRefreshMinutes(Number(e.target.value || refreshBounds.defaultValue))}
                className="mt-2 w-full"
              />
              <div className="mt-1 flex justify-between text-xs text-slate-500">
                <span>{refreshBounds.min} мин</span>
                <span>{refreshBounds.max} мин</span>
              </div>
            </div>
          </div>

          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            Это локальные настройки браузера. Telegram delivery управляется серверными настройками ниже.
          </div>
        </BentoCard>

        <BentoCard title="Статус рантайма" className="xl:col-span-2">
          <div className="grid gap-3">
            <MetricTile label="Режим движка" value={engineMode} />
            <MetricTile label="Состояние рынка" value={marketState} />
            <MetricTile label="Подарков" value={gifts.toLocaleString('ru-RU')} />
            <MetricTile label="Коллекций" value={collections.toLocaleString('ru-RU')} />
          </div>
        </BentoCard>

        <BentoCard title="Telegram delivery" className="xl:col-span-6">
          {!telegramAuthed ? (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-800">
              Войдите через Telegram, чтобы управлять отправкой сигналов и тестировать delivery.
            </div>
          ) : (
            <div className="space-y-4">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <MetricTile label="BOT configured" value={tgConfigured ? 'yes' : 'no'} />
                <MetricTile label="Worker" value={tgWorkerAlive ? 'alive' : 'idle'} />
                <MetricTile label="Queue" value={String(tgQueueSize)} />
                <MetricTile label="Sent / Failed" value={`${tgSentTotal} / ${tgFailedTotal}`} />
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <label className="flex items-center justify-between rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-sm">
                  <span>Включить Telegram delivery</span>
                  <input type="checkbox" checked={tgForm.enabled} onChange={(e) => setTgForm((s) => ({ ...s, enabled: e.target.checked }))} className="h-4 w-4" />
                </label>
                <label className="flex items-center justify-between rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-sm">
                  <span>Отправлять market status</span>
                  <input type="checkbox" checked={tgForm.marketEnabled} onChange={(e) => setTgForm((s) => ({ ...s, marketEnabled: e.target.checked }))} className="h-4 w-4" />
                </label>
                <label className="flex items-center justify-between rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-sm">
                  <span>Отправлять gift_signal</span>
                  <input type="checkbox" checked={tgForm.giftEnabled} onChange={(e) => setTgForm((s) => ({ ...s, giftEnabled: e.target.checked }))} className="h-4 w-4" />
                </label>
                <label className="flex items-center justify-between rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-sm">
                  <span>Изображение подарка в сигнале</span>
                  <input type="checkbox" checked={tgForm.includeImage} onChange={(e) => setTgForm((s) => ({ ...s, includeImage: e.target.checked }))} className="h-4 w-4" />
                </label>
              </div>

              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Market status interval (sec)</span>
                  <input type="number" min={60} max={86400} value={tgForm.marketIntervalSec} onChange={(e) => setTgForm((s) => ({ ...s, marketIntervalSec: Number(e.target.value || 900) }))} className="gmz-input" />
                </label>
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">EdgeRank ≥</span>
                  <input type="number" min={0} max={100} value={tgForm.edgeRankMin} onChange={(e) => setTgForm((s) => ({ ...s, edgeRankMin: Number(e.target.value || 55) }))} className="gmz-input" />
                </label>
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Conf ≥</span>
                  <input type="number" min={0} max={100} value={tgForm.confMin} onChange={(e) => setTgForm((s) => ({ ...s, confMin: Number(e.target.value || 35) }))} className="gmz-input" />
                </label>
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Profit % ≥</span>
                  <input type="number" min={0} max={1000} step={0.5} value={tgForm.profitMin} onChange={(e) => setTgForm((s) => ({ ...s, profitMin: Number(e.target.value || 8) }))} className="gmz-input" />
                </label>
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Rate limit / min</span>
                  <input type="number" min={1} max={120} value={tgForm.rateLimitPerMinute} onChange={(e) => setTgForm((s) => ({ ...s, rateLimitPerMinute: Number(e.target.value || 20) }))} className="gmz-input" />
                </label>
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Max retries</span>
                  <input type="number" min={1} max={10} value={tgForm.maxRetries} onChange={(e) => setTgForm((s) => ({ ...s, maxRetries: Number(e.target.value || 3) }))} className="gmz-input" />
                </label>
                <label className="block xl:col-span-1">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Retry backoff (sec)</span>
                  <input type="number" min={0.1} max={30} step={0.1} value={tgForm.retryBackoffSec} onChange={(e) => setTgForm((s) => ({ ...s, retryBackoffSec: Number(e.target.value || 1.5) }))} className="gmz-input" />
                </label>
              </div>

              <div className="flex flex-wrap gap-2">
                <button type="button" className="gmz-btn gmz-btn-primary px-4 py-2 text-sm" disabled={tgSaving || tgLoading} onClick={() => { void saveTelegramSettings() }}>
                  {tgSaving ? 'Сохранение…' : 'Сохранить Telegram delivery'}
                </button>
                <button type="button" className="gmz-btn px-4 py-2 text-sm" disabled={tgSaving || tgLoading} onClick={() => { void resetTelegramSettings() }}>
                  Сбросить к defaults
                </button>
                <button type="button" className="gmz-btn px-4 py-2 text-sm" disabled={tgLoading} onClick={() => { void runTelegramTest('gift_signal') }}>
                  Тест gift_signal
                </button>
                <button type="button" className="gmz-btn px-4 py-2 text-sm" disabled={tgLoading} onClick={() => { void runTelegramTest('market_status') }}>
                  Тест market_status
                </button>
              </div>

              {tgToast ? <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{tgToast}</div> : null}
              {tgError ? <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{tgError}</div> : null}
              {tgLastError ? <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">last_error: {tgLastError}</div> : null}
              {tgPreview ? (
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-slate-700">Preview</span>
                  <textarea value={tgPreview} readOnly className="min-h-[180px] w-full rounded-xl border border-[var(--line)] bg-white/80 p-3 font-mono text-xs text-slate-800" />
                </label>
              ) : null}

              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-xl border border-[var(--line)] bg-white/70 p-3 text-sm">
                  <div className="mb-2 font-semibold">Журнал отправок</div>
                  {tgJournal.sent.length ? (
                    <div className="max-h-[180px] space-y-2 overflow-y-auto text-xs text-slate-700">
                      {tgJournal.sent.map((row, idx) => (
                        <div key={String(row.key || idx)} className="rounded-lg border border-slate-200 bg-white px-2 py-2">
                          <div><strong>key:</strong> {String(row.key || '—')}</div>
                          <div><strong>kind:</strong> {String(row.kind || '—')}</div>
                          <div><strong>sent_at:</strong> {String(row.sent_at || '—')}</div>
                        </div>
                      ))}
                    </div>
                  ) : <div className="text-xs text-slate-500">Пока нет отправок</div>}
                </div>
                <div className="rounded-xl border border-[var(--line)] bg-white/70 p-3 text-sm">
                  <div className="mb-2 font-semibold">Ошибки доставки</div>
                  {tgJournal.failed.length ? (
                    <div className="max-h-[180px] space-y-2 overflow-y-auto text-xs text-slate-700">
                      {tgJournal.failed.map((row, idx) => (
                        <div key={String(row.key || row.ts || idx)} className="rounded-lg border border-rose-200 bg-rose-50 px-2 py-2">
                          <div><strong>key:</strong> {String(row.key || '—')}</div>
                          <div><strong>error:</strong> {String(row.error || '—')}</div>
                          <div><strong>ts:</strong> {String(row.ts || '—')}</div>
                        </div>
                      ))}
                    </div>
                  ) : <div className="text-xs text-slate-500">Ошибок пока нет</div>}
                </div>
              </div>
            </div>
          )}
        </BentoCard>

        <BentoCard title="Alerts v1" className="xl:col-span-6">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-2">
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-slate-700">rule_id (для обновления)</span>
                <input value={alertRuleId} onChange={(e) => setAlertRuleId(e.target.value)} className="gmz-input" placeholder="auto/new если пусто" />
              </label>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-slate-700">Название</span>
                <input value={alertName} onChange={(e) => setAlertName(e.target.value)} className="gmz-input" placeholder="Например: Whale spike" />
              </label>
              <label className="flex items-center justify-between rounded-xl border border-[var(--line)] bg-[rgba(255,255,255,0.72)] px-3 py-2 text-sm">
                <span>Enabled</span>
                <input type="checkbox" checked={alertEnabled} onChange={(e) => setAlertEnabled(e.target.checked)} className="h-4 w-4" />
              </label>
              <button
                type="button"
                className="gmz-btn gmz-btn-primary px-4 py-2 text-sm"
                disabled={alertSaving}
                onClick={() => {
                  void (async () => {
                    setAlertSaving(true)
                    setAlertsError('')
                    try {
                      const name = String(alertName || '').trim()
                      if (!name) throw new Error('name_required')
                      const parsed = JSON.parse(alertRuleJson || '{}')
                      await upsertAlertV1({
                        rule_id: String(alertRuleId || '').trim() || undefined,
                        name,
                        enabled: alertEnabled,
                        rule_json: parsed,
                      })
                      const payload = await getAlertsV1()
                      setAlerts(Array.isArray(payload.items) ? payload.items : [])
                    } catch (e) {
                      setAlertsError(e instanceof Error ? e.message : 'Ошибка сохранения alerts')
                    } finally {
                      setAlertSaving(false)
                    }
                  })()
                }}
              >
                {alertSaving ? 'Сохранение…' : 'Сохранить alert'}
              </button>
            </div>

            <div className="space-y-2">
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-slate-700">rule_json</span>
                <textarea
                  value={alertRuleJson}
                  onChange={(e) => setAlertRuleJson(e.target.value)}
                  className="min-h-[180px] w-full rounded-xl border border-[var(--line)] bg-white/80 p-3 font-mono text-xs text-slate-800"
                  spellCheck={false}
                />
              </label>
              {alertsError ? <div className="text-sm text-rose-700">{alertsError}</div> : null}
              <div className="rounded-xl border border-[var(--line)] bg-white/70 p-3 text-sm">
                <div className="mb-2 font-semibold">Текущие правила ({alerts.length})</div>
                {alertsLoading ? (
                  <div className="text-slate-500">Загрузка…</div>
                ) : alerts.length ? (
                  <div className="max-h-[180px] overflow-y-auto space-y-1">
                    {alerts.map((a, idx) => (
                      <button
                        key={String(a.rule_id || a.name || `alert-${idx}`)}
                        type="button"
                        className="flex w-full items-center justify-between rounded-lg border border-slate-200 bg-white px-2 py-1 text-left text-xs hover:bg-slate-50"
                        onClick={() => {
                          setAlertRuleId(String(a.rule_id || ''))
                          setAlertName(String(a.name || ''))
                          setAlertEnabled(Boolean(a.enabled))
                        }}
                      >
                        <span className="truncate">{String(a.name || a.rule_id || 'alert')}</span>
                        <span className={a.enabled ? 'text-emerald-700' : 'text-slate-500'}>{a.enabled ? 'on' : 'off'}</span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="text-slate-500">Нет правил</div>
                )}
              </div>
            </div>
          </div>
        </BentoCard>
      </BentoGrid>
    </section>
  )
}
