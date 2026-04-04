import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { BentoCard } from '../components/BentoCard'
import { BentoGrid } from '../components/BentoGrid'
import { LoadingBlock } from '../components/LoadingBlock'
import { MetricTile } from '../components/MetricTile'
import { PageHeader } from '../components/PageHeader'
import { getTelegramAuthConfig, getTelegramAuthMe, getTelegramOwnedGifts, postTelegramAuthVerify, postTelegramLogout, postTelegramWebAppVerify } from '../lib/api'
import type { AuthUser, OwnedGiftItem } from '../types/api'

const TELEGRAM_WIDGET_SRC = 'https://telegram.org/js/telegram-widget.js?22'

declare global {
  interface Window {
    gmzTelegramAuth?: (user: Record<string, unknown>) => void
    Telegram?: {
      WebApp?: {
        initData?: string
        ready?: () => void
        expand?: () => void
      }
    }
  }
}

function fmtTon(value?: number | null): string {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return '—'
  return `${n.toFixed(2)} TON`
}

function fmtDate(value?: string): string {
  const raw = String(value || '').trim()
  if (!raw) return '—'
  const ts = Date.parse(raw)
  if (Number.isNaN(ts)) return raw
  return new Date(ts).toLocaleString('ru-RU')
}

function ensureTelegramWidgetScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src^="${TELEGRAM_WIDGET_SRC}"]`)
    if (existing) {
      if ((existing as HTMLScriptElement).dataset.loaded === '1') {
        resolve()
        return
      }
      existing.addEventListener('load', () => resolve(), { once: true })
      existing.addEventListener('error', () => reject(new Error('telegram_widget_load_failed')), { once: true })
      return
    }
    const script = document.createElement('script')
    script.src = TELEGRAM_WIDGET_SRC
    script.async = true
    script.dataset.loaded = '0'
    script.onload = () => {
      script.dataset.loaded = '1'
      resolve()
    }
    script.onerror = () => reject(new Error('telegram_widget_load_failed'))
    document.head.appendChild(script)
  })
}

export function CabinetPage() {
  const widgetRef = useRef<HTMLDivElement | null>(null)
  const [authEnabled, setAuthEnabled] = useState(false)
  const [botUsername, setBotUsername] = useState('')
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [authBusy, setAuthBusy] = useState(false)
  const [error, setError] = useState('')
  const [ownedLoading, setOwnedLoading] = useState(false)
  const [ownedSource, setOwnedSource] = useState('')
  const [ownedMessage, setOwnedMessage] = useState('')
  const [ownedGifts, setOwnedGifts] = useState<OwnedGiftItem[]>([])

  const loadSession = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [cfg, me] = await Promise.all([getTelegramAuthConfig(), getTelegramAuthMe()])
      setAuthEnabled(Boolean(cfg.enabled))
      setBotUsername(String(cfg.bot_username || ''))
      setUser(me.authenticated ? (me.user || null) : null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'auth_load_failed')
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  const loadOwnedGifts = useCallback(async () => {
    setOwnedLoading(true)
    try {
      const payload = await getTelegramOwnedGifts()
      setOwnedGifts(Array.isArray(payload.items) ? (payload.items as OwnedGiftItem[]) : [])
      setOwnedSource(String(payload.source || ''))
      setOwnedMessage(String(payload.message || ''))
    } catch (e) {
      setOwnedGifts([])
      setOwnedSource('error')
      setOwnedMessage(e instanceof Error ? e.message : 'owned_gifts_failed')
    } finally {
      setOwnedLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadSession()
  }, [loadSession])

  useEffect(() => {
    if (!user) {
      setOwnedGifts([])
      setOwnedSource('')
      setOwnedMessage('')
      return
    }
    void loadOwnedGifts()
  }, [loadOwnedGifts, user])

  useEffect(() => {
    if (!authEnabled || !botUsername || user || !widgetRef.current) return
    let mounted = true
    const mount = async () => {
      try {
        await ensureTelegramWidgetScript()
        if (!mounted || !widgetRef.current) return
        widgetRef.current.innerHTML = ''
        window.gmzTelegramAuth = async (telegramUser: Record<string, unknown>) => {
          setAuthBusy(true)
          setError('')
          try {
            await postTelegramAuthVerify(telegramUser)
            await loadSession()
          } catch (e) {
            setError(e instanceof Error ? e.message : 'telegram_auth_failed')
          } finally {
            setAuthBusy(false)
          }
        }
        const script = document.createElement('script')
        script.async = true
        script.src = TELEGRAM_WIDGET_SRC
        script.setAttribute('data-telegram-login', botUsername)
        script.setAttribute('data-size', 'large')
        script.setAttribute('data-radius', '14')
        script.setAttribute('data-request-access', 'write')
        script.setAttribute('data-userpic', 'false')
        script.setAttribute('data-onauth', 'gmzTelegramAuth(user)')
        widgetRef.current.appendChild(script)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'telegram_widget_failed')
      }
    }
    void mount()
    return () => {
      mounted = false
      window.gmzTelegramAuth = undefined
    }
  }, [authEnabled, botUsername, loadSession, user])

  useEffect(() => {
    if (!authEnabled || user) return
    const initData = String(window.Telegram?.WebApp?.initData || '').trim()
    if (!initData) return
    let mounted = true
    const run = async () => {
      setAuthBusy(true)
      setError('')
      try {
        window.Telegram?.WebApp?.ready?.()
        window.Telegram?.WebApp?.expand?.()
        await postTelegramWebAppVerify(initData)
        if (mounted) await loadSession()
      } catch (e) {
        if (mounted) setError(e instanceof Error ? e.message : 'telegram_webapp_auth_failed')
      } finally {
        if (mounted) setAuthBusy(false)
      }
    }
    void run()
    return () => {
      mounted = false
    }
  }, [authEnabled, loadSession, user])

  const subtitle = useMemo(() => {
    if (user) return 'Личный кабинет Telegram-пользователя и подарки в наличии'
    return 'Авторизация через Telegram в стиле Fragment, при этом сайт остается полностью доступен без входа'
  }, [user])

  const ownedStats = useMemo(() => {
    const collections = new Set<string>()
    let floorTotal = 0
    let fairTotal = 0
    let floorCount = 0
    let fairCount = 0
    for (const row of ownedGifts) {
      const collection = String(row.collection || '').trim()
      if (collection) collections.add(collection)
      const floor = Number(row.floor_ton)
      const fair = Number(row.fair_ton)
      if (Number.isFinite(floor) && floor > 0) {
        floorTotal += floor
        floorCount += 1
      }
      if (Number.isFinite(fair) && fair > 0) {
        fairTotal += fair
        fairCount += 1
      }
    }
    return {
      total: ownedGifts.length,
      collections: collections.size,
      floorAvg: floorCount ? floorTotal / floorCount : null,
      fairAvg: fairCount ? fairTotal / fairCount : null,
    }
  }, [ownedGifts])

  return (
    <section>
      <PageHeader title="Кабинет" subtitle={subtitle} />

      <BentoGrid>
        <BentoCard title="Telegram" className="xl:col-span-4">
          {loading ? <LoadingBlock /> : user ? (
            <div className="space-y-4">
              <div className="flex items-center gap-3 rounded-2xl border border-[var(--line)] bg-white/75 p-3">
                {user.photo_url ? <img src={String(user.photo_url)} alt="" className="h-14 w-14 rounded-full object-cover" referrerPolicy="no-referrer" /> : <div className="flex h-14 w-14 items-center justify-center rounded-full bg-[#eaf3ff] text-xl">✈️</div>}
                <div>
                  <div className="text-lg font-semibold text-slate-900">{[user.first_name, user.last_name].filter(Boolean).join(' ') || 'Telegram user'}</div>
                  <div className="text-sm text-slate-600">{user.username ? `@${user.username}` : 'Без username'} · ID {user.id ?? '—'}</div>
                  <div className="text-xs text-slate-500">Вход подтвержден через Telegram</div>
                </div>
              </div>
              <div className="flex gap-2">
                <button type="button" className="gmz-btn px-4 py-2 text-sm" onClick={() => { void loadOwnedGifts() }} disabled={ownedLoading}>
                  {ownedLoading ? 'Обновление…' : 'Обновить подарки'}
                </button>
                <button type="button" className="gmz-btn rounded-xl border border-rose-200 bg-[#fff8f8] px-4 py-2 text-sm font-semibold text-rose-700" onClick={() => { void postTelegramLogout().then(() => loadSession()) }}>
                  Выйти
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="rounded-2xl border border-[var(--line)] bg-white/75 p-4 text-sm text-slate-700">
                Вход через Telegram не обязателен: аналитика и разделы сайта доступны без авторизации.
                После входа можно открыть личный кабинет и видеть свои подарки, если источник инвентаря подключен на backend.
              </div>
              {!authEnabled ? (
                <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-800">
                  Telegram auth пока не настроен на backend.
                </div>
              ) : (
                <div className="rounded-2xl border border-[var(--line)] bg-white/75 p-4">
                  <div className="mb-3 text-sm font-medium text-slate-700">Войти через Telegram</div>
                  <div ref={widgetRef} />
                  {authBusy ? <div className="mt-2 text-xs text-slate-500">Проверяем подпись Telegram…</div> : null}
                </div>
              )}
            </div>
          )}
          {error ? <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div> : null}
        </BentoCard>

        <BentoCard title="Подарки в наличии" className="xl:col-span-8">
          {!user ? (
            <div className="rounded-xl border border-dashed border-[var(--line)] bg-white/65 px-4 py-5 text-sm text-slate-600">
              Авторизуйтесь через Telegram, чтобы увидеть подарки пользователя. Основной функционал сайта остается доступным без входа.
            </div>
          ) : ownedLoading ? (
            <LoadingBlock />
          ) : ownedGifts.length ? (
            <div className="space-y-4">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <MetricTile label="Всего подарков" value={String(ownedStats.total)} />
                <MetricTile label="Коллекций" value={String(ownedStats.collections)} />
                <MetricTile label="Средний Floor" value={fmtTon(ownedStats.floorAvg)} />
                <MetricTile label="Средний Fair" value={fmtTon(ownedStats.fairAvg)} />
              </div>
              {ownedSource ? <div className="text-xs text-slate-500">source: {ownedSource}</div> : null}
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {ownedGifts.map((gift, idx) => (
                  <article key={String(gift.gift_id || gift.variant_id || idx)} className="overflow-hidden rounded-2xl border border-[var(--line)] bg-white/80 shadow-soft">
                    <div className="aspect-[4/3] w-full bg-[linear-gradient(135deg,#eef6ff,#f9fbff)]">
                      {gift.preview_url ? <img src={String(gift.preview_url)} alt={String(gift.variant_label || gift.collection || 'Gift')} className="h-full w-full object-cover" loading="lazy" referrerPolicy="no-referrer" /> : null}
                    </div>
                    <div className="space-y-2 p-4">
                      <div>
                        <div className="text-sm font-semibold text-slate-900">{gift.variant_label || gift.collection || 'Gift'}</div>
                        <div className="mt-1 text-xs text-slate-500">{[gift.collection, gift.model, gift.background, gift.pattern].filter(Boolean).join(' / ') || 'Без детального профиля'}</div>
                      </div>
                      <div className="grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
                        <div>Floor: {fmtTon(gift.floor_ton)}</div>
                        <div>Fair: {fmtTon(gift.fair_ton)}</div>
                        <div>Статус: {String(gift.status || 'OWNED')}</div>
                        <div>Дата: {fmtDate(gift.acquired_at)}</div>
                      </div>
                      <div className="flex flex-wrap gap-3 text-xs font-semibold">
                        {gift.variant_id ? (
                          <Link to={`/variant/${encodeURIComponent(String(gift.variant_id))}`} className="text-[var(--accent)] hover:underline">
                            Открыть variant
                          </Link>
                        ) : null}
                        {gift.fragment_url ? (
                          <a href={String(gift.fragment_url)} target="_blank" rel="noreferrer" className="text-[var(--accent)] hover:underline">
                            Открыть в Fragment
                          </a>
                        ) : null}
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-[var(--line)] bg-white/70 px-4 py-4 text-sm text-slate-600">
              {ownedMessage || 'Пока нет данных о подарках пользователя.'}
              {ownedSource ? <div className="mt-2 text-xs text-slate-500">source: {ownedSource}</div> : null}
              {ownedSource === 'remote_error' ? <div className="mt-2 text-xs text-amber-700">Проверь token/endpoint для owned gifts или включи локальный fallback snapshot.</div> : null}
            </div>
          )}
        </BentoCard>
      </BentoGrid>
    </section>
  )
}
