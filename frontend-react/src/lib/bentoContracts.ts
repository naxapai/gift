import bentoContractsRaw from '../../../config/contracts/bento_ui_blocks.json'
import type { TimeframeKey } from './metrics'

type BentoBlock = {
  id?: string
  metrics?: unknown
  title?: unknown
  source?: unknown
  controls?: {
    timeframe?: unknown
    [key: string]: unknown
  }
}

type BentoPageLayout = {
  rows?: Array<{
    blocks?: BentoBlock[]
  }>
}

type BentoContracts = {
  pages?: Record<
    string,
    {
      title_ru?: string
      layout?: BentoPageLayout
    }
  >
}

const BENTO_CONTRACTS = (bentoContractsRaw || {}) as BentoContracts
const ALLOWED_TIMEFRAMES = new Set<TimeframeKey>(['1h', '6h', '24h', '7d'])

function collectBlocks(pageId: string): BentoBlock[] {
  const page = (BENTO_CONTRACTS.pages || {})[pageId]
  const rows = page?.layout?.rows || []
  const out: BentoBlock[] = []
  for (const row of rows) {
    const blocks = row?.blocks || []
    for (const block of blocks) out.push(block || {})
  }
  return out
}

function findBlock(pageId: string, blockId: string): BentoBlock | undefined {
  return collectBlocks(pageId).find((x) => String(x?.id || '') === String(blockId))
}

export function bentoPageTitleRu(pageId: string, fallback: string): string {
  const page = (BENTO_CONTRACTS.pages || {})[pageId]
  const title = String(page?.title_ru || '').trim()
  return title || fallback
}

export function bentoTimeframes(pageId: string, blockId: string, fallback: TimeframeKey[]): TimeframeKey[] {
  const block = findBlock(pageId, blockId)
  const raw = block?.controls?.timeframe
  if (!Array.isArray(raw)) return fallback
  const out: TimeframeKey[] = []
  for (const item of raw) {
    const tf = String(item || '').trim() as TimeframeKey
    if (!ALLOWED_TIMEFRAMES.has(tf)) continue
    if (!out.includes(tf)) out.push(tf)
  }
  return out.length ? out : fallback
}

export function bentoBlockMetrics(pageId: string, blockId: string, fallback: string[] = []): string[] {
  const block = findBlock(pageId, blockId)
  const raw = block?.metrics
  if (!Array.isArray(raw)) return fallback
  const out: string[] = []
  for (const item of raw) {
    const metric = String(item || '').trim().toUpperCase()
    if (!metric) continue
    if (!out.includes(metric)) out.push(metric)
  }
  return out.length ? out : fallback
}

export function bentoPageMetrics(pageId: string, fallback: string[] = []): string[] {
  const blocks = collectBlocks(pageId)
  const out: string[] = []
  for (const block of blocks) {
    const raw = block?.metrics
    if (!Array.isArray(raw)) continue
    for (const item of raw) {
      const metric = String(item || '').trim().toUpperCase()
      if (!metric || out.includes(metric)) continue
      out.push(metric)
    }
  }
  return out.length ? out : fallback
}

export function bentoBlockTitle(pageId: string, blockId: string, fallback: string): string {
  const block = findBlock(pageId, blockId)
  const title = String(block?.title || '').trim()
  return title || fallback
}

export function bentoBlockSource(pageId: string, blockId: string, fallback = ''): string {
  const block = findBlock(pageId, blockId)
  const source = String(block?.source || '').trim()
  return source || fallback
}

export function bentoBlockControlNumber(pageId: string, blockId: string, key: string, fallback: number): number {
  const block = findBlock(pageId, blockId)
  const n = Number(block?.controls?.[key])
  return Number.isFinite(n) ? n : fallback
}
