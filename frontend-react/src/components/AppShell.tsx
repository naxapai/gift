import clsx from 'clsx'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, NavLink, Outlet } from 'react-router-dom'
import { getTelegramAuthBootstrap, getTelegramAuthMe, getTelegramOwnedGifts, getTonAuthConfig, getTonAuthMe, getTonBalance, getTradingAccess, postTelegramAuthVerify, postTelegramLogout, postTelegramWebAppVerify, postTonChallenge, postTonLogout, postTonVerify, type TonWalletInfo } from '../lib/api'
import type { OwnedGiftItem } from '../types/api'

const navItems = [
  { to: '/', label: 'Обзор' },
  { to: '/catalog', label: 'Каталог' },
  { to: '/screeners', label: 'Скринеры' },
  { to: '/signals', label: 'Сигналы' },
  { to: '/listing', label: 'Листинг' },
  { to: '/trades', label: 'Сделки', tradeOnly: true },
  { to: '/favorites', label: 'Избранное' },
  { to: '/settings', label: 'Настройки' },
]

const TONCONNECT_UI_SRC = 'https://unpkg.com/@tonconnect/ui@2.0.9/dist/tonconnect-ui.min.js'
const TELEGRAM_WIDGET_SRC = 'https://telegram.org/js/telegram-widget.js?22'
const TONCONNECT_BUTTON_ROOT_ID = 'gmz-tonconnect-anchor'
const LS_TELEGRAM_USER = 'gmz:telegram:user'
const LS_TON_WALLET = 'gmz:ton:wallet'

declare global {
  interface Window {
    gmzTelegramAuthShell?: (user: Record<string, unknown>) => void
  }
}

function fmtTon(value?: number | null): string {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return '—'
  return `${n.toFixed(2)} TON`
}

function shortTonAddress(address?: string | null): string {
  const raw = String(address || '').trim()
  if (!raw) return 'TON подключен'
  if (raw.length <= 14) return raw
  return `${raw.slice(0, 6)}...${raw.slice(-6)}`
}

function formatConnectedAt(wallet?: TonWalletInfo | null): string {
  const ts = Number(wallet?.verified_at || 0)
  if (!Number.isFinite(ts) || ts <= 0) return '—'
  return new Date(ts * 1000).toLocaleString('ru-RU')
}

function formatTonBalance(value?: number | null): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '— TON'
  return `${n.toFixed(3)} TON`
}

function readJson<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

function writeJson(key: string, value: unknown | null) {
  try {
    if (value == null) {
      localStorage.removeItem(key)
      return
    }
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // ignore
  }
}

let tonScriptPromise: Promise<void> | null = null
let telegramScriptPromise: Promise<void> | null = null

async function ensureTonConnectSdk(): Promise<void> {
  if (window.TON_CONNECT_UI?.TonConnectUI) return
  if (!tonScriptPromise) {
    tonScriptPromise = new Promise<void>((resolve, reject) => {
      const existing = document.querySelector<HTMLScriptElement>(`script[src="${TONCONNECT_UI_SRC}"]`)
      if (existing) {
        existing.addEventListener('load', () => resolve(), { once: true })
        existing.addEventListener('error', () => reject(new Error('tonconnect_sdk_load_failed')), { once: true })
        return
      }
      const script = document.createElement('script')
      script.src = TONCONNECT_UI_SRC
      script.async = true
      script.onload = () => resolve()
      script.onerror = () => reject(new Error('tonconnect_sdk_load_failed'))
      document.head.appendChild(script)
    })
  }
  await tonScriptPromise
}

async function ensureTelegramWidgetSdk(): Promise<void> {
  if ((window as typeof window & { TelegramLoginWidget?: unknown }).TelegramLoginWidget) return
  if (!telegramScriptPromise) {
    telegramScriptPromise = new Promise<void>((resolve, reject) => {
      const existing = document.querySelector<HTMLScriptElement>(`script[src^="${TELEGRAM_WIDGET_SRC}"]`)
      if (existing) {
        existing.addEventListener('load', () => resolve(), { once: true })
        existing.addEventListener('error', () => reject(new Error('telegram_widget_load_failed')), { once: true })
        return
      }
      const script = document.createElement('script')
      script.src = TELEGRAM_WIDGET_SRC
      script.async = true
      script.onload = () => resolve()
      script.onerror = () => reject(new Error('telegram_widget_load_failed'))
      document.head.appendChild(script)
    })
  }
  await telegramScriptPromise
}

function NavItem({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        clsx(
          'gmz-btn rounded-xl border bg-white px-4 py-2 text-left text-sm font-semibold transition',
          isActive
            ? 'border-[var(--accent)] bg-[#eaf3ff] text-[var(--accent)] shadow-[inset_0_0_0_1px_rgba(27,99,230,0.16)]'
            : 'border-[#c8d5ea] text-slate-700 hover:border-[#9fbef1]',
        )
      }
    >
      {label}
    </NavLink>
  )
}

export function AppShell() {
  const initialTelegramUser = readJson<{ id?: number; username?: string; first_name?: string; last_name?: string; photo_url?: string }>(LS_TELEGRAM_USER)
  const initialTonWallet = readJson<TonWalletInfo>(LS_TON_WALLET)
  const [tradeAllowed, setTradeAllowed] = useState(false)
  const [telegramUser, setTelegramUser] = useState<{ id?: number; username?: string; first_name?: string; last_name?: string; photo_url?: string } | null>(initialTelegramUser)
  const [telegramAuthEnabled, setTelegramAuthEnabled] = useState(false)
  const [telegramBotUsername, setTelegramBotUsername] = useState('')
  const [telegramAuthBusy, setTelegramAuthBusy] = useState(false)
  const [telegramAuthError, setTelegramAuthError] = useState('')
  const [tonConnected, setTonConnected] = useState(Boolean(initialTonWallet?.address))
  const [tonWallet, setTonWallet] = useState<TonWalletInfo | null>(initialTonWallet)
  const [tonConnecting, setTonConnecting] = useState(false)
  const [tonMenuOpen, setTonMenuOpen] = useState(false)
  const [tonBalance, setTonBalance] = useState<number | null>(null)
  const [tonBalanceLoading, setTonBalanceLoading] = useState(false)
  const [tonError, setTonError] = useState('')
  const [profileOpen, setProfileOpen] = useState(false)
  const [ownedLoading, setOwnedLoading] = useState(false)
  const [ownedGifts, setOwnedGifts] = useState<OwnedGiftItem[]>([])
  const [ownedSource, setOwnedSource] = useState('')
  const [ownedMessage, setOwnedMessage] = useState('')
  const tonUiRef = useRef<{
    wallet?: { account?: { address?: string; chain?: string; publicKey?: string; [key: string]: unknown } } | null
    connectionRestored?: Promise<unknown>
    connectWallet: (opts?: { tonProof?: string }) => Promise<{ account?: { address?: string; chain?: string; publicKey?: string; [key: string]: unknown }; connectItems?: { tonProof?: { proof?: Record<string, unknown> } } }>
    disconnect: () => Promise<void>
  } | null>(null)
  const telegramWidgetRef = useRef<HTMLDivElement | null>(null)
  const tonMenuRef = useRef<HTMLDivElement | null>(null)
  const profileMenuRef = useRef<HTMLDivElement | null>(null)

  const refreshTradeAccess = useCallback(async () => {
    try {
      const access = await getTradingAccess()
      setTradeAllowed(Boolean(access?.allowed))
      return access
    } catch {
      setTradeAllowed(false)
      return { allowed: false }
    }
  }, [])

  useEffect(() => {
    let stop = false
    ;(async () => {
      try {
        const [authRaw, tradeAccess] = await Promise.all([
          getTelegramAuthBootstrap().catch(() => ({ authenticated: false, user: null })),
          getTradingAccess().catch(() => ({ allowed: false })),
        ])
        const auth = authRaw && typeof authRaw === 'object' ? authRaw as { authenticated?: boolean; user?: { id?: number; username?: string; first_name?: string; last_name?: string; photo_url?: string } | null; enabled?: boolean; bot_username?: string } : {}
        if (!stop) setTradeAllowed(Boolean(tradeAccess?.allowed))
        if (!stop) {
          if (auth?.authenticated) {
            setTelegramUser(auth.user || null)
            writeJson(LS_TELEGRAM_USER, auth.user || null)
          } else {
            setTelegramUser(null)
            setProfileOpen(false)
            writeJson(LS_TELEGRAM_USER, null)
          }
          setTelegramAuthEnabled(Boolean(auth?.enabled))
          setTelegramBotUsername(String(auth?.bot_username || ''))
        }
      } catch {
        if (!stop) setTradeAllowed(false)
        if (!stop) {
          setTelegramAuthEnabled(false)
          setTelegramBotUsername('')
        }
      }
    })()
    return () => {
      stop = true
    }
  }, [])

  useEffect(() => {
    let stop = false
    const load = async () => {
      try {
        const [auth, tradeAccess] = await Promise.all([
          getTelegramAuthMe(),
          getTradingAccess().catch(() => ({ allowed: false })),
        ])
        if (!stop) {
          if (auth?.authenticated) {
            setTelegramUser(auth.user || null)
            writeJson(LS_TELEGRAM_USER, auth.user || null)
          } else {
            setTelegramUser(null)
            setProfileOpen(false)
            writeJson(LS_TELEGRAM_USER, null)
          }
        }
        if (!stop) setTradeAllowed(Boolean(tradeAccess?.allowed))
      } catch {
        // keep cached telegram user on transient failure
      }
    }
    void load()
    const timer = window.setInterval(() => { void load() }, 60000)
    return () => {
      stop = true
      window.clearInterval(timer)
    }
  }, [])

  const refreshTonMe = useCallback(async () => {
    try {
      const me = await getTonAuthMe()
      const connected = Boolean(me?.connected)
      if (connected) {
        setTonConnected(true)
        setTonWallet(me.wallet || null)
        writeJson(LS_TON_WALLET, me.wallet || null)
      } else {
        // Server-side TON session is authoritative. If it says the wallet is
        // disconnected, clear any stale cached wallet from previous sessions.
        setTonConnected(false)
        setTonWallet(null)
        setTonMenuOpen(false)
        setTonBalance(null)
        writeJson(LS_TON_WALLET, null)
      }
      setTonError('')
    } catch (e) {
      // keep cached TON wallet on transient failure
      setTonError(e instanceof Error ? e.message : 'ton_me_failed')
    }
  }, [])

  const refreshTonBalance = useCallback(async () => {
    if (!tonConnected || !tonWallet?.address || tonBalanceLoading) return
    setTonBalanceLoading(true)
    try {
      const payload = await getTonBalance()
      const amount = Number(payload?.ton_balance)
      setTonBalance(Number.isFinite(amount) ? amount : null)
    } catch {
      setTonBalance(null)
    } finally {
      setTonBalanceLoading(false)
    }
  }, [tonConnected, tonWallet?.address, tonBalanceLoading])

  const ensureTonUi = useCallback(async () => {
    await ensureTonConnectSdk()
    if (!window.TON_CONNECT_UI?.TonConnectUI) throw new Error('tonconnect_sdk_unavailable')
    if (!tonUiRef.current) {
        tonUiRef.current = new window.TON_CONNECT_UI.TonConnectUI({
          manifestUrl: `${window.location.origin}/tonconnect-manifest.json`,
          buttonRootId: TONCONNECT_BUTTON_ROOT_ID,
        })
      if (tonUiRef.current?.connectionRestored) {
        await tonUiRef.current.connectionRestored.catch(() => undefined)
      }
    }
    return tonUiRef.current
  }, [])

  const connectTon = useCallback(async () => {
    if (tonConnecting) return
    setTonConnecting(true)
    setTonError('')
    try {
      await getTonAuthConfig().catch(() => null)
      const ui = await ensureTonUi()
      const existingAccount = ui.wallet?.account || null
      if (existingAccount?.address && tonConnected && tonWallet?.address === existingAccount.address) {
        setTonMenuOpen(true)
        await refreshTonBalance()
        return
      }
      if (existingAccount?.address) {
        await ui.disconnect().catch(() => undefined)
        await postTonLogout().catch(() => undefined)
      }
      const challengePayload = await postTonChallenge()
      const challenge = String(challengePayload?.challenge || '').trim()
      if (!challenge) throw new Error('challenge_missing')
      let connected
      try {
        connected = await ui.connectWallet({ tonProof: challenge })
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e || '')
        if (msg.includes('wallet already connected')) {
          await ui.disconnect().catch(() => undefined)
          connected = await ui.connectWallet({ tonProof: challenge })
        } else {
          throw e
        }
      }
      const account = connected?.account || ui.wallet?.account || null
      if (!account?.address) throw new Error('ton_account_missing')
      const tonProof = connected?.connectItems?.tonProof?.proof || null
      await postTonVerify({
        account,
        ton_proof: tonProof,
      })
      await refreshTonMe()
      await refreshTradeAccess()
      setTonMenuOpen(true)
      await refreshTonBalance()
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'ton_connect_failed'
      setTonError(msg)
    } finally {
      setTonConnecting(false)
    }
  }, [ensureTonUi, refreshTonBalance, refreshTonMe, refreshTradeAccess, tonConnecting])

  const disconnectTon = useCallback(async () => {
    setTonConnecting(true)
    try {
      await postTonLogout()
      if (tonUiRef.current) {
        await tonUiRef.current.disconnect().catch(() => undefined)
      }
    } catch (e) {
      setTonError(e instanceof Error ? e.message : 'ton_logout_failed')
    } finally {
      setTonConnected(false)
      setTonWallet(null)
      setTonMenuOpen(false)
      setTonBalance(null)
      writeJson(LS_TON_WALLET, null)
      void refreshTradeAccess()
      setTonConnecting(false)
    }
  }, [refreshTradeAccess])

  useEffect(() => {
    void refreshTonMe()
    const timer = window.setInterval(() => {
      void refreshTonMe()
    }, 30000)
    return () => window.clearInterval(timer)
  }, [refreshTonMe])

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
    if (!telegramUser || !profileOpen) return
    void loadOwnedGifts()
  }, [telegramUser, profileOpen, loadOwnedGifts])

  useEffect(() => {
    if (!profileOpen || telegramUser || !telegramAuthEnabled || !telegramBotUsername || !telegramWidgetRef.current) return
    let mounted = true
    const mount = async () => {
      try {
        const initData = String(window.Telegram?.WebApp?.initData || '').trim()
        if (initData) {
          setTelegramAuthBusy(true)
          setTelegramAuthError('')
          try {
            window.Telegram?.WebApp?.ready?.()
            window.Telegram?.WebApp?.expand?.()
            await postTelegramWebAppVerify(initData)
            const auth = await getTelegramAuthBootstrap()
            if (mounted) {
              setTelegramUser(auth?.authenticated ? (auth.user || null) : null)
              writeJson(LS_TELEGRAM_USER, auth?.authenticated ? (auth.user || null) : null)
              void refreshTradeAccess()
            }
          } catch (e) {
            if (mounted) setTelegramAuthError(e instanceof Error ? e.message : 'telegram_webapp_auth_failed')
          } finally {
            if (mounted) setTelegramAuthBusy(false)
          }
          return
        }
        await ensureTelegramWidgetSdk()
        if (!mounted || !telegramWidgetRef.current) return
        telegramWidgetRef.current.innerHTML = ''
        window.gmzTelegramAuthShell = async (telegramUser: Record<string, unknown>) => {
          setTelegramAuthBusy(true)
          setTelegramAuthError('')
          try {
            await postTelegramAuthVerify(telegramUser)
            const auth = await getTelegramAuthBootstrap()
            if (mounted) {
              setTelegramUser(auth?.authenticated ? (auth.user || null) : null)
              writeJson(LS_TELEGRAM_USER, auth?.authenticated ? (auth.user || null) : null)
              void refreshTradeAccess()
            }
          } catch (e) {
            if (mounted) setTelegramAuthError(e instanceof Error ? e.message : 'telegram_auth_failed')
          } finally {
            if (mounted) setTelegramAuthBusy(false)
          }
        }
        const script = document.createElement('script')
        script.async = true
        script.src = TELEGRAM_WIDGET_SRC
        script.setAttribute('data-telegram-login', telegramBotUsername)
        script.setAttribute('data-size', 'large')
        script.setAttribute('data-radius', '14')
        script.setAttribute('data-request-access', 'write')
        script.setAttribute('data-userpic', 'false')
        script.setAttribute('data-onauth', 'gmzTelegramAuthShell(user)')
        script.setAttribute('data-auth-url', `${window.location.origin}/api/auth/telegram/callback?redirect_to=${encodeURIComponent(`${window.location.pathname}${window.location.search}${window.location.hash}` || '/')}`)
        telegramWidgetRef.current.appendChild(script)
      } catch (e) {
        if (mounted) setTelegramAuthError(e instanceof Error ? e.message : 'telegram_widget_failed')
      }
    }
    void mount()
    return () => {
      mounted = false
      window.gmzTelegramAuthShell = undefined
    }
  }, [profileOpen, telegramUser, telegramAuthEnabled, telegramBotUsername, refreshTradeAccess])

  useEffect(() => {
    if (!tonMenuOpen) return
    void refreshTonBalance()
  }, [tonMenuOpen, refreshTonBalance])

  useEffect(() => {
    if (!tonMenuOpen && !profileOpen) return
    const onPointerDown = (e: MouseEvent) => {
      const insideTon = tonMenuRef.current?.contains(e.target as Node)
      const insideProfile = profileMenuRef.current?.contains(e.target as Node)
      if (!insideTon) {
        setTonMenuOpen(false)
      }
      if (!insideProfile) {
        setProfileOpen(false)
      }
    }
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setTonMenuOpen(false)
        setProfileOpen(false)
      }
    }
    window.addEventListener('mousedown', onPointerDown)
    window.addEventListener('keydown', onEsc)
    return () => {
      window.removeEventListener('mousedown', onPointerDown)
      window.removeEventListener('keydown', onEsc)
    }
  }, [tonMenuOpen, profileOpen])

  const visibleNavItems = useMemo(
    () => navItems.filter((item) => !item.tradeOnly || tradeAllowed),
    [tradeAllowed],
  )

  return (
    <div className="min-h-screen bg-app-gradient text-slate-900">
      <header className="sticky top-0 z-50 border-b border-[#cfd9e9] bg-[rgba(244,248,255,0.84)] backdrop-blur">
        <div className="mx-auto flex max-w-[1680px] items-center justify-between gap-4 px-4 py-3 lg:px-6">
          <div className="flex items-center">
            <img
              src="/logo.png"
              alt=""
              aria-hidden="true"
              className="h-8 w-auto max-w-[320px] object-contain"
              onError={(e) => {
                e.currentTarget.onerror = null
                e.currentTarget.src = '/favicon.png'
              }}
            />
            <span className="sr-only">GiftMarketZone</span>
          </div>
          <div className="flex items-center gap-3">
            <div
              className="relative"
              ref={profileMenuRef}
            >
              <button
                type="button"
                className="gmz-btn flex items-center gap-2 rounded-xl border border-[#c8d5ea] bg-white px-4 py-2 text-sm font-semibold text-slate-700"
                onClick={() => setProfileOpen((s) => !s)}
              >
                {telegramUser?.photo_url ? (
                  <img src={String(telegramUser.photo_url)} alt="" className="h-5 w-5 rounded-full object-cover" referrerPolicy="no-referrer" />
                ) : (
                  <span aria-hidden="true" className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-[#eaf3ff] text-[10px] font-semibold text-[var(--accent)]">TG</span>
                )}
                <span>{telegramUser ? (telegramUser.username ? `@${telegramUser.username}` : (telegramUser.first_name || 'Профиль')) : 'Войти через Telegram'}</span>
              </button>
              {profileOpen ? (
                <div className="absolute right-0 top-[calc(100%+8px)] z-50 w-[360px] rounded-2xl border border-[var(--line)] bg-white/95 p-3 shadow-soft backdrop-blur">
                  {telegramUser ? (
                    <div className="space-y-3">
                      <div className="flex items-center gap-3">
                        {telegramUser.photo_url ? <img src={String(telegramUser.photo_url)} alt="" className="h-10 w-10 rounded-full object-cover" referrerPolicy="no-referrer" /> : <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#eaf3ff] text-sm font-semibold text-[var(--accent)]">TG</div>}
                        <div>
                          <div className="text-sm font-semibold text-slate-900">{[telegramUser.first_name, telegramUser.last_name].filter(Boolean).join(' ') || 'Telegram user'}</div>
                          <div className="text-xs text-slate-500">{telegramUser.username ? `@${telegramUser.username}` : 'Без username'} · ID {telegramUser.id ?? '—'}</div>
                        </div>
                      </div>
                      {ownedLoading ? <div className="text-xs text-slate-500">Загрузка подарков…</div> : ownedGifts.length ? (
                        <div className="space-y-2">
                          <div className="text-xs font-semibold text-slate-700">Подарки в наличии</div>
                          <div className="max-h-[220px] space-y-2 overflow-y-auto">
                            {ownedGifts.slice(0, 6).map((gift, idx) => (
                              <div key={String(gift.gift_id || gift.variant_id || idx)} className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white p-2">
                                <div className="h-12 w-12 overflow-hidden rounded-lg bg-slate-100">{gift.preview_url ? <img src={String(gift.preview_url)} alt="" className="h-full w-full object-cover" referrerPolicy="no-referrer" /> : null}</div>
                                <div className="min-w-0 flex-1">
                                  <div className="truncate text-xs font-semibold text-slate-900">{gift.variant_label || gift.collection || 'Gift'}</div>
                                  <div className="text-[11px] text-slate-500">Floor {fmtTon(gift.floor_ton)} · Fair {fmtTon(gift.fair_ton)}</div>
                                </div>
                                {gift.variant_id ? <Link to={`/variant/${encodeURIComponent(String(gift.variant_id))}`} className="text-[11px] font-semibold text-[var(--accent)] hover:underline">Открыть</Link> : null}
                              </div>
                            ))}
                          </div>
                          {ownedSource ? <div className="text-[11px] text-slate-400">source: {ownedSource}</div> : null}
                        </div>
                      ) : (
                        <div className="text-xs text-slate-500">{ownedMessage || 'Пока нет данных о подарках пользователя.'}</div>
                      )}
                      <div className="flex gap-2">
                        <button type="button" className="gmz-btn gmz-btn-ghost flex-1 px-3 py-2 text-sm" onClick={() => void loadOwnedGifts()} disabled={ownedLoading}>Обновить</button>
                        <button type="button" className="gmz-btn flex-1 rounded-xl border border-rose-200 bg-[#fff8f8] px-3 py-2 text-sm font-semibold text-rose-700" onClick={() => { void postTelegramLogout().then(async () => { setProfileOpen(false); await getTelegramAuthBootstrap().catch(() => ({ authenticated: false })); setTelegramUser(null); writeJson(LS_TELEGRAM_USER, null) }) }}>Выйти</button>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <div className="text-sm text-slate-600">Войдите через Telegram, чтобы видеть данные профиля и подарки.</div>
                      {telegramAuthEnabled ? <div ref={telegramWidgetRef} /> : <div className="text-xs text-amber-700">Telegram auth пока не настроен на backend.</div>}
                      {telegramAuthBusy ? <div className="text-xs text-slate-500">Проверяем подпись Telegram…</div> : null}
                      {telegramAuthError ? <div className="text-xs text-rose-600">{telegramAuthError}</div> : null}
                    </div>
                  )}
                </div>
              ) : null}
            </div>
            <div className="relative" ref={tonMenuRef}>
            <button
              type="button"
              className="gmz-btn gmz-btn-primary flex items-center gap-2 px-4 text-sm"
              onClick={() => {
                if (tonConnected) {
                  setTonMenuOpen((s) => !s)
                } else {
                  void connectTon()
                }
              }}
              disabled={tonConnecting}
            >
              <span>
                {tonConnecting ? 'Подключение TON...' : tonConnected ? shortTonAddress(tonWallet?.address) : 'Подключить TON'}
              </span>
              {tonConnected ? <span aria-hidden="true">▾</span> : null}
            </button>
            {tonConnected && tonMenuOpen ? (
              <div className="absolute right-0 top-[calc(100%+8px)] z-50 w-[300px] rounded-2xl border border-[var(--line)] bg-white/95 p-3 shadow-soft backdrop-blur">
                <div className="text-xs text-slate-500">Подключенный кошелек</div>
                <div className="mt-1 break-all text-sm font-semibold text-slate-900">{tonWallet?.address || '—'}</div>
                <div className="mt-2 grid gap-1 text-xs text-slate-600">
                  <div>Chain: {String(tonWallet?.chain || '—')}</div>
                  <div>Баланс: {tonBalanceLoading ? 'загрузка…' : formatTonBalance(tonBalance)}</div>
                  <div>Дата подключения: {formatConnectedAt(tonWallet)}</div>
                </div>
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    className="gmz-btn gmz-btn-ghost flex-1 px-3 py-2 text-sm"
                    onClick={() => void refreshTonBalance()}
                    disabled={tonBalanceLoading}
                  >
                    Обновить баланс
                  </button>
                  <button
                    type="button"
                    className="gmz-btn flex-1 rounded-xl border border-rose-200 bg-[#fff8f8] px-3 py-2 text-sm font-semibold text-rose-700"
                    onClick={() => void disconnectTon()}
                    disabled={tonConnecting}
                  >
                    Отключить
                  </button>
                </div>
              </div>
            ) : null}
            {tonError ? (
              <div className="mt-1 max-w-[320px] text-right text-[11px] text-rose-600">
                TON: {tonError}
              </div>
            ) : null}
            </div>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-[1680px] gap-4 px-3 py-4 lg:grid-cols-[240px_minmax(0,1fr)] lg:px-6">
        <div id={TONCONNECT_BUTTON_ROOT_ID} className="hidden" />
        <aside className="gmz-panel sticky top-[78px] hidden h-fit p-3 lg:block">
          <nav className="flex flex-col gap-2">
            {visibleNavItems.map((item) => (
              <NavItem key={item.to} to={item.to} label={item.label} />
            ))}
          </nav>
        </aside>

        <main className="min-w-0">
          <div>
            <Outlet />
          </div>
        </main>
      </div>

      <nav className="fixed inset-x-0 bottom-2 z-30 mx-auto flex max-w-[720px] items-center justify-between gap-2 rounded-2xl border border-[#c8d5ea] bg-[rgba(255,255,255,0.95)] p-2 shadow-soft lg:hidden">
        {visibleNavItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              clsx(
                'flex-1 rounded-xl px-2 py-2 text-center text-xs font-semibold transition',
                isActive ? 'bg-[#eaf3ff] text-[var(--accent)]' : 'text-slate-600',
              )
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
