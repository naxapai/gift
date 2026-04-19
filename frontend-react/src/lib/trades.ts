export interface TradePrefill {
  variantId?: string
  collectionId?: string
  collection?: string
  model?: string
  background?: string
  pattern?: string
  intent?: 'BUY' | 'BUY_AND_LIST'
}

export function buildTradesHref(prefill: TradePrefill): string {
  const q = new URLSearchParams()
  if (prefill.variantId) q.set('variant_id', String(prefill.variantId).trim())
  if (prefill.collectionId) q.set('collection_id', String(prefill.collectionId).trim())
  if (prefill.collection) q.set('collection', String(prefill.collection).trim())
  if (prefill.model) q.set('model', String(prefill.model).trim())
  if (prefill.background) q.set('background', String(prefill.background).trim())
  if (prefill.pattern) q.set('pattern', String(prefill.pattern).trim())
  if (prefill.intent) q.set('intent', String(prefill.intent).trim())
  const raw = q.toString()
  return raw ? `/trades?${raw}` : '/trades'
}
