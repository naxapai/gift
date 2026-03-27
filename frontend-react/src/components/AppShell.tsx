import { motion } from 'framer-motion'
import clsx from 'clsx'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { getAdminAccess, getTelegramAuthMe, getTonAuthConfig, getTonAuthMe, getTonBalance, postTonChallenge, postTonLogout, postTonVerify, type TonWalletInfo } from '../lib/api'

const navItems = [
  { to: '/', label: 'Обзор' },
  { to: '/catalog', label: 'Каталог' },
  { to: '/screeners', label: 'Скринеры' },
  { to: '/signals', label: 'Сигналы' },
  { to: '/listing', label: 'Листинг' },
  { to: '/favorites', label: 'Избранное' },
  { to: '/cabinet', label: 'Кабинет' },
  { to: '/admin', label: 'Админ', adminOnly: true },
  { to: '/settings', label: 'Настройки' },
]

const TONCONNECT_UI_SRC = 'https://unpkg.com/@tonconnect/ui@2.0.9/dist/tonconnect-ui.min.js'

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

let tonScriptPromise: Promise<void> | null = null

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
  const [adminAllowed, setAdminAllowed] = useState(false)
  const [telegramUser, setTelegramUser] = useState<{ id?: number; username?: string; first_name?: string; last_name?: string; photo_url?: string } | null>(null)
  const [tonConnected, setTonConnected] = useState(false)
  const [tonWallet, setTonWallet] = useState<TonWalletInfo | null>(null)
  const [tonConnecting, setTonConnecting] = useState(false)
  const [tonMenuOpen, setTonMenuOpen] = useState(false)
  const [tonBalance, setTonBalance] = useState<number | null>(null)
  const [tonBalanceLoading, setTonBalanceLoading] = useState(false)
  const [tonError, setTonError] = useState('')
  const tonUiRef = useRef<{
    wallet?: { account?: { address?: string; chain?: string; publicKey?: string; [key: string]: unknown } } | null
    connectionRestored?: Promise<unknown>
    connectWallet: (opts?: { tonProof?: string }) => Promise<{ account?: { address?: string; chain?: string; publicKey?: string; [key: string]: unknown }; connectItems?: { tonProof?: { proof?: Record<string, unknown> } } }>
    disconnect: () => Promise<void>
  } | null>(null)
  const tonMenuRef = useRef<HTMLDivElement | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    let stop = false
    ;(async () => {
      try {
        const [access, auth] = await Promise.all([getAdminAccess(), getTelegramAuthMe().catch(() => ({ authenticated: false, user: null }))])
        if (!stop) setAdminAllowed(Boolean(access?.is_admin))
        if (!stop) setTelegramUser(auth?.authenticated ? (auth.user || null) : null)
      } catch {
        if (!stop) setAdminAllowed(false)
        if (!stop) setTelegramUser(null)
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
        const auth = await getTelegramAuthMe()
        if (!stop) setTelegramUser(auth?.authenticated ? (auth.user || null) : null)
      } catch {
        if (!stop) setTelegramUser(null)
      }
    }
    void load()
    const timer = window.setInterval(() => { void load() }, 30000)
    return () => {
      stop = true
      window.clearInterval(timer)
    }
  }, [])

  const refreshTonMe = useCallback(async () => {
    try {
      const me = await getTonAuthMe()
      const connected = Boolean(me?.connected)
      setTonConnected(connected)
      setTonWallet(connected ? (me.wallet || null) : null)
      if (!connected) {
        setTonMenuOpen(false)
        setTonBalance(null)
      }
      setTonError('')
    } catch (e) {
      setTonConnected(false)
      setTonWallet(null)
      setTonMenuOpen(false)
      setTonBalance(null)
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
        buttonRootId: null,
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
      const challengePayload = await postTonChallenge()
      const challenge = String(challengePayload?.challenge || '').trim()
      if (!challenge) throw new Error('challenge_missing')
      const connected = await ui.connectWallet({ tonProof: challenge })
      const account = connected?.account || ui.wallet?.account || null
      if (!account?.address) throw new Error('ton_account_missing')
      const tonProof = connected?.connectItems?.tonProof?.proof || null
      await postTonVerify({
        account,
        ton_proof: tonProof,
      })
      await refreshTonMe()
      setTonMenuOpen(true)
      await refreshTonBalance()
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'ton_connect_failed'
      setTonError(msg)
    } finally {
      setTonConnecting(false)
    }
  }, [ensureTonUi, refreshTonBalance, refreshTonMe, tonConnecting])

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
      setTonConnecting(false)
    }
  }, [])

  useEffect(() => {
    void refreshTonMe()
    const timer = window.setInterval(() => {
      void refreshTonMe()
    }, 30000)
    return () => window.clearInterval(timer)
  }, [refreshTonMe])

  useEffect(() => {
    if (!tonMenuOpen) return
    void refreshTonBalance()
  }, [tonMenuOpen, refreshTonBalance])

  useEffect(() => {
    if (!tonMenuOpen) return
    const onPointerDown = (e: MouseEvent) => {
      if (!tonMenuRef.current) return
      if (!tonMenuRef.current.contains(e.target as Node)) {
        setTonMenuOpen(false)
      }
    }
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setTonMenuOpen(false)
    }
    window.addEventListener('mousedown', onPointerDown)
    window.addEventListener('keydown', onEsc)
    return () => {
      window.removeEventListener('mousedown', onPointerDown)
      window.removeEventListener('keydown', onEsc)
    }
  }, [tonMenuOpen])

  const visibleNavItems = useMemo(
    () => navItems.filter((item) => !item.adminOnly || adminAllowed),
    [adminAllowed],
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
            <button
              type="button"
              className="gmz-btn flex items-center gap-2 rounded-xl border border-[#c8d5ea] bg-white px-4 py-2 text-sm font-semibold text-slate-700"
              onClick={() => navigate('/cabinet')}
            >
              {telegramUser?.photo_url ? (
                <img src={String(telegramUser.photo_url)} alt="" className="h-5 w-5 rounded-full object-cover" referrerPolicy="no-referrer" />
              ) : (
                <span aria-hidden="true">✈️</span>
              )}
              <span>{telegramUser ? (telegramUser.username ? `@${telegramUser.username}` : (telegramUser.first_name || 'Кабинет')) : 'Войти через Telegram'}</span>
            </button>
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
        <aside className="gmz-panel sticky top-[78px] hidden h-fit p-3 lg:block">
          <nav className="flex flex-col gap-2">
            {visibleNavItems.map((item) => (
              <NavItem key={item.to} to={item.to} label={item.label} />
            ))}
          </nav>
        </aside>

        <main className="min-w-0">
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18 }}>
            <Outlet />
          </motion.div>
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
