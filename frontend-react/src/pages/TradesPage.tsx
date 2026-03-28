import { useCallback, useEffect, useMemo, useState } from 'react'
import { BentoCard } from '../components/BentoCard'
import { BentoGrid } from '../components/BentoGrid'
import { LoadingBlock } from '../components/LoadingBlock'
import { MetricTile } from '../components/MetricTile'
import { PageHeader } from '../components/PageHeader'
import { getAutoSellRules, getBuyQuote, getTelegramAuthMe, getTonAuthMe, getTradeHoldings, getTradeIntents, getTradePnl, getTradePositions, getTradingAccess, getWalletActivity, postFastBuyConfirm, postTradeIntent, postTradeIntentConfirm } from '../lib/api'
import type { AutoSellRule, HoldingPro, PositionPro, PnlSummaryPro, TradeIntent, WalletActivityItem } from '../types/api'

function ton(v?: number | null): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return `${n.toFixed(2)} TON`
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
  const [creating, setCreating] = useState(false)
  const [actionBusyId, setActionBusyId] = useState('')

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

  const createBuy = useCallback(async (intentType: 'BUY' | 'BUY_AND_LIST' | 'FAST_BUY') => {
    if (!walletAddress || !variantId.trim()) return
    setCreating(true)
    setError('')
    try {
      if (intentType === 'FAST_BUY') {
        const quote = await getBuyQuote({ variantId: variantId.trim(), maxPriceTon: Number(maxPriceTon || 0), walletAddress })
        await postFastBuyConfirm({ buy_quote_token: quote.buy_quote_token, tx_hash: `fast_${Date.now()}`, wallet_address: walletAddress })
      } else {
        const payload: Record<string, unknown> = {
          intent_type: intentType,
          variant_id: variantId.trim(),
          wallet_address: walletAddress,
          max_spend_ton: Number(maxPriceTon || 0),
          chain_policy: intentType === 'BUY_AND_LIST' ? 'BUY_THEN_LIST' : 'MANUAL',
        }
        if (intentType === 'BUY_AND_LIST') {
          payload.post_action = { type: 'LIST', listing_params: { list_price_ton: Number(maxPriceTon || 0) * 1.1, duration_sec: 86400, marketplace: 'fragment' } }
        }
        const created = await postTradeIntent(payload)
        await postTradeIntentConfirm(created.intent.intent_id, { tx_hash: `std_${Date.now()}`, wallet_address: walletAddress })
      }
      setVariantId('')
      setMaxPriceTon('')
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'trade_create_failed')
    } finally {
      setCreating(false)
    }
  }, [walletAddress, variantId, maxPriceTon, load])

  const runHoldingAction = useCallback(async (holding: HoldingPro, action: 'LIST' | 'CANCEL_LISTING' | 'SELL' | 'TRANSFER') => {
    if (!walletAddress) return
    setActionBusyId(`${holding.holding_id}:${action}`)
    setError('')
    try {
      const payload: Record<string, unknown> = {
        intent_type: action,
        variant_id: holding.variant_id,
        wallet_address: walletAddress,
        gift_unique_id: holding.gift_unique_id,
        price_ton: holding.listed_price_ton || holding.acquired_price_ton,
      }
      if (action === 'LIST') {
        payload.post_action = { type: 'LIST', listing_params: { list_price_ton: Number((holding.acquired_price_ton || 0) * 1.12), duration_sec: 86400, marketplace: 'fragment' } }
      }
      if (action === 'TRANSFER') {
        payload.transfer_params = { telegram_user_id: '144832201' }
      }
      const created = await postTradeIntent(payload)
      await postTradeIntentConfirm(created.intent.intent_id, { tx_hash: `${action.toLowerCase()}_${Date.now()}`, wallet_address: walletAddress })
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'holding_action_failed')
    } finally {
      setActionBusyId('')
    }
  }, [walletAddress, load])

  const policyText = useMemo(() => 'Variant A only: BUY -> CONFIRMED -> LIST. FAST BUY enabled. Backend never stores private keys.', [])

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
      ) : loading ? (
        <LoadingBlock />
      ) : (
        <BentoGrid>
          <BentoCard title="Policy" className="xl:col-span-12">
            <div className="text-sm text-slate-700">{policyText}</div>
          </BentoCard>
          <BentoCard title="Fast Buy / Buy / Buy+List" className="xl:col-span-12">
            <div className="grid gap-3 md:grid-cols-3">
              <input value={variantId} onChange={(e) => setVariantId(e.target.value)} placeholder="variant_id" className="gmz-input" />
              <input value={maxPriceTon} onChange={(e) => setMaxPriceTon(e.target.value)} placeholder="max price TON" className="gmz-input" />
              <div className="flex flex-wrap gap-2">
                <button type="button" className="gmz-btn gmz-btn-primary px-4 py-2 text-sm" disabled={creating} onClick={() => { void createBuy('FAST_BUY') }}>FAST BUY</button>
                <button type="button" className="gmz-btn px-4 py-2 text-sm" disabled={creating} onClick={() => { void createBuy('BUY') }}>BUY</button>
                <button type="button" className="gmz-btn px-4 py-2 text-sm" disabled={creating} onClick={() => { void createBuy('BUY_AND_LIST') }}>BUY+LIST</button>
              </div>
            </div>
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
            <div className="overflow-x-auto"><table className="min-w-full text-sm"><thead><tr className="text-left text-slate-500"><th>Variant</th><th>Qty</th><th>Avg buy</th><th>Mark</th><th>UPnL</th><th>Action</th></tr></thead><tbody>{positions.map((row) => <tr key={row.position_id} className="border-t border-slate-100"><td className="py-2">{row.variant_id}</td><td>{row.qty}</td><td>{ton(row.avg_buy_price_ton)}</td><td>{ton(row.mark_price_ton)}</td><td>{ton(row.unrealized_pnl_ton)}</td><td>{row.action || '—'}</td></tr>)}</tbody></table></div>
          </BentoCard>
          <BentoCard title="Holdings" className="xl:col-span-12">
            <div className="overflow-x-auto"><table className="min-w-full text-sm"><thead><tr className="text-left text-slate-500"><th>Gift</th><th>Variant</th><th>Status</th><th>Acquired</th><th>Listed</th><th>Actions</th></tr></thead><tbody>{holdings.map((row) => <tr key={row.holding_id} className="border-t border-slate-100"><td className="py-2">{row.gift_unique_id}</td><td>{row.variant_id}</td><td>{row.status}</td><td>{ton(row.acquired_price_ton)}</td><td>{ton(row.listed_price_ton)}</td><td><div className="flex flex-wrap gap-2 py-2">{row.status === 'OWNED' ? <button type="button" className="gmz-btn px-3 py-1 text-xs" disabled={actionBusyId === `${row.holding_id}:LIST`} onClick={() => { void runHoldingAction(row, 'LIST') }}>LIST</button> : null}{row.status === 'LISTED' ? <button type="button" className="gmz-btn px-3 py-1 text-xs" disabled={actionBusyId === `${row.holding_id}:CANCEL_LISTING`} onClick={() => { void runHoldingAction(row, 'CANCEL_LISTING') }}>CANCEL</button> : null}{row.status === 'OWNED' ? <button type="button" className="gmz-btn px-3 py-1 text-xs" disabled={actionBusyId === `${row.holding_id}:SELL`} onClick={() => { void runHoldingAction(row, 'SELL') }}>SELL</button> : null}{row.status === 'OWNED' ? <button type="button" className="gmz-btn px-3 py-1 text-xs" disabled={actionBusyId === `${row.holding_id}:TRANSFER`} onClick={() => { void runHoldingAction(row, 'TRANSFER') }}>TRANSFER</button> : null}</div></td></tr>)}</tbody></table></div>
          </BentoCard>
          <BentoCard title="History" className="xl:col-span-12">
            <div className="overflow-x-auto"><table className="min-w-full text-sm"><thead><tr className="text-left text-slate-500"><th>Intent</th><th>Type</th><th>Status</th><th>Variant</th><th>Created</th></tr></thead><tbody>{history.map((row) => <tr key={row.intent_id} className="border-t border-slate-100"><td className="py-2">{row.intent_id}</td><td>{row.intent_type}</td><td>{row.status}</td><td>{row.variant_id}</td><td>{new Date(row.created_at).toLocaleString('ru-RU')}</td></tr>)}</tbody></table></div>
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
