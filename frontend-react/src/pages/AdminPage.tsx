import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { BentoCard } from '../components/BentoCard'
import { BentoGrid } from '../components/BentoGrid'
import { LoadingBlock } from '../components/LoadingBlock'
import { PageHeader } from '../components/PageHeader'
import { getAdminAccess, getAdminFormulaGatesStatus, getAdminRefreshStatus, getAdminRuntimeHttpMetrics, getAdminSignalEngineConfig, getAdminSignalPreview, getAlertsV1, postAlertTestV1, resetAdminRuntimeHttpMetrics, resetAdminSignalEngineConfig, saveAdminSignalEngineConfig, signalTypeRu, triggerAdminRefresh } from '../lib/api'
import { readUiAutoRefreshMinutes, uiAutoRefreshMs } from '../lib/uiSettings'
import type { SignalItem } from '../types/api'

type AccessState = {
  loading: boolean
  isAdmin: boolean
  userId: number | null
  error: string
}

interface AdminCachePayload {
  savedAt: number
  data: {
    cfgText: string
    signals: SignalItem[]
    refreshStatus: Record<string, unknown> | null
    formulaStatus: Record<string, unknown> | null
    runtimeHttp: Record<string, unknown> | null
    alertRuleId: string
  }
}

const ADMIN_CACHE_KEY = 'gmz.admin.cache.v1'

function signalChip(type?: string): string {
  const t = String(type || '').toUpperCase()
  if (t === 'BUY') return 'gmz-chip buy'
  if (t === 'SELL') return 'gmz-chip sell'
  if (t === 'WATCH') return 'gmz-chip watch'
  return 'gmz-chip hold'
}

export function AdminPage() {
  const autoRefreshMinutes = useMemo(() => readUiAutoRefreshMinutes(), [])
  const autoRefreshMs = useMemo(() => uiAutoRefreshMs(autoRefreshMinutes), [autoRefreshMinutes])
  const nextRefreshAtRef = useRef<number>(Date.now() + autoRefreshMs)
  const firstLoadRef = useRef(true)
  const [access, setAccess] = useState<AccessState>({
    loading: true,
    isAdmin: false,
    userId: null,
    error: '',
  })
  const [cfgText, setCfgText] = useState('{}')
  const [cfgError, setCfgError] = useState('')
  const [cfgSaving, setCfgSaving] = useState(false)
  const [signals, setSignals] = useState<SignalItem[]>([])
  const [signalsLoading, setSignalsLoading] = useState(false)
  const [refreshLoading, setRefreshLoading] = useState(false)
  const [toast, setToast] = useState('')
  const [refreshStatus, setRefreshStatus] = useState<Record<string, unknown> | null>(null)
  const [formulaStatus, setFormulaStatus] = useState<Record<string, unknown> | null>(null)
  const [runtimeHttp, setRuntimeHttp] = useState<Record<string, unknown> | null>(null)
  const [alertRuleId, setAlertRuleId] = useState('')
  const [alertLoading, setAlertLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const loadSignals = useCallback(async () => {
    setSignalsLoading(true)
    try {
      const payload = await getAdminSignalPreview(120)
      setSignals(Array.isArray(payload.items) ? payload.items : [])
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'Не удалось загрузить предпросмотр сигналов')
    } finally {
      setSignalsLoading(false)
    }
  }, [])

  const loadOpsStatus = useCallback(async () => {
    try {
      const [refreshPayload, formulaPayload, runtimePayload] = await Promise.all([
        getAdminRefreshStatus().catch(() => null),
        getAdminFormulaGatesStatus().catch(() => null),
        getAdminRuntimeHttpMetrics().catch(() => null),
      ])
      setRefreshStatus(refreshPayload && typeof refreshPayload === 'object' ? refreshPayload : null)
      setFormulaStatus(formulaPayload && typeof formulaPayload === 'object' ? formulaPayload : null)
      setRuntimeHttp(runtimePayload && typeof runtimePayload === 'object' ? runtimePayload : null)
    } catch {
      // best effort block, UI remains functional
    }
  }, [])

  const preloadAlertRule = useCallback(async () => {
    try {
      const payload = await getAlertsV1()
      const first = Array.isArray(payload.items) ? payload.items.find((x) => String(x?.rule_id || '').trim()) : null
      if (first?.rule_id) setAlertRuleId(String(first.rule_id))
    } catch {
      // optional, do not block admin page
    }
  }, [])

  const loadConfig = useCallback(async () => {
    try {
      const payload = await getAdminSignalEngineConfig()
      setCfgText(JSON.stringify(payload.overrides || {}, null, 2))
      setCfgError('')
    } catch (e) {
      setCfgError(e instanceof Error ? e.message : 'Ошибка загрузки конфигурации')
    }
  }, [])

  useEffect(() => {
    let stop = false
    ;(async () => {
      try {
        const accessPayload = await getAdminAccess()
        if (stop) return
        const isAdmin = Boolean(accessPayload?.is_admin)
        setAccess({
          loading: false,
          isAdmin,
          userId: Number.isFinite(Number(accessPayload?.user_id)) ? Number(accessPayload?.user_id) : null,
          error: '',
        })
        if (isAdmin) {
          let shouldRefresh = true
          try {
            const raw = sessionStorage.getItem(ADMIN_CACHE_KEY)
            if (raw) {
              const parsed = JSON.parse(raw) as AdminCachePayload
              if (parsed && parsed.data && Number.isFinite(Number(parsed.savedAt))) {
                setCfgText(typeof parsed.data.cfgText === 'string' ? parsed.data.cfgText : '{}')
                setSignals(Array.isArray(parsed.data.signals) ? parsed.data.signals : [])
                setRefreshStatus(parsed.data.refreshStatus && typeof parsed.data.refreshStatus === 'object' ? parsed.data.refreshStatus : null)
                setFormulaStatus(parsed.data.formulaStatus && typeof parsed.data.formulaStatus === 'object' ? parsed.data.formulaStatus : null)
                setRuntimeHttp(parsed.data.runtimeHttp && typeof parsed.data.runtimeHttp === 'object' ? parsed.data.runtimeHttp : null)
                setAlertRuleId(typeof parsed.data.alertRuleId === 'string' ? parsed.data.alertRuleId : '')
                const savedAt = Number(parsed.savedAt || 0)
                const ageMs = Date.now() - savedAt
                if (ageMs < autoRefreshMs) {
                  nextRefreshAtRef.current = savedAt + autoRefreshMs
                  shouldRefresh = false
                }
              }
            }
          } catch {
            // ignore corrupted cache, fallback to network
          }
          if (shouldRefresh) {
            setRefreshing(true)
            await Promise.allSettled([loadConfig(), loadSignals(), loadOpsStatus(), preloadAlertRule()])
            if (!stop) {
              nextRefreshAtRef.current = Date.now() + autoRefreshMs
              setRefreshing(false)
            }
          }
        }
      } catch (e) {
        if (stop) return
        setAccess({
          loading: false,
          isAdmin: false,
          userId: null,
          error: e instanceof Error ? e.message : 'Не удалось проверить права доступа',
        })
      }
    })()
    return () => {
      stop = true
    }
  }, [autoRefreshMs, loadConfig, loadSignals, loadOpsStatus, preloadAlertRule])

  useEffect(() => {
    if (!access.isAdmin || access.loading) return
    const refresh = async () => {
      if (firstLoadRef.current) {
        firstLoadRef.current = false
        return
      }
      setRefreshing(true)
      await Promise.allSettled([loadConfig(), loadSignals(), loadOpsStatus(), preloadAlertRule()])
      nextRefreshAtRef.current = Date.now() + autoRefreshMs
      setRefreshing(false)
    }
    const delay = Math.max(5_000, nextRefreshAtRef.current - Date.now())
    const timer = window.setTimeout(() => {
      void refresh()
    }, delay)
    return () => window.clearTimeout(timer)
  }, [access.isAdmin, access.loading, autoRefreshMs, loadConfig, loadSignals, loadOpsStatus, preloadAlertRule])

  useEffect(() => {
    if (!access.isAdmin || access.loading) return
    try {
      const payload: AdminCachePayload = {
        savedAt: Date.now(),
        data: {
          cfgText,
          signals,
          refreshStatus,
          formulaStatus,
          runtimeHttp,
          alertRuleId,
        },
      }
      sessionStorage.setItem(ADMIN_CACHE_KEY, JSON.stringify(payload))
    } catch {
      // best effort cache only
    }
  }, [access.isAdmin, access.loading, alertRuleId, cfgText, formulaStatus, refreshStatus, runtimeHttp, signals])

  const byType = useMemo(() => ({
    buy: signals.filter((x) => String(x.type || x.action || '').toUpperCase() === 'BUY').length,
    sell: signals.filter((x) => String(x.type || x.action || '').toUpperCase() === 'SELL').length,
    watch: signals.filter((x) => String(x.type || x.action || '').toUpperCase() === 'WATCH').length,
    skip: signals.filter((x) => String(x.type || x.action || '').toUpperCase() === 'SKIP').length,
  }), [signals])

  const runtimeLatency = useMemo(() => {
    const latency = (runtimeHttp?.latency_ms || {}) as Record<string, unknown>
    const p50 = Number(latency.p50 || 0)
    const p95 = Number(latency.p95 || 0)
    const p99 = Number(latency.p99 || 0)
    return {
      p50: Number.isFinite(p50) ? p50 : 0,
      p95: Number.isFinite(p95) ? p95 : 0,
      p99: Number.isFinite(p99) ? p99 : 0,
    }
  }, [runtimeHttp])

  const runtimeSse = useMemo(() => {
    const sse = (runtimeHttp?.sse || {}) as Record<string, unknown>
    const rate = Number(sse.abrupt_disconnect_rate_pct || 0)
    let active = 0
    if (sse.active && typeof sse.active === 'object') {
      active = (Object.values(sse.active as Record<string, unknown>) as unknown[]).reduce<number>(
        (acc, v) => acc + (Number(v) || 0),
        0,
      )
    }
    return {
      rate: Number.isFinite(rate) ? rate : 0,
      active: Number.isFinite(active) ? active : 0,
    }
  }, [runtimeHttp])

  const onSave = useCallback(async () => {
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(cfgText || '{}')
      setCfgError('')
    } catch {
      setCfgError('Конфиг должен быть валидным JSON')
      return
    }
    setCfgSaving(true)
    try {
      await saveAdminSignalEngineConfig(parsed)
      setToast('Конфиг сохранён')
      await loadConfig()
      await loadSignals()
    } catch (e) {
      setCfgError(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setCfgSaving(false)
    }
  }, [cfgText, loadConfig, loadSignals])

  const onReset = useCallback(async () => {
    setCfgSaving(true)
    try {
      await resetAdminSignalEngineConfig()
      setToast('Конфиг сброшен')
      await loadConfig()
      await loadSignals()
    } catch (e) {
      setCfgError(e instanceof Error ? e.message : 'Ошибка сброса')
    } finally {
      setCfgSaving(false)
    }
  }, [loadConfig, loadSignals])

  const onRefresh = useCallback(async () => {
    setRefreshLoading(true)
    try {
      await triggerAdminRefresh()
      setToast('Пересчёт запущен')
      await Promise.all([loadSignals(), loadOpsStatus()])
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'Не удалось запустить пересчёт')
    } finally {
      setRefreshLoading(false)
    }
  }, [loadSignals, loadOpsStatus])

  const onResetHttpMetrics = useCallback(async () => {
    try {
      await resetAdminRuntimeHttpMetrics()
      setToast('HTTP/SSE метрики сброшены')
      await loadOpsStatus()
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'Не удалось сбросить runtime метрики')
    }
  }, [loadOpsStatus])

  const onAlertTest = useCallback(async () => {
    const ruleId = String(alertRuleId || '').trim()
    if (!ruleId) {
      setToast('Укажите rule_id для тестового алерта')
      return
    }
    setAlertLoading(true)
    try {
      await postAlertTestV1(ruleId)
      setToast(`Тестовый алерт отправлен: ${ruleId}`)
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'Не удалось отправить тестовый алерт')
    } finally {
      setAlertLoading(false)
    }
  }, [alertRuleId])

  return (
    <section>
      <PageHeader title="Админ" subtitle="Управление сигналами и проверка качества прод-движка" />

      {access.isAdmin && refreshing ? (
        <div className="mb-3 rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-700">
          Обновляем admin-данные в фоне…
        </div>
      ) : null}

      {toast ? (
        <div className="mb-3 rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-700">{toast}</div>
      ) : null}

      {access.loading ? (
        <LoadingBlock className="h-28" />
      ) : !access.isAdmin ? (
        <Navigate to="/" replace />
      ) : (
        <BentoGrid>
          <BentoCard title="Права и статус" className="xl:col-span-2">
            <div className="space-y-2 text-sm">
              <div><strong>Статус:</strong> admin</div>
              <div><strong>Telegram ID:</strong> {access.userId ?? '—'}</div>
            </div>
          </BentoCard>

          <BentoCard title="Операционный статус" className="xl:col-span-4">
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-sm">
                Refresh in progress: <strong>{Boolean(refreshStatus?.in_progress) ? 'yes' : 'no'}</strong>
              </div>
              <div className="rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-sm">
                Last mode: <strong>{String(refreshStatus?.last_mode || '—')}</strong>
              </div>
              <div className="rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-sm">
                Gates: <strong>{Boolean(formulaStatus?.gates_ok) ? 'ok' : 'fail'}</strong>
              </div>
              <div className="rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-sm">
                Corridor: <strong>{Boolean(formulaStatus?.corridor_ok) ? 'ok' : 'fail'}</strong>
              </div>
            </div>
            <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-sm">
                HTTP req: <strong>{Number(runtimeHttp?.total_requests || 0)}</strong>
              </div>
              <div className="rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-sm">
                p50/p95/p99: <strong>{runtimeLatency.p50.toFixed(1)} / {runtimeLatency.p95.toFixed(1)} / {runtimeLatency.p99.toFixed(1)} ms</strong>
              </div>
              <div className="rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-sm">
                5xx: <strong>{Number(((runtimeHttp?.statuses as Record<string, unknown> | null)?.['5xx']) || 0)}</strong>
              </div>
              <div className="rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-sm">
                Uptime: <strong>{Number(runtimeHttp?.uptime_sec || 0)}s</strong>
              </div>
              <div className="rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-sm">
                SSE active: <strong>{runtimeSse.active}</strong>
              </div>
              <div className="rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-sm">
                SSE abrupt %: <strong>{runtimeSse.rate.toFixed(2)}</strong>
              </div>
            </div>
            <div className="mt-2 text-xs text-slate-500">
              source: {String(formulaStatus?.report_source || 'n/a')} • error: {String(formulaStatus?.error || '') || 'none'}
            </div>
          </BentoCard>

          <BentoCard title="Сигнальный движок" className="xl:col-span-6">
            <div className="mb-2 flex flex-wrap gap-2">
              <button type="button" className="gmz-btn gmz-btn-ghost px-3 py-2 text-sm" onClick={() => void loadConfig()} disabled={cfgSaving}>
                Обновить
              </button>
              <button type="button" className="gmz-btn gmz-btn-primary px-3 py-2 text-sm" onClick={() => void onSave()} disabled={cfgSaving}>
                {cfgSaving ? 'Сохраняем…' : 'Сохранить'}
              </button>
              <button type="button" className="gmz-btn gmz-btn-ghost px-3 py-2 text-sm" onClick={() => void onReset()} disabled={cfgSaving}>
                Сбросить
              </button>
              <button type="button" className="gmz-btn gmz-btn-ghost px-3 py-2 text-sm" onClick={() => void onRefresh()} disabled={refreshLoading}>
                {refreshLoading ? 'Запуск…' : 'Запустить пересчёт'}
              </button>
              <button type="button" className="gmz-btn gmz-btn-ghost px-3 py-2 text-sm" onClick={() => void onResetHttpMetrics()}>
                Сбросить runtime метрики
              </button>
            </div>
            <div className="mb-2 grid gap-2 sm:grid-cols-[1fr_auto]">
              <input
                value={alertRuleId}
                onChange={(e) => setAlertRuleId(e.target.value)}
                className="gmz-input"
                placeholder="rule_id для /v1/alerts/test"
              />
              <button
                type="button"
                className="gmz-btn gmz-btn-ghost px-3 py-2 text-sm"
                onClick={() => void onAlertTest()}
                disabled={alertLoading}
              >
                {alertLoading ? 'Отправка…' : 'Тест алерт'}
              </button>
            </div>
            <textarea
              value={cfgText}
              onChange={(e) => setCfgText(e.target.value)}
              className="min-h-[260px] w-full rounded-xl border border-[var(--line)] bg-white/80 p-3 font-mono text-xs text-slate-800"
              spellCheck={false}
            />
            {cfgError ? <div className="mt-2 text-sm text-rose-700">{cfgError}</div> : null}
          </BentoCard>

          <BentoCard title="Предпросмотр сигналов" className="xl:col-span-6">
            <div className="mb-3 grid gap-2 sm:grid-cols-4">
              <div className="rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-sm">BUY: <strong>{byType.buy}</strong></div>
              <div className="rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-sm">SELL: <strong>{byType.sell}</strong></div>
              <div className="rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-sm">WATCH: <strong>{byType.watch}</strong></div>
              <div className="rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-sm">SKIP: <strong>{byType.skip}</strong></div>
            </div>

            {signalsLoading ? (
              <LoadingBlock className="h-20" />
            ) : signals.length ? (
              <div className="gmz-table-wrap max-h-[420px]">
                <table className="gmz-table">
                  <thead>
                    <tr>
                      <th>Тип</th>
                      <th>Подарок</th>
                      <th>Score</th>
                      <th>Conf</th>
                      <th>Цена</th>
                      <th>Время</th>
                    </tr>
                  </thead>
                  <tbody>
                    {signals.map((row) => {
                      const key = String(row.signal_id || `${row.variant_id}|${row.ts}`)
                      const action = String(row.type || row.action || '').toUpperCase()
                      const gift = row.variant_label || [row.collection, row.model, row.background, row.pattern].filter(Boolean).join(' • ')
                      return (
                        <tr key={key}>
                          <td><span className={signalChip(action)}>{signalTypeRu(action)}</span></td>
                          <td className="max-w-[360px] truncate">{gift || row.variant_id || '—'}</td>
                          <td>{Number(row.score100 || 0).toFixed(1)}</td>
                          <td>{Number(row.conf_pct || 0).toFixed(1)}%</td>
                          <td>{Number(row.price_ton || 0).toFixed(2)} TON</td>
                          <td>{row.ts ? new Date(row.ts).toLocaleString('ru-RU') : '—'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-sm text-slate-500">Сигналы предпросмотра не найдены</div>
            )}
          </BentoCard>
        </BentoGrid>
      )}
    </section>
  )
}
