import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { BentoCard } from '../components/BentoCard'
import { BentoGrid } from '../components/BentoGrid'
import { LoadingBlock } from '../components/LoadingBlock'
import { MetricTile } from '../components/MetricTile'
import { PageHeader } from '../components/PageHeader'
import { getAutoSellRules, getBuyQuote, getTelegramAuthMe, getTonAuthMe, getTradeHoldings, getTradeIntents, getTradePnl, getTradePositions, getTradingAccess, getWalletActivity, postFastBuyConfirm, postRetryListIntent, postTradeIntent, postTradeIntentConfirm, subscribePnlStream, subscribeTradesStream } from '../lib/api'
import type { AutoSellRule, HoldingPro, PositionPro, PnlSummaryPro, TradeIntent, WalletActivityItem } from '../types/api'

function ton(v?: number | null): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return `${n.toFixed(2)} TON`
}

async function walletTxHash(walletTx: Record<string, unknown>): Promise<string> {
  const raw = JSON.stringify(walletTx || {})
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
  const ui = new uiCtor({ manifestUrl: `${window.location.origin}/tonconnect-manifest.json`, buttonRootId: null })
  if (ui.connectionRestored) {
    await ui.connectionRestored.catch(() => undefined)
  }
  const res = await ui.sendTransaction(walletTx as { validUntil: number; messages: Array<{ address: string; amount: string; payload?: string; stateInit?: string }> })
  const txHash = String((res && (res.transactionHash || res.boc)) || `sim_${Date.now()}`)
  return { txHash, payloadHash }
}

export function TradesPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [telegramUserId, setTelegramUserId] = useState('')
  const [walletAddress, setWalletAddress] = useState('')
  const [allowed, setAllowed] = useState(false)
  const [pnl, setPnl] = useState<PnlSummaryPro | null>(null)
  const [positions, setPositions] = useState<PositionPro[]>([])
  const [holdings, setHoldings] = useState<HoldingPro[]>([])
  const [history, setHistory] = useState<TradeIntent[]>([])
  const [activity, setActivity] = useState<WalletActivityItem[]>([])
  const [rules, setRules] = useState<AutoSellRule[]>([])
  const [variantId, setVariantId] = useState('')
  const [maxPriceTon, setMaxPriceTon] = useState('')
  const [slippageBps, setSlippageBps] = useState('100')
  const [buyAndListPriceTon, setBuyAndListPriceTon] = useState('')
  const [creating, setCreating] = useState(false)
  const [actionBusyId, setActionBusyId] = useState('')
  const [optimisticHistory, setOptimisticHistory] = useState<TradeIntent[]>([])
  const [expandedIntentId, setExpandedIntentId] = useState('')
  const [holdingDrafts, setHoldingDrafts] = useState<Record<string, { listPriceTon: string; transferUserId: string }>>({})

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
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
      if (!isAllowed || !wa) {
        setPnl(null)
        setPositions([])
        setHoldings([])
        setHistory([])
        setActivity([])
        setRules([])
        return
      }
      const [nextPnl, nextPositions, nextHoldings, nextHistory, nextActivity, nextRules] = await Promise.all([
        getTradePnl(wa),
        getTradePositions(wa),
        getTradeHoldings(wa),
        getTradeIntents(wa),
        getWalletActivity(wa),
        getAutoSellRules(wa),
      ])
      setPnl(nextPnl)
      setPositions(nextPositions.items || [])
      setHoldings(nextHoldings.items || [])
      setHistory(nextHistory.items || [])
      setActivity(nextActivity.items || [])
      setRules(nextRules.items || [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'trades_load_failed')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

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
      tradesEs = subscribeTradesStream(walletAddress, () => {
        retryIndex = 0
        disconnectedAt = 0
        void load()
      }, () => {
        closeAll()
        if (stopped) return
        if (!disconnectedAt) disconnectedAt = Date.now()
        const delay = reconnectSteps[Math.min(retryIndex, reconnectSteps.length - 1)]
        retryIndex += 1
        if (retryTimer) window.clearTimeout(retryTimer)
        retryTimer = window.setTimeout(() => {
          if ((Date.now() - disconnectedAt) > 60000) void load()
          connect()
        }, delay)
      })
      pnlEs = subscribePnlStream(walletAddress, () => {
        retryIndex = 0
        disconnectedAt = 0
        void load()
      }, () => {
        closeAll()
        if (stopped) return
        if (!disconnectedAt) disconnectedAt = Date.now()
        const delay = reconnectSteps[Math.min(retryIndex, reconnectSteps.length - 1)]
        retryIndex += 1
        if (retryTimer) window.clearTimeout(retryTimer)
        retryTimer = window.setTimeout(() => {
          if ((Date.now() - disconnectedAt) > 60000) void load()
          connect()
        }, delay)
      })
    }
    connect()
    return () => {
      stopped = true
      closeAll()
      if (retryTimer) window.clearTimeout(retryTimer)
    }
  }, [allowed, walletAddress, load])

  const createBuy = useCallback(async (intentType: 'BUY' | 'BUY_AND_LIST' | 'FAST_BUY') => {
    if (!walletAddress || !variantId.trim()) return
    setCreating(true)
    setError('')
    try {
      const optimisticId = `optimistic_${Date.now()}`
      setOptimisticHistory((prev) => [{ intent_id: optimisticId, intent_type: intentType === 'FAST_BUY' ? 'BUY' : intentType, variant_id: variantId.trim(), wallet_address: walletAddress, status: 'PENDING_SIGNATURE', created_at: new Date().toISOString(), expires_at: new Date(Date.now() + 600000).toISOString(), source: intentType === 'FAST_BUY' ? 'FAST_BUY' : 'STANDARD' }, ...prev].slice(0, 30))
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
    } catch (e) {
      setError(e instanceof Error ? e.message : 'trade_create_failed')
    } finally {
      setOptimisticHistory([])
      setCreating(false)
    }
  }, [walletAddress, variantId, maxPriceTon, slippageBps, buyAndListPriceTon, load])

  const runHoldingAction = useCallback(async (holding: HoldingPro, action: 'LIST' | 'CANCEL_LISTING' | 'SELL' | 'TRANSFER') => {
    if (!walletAddress) return
    setActionBusyId(`${holding.holding_id}:${action}`)
    setError('')
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
      setError(e instanceof Error ? e.message : 'holding_action_failed')
    } finally {
      setActionBusyId('')
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
    setError('')
    try {
      await postRetryListIntent(parentIntentId)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'retry_list_failed')
    } finally {
      setActionBusyId('')
    }
  }, [load])

  const policyText = useMemo(() => 'Variant A only: BUY -> CONFIRMED -> LIST. FAST BUY enabled. Backend never stores private keys.', [])
  const mergedHistory = useMemo(() => {
    const items = [...optimisticHistory, ...history]
    const seen = new Set<string>()
    return items.filter((row) => {
      const key = String(row.intent_id || '')
      if (!key || seen.has(key)) return false
      seen.add(key)
      return true
    })
  }, [history, optimisticHistory])

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
            Для покупки и продажи подарков нужен подключенный TON wallet.
          </div>
        </BentoCard>
      ) : loading ? (
        <LoadingBlock />
      ) : (
        <BentoGrid>
          <BentoCard title="Policy" className="xl:col-span-12">
            <div className="text-sm text-slate-700">{policyText}</div>
          </BentoCard>
          <BentoCard title="Fast Buy / Buy / Buy+List" className="xl:col-span-12">
            <div className="grid gap-3 md:grid-cols-4">
              <input value={variantId} onChange={(e) => setVariantId(e.target.value)} placeholder="variant_id" className="gmz-input" />
              <input value={maxPriceTon} onChange={(e) => setMaxPriceTon(e.target.value)} placeholder="max price TON" className="gmz-input" />
              <input value={slippageBps} onChange={(e) => setSlippageBps(e.target.value)} placeholder="slippage bps" className="gmz-input" />
              <input value={buyAndListPriceTon} onChange={(e) => setBuyAndListPriceTon(e.target.value)} placeholder="BUY+LIST price TON" className="gmz-input" />
              <div className="flex flex-wrap gap-2">
                <button type="button" className="gmz-btn gmz-btn-primary px-4 py-2 text-sm" disabled={creating} onClick={() => { void createBuy('FAST_BUY') }}>FAST BUY</button>
                <button type="button" className="gmz-btn px-4 py-2 text-sm" disabled={creating} onClick={() => { void createBuy('BUY') }}>BUY</button>
                <button type="button" className="gmz-btn px-4 py-2 text-sm" disabled={creating} onClick={() => { void createBuy('BUY_AND_LIST') }}>BUY+LIST</button>
              </div>
            </div>
            <div className="mt-2 text-xs text-slate-500">Кнопка “Купить и выставить” создает 2 шага: BUY → CONFIRMED → LIST.</div>
            {error ? <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div> : null}
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
            {!positions.length ? <div className="mb-3 rounded-xl border border-dashed border-[var(--line)] bg-white/60 px-4 py-4 text-sm text-slate-600">Нет открытых позиций. <Link to="/catalog" className="font-semibold text-[var(--accent)] hover:underline">Откройте каталог</Link> и купите первый подарок.</div> : null}
            <div className="grid gap-3 md:hidden">
              {positions.map((row) => (
                <article key={row.position_id} className="rounded-2xl border border-[var(--line)] bg-white/75 p-4 text-sm shadow-soft">
                  <div className="flex items-center justify-between"><strong>{row.variant_id}</strong><span>{row.action || '—'}</span></div>
                  <div className="mt-2 grid gap-2 text-xs text-slate-600"><div>Qty: {row.qty}</div><div>Avg buy: {ton(row.avg_buy_price_ton)}</div><div>Mark: {ton(row.mark_price_ton)}</div><div>UPnL: {ton(row.unrealized_pnl_ton)}</div></div>
                </article>
              ))}
            </div>
            <div className="overflow-x-auto"><table className="min-w-full text-sm"><thead><tr className="text-left text-slate-500"><th>Variant</th><th>Qty</th><th>Avg buy</th><th>Mark</th><th>UPnL</th><th>Action</th></tr></thead><tbody>{positions.map((row) => <tr key={row.position_id} className="border-t border-slate-100"><td className="py-2">{row.variant_id}</td><td>{row.qty}</td><td>{ton(row.avg_buy_price_ton)}</td><td>{ton(row.mark_price_ton)}</td><td>{ton(row.unrealized_pnl_ton)}</td><td>{row.action || '—'}</td></tr>)}</tbody></table></div>
          </BentoCard>
          <BentoCard title="Holdings" className="xl:col-span-12">
            {!holdings.length ? <div className="mb-3 rounded-xl border border-dashed border-[var(--line)] bg-white/60 px-4 py-4 text-sm text-slate-600">Нет holdings. После подтвержденной покупки подарок появится здесь.</div> : null}
            <div className="grid gap-3 md:hidden">
              {holdings.map((row) => (
                <article key={row.holding_id} className="rounded-2xl border border-[var(--line)] bg-white/75 p-4 text-sm shadow-soft">
                  <div className="flex items-center justify-between"><strong>{row.variant_id}</strong><span>{row.status}</span></div>
                  <div className="mt-2 grid gap-2 text-xs text-slate-600"><div>Gift: {row.gift_unique_id}</div><div>Acquired: {ton(row.acquired_price_ton)}</div><div>Listed: {ton(row.listed_price_ton)}</div></div>
                  {row.status === 'OWNED' ? <input value={holdingDrafts[row.holding_id]?.listPriceTon || ''} onChange={(e) => updateHoldingDraft(row.holding_id, { listPriceTon: e.target.value })} placeholder="Цена листинга TON" className="gmz-input mt-3 text-xs" /> : null}
                  {row.status === 'OWNED' ? <input value={holdingDrafts[row.holding_id]?.transferUserId || ''} onChange={(e) => updateHoldingDraft(row.holding_id, { transferUserId: e.target.value })} placeholder="Telegram user id для TRANSFER" className="gmz-input mt-2 text-xs" /> : null}
                  <div className="mt-3 flex flex-wrap gap-2">{row.status === 'OWNED' ? <button type="button" className="gmz-btn px-3 py-1 text-xs" disabled={actionBusyId === `${row.holding_id}:LIST`} onClick={() => { void runHoldingAction(row, 'LIST') }}>LIST</button> : null}{row.status === 'LISTED' ? <button type="button" className="gmz-btn px-3 py-1 text-xs" disabled={actionBusyId === `${row.holding_id}:CANCEL_LISTING`} onClick={() => { void runHoldingAction(row, 'CANCEL_LISTING') }}>CANCEL</button> : null}{row.status === 'OWNED' ? <button type="button" className="gmz-btn px-3 py-1 text-xs" disabled={actionBusyId === `${row.holding_id}:SELL`} onClick={() => { void runHoldingAction(row, 'SELL') }}>SELL</button> : null}{row.status === 'OWNED' ? <button type="button" className="gmz-btn px-3 py-1 text-xs" disabled={actionBusyId === `${row.holding_id}:TRANSFER`} onClick={() => { void runHoldingAction(row, 'TRANSFER') }}>TRANSFER</button> : null}</div>
                </article>
              ))}
            </div>
            <div className="overflow-x-auto"><table className="min-w-full text-sm"><thead><tr className="text-left text-slate-500"><th>Gift</th><th>Variant</th><th>Status</th><th>Acquired</th><th>Listed</th><th>List price</th><th>Transfer</th><th>Actions</th></tr></thead><tbody>{holdings.map((row) => <tr key={row.holding_id} className="border-t border-slate-100"><td className="py-2">{row.gift_unique_id}</td><td>{row.variant_id}</td><td>{row.status}</td><td>{ton(row.acquired_price_ton)}</td><td>{ton(row.listed_price_ton)}</td><td>{row.status === 'OWNED' ? <input value={holdingDrafts[row.holding_id]?.listPriceTon || ''} onChange={(e) => updateHoldingDraft(row.holding_id, { listPriceTon: e.target.value })} placeholder={String(Number((row.acquired_price_ton || 0) * 1.12).toFixed(2))} className="gmz-input text-xs" /> : '—'}</td><td>{row.status === 'OWNED' ? <input value={holdingDrafts[row.holding_id]?.transferUserId || ''} onChange={(e) => updateHoldingDraft(row.holding_id, { transferUserId: e.target.value })} placeholder="144832201" className="gmz-input text-xs" /> : '—'}</td><td><div className="flex flex-wrap gap-2 py-2">{row.status === 'OWNED' ? <button type="button" className="gmz-btn px-3 py-1 text-xs" disabled={actionBusyId === `${row.holding_id}:LIST`} onClick={() => { void runHoldingAction(row, 'LIST') }}>LIST</button> : null}{row.status === 'LISTED' ? <button type="button" className="gmz-btn px-3 py-1 text-xs" disabled={actionBusyId === `${row.holding_id}:CANCEL_LISTING`} onClick={() => { void runHoldingAction(row, 'CANCEL_LISTING') }}>CANCEL</button> : null}{row.status === 'OWNED' ? <button type="button" className="gmz-btn px-3 py-1 text-xs" disabled={actionBusyId === `${row.holding_id}:SELL`} onClick={() => { void runHoldingAction(row, 'SELL') }}>SELL</button> : null}{row.status === 'OWNED' ? <button type="button" className="gmz-btn px-3 py-1 text-xs" disabled={actionBusyId === `${row.holding_id}:TRANSFER`} onClick={() => { void runHoldingAction(row, 'TRANSFER') }}>TRANSFER</button> : null}</div></td></tr>)}</tbody></table></div>
          </BentoCard>
          <BentoCard title="History" className="xl:col-span-12">
            {!mergedHistory.length ? <div className="mb-3 rounded-xl border border-dashed border-[var(--line)] bg-white/60 px-4 py-4 text-sm text-slate-600">История сделок пуста. Создайте первый BUY или FAST BUY.</div> : null}
            <div className="grid gap-3 md:hidden">
              {mergedHistory.map((row) => (
                <article key={row.intent_id} className="rounded-2xl border border-[var(--line)] bg-white/75 p-4 text-sm shadow-soft">
                  <div className="flex items-center justify-between"><strong>{row.intent_type}</strong><span>{row.status}</span></div>
                  <div className="mt-2 text-xs text-slate-600">{row.variant_id}</div>
                  <div className="mt-1 text-xs text-slate-500">{new Date(row.created_at).toLocaleString('ru-RU')}</div>
                  {(row.intent_type === 'BUY_AND_LIST' || (row.chain_policy === 'BUY_THEN_LIST' && !row.parent_intent_id)) ? <button type="button" className="gmz-btn mt-3 px-3 py-1 text-xs" disabled={actionBusyId === `retry:${row.intent_id}`} onClick={() => { void retryChildList(row.intent_id) }}>Повторить выставление</button> : null}
                </article>
              ))}
            </div>
            <div className="overflow-x-auto"><table className="min-w-full text-sm"><thead><tr className="text-left text-slate-500"><th>Intent</th><th>Type</th><th>Status</th><th>Variant</th><th>Created</th><th>Chain</th><th>Actions</th></tr></thead><tbody>{mergedHistory.map((row) => <><tr key={row.intent_id} className="border-t border-slate-100 align-top"><td className="py-2">{row.intent_id}</td><td>{row.intent_type}</td><td>{row.status}</td><td>{row.variant_id}</td><td>{new Date(row.created_at).toLocaleString('ru-RU')}</td><td>{row.chain_id || '—'}{row.parent_intent_id ? <div className="text-xs text-slate-500">parent: {row.parent_intent_id}</div> : null}</td><td><button type="button" className="gmz-btn px-3 py-1 text-xs" onClick={() => setExpandedIntentId((prev) => prev === row.intent_id ? '' : row.intent_id)}>{expandedIntentId === row.intent_id ? 'Скрыть' : 'Детали'}</button>{row.intent_type === 'BUY_AND_LIST' || (row.chain_policy === 'BUY_THEN_LIST' && !row.parent_intent_id) ? <button type="button" className="gmz-btn ml-2 px-3 py-1 text-xs" disabled={actionBusyId === `retry:${row.intent_id}`} onClick={() => { void retryChildList(row.intent_id) }}>Повторить выставление</button> : null}<div className="mt-1 text-xs text-slate-500">{Array.isArray((row as { status_timeline?: unknown }).status_timeline) ? `${((row as { status_timeline?: Array<unknown> }).status_timeline || []).length} steps` : 'timeline pending'}</div></td></tr>{expandedIntentId === row.intent_id ? <tr className="bg-slate-50"><td colSpan={7} className="px-3 py-3 text-xs text-slate-700"><div><strong>reasons:</strong> {Array.isArray(row.reasons) && row.reasons.length ? row.reasons.join(' | ') : '—'}</div><div className="mt-1"><strong>risk_flags:</strong> {Array.isArray(row.risk_flags) && row.risk_flags.length ? row.risk_flags.join(' | ') : '—'}</div><div className="mt-1"><strong>decision_trace:</strong> <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded-lg bg-white p-2">{JSON.stringify(row.decision_trace || {}, null, 2)}</pre></div></td></tr> : null}</>)}</tbody></table></div>
          </BentoCard>
          <BentoCard title="Wallet activity" className="xl:col-span-12">
            <div className="overflow-x-auto"><table className="min-w-full text-sm"><thead><tr className="text-left text-slate-500"><th>Time</th><th>Direction</th><th>Amount</th><th>Tx</th></tr></thead><tbody>{activity.map((row) => <tr key={`${row.tx_hash}-${row.ts}`} className="border-t border-slate-100"><td className="py-2">{new Date(row.ts).toLocaleString('ru-RU')}</td><td>{row.direction}</td><td>{ton(row.amount_ton)}</td><td>{row.tx_hash}</td></tr>)}</tbody></table></div>
          </BentoCard>
          <BentoCard title="AutoSell rules" className="xl:col-span-12">
            <div className="text-sm text-slate-600">Активных правил: {rules.length}. Редактор доступен в разделе Настройки.</div>
          </BentoCard>
        </BentoGrid>
      )}
    </section>
  )
}
