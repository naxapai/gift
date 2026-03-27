export const OPENAPI_V1 = {
  overview: '/v1/overview',
  marketStatus: '/v1/market/status',
  signals: '/v1/signals',
  collections: '/v1/collections',
  variants: '/v1/variants',
  variantsResolve: '/v1/variants/resolve',
  metrics: '/v1/metrics',
  listingsSummary: '/v1/listings/summary',
  listingsSourceStatus: '/v1/listings/source-status',
  listings: '/v1/listings',
  listingsNew: '/v1/listings/new',
  listingsRace: '/v1/listings/race',
  listingsHistory: '/v1/listings/history',
  listingSignals: '/v1/listings/signals',
  listingsStream: '/v1/stream/listings',
  signalsStream: '/v1/stream/signals',
  screenersFeed: '/v1/screeners/feed',
  screenersStream: '/v1/stream/screeners',
  catalogFeed: '/v1/catalog/feed',
  catalogStream: '/v1/stream/catalog',
  catalogVariant: '/v1/catalog/variant',
  favorites: '/v1/favorites',
  stream: '/v1/stream',
} as const

export function withMode(path: string, mode = 'tz'): string {
  const q = new URLSearchParams({ mode })
  return `${path}?${q.toString()}`
}

export function withQuery(path: string, params: URLSearchParams): string {
  const query = params.toString()
  return query ? `${path}?${query}` : path
}

export function variantDetailsPath(variantId: string, mode = 'tz'): string {
  const q = new URLSearchParams({ mode })
  return `${OPENAPI_V1.variants}/${encodeURIComponent(variantId)}?${q.toString()}`
}
