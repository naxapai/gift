import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { BentoCard } from '../components/BentoCard'
import { GmzSelect } from '../components/GmzSelect'
import { BentoGrid } from '../components/BentoGrid'
import { DecisionTraceCard } from '../components/DecisionTraceCard'
import { LoadingBlock } from '../components/LoadingBlock'
import { MetricTile } from '../components/MetricTile'
import { PageHeader } from '../components/PageHeader'
import {
  getBuyQuote,
  getCollections,
  getTelegramAuthMe,
  getTonAuthMe,
  getTradesWorkspace,
  getTradingAccess,
  getVariants,
  postFastBuyConfirm,
  postRetryListIntent,
  postTradeIntent,
  postTradeIntentConfirm,
  resolveVariantByTraits,
  subscribePnlStream,
  subscribeTradesStream,
} from '../lib/api'
import type {
  AutoSellRule,
  CollectionItem,
  HoldingPro,
  PnlSummaryPro,
  PositionPro,
  TradeIntent,
  VariantItem,
  WalletActivityItem,
} from '../types/api'

const TONCONNECT_BUTTON_ROOT_ID = 'gmz-tonconnect-anchor'
type TradesUiIntent = TradeIntent & { optimistic?: boolean; failure_reason?: string | null }
type TradesWorkspace = Awaited<ReturnType<typeof getTradesWorkspace>>
type TradesStreamEvent = { event?: string; ts?: string; payload?: Record<string, unknown> }

function ton(v?: number | null): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return `${n.toFixed(2)} TON`
}

function readableTradeError(message: string): string {
  const raw = String(message || '')
  if (raw.includes('holding_not_found')) return 'Holding не найден для выбранного варианта.'
  if (raw.includes('holding_not_owned_for_list')) return 'Листинг доступен только для holding в статусе OWNED.'
  if (raw.includes('holding_not_listed')) return 'Отмена листинга доступна только для LISTED holding.'
  if (raw.includes('holding_not_sellable')) return 'Продажа доступна только для OWNED или LISTED holding.'
  if (raw.includes('holding_not_transferable')) return 'TRANSFER доступен только для OWNED holding.'
  if (raw.includes('list_intent_already_pending')) return 'Уже есть pending LIST intent для этого варианта.'
  if (raw.includes('cancel_listing_already_pending')) return 'Уже есть pending CANCEL_LISTING intent для этого варианта.'
  if (raw.includes('sell_intent_already_pending')) return 'Уже есть pending SELL intent для этого варианта.'
  if (raw.includes('transfer_intent_already_pending')) return 'Уже есть pending TRANSFER intent для этого варианта.'
  if (raw.includes('list_price_required')) return 'Укажите цену листинга.'
  if (raw.includes('transfer_target_required')) return 'Укажите Telegram user id или username для TRANSFER.'
  if (raw.includes('wallet_tx_payload_mismatch')) return 'Кошелек подписал не тот payload. Повторите операцию.'
  if (raw.includes('TON wallet was not connected')) return 'Подключите TON wallet перед отправкой транзакции.'
  return raw || 'Не удалось выполнить торговую операцию.'
}

function timelineSteps(value: unknown): Array<{ status: string; ts: string; source?: string; reason?: string }> {
  if (!Array.isArray(value)) return []
  return value
    .filter((x) => x && typeof x === 'object')
    .map((x) => {
      const row = x as Record<string, unknown>
      return {
        status: String(row.status || '—'),
        ts: String(row.ts || ''),
        source: row.source ? String(row.source) : undefined,
        reason: row.reason ? String(row.reason) : undefined,
      }
    })
}

function stableJson(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map((item) => stableJson(item)).join(',')}]`
  const row = value as Record<string, unknown>
  return `{${Object.keys(row).sort().map((key) => `${JSON.stringify(key)}:${stableJson(row[key])}`).join(',')}}`
}

async function walletTxHash(walletTx: Record<string, unknown>): Promise<string> {
  const raw = stableJson(walletTx || {})
  const bytes = new TextEncoder().encode(raw)
  const digest = await window.crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('')
}

async function sendTonWalletTx(walletTx: Record<string, unknown>): Promise<{ txHash: string; payloadHash: string }> {
  const payloadHash = await walletTxHash(walletTx)
  const uiCtor = window.TON_CONNECT_UI?.TonConnectUI
  if (!uiCtor) {
    return { txHash: `sim_${Date.now()}`, payloadHash }
  }
  const ui = new uiCtor({ manifestUrl: `${window.location.origin}/tonconnect-manifest.json`, buttonRootId: TONCONNECT_BUTTON_ROOT_ID })
  if (ui.connectionRestored) {
    await ui.connectionRestored.catch(() => undefined)
  }
  if (!ui.wallet?.account?.address) {
    throw new Error('TON wallet was not connected')
  }
  const res = await ui.sendTransaction(walletTx as { validUntil: number; messages: Array<{ address: string; amount: string; payload?: string; stateInit?: string }> })
  const txHash = String((res && (res.transactionHash || res.boc)) || `sim_${Date.now()}`)
  return { txHash, payloadHash }
}

export function TradesPage() {
  const openTonConnect = useCallback(() => {
    const root = document.getElementById(TONCONNECT_BUTTON_ROOT_ID)
    root?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    const button = root?.querySelector('button') as HTMLButtonElement | null
    button?.click()
  }, [])

  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [toast, setToast] = useState('')
  const [telegramUserId, setTelegramUserId] = useState('')
  const [walletAddress, setWalletAddress] = useState('')
  const [allowed, setAllowed] = useState(false)
  const [walletResolved, setWalletResolved] = useState(false)
  const [pnl, setPnl] = useState<PnlSummaryPro | null>(null)
  const [positions, setPositions] = useState<PositionPro[]>([])
  const [holdings, setHoldings] = useState<HoldingPro[]>([])
  const [history, setHistory] = useState<TradeIntent[]>([])
  const [activity, setActivity] = useState<WalletActivityItem[]>([])
  const [rules, setRules] = useState<AutoSellRule[]>([])
  const [variantId, setVariantId] = useState('')
  const [collections, setCollections] = useState<CollectionItem[]>([])
  const [tradeVariants, setTradeVariants] = useState<VariantItem[]>([])
  const [selectorLoading, setSelectorLoading] = useState(false)
  const [selectedCollectionId, setSelectedCollectionId] = useState('')
  const [selectedModel, setSelectedModel] = useState('')
  const [selectedBackground, setSelectedBackground] = useState('')
  const [selectedPattern, setSelectedPattern] = useState('')
  const [maxPriceTon, setMaxPriceTon] = useState('')
  const [slippageBps, setSlippageBps] = useState('100')
  const [buyAndListPriceTon, setBuyAndListPriceTon] = useState('')
  const [creating, setCreating] = useState(false)
  const [actionBusyId, setActionBusyId] = useState('')
  const [optimisticHistory, setOptimisticHistory] = useState<TradesUiIntent[]>([])
  const [expandedIntentId, setExpandedIntentId] = useState('')
  const [expandedPositionId, setExpandedPositionId] = useState('')
  const [expandedHoldingId, setExpandedHoldingId] = useState('')
  const [holdingDrafts, setHoldingDrafts] = useState<Record<string, { listPriceTon: string; transferUserId: string }>>({})
  const [mobileActionHoldingId, setMobileActionHoldingId] = useState('')
  const seenSseKeysRef = useRef<Map<string, number>>(new Map())
  const sseRefreshTimerRef = useRef<number | null>(null)

  const applyWorkspace = useCallback((workspace: TradesWorkspace) => {
    setPnl(workspace.pnl || null)
    setPositions(Array.isArray(workspace.positions) ? workspace.positions : [])
    setHoldings(Array.isArray(workspace.holdings) ? workspace.holdings : [])
    setHistory(Array.isArray(workspace.history) ? workspace.history : [])
    setActivity(Array.isArray(workspace.wallet_activity) ? workspace.wallet_activity : [])
    setRules(Array.isArray(workspace.autosell_rules) ? workspace.autosell_rules : [])
  }, [])

  const clearWorkspace = useCallback(() => {
    setPnl(null)
    setPositions([])
    setHoldings([])
    setHistory([])
    setActivity([])
    setRules([])
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const [auth, tonAuth, access] = await Promise.all([
        getTelegramAuthMe(),
        getTonAuthMe(),
        getTradingAccess(),
      ])
      setTelegramUserId(String(auth.user?.id || ''))
      const wa = String(tonAuth.wallet?.address || access.wallet_address || '')
      setWalletAddress(wa)
      const isAllowed = Boolean(access.allowed)
      setAllowed(isAllowed)
      setWalletResolved(true)
      if (!isAllowed || !wa) {
        clearWorkspace()
        return
      }
      const workspace = await getTradesWorkspace(wa)
      applyWorkspace(workspace)
    } catch (e) {
      setWalletResolved(true)
      setLoadError(e instanceof Error ? e.message : 'trades_load_failed')
    } finally {
      setLoading(false)
    }
  }, [applyWorkspace, clearWorkspace])

  const refreshWorkspace = useCallback(async () => {
    if (!walletAddress) return
    try {
      const workspace = await getTradesWorkspace(walletAddress)
      applyWorkspace(workspace)
      setLoadError('')
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'trades_workspace_refresh_failed')
    }
  }, [applyWorkspace, walletAddress])

  const scheduleSseRefresh = useCallback((event?: TradesStreamEvent) => {
    const payload = event?.payload && typeof event.payload === 'object' ? event.payload : {}
    const id = String(
      payload.intent_id ||
      payload.position_id ||
      payload.holding_id ||
      payload.activity_id ||
      payload.rule_id ||
      payload.tx_hash ||
      '',
    )
    const key = id ? `${event?.event || 'event'}:${id}` : ''
    const now = Date.now()
    for (const [seenKey, seenAt] of seenSseKeysRef.current) {
      if (now - seenAt > 60000) seenSseKeysRef.current.delete(seenKey)
    }
    if (key) {
      if (seenSseKeysRef.current.has(key)) return
      seenSseKeysRef.current.set(key, now)
    }
    if (sseRefreshTimerRef.current) window.clearTimeout(sseRefreshTimerRef.current)
    sseRefreshTimerRef.current = window.setTimeout(() => {
      sseRefreshTimerRef.current = null
      void refreshWorkspace()
    }, 150)
  }, [refreshWorkspace])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!allowed) return
    let cancelled = false
    const run = async () => {
      setSelectorLoading(true)
      try {
        const [collectionsPayload, variantsPayload] = await Promise.all([
          getCollections(1000).catch(() => []),
          getVariants({ sort: 'score_desc', cap: 5000 }).catch(() => []),
        ])
        if (cancelled) return
        setCollections(Array.isArray(collectionsPayload) ? collectionsPayload : [])
        setTradeVariants(Array.isArray(variantsPayload) ? variantsPayload : [])
      } finally {
        if (!cancelled) setSelectorLoading(false)
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [allowed])

  useEffect(() => {
    if (!selectedCollectionId || !selectedModel) {
      setVariantId('')
      return
    }
    let cancelled = false
    const run = async () => {
      try {
        const resolved = await resolveVariantByTraits({
          collectionId: selectedCollectionId,
          model: selectedModel,
          background: selectedBackground || undefined,
          pattern: selectedPattern || undefined,
          activeOnly: false,
          mode: 'tz',
        })
        if (!cancelled) setVariantId(String(resolved?.variant_id || '').trim())
      } catch {
        if (!cancelled) setVariantId('')
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [selectedCollectionId, selectedModel, selectedBackground, selectedPattern])

  useEffect(() => {
    if (!allowed || !walletAddress) return
    let stopped = false
    let retryTimer: number | null = null
    let tradesEs: EventSource | null = null
    let pnlEs: EventSource | null = null
    const reconnectSteps = [1000, 2000, 5000, 10000, 30000]
    let retryIndex = 0
    let disconnectedAt = 0
    const closeAll = () => {
      tradesEs?.close()
      pnlEs?.close()
      tradesEs = null
      pnlEs = null
    }
    const connect = () => {
      closeAll()
      tradesEs = subscribeTradesStream(walletAddress, (event) => {
        retryIndex = 0
        disconnectedAt = 0
        scheduleSseRefresh(event)
      }, () => {
        closeAll()
        if (stopped) return
        if (!disconnectedAt) disconnectedAt = Date.now()
        const delay = reconnectSteps[Math.min(retryIndex, reconnectSteps.length - 1)]
        retryIndex += 1
        if (retryTimer) window.clearTimeout(retryTimer)
        retryTimer = window.setTimeout(() => {
          if ((Date.now() - disconnectedAt) > 60000) void refreshWorkspace()
          connect()
        }, delay)
      })
      pnlEs = subscribePnlStream(walletAddress, (event) => {
        retryIndex = 0
        disconnectedAt = 0
        scheduleSseRefresh(event)
      }, () => {
        closeAll()
        if (stopped) return
        if (!disconnectedAt) disconnectedAt = Date.now()
        const delay = reconnectSteps[Math.min(retryIndex, reconnectSteps.length - 1)]
        retryIndex += 1
        if (retryTimer) window.clearTimeout(retryTimer)
        retryTimer = window.setTimeout(() => {
          if ((Date.now() - disconnectedAt) > 60000) void refreshWorkspace()
          connect()
        }, delay)
      })
    }
    connect()
    return () => {
      stopped = true
      closeAll()
      if (retryTimer) window.clearTimeout(retryTimer)
      if (sseRefreshTimerRef.current) window.clearTimeout(sseRefreshTimerRef.current)
      sseRefreshTimerRef.current = null
      seenSseKeysRef.current.clear()
    }
  }, [allowed, walletAddress, refreshWorkspace, scheduleSseRefresh])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(''), 4200)
    return () => window.clearTimeout(timer)
  }, [toast])

  useEffect(() => {
    if (!mobileActionHoldingId) return
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMobileActionHoldingId('')
    }
    window.addEventListener('keydown', onEsc)
    return () => window.removeEventListener('keydown', onEsc)
  }, [mobileActionHoldingId])

  const createBuy = useCallback(async (intentType: 'BUY' | 'BUY_AND_LIST' | 'FAST_BUY') => {
    if (!walletAddress || !variantId.trim()) return
    setCreating(true)
    setToast('')
    let optimisticId = ''
    try {
      optimisticId = `optimistic_${Date.now()}`
      setOptimisticHistory((prev) => [
        {
          intent_id: optimisticId,
          intent_type: intentType === 'FAST_BUY' ? 'BUY' : intentType,
          variant_id: variantId.trim(),
          wallet_address: walletAddress,
          status: 'PENDING_SIGNATURE',
          created_at: new Date().toISOString(),
          expires_at: new Date(Date.now() + 600000).toISOString(),
          source: intentType === 'FAST_BUY' ? 'FAST_BUY' : 'STANDARD',
          optimistic: true,
        },
        ...prev,
      ].slice(0, 30))
      if (intentType === 'FAST_BUY') {
        const quote = await getBuyQuote({ variantId: variantId.trim(), maxPriceTon: Number(maxPriceTon || 0), slippageBps: Number(slippageBps || 100), walletAddress })
        const tx = await sendTonWalletTx((quote as unknown as { wallet_tx?: Record<string, unknown> }).wallet_tx || {})
        await postFastBuyConfirm({ buy_quote_token: quote.buy_quote_token, tx_hash: tx.txHash, wallet_address: walletAddress, client_meta: { payload_hash: tx.payloadHash } })
      } else {
        const payload: Record<string, unknown> = {
          intent_type: intentType,
          variant_id: variantId.trim(),
          wallet_address: walletAddress,
          max_spend_ton: Number(maxPriceTon || 0),
          chain_policy: intentType === 'BUY_AND_LIST' ? 'BUY_THEN_LIST' : 'MANUAL',
        }
        if (intentType === 'BUY_AND_LIST') {
          payload.post_action = { type: 'LIST', listing_params: { list_price_ton: Number(buyAndListPriceTon || Number(maxPriceTon || 0) * 1.1), duration_sec: 86400, marketplace: 'fragment' } }
        }
        const created = await postTradeIntent(payload)
        const tx = await sendTonWalletTx(created.wallet_tx || {})
        await postTradeIntentConfirm(created.intent.intent_id, { tx_hash: tx.txHash, wallet_address: walletAddress, signature_meta: { payload_hash: tx.payloadHash } })
      }
      setVariantId('')
      setMaxPriceTon('')
      setBuyAndListPriceTon('')
      await load()
      setOptimisticHistory((prev) => prev.filter((row) => row.intent_id !== optimisticId))
    } catch (e) {
      const message = readableTradeError(e instanceof Error ? e.message : 'trade_create_failed')
      setToast(message)
      setOptimisticHistory((prev) => prev.map((row) => row.intent_id === optimisticId ? { ...row, status: 'FAILED', failure_reason: message } : row))
    } finally {
      setCreating(false)
    }
  }, [walletAddress, variantId, maxPriceTon, slippageBps, buyAndListPriceTon, load])

  const runHoldingAction = useCallback(async (holding: HoldingPro, action: 'LIST' | 'CANCEL_LISTING' | 'SELL' | 'TRANSFER') => {
    if (!walletAddress) return
    setActionBusyId(`${holding.holding_id}:${action}`)
    setToast('')
    try {
      const draft = holdingDrafts[holding.holding_id] || { listPriceTon: '', transferUserId: '' }
      const payload: Record<string, unknown> = {
        intent_type: action,
        variant_id: holding.variant_id,
        wallet_address: walletAddress,
        gift_unique_id: holding.gift_unique_id,
        price_ton: holding.listed_price_ton || holding.acquired_price_ton,
      }
      if (action === 'LIST') {
        const listPriceTon = Number(draft.listPriceTon || Number((holding.acquired_price_ton || 0) * 1.12))
        payload.post_action = { type: 'LIST', listing_params: { list_price_ton: listPriceTon, duration_sec: 86400, marketplace: 'fragment' } }
      }
      if (action === 'TRANSFER') {
        payload.transfer_params = { telegram_user_id: String(draft.transferUserId || '144832201') }
      }
      const created = await postTradeIntent(payload)
      const tx = await sendTonWalletTx(created.wallet_tx || {})
      await postTradeIntentConfirm(created.intent.intent_id, { tx_hash: tx.txHash, wallet_address: walletAddress, signature_meta: { payload_hash: tx.payloadHash } })
      await load()
    } catch (e) {
      setToast(readableTradeError(e instanceof Error ? e.message : 'holding_action_failed'))
    } finally {
      setActionBusyId('')
      setMobileActionHoldingId('')
    }
  }, [walletAddress, load, holdingDrafts])

  const updateHoldingDraft = useCallback((holdingId: string, patch: Partial<{ listPriceTon: string; transferUserId: string }>) => {
    setHoldingDrafts((prev) => ({
      ...prev,
      [holdingId]: {
        listPriceTon: prev[holdingId]?.listPriceTon || '',
        transferUserId: prev[holdingId]?.transferUserId || '',
        ...patch,
      },
    }))
  }, [])

  const retryChildList = useCallback(async (parentIntentId: string) => {
    setActionBusyId(`retry:${parentIntentId}`)
    setToast('')
    try {
      await postRetryListIntent(parentIntentId)
      await load()
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'retry_list_failed')
    } finally {
      setActionBusyId('')
    }
  }, [load])

  const collectionOptions = useMemo(() => (collections || []).map((row) => ({
    value: String(row.collection_id || ''),
    label: String(row.name || row.collection_id || ''),
  })).filter((row) => row.value && row.label), [collections])

  const collectionVariants = useMemo(() => (
    (tradeVariants || []).filter((row) => !selectedCollectionId || String(row.collection_id || '') === selectedCollectionId)
  ), [tradeVariants, selectedCollectionId])

  const modelOptions = useMemo(() => Array.from(new Set(
    collectionVariants.map((row) => String(row.model || '').trim()).filter(Boolean),
  )).map((value) => ({ value, label: value })), [collectionVariants])

  const backgroundOptions = useMemo(() => Array.from(new Set(
    collectionVariants
      .filter((row) => !selectedModel || String(row.model || '').trim() === selectedModel)
      .map((row) => String(row.background || '').trim())
      .filter(Boolean),
  )).map((value) => ({ value, label: value })), [collectionVariants, selectedModel])

  const patternOptions = useMemo(() => Array.from(new Set(
    collectionVariants
      .filter((row) => (!selectedModel || String(row.model || '').trim() === selectedModel) && (!selectedBackground || String(row.background || '').trim() === selectedBackground))
      .map((row) => String(row.pattern || '').trim())
      .filter(Boolean),
  )).map((value) => ({ value, label: value })), [collectionVariants, selectedModel, selectedBackground])

  const selectedVariantLabel = useMemo(() => {
    if (!variantId) return ''
    const row = (tradeVariants || []).find((item) => String(item.variant_id || '') === variantId)
    if (!row) return variantId
    return [row.collection_name, row.model, row.background, row.pattern].filter(Boolean).join(' • ') || variantId
  }, [tradeVariants, variantId])

  const policyText = useMemo(() => 'Variant A only: BUY -> CONFIRMED -> LIST. FAST BUY enabled. Backend never stores private keys.', [])
  const mergedHistory = useMemo<TradesUiIntent[]>(() => {
    const items = [...optimisticHistory, ...history]
    const seen = new Set<string>()
    return items.filter((row) => {
      const key = String(row.intent_id || '')
      if (!key || seen.has(key)) return false
      seen.add(key)
      return true
    }) as TradesUiIntent[]
  }, [history, optimisticHistory])

  const walletStatePending = loading || !walletResolved
  const mobileActionHolding = useMemo(
    () => holdings.find((row) => row.holding_id === mobileActionHoldingId) || null,
    [holdings, mobileActionHoldingId],
  )

  const renderHoldingActions = useCallback((row: HoldingPro, compact = false) => {
    const busy = actionBusyId.startsWith(`${row.holding_id}:`)
    return (
      <div className={compact ? 'space-y-2' : 'flex flex-wrap gap-2 py-2'}>
        {row.status === 'OWNED' ? <button type="button" className="gmz-btn px-3 py-1 text-xs" disabled={busy || walletStatePending} onClick={() => { void runHoldingAction(row, 'LIST') }}>LIST</button> : null}
        {row.status === 'LISTED' ? <button type="button" className="gmz-btn px-3 py-1 text-xs" disabled={busy || walletStatePending} onClick={() => { void runHoldingAction(row, 'CANCEL_LISTING') }}>CANCEL</button> : null}
        {row.status === 'OWNED' ? <button type="button" className="gmz-btn px-3 py-1 text-xs" disabled={busy || walletStatePending} onClick={() => { void runHoldingAction(row, 'SELL') }}>SELL</button> : null}
        {row.status === 'OWNED' ? <button type="button" className="gmz-btn px-3 py-1 text-xs" disabled={busy || walletStatePending} onClick={() => { void runHoldingAction(row, 'TRANSFER') }}>TRANSFER</button> : null}
        {busy ? <div className="text-xs text-slate-500">{compact ? 'Операция выполняется…' : 'pending…'}</div> : null}
      </div>
    )
  }, [actionBusyId, runHoldingAction, walletStatePending])

  return (
    <section>
      <PageHeader title="Сделки" subtitle="PRO Trading workspace: intents, holdings, positions, wallet activity, Fast Buy, Variant A BUY+LIST" />
      {!allowed ? (
        <BentoCard title="Доступ ограничен">
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-4 text-sm text-amber-800">
            Тестовый trading module сейчас доступен только для Telegram account `144832201`.
            <div className="mt-2 text-xs">Ваш Telegram user id: {telegramUserId || 'не авторизован'}; wallet: {walletAddress || 'не подключен'}</div>
          </div>
        </BentoCard>
      ) : !walletAddress ? (
        <BentoCard title="Подключите кошелек">
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-4 text-sm text-amber-800">
            <div>Для покупки и продажи подарков нужен подключенный TON wallet.</div>
            <button type="button" className="gmz-btn gmz-btn-primary mt-3 px-4 py-2 text-sm" onClick={openTonConnect}>Подключить TON wallet</button>
          </div>
        </BentoCard>
      ) : loading ? (
        <LoadingBlock />
      ) : (
        <BentoGrid>
          {loadError ? (
            <BentoCard title="Ошибка загрузки" className="xl:col-span-12">
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-4 text-sm text-rose-700">
                <div>{loadError}</div>
                <button type="button" className="gmz-btn gmz-btn-primary px-4 py-2 text-sm" onClick={() => { void load() }}>Повторить</button>
              </div>
            </BentoCard>
          ) : null}

          <BentoCard title="Policy" className="xl:col-span-12">
            <div className="text-sm text-slate-700">{policyText}</div>
          </BentoCard>

          <BentoCard title="Fast Buy / Buy / Buy+List" className="xl:col-span-12">
            <div className="grid gap-3 md:grid-cols-4">
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-slate-700">Коллекция</span>
                <GmzSelect
                  value={selectedCollectionId}
                  onChange={(value) => {
                    setSelectedCollectionId(value)
                    setSelectedModel('')
                    setSelectedBackground('')
                    setSelectedPattern('')
                    setVariantId('')
                  }}
                  options={collectionOptions}
                  placeholder={selectorLoading ? 'Загрузка…' : 'Выберите коллекцию'}
                  disabled={selectorLoading || walletStatePending}
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-slate-700">Модель</span>
                <GmzSelect
                  value={selectedModel}
                  onChange={(value) => {
                    setSelectedModel(value)
                    setSelectedBackground('')
                    setSelectedPattern('')
                    setVariantId('')
                  }}
                  options={modelOptions}
                  placeholder="Выберите модель"
                  disabled={selectorLoading || walletStatePending || !selectedCollectionId}
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-slate-700">Фон</span>
                <GmzSelect
                  value={selectedBackground}
                  onChange={(value) => {
                    setSelectedBackground(value)
                    setSelectedPattern('')
                    setVariantId('')
                  }}
                  options={backgroundOptions}
                  placeholder="Выберите фон"
                  disabled={selectorLoading || walletStatePending || !selectedCollectionId || !selectedModel}
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-slate-700">Узор</span>
                <GmzSelect
                  value={selectedPattern}
                  onChange={(value) => {
                    setSelectedPattern(value)
                    setVariantId('')
                  }}
                  options={patternOptions}
                  placeholder="Выберите узор"
                  disabled={selectorLoading || walletStatePending || !selectedCollectionId || !selectedModel}
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-slate-700">Выбранный variant_id</span>
                <input value={variantId} readOnly placeholder="variant_id будет выбран автоматически" className="gmz-input bg-slate-50" />
              </label>
              <label className="block md:col-span-3">
                <span className="mb-1 block text-sm font-medium text-slate-700">Вариант</span>
                <input value={selectedVariantLabel} readOnly placeholder="Выберите коллекцию / модель / фон / узор" className="gmz-input bg-slate-50" />
              </label>
              <input value={maxPriceTon} onChange={(e) => setMaxPriceTon(e.target.value)} placeholder="max price TON" className="gmz-input" disabled={walletStatePending} />
              <input value={slippageBps} onChange={(e) => setSlippageBps(e.target.value)} placeholder="slippage bps" className="gmz-input" disabled={walletStatePending} />
              <input value={buyAndListPriceTon} onChange={(e) => setBuyAndListPriceTon(e.target.value)} placeholder="BUY+LIST price TON" className="gmz-input" disabled={walletStatePending} />
              <div className="flex flex-wrap gap-2">
                <button type="button" className="gmz-btn gmz-btn-primary px-4 py-2 text-sm" disabled={creating || !variantId || walletStatePending} onClick={() => { void createBuy('FAST_BUY') }}>FAST BUY</button>
                <button type="button" className="gmz-btn px-4 py-2 text-sm" disabled={creating || !variantId || walletStatePending} onClick={() => { void createBuy('BUY') }}>BUY</button>
                <button type="button" className="gmz-btn px-4 py-2 text-sm" disabled={creating || !variantId || walletStatePending} onClick={() => { void createBuy('BUY_AND_LIST') }}>BUY+LIST</button>
              </div>
            </div>
            <div className="mt-2 text-xs text-slate-500">Кнопка “Купить и выставить” создает 2 шага: BUY → CONFIRMED → LIST.</div>
          </BentoCard>

          <BentoCard title="PnL PRO" className="xl:col-span-12">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
              <MetricTile label="PnL today" value={ton(pnl?.pnl_today_ton)} />
              <MetricTile label="Exposure" value={ton(pnl?.exposure_ton)} />
              <MetricTile label="Win rate" value={`${Number(pnl?.win_rate || 0).toFixed(1)}%`} />
              <MetricTile label="Best trade" value={ton(pnl?.best_trade_ton)} />
              <MetricTile label="Regime" value={String(pnl?.market_regime || '—')} />
            </div>
          </BentoCard>

          <BentoCard title="Positions" className="xl:col-span-12">
            {!positions.length ? (
              <div className="mb-3 rounded-xl border border-dashed border-[var(--line)] bg-white/60 px-4 py-4 text-sm text-slate-600">
                Нет открытых позиций. <Link to="/catalog" className="font-semibold text-[var(--accent)] hover:underline">Откройте каталог</Link> и купите первый подарок.
              </div>
            ) : null}
            <div className="grid gap-3 md:hidden">
              {positions.map((row) => (
                <article key={row.position_id} className="rounded-2xl border border-[var(--line)] bg-white/75 p-4 text-sm shadow-soft">
                  <div className="flex items-center justify-between"><strong>{row.variant_id}</strong><span>{row.action || '—'}</span></div>
                  <div className="mt-2 grid gap-2 text-xs text-slate-600">
                    <div>Qty: {row.qty}</div>
                    <div>Avg buy: {ton(row.avg_buy_price_ton)}</div>
                    <div>Mark: {ton(row.mark_price_ton)}</div>
                    <div>UPnL: {ton(row.unrealized_pnl_ton)}</div>
                  </div>
                  {Array.isArray(row.reasons) && row.reasons.length ? <div className="mt-2 text-xs text-slate-500">Причины: {row.reasons.join(' • ')}</div> : null}
                  {Array.isArray(row.risk_flags) && row.risk_flags.length ? <div className="mt-2 text-xs text-slate-500">Риски: {row.risk_flags.join(' • ')}</div> : null}
                </article>
              ))}
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500"><th>Variant</th><th>Qty</th><th>Avg buy</th><th>Mark</th><th>UPnL</th><th>Action</th><th>Details</th></tr>
                </thead>
                <tbody>
                  {positions.map((row) => (
                    <>
                      <tr key={row.position_id} className="border-t border-slate-100">
                        <td className="py-2">{row.variant_id}</td>
                        <td>{row.qty}</td>
                        <td>{ton(row.avg_buy_price_ton)}</td>
                        <td>{ton(row.mark_price_ton)}</td>
                        <td>{ton(row.unrealized_pnl_ton)}</td>
                        <td>{row.action || '—'}</td>
                        <td><button type="button" className="gmz-btn px-3 py-1 text-xs" onClick={() => setExpandedPositionId((prev) => prev === row.position_id ? '' : row.position_id)}>{expandedPositionId === row.position_id ? 'Скрыть' : 'Детали'}</button></td>
                      </tr>
                      {expandedPositionId === row.position_id ? (
                        <tr className="bg-slate-50">
                          <td colSpan={7} className="px-3 py-3 text-xs text-slate-700">
                            <div><strong>reasons:</strong> {Array.isArray(row.reasons) && row.reasons.length ? row.reasons.join(' | ') : '—'}</div>
                            <div className="mt-1"><strong>risk_flags:</strong> {Array.isArray(row.risk_flags) && row.risk_flags.length ? row.risk_flags.join(' | ') : '—'}</div>
                            <div className="mt-2"><DecisionTraceCard trace={row.decision_trace} title="Decision Trace" /></div>
                          </td>
                        </tr>
                      ) : null}
                    </>
                  ))}
                </tbody>
              </table>
            </div>
          </BentoCard>

          <BentoCard title="Holdings" className="xl:col-span-12">
            {!holdings.length ? <div className="mb-3 rounded-xl border border-dashed border-[var(--line)] bg-white/60 px-4 py-4 text-sm text-slate-600">Нет holdings. После подтвержденной покупки подарок появится здесь. <Link to="/catalog" className="font-semibold text-[var(--accent)] hover:underline">Перейти в каталог</Link>.</div> : null}
            <div className="grid gap-3 md:hidden">
              {holdings.map((row) => (
                <article key={row.holding_id} className="rounded-2xl border border-[var(--line)] bg-white/75 p-4 text-sm shadow-soft">
                  <div className="flex items-center justify-between"><strong>{row.variant_id}</strong><span>{row.status}</span></div>
                  <div className="mt-2 grid gap-2 text-xs text-slate-600"><div>Gift: {row.gift_unique_id}</div><div>Acquired: {ton(row.acquired_price_ton)}</div><div>Listed: {ton(row.listed_price_ton)}</div></div>
                  {row.listing_meta ? <div className="mt-2 text-xs text-slate-500">Listing: {JSON.stringify(row.listing_meta)}</div> : null}
                  {row.transfer_meta ? <div className="mt-2 text-xs text-slate-500">Transfer: {JSON.stringify(row.transfer_meta)}</div> : null}
                  <div className="mt-3">
                    <button type="button" className="gmz-btn w-full px-3 py-2 text-xs" onClick={() => setMobileActionHoldingId(row.holding_id)}>Действия</button>
                  </div>
                </article>
              ))}
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500"><th>Gift</th><th>Variant</th><th>Status</th><th>Acquired</th><th>Listed</th><th>List price</th><th>Transfer</th><th>Meta</th><th>Actions</th><th>Details</th></tr>
                </thead>
                <tbody>
                  {holdings.map((row) => (
                    <>
                      <tr key={row.holding_id} className="border-t border-slate-100">
                        <td className="py-2">{row.gift_unique_id}</td>
                        <td>{row.variant_id}</td>
                        <td>{row.status}{actionBusyId.startsWith(`${row.holding_id}:`) ? <div className="text-xs text-slate-500">pending…</div> : null}</td>
                        <td>{ton(row.acquired_price_ton)}</td>
                        <td>{ton(row.listed_price_ton)}</td>
                        <td>{row.status === 'OWNED' ? <input value={holdingDrafts[row.holding_id]?.listPriceTon || ''} onChange={(e) => updateHoldingDraft(row.holding_id, { listPriceTon: e.target.value })} placeholder={String(Number((row.acquired_price_ton || 0) * 1.12).toFixed(2))} className="gmz-input text-xs" /> : '—'}</td>
                        <td>{row.status === 'OWNED' ? <input value={holdingDrafts[row.holding_id]?.transferUserId || ''} onChange={(e) => updateHoldingDraft(row.holding_id, { transferUserId: e.target.value })} placeholder="144832201" className="gmz-input text-xs" /> : '—'}</td>
                        <td className="max-w-[220px] py-2 text-xs text-slate-500">{row.listing_meta ? <div>Listing: {JSON.stringify(row.listing_meta)}</div> : null}{row.transfer_meta ? <div className="mt-1">Transfer: {JSON.stringify(row.transfer_meta)}</div> : null}{!row.listing_meta && !row.transfer_meta ? '—' : null}</td>
                        <td>{renderHoldingActions(row)}</td>
                        <td><button type="button" className="gmz-btn px-3 py-1 text-xs" onClick={() => setExpandedHoldingId((prev) => prev === row.holding_id ? '' : row.holding_id)}>{expandedHoldingId === row.holding_id ? 'Скрыть' : 'Детали'}</button></td>
                      </tr>
                      {expandedHoldingId === row.holding_id ? (
                        <tr className="bg-slate-50">
                          <td colSpan={10} className="px-3 py-3 text-xs text-slate-700">
                            <div><strong>listing_meta:</strong> <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded-lg bg-white p-2">{JSON.stringify(row.listing_meta || {}, null, 2)}</pre></div>
                            <div className="mt-2"><strong>transfer_meta:</strong> <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded-lg bg-white p-2">{JSON.stringify(row.transfer_meta || {}, null, 2)}</pre></div>
                          </td>
                        </tr>
                      ) : null}
                    </>
                  ))}
                </tbody>
              </table>
            </div>
          </BentoCard>

          <BentoCard title="History" className="xl:col-span-12">
            {!mergedHistory.length ? <div className="mb-3 rounded-xl border border-dashed border-[var(--line)] bg-white/60 px-4 py-4 text-sm text-slate-600">История сделок пуста. Создайте первый BUY или FAST BUY. <Link to="/catalog" className="font-semibold text-[var(--accent)] hover:underline">Выбрать подарок</Link>.</div> : null}
            <div className="grid gap-3 md:hidden">
              {mergedHistory.map((row) => (
                <article key={row.intent_id} className="rounded-2xl border border-[var(--line)] bg-white/75 p-4 text-sm shadow-soft">
                  <div className="flex items-center justify-between"><strong>{row.intent_type}</strong><span>{row.status}</span></div>
                  <div className="mt-2 text-xs text-slate-600">{row.variant_id}</div>
                  <div className="mt-1 text-xs text-slate-500">{new Date(row.created_at).toLocaleString('ru-RU')}</div>
                  {row.failure_reason ? <div className="mt-2 rounded-lg border border-rose-200 bg-rose-50 px-2 py-2 text-xs text-rose-700">{row.failure_reason}</div> : null}
                  <div className="mt-2 space-y-1 text-xs text-slate-600">
                    {timelineSteps((row as { status_timeline?: unknown }).status_timeline).map((step, idx) => (
                      <div key={`${row.intent_id}-step-${idx}`}>{step.status} · {step.ts ? new Date(step.ts).toLocaleString('ru-RU') : '—'}{step.reason ? ` · ${step.reason}` : ''}</div>
                    ))}
                  </div>
                  {(row.intent_type === 'BUY_AND_LIST' || (row.chain_policy === 'BUY_THEN_LIST' && !row.parent_intent_id)) ? <button type="button" className="gmz-btn mt-3 px-3 py-1 text-xs" disabled={actionBusyId === `retry:${row.intent_id}`} onClick={() => { void retryChildList(row.intent_id) }}>Повторить выставление</button> : null}
                </article>
              ))}
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500"><th>Intent</th><th>Type</th><th>Status</th><th>Variant</th><th>Created</th><th>Chain</th><th>Actions</th></tr>
                </thead>
                <tbody>
                  {mergedHistory.map((row) => (
                    <>
                      <tr key={row.intent_id} className="border-t border-slate-100 align-top">
                        <td className="py-2">{row.intent_id}</td>
                        <td>{row.intent_type}</td>
                        <td>{row.status}{row.failure_reason ? <div className="mt-1 text-xs text-rose-600">{row.failure_reason}</div> : null}</td>
                        <td>{row.variant_id}</td>
                        <td>{new Date(row.created_at).toLocaleString('ru-RU')}</td>
                        <td>{row.chain_id || '—'}{row.parent_intent_id ? <div className="text-xs text-slate-500">parent: {row.parent_intent_id}</div> : null}</td>
                        <td>
                          <button type="button" className="gmz-btn px-3 py-1 text-xs" onClick={() => setExpandedIntentId((prev) => prev === row.intent_id ? '' : row.intent_id)}>{expandedIntentId === row.intent_id ? 'Скрыть' : 'Детали'}</button>
                          {row.intent_type === 'BUY_AND_LIST' || (row.chain_policy === 'BUY_THEN_LIST' && !row.parent_intent_id) ? <button type="button" className="gmz-btn ml-2 px-3 py-1 text-xs" disabled={actionBusyId === `retry:${row.intent_id}`} onClick={() => { void retryChildList(row.intent_id) }}>Повторить выставление</button> : null}
                          <div className="mt-1 text-xs text-slate-500">{timelineSteps((row as { status_timeline?: unknown }).status_timeline).length ? `${timelineSteps((row as { status_timeline?: unknown }).status_timeline).length} steps` : 'timeline pending'}</div>
                        </td>
                      </tr>
                      {expandedIntentId === row.intent_id ? (
                        <tr className="bg-slate-50">
                          <td colSpan={7} className="px-3 py-3 text-xs text-slate-700">
                            <div><strong>reasons:</strong> {Array.isArray(row.reasons) && row.reasons.length ? row.reasons.join(' | ') : '—'}</div>
                            <div className="mt-1"><strong>risk_flags:</strong> {Array.isArray(row.risk_flags) && row.risk_flags.length ? row.risk_flags.join(' | ') : '—'}</div>
                            <div className="mt-1"><strong>status_timeline:</strong> <div className="mt-1 space-y-1">{timelineSteps((row as { status_timeline?: unknown }).status_timeline).map((step, idx) => <div key={`${row.intent_id}-timeline-${idx}`}>{step.status} · {step.ts ? new Date(step.ts).toLocaleString('ru-RU') : '—'}{step.source ? ` · ${step.source}` : ''}{step.reason ? ` · ${step.reason}` : ''}</div>)}</div></div>
                            {Array.isArray(row.executions) && row.executions.length ? <div className="mt-2"><strong>executions:</strong> <div className="mt-1 space-y-1">{row.executions.map((exec, idx) => <div key={`${row.intent_id}-exec-${idx}`}>{String(exec.result || '—')} · {String(exec.tx_hash || '—')}{exec.error_code ? ` · ${String(exec.error_code)}` : ''}</div>)}</div></div> : null}
                            {row.post_action ? <div className="mt-2"><strong>post_action:</strong> <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded-lg bg-white p-2">{JSON.stringify(row.post_action, null, 2)}</pre></div> : null}
                            {row.transfer_params ? <div className="mt-2"><strong>transfer_params:</strong> <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded-lg bg-white p-2">{JSON.stringify(row.transfer_params, null, 2)}</pre></div> : null}
                            <div className="mt-2"><strong>decision_trace:</strong> <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded-lg bg-white p-2">{JSON.stringify(row.decision_trace || {}, null, 2)}</pre></div>
                          </td>
                        </tr>
                      ) : null}
                    </>
                  ))}
                </tbody>
              </table>
            </div>
          </BentoCard>

          <BentoCard title="Wallet activity" className="xl:col-span-12">
            {!activity.length ? <div className="mb-3 rounded-xl border border-dashed border-[var(--line)] bg-white/60 px-4 py-4 text-sm text-slate-600">Активность кошелька пока пуста. После первой сделки здесь появятся списания и подтверждения.</div> : null}
            <div className="grid gap-3 md:hidden">
              {activity.map((row) => (
                <article key={`${row.tx_hash}-${row.ts}`} className="rounded-2xl border border-[var(--line)] bg-white/75 p-4 text-sm shadow-soft">
                  <div className="flex items-center justify-between"><strong>{row.direction}</strong><span>{ton(row.amount_ton)}</span></div>
                  <div className="mt-2 text-xs text-slate-600">{new Date(row.ts).toLocaleString('ru-RU')}</div>
                  <div className="mt-1 break-all text-xs text-slate-500">{row.tx_hash}</div>
                </article>
              ))}
            </div>
            <div className="hidden overflow-x-auto md:block">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500"><th>Time</th><th>Direction</th><th>Amount</th><th>Tx</th></tr>
                </thead>
                <tbody>
                  {activity.map((row) => (
                    <tr key={`${row.tx_hash}-${row.ts}`} className="border-t border-slate-100"><td className="py-2">{new Date(row.ts).toLocaleString('ru-RU')}</td><td>{row.direction}</td><td>{ton(row.amount_ton)}</td><td>{row.tx_hash}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </BentoCard>

          <BentoCard title="AutoSell rules" className="xl:col-span-12">
            <div className="text-sm text-slate-600">Активных правил: {rules.length}. Редактор доступен в разделе Настройки.</div>
          </BentoCard>
        </BentoGrid>
      )}

      {toast ? (
        <div className="gmz-toast" role="status" aria-live="polite">
          {toast}
        </div>
      ) : null}

      {mobileActionHolding ? (
        <>
          <button type="button" className="gmz-bottom-sheet-backdrop md:hidden" aria-label="Закрыть действия" onClick={() => setMobileActionHoldingId('')} />
          <div className="gmz-bottom-sheet md:hidden">
            <div className="gmz-bottom-sheet-handle" />
            <div className="mb-3">
              <div className="text-base font-semibold text-slate-900">Действия по holding</div>
              <div className="mt-1 text-xs text-slate-500">{mobileActionHolding.variant_id}</div>
            </div>
            {mobileActionHolding.status === 'OWNED' ? (
              <div className="space-y-2">
                <input value={holdingDrafts[mobileActionHolding.holding_id]?.listPriceTon || ''} onChange={(e) => updateHoldingDraft(mobileActionHolding.holding_id, { listPriceTon: e.target.value })} placeholder={String(Number((mobileActionHolding.acquired_price_ton || 0) * 1.12).toFixed(2))} className="gmz-input text-sm" />
                <input value={holdingDrafts[mobileActionHolding.holding_id]?.transferUserId || ''} onChange={(e) => updateHoldingDraft(mobileActionHolding.holding_id, { transferUserId: e.target.value })} placeholder="Telegram user id для TRANSFER" className="gmz-input text-sm" />
              </div>
            ) : null}
            <div className="mt-4">{renderHoldingActions(mobileActionHolding, true)}</div>
            <button type="button" className="gmz-btn mt-3 w-full px-4 py-2 text-sm" onClick={() => setMobileActionHoldingId('')}>Закрыть</button>
          </div>
        </>
      ) : null}
    </section>
  )
}
