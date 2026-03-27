import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BentoCard } from '../components/BentoCard'
import { LoadingBlock } from '../components/LoadingBlock'
import { PageHeader } from '../components/PageHeader'
import { getFavorites, getVariants, removeFavorite, upsertFavorite } from '../lib/api'
import { readUiAutoRefreshMinutes, uiAutoRefreshMs } from '../lib/uiSettings'
import type { VariantItem } from '../types/api'

const LS_KEY = 'gmz:favorite_variant_ids'
const FAVORITES_CACHE_KEY = 'gmz.favorites.cache.v1'

function readLocalFavorites(): string[] {
  try {
    const raw = localStorage.getItem(LS_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.map((x) => String(x)) : []
  } catch {
    return []
  }
}

function writeLocalFavorites(ids: string[]) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify([...new Set(ids)]))
  } catch {
    // ignore
  }
}

interface FavoritesCachePayload {
  savedAt: number
  data: {
    allVariants: VariantItem[]
    favoriteIds: string[]
    query: string
    authRequired: boolean
  }
}

function formatCountdown(totalSec: number): string {
  const sec = Math.max(0, Math.floor(totalSec))
  const mm = Math.floor(sec / 60)
  const ss = sec % 60
  return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
}

export function FavoritesPage() {
  const navigate = useNavigate()
  const autoRefreshMinutes = useMemo(() => readUiAutoRefreshMinutes(), [])
  const autoRefreshMs = useMemo(() => uiAutoRefreshMs(autoRefreshMinutes), [autoRefreshMinutes])
  const [allVariants, setAllVariants] = useState<VariantItem[]>([])
  const [favoriteIds, setFavoriteIds] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [authRequired, setAuthRequired] = useState(false)
  const [nextRefreshSec, setNextRefreshSec] = useState(Math.ceil(autoRefreshMs / 1000))
  const firstLoadRef = useRef(true)
  const initDoneRef = useRef(false)
  const nextRefreshAtRef = useRef<number>(Date.now() + autoRefreshMs)
  const lastAutoRefreshAtRef = useRef<number>(0)

  const scheduleNextAutoRefresh = useCallback((baseTs: number = Date.now()) => {
    nextRefreshAtRef.current = baseTs + autoRefreshMs
    setNextRefreshSec(Math.ceil(autoRefreshMs / 1000))
  }, [autoRefreshMs])

  const load = useCallback(async () => {
    if (firstLoadRef.current) setLoading(true)
    else setRefreshing(true)
    setError('')
    try {
      const [variants, remoteFav] = await Promise.all([
        getVariants({ sort: 'floor_ton.asc', cap: 5000 }),
        getFavorites().catch((e) => {
          const msg = e instanceof Error ? e.message : ''
          if (msg.includes('401') || msg.includes('403')) {
            setAuthRequired(true)
            return { items: readLocalFavorites().map((id) => ({ variant_id: id })) }
          }
          throw e
        }),
      ])
      setAllVariants(variants)
      const ids = (remoteFav.items || []).map((x) => String(x.variant_id || '')).filter(Boolean)
      setFavoriteIds(ids)
      writeLocalFavorites(ids)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки избранного')
      const local = readLocalFavorites()
      setFavoriteIds(local)
      setAllVariants(await getVariants({ sort: 'floor_ton.asc', cap: 2000 }).catch(() => []))
    } finally {
      setLoading(false)
      setRefreshing(false)
      firstLoadRef.current = false
    }
  }, [])

  useEffect(() => {
    if (initDoneRef.current) return
    initDoneRef.current = true

    let hydrated = false
    try {
      const raw = sessionStorage.getItem(FAVORITES_CACHE_KEY)
      if (raw) {
        const parsed = JSON.parse(raw) as FavoritesCachePayload
        if (parsed && parsed.data && Number.isFinite(Number(parsed.savedAt))) {
          const d = parsed.data
          setAllVariants(Array.isArray(d.allVariants) ? d.allVariants : [])
          setFavoriteIds(Array.isArray(d.favoriteIds) ? d.favoriteIds : [])
          setQuery(String(d.query || ''))
          setAuthRequired(Boolean(d.authRequired))
          setLoading(false)
          setRefreshing(false)
          firstLoadRef.current = false
          hydrated = true

          const savedAt = Number(parsed.savedAt || 0)
          const ageMs = Date.now() - savedAt
          if (ageMs > 0 && ageMs < autoRefreshMs) {
            nextRefreshAtRef.current = savedAt + autoRefreshMs
            setNextRefreshSec(Math.ceil(Math.max(0, nextRefreshAtRef.current - Date.now()) / 1000))
          } else {
            lastAutoRefreshAtRef.current = Date.now()
            scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
            void load()
          }
        }
      }
    } catch {
      // cache read is best effort
    }

    if (!hydrated) {
      lastAutoRefreshAtRef.current = Date.now()
      scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
      void load()
      return
    }

    try {
      const raw = sessionStorage.getItem(FAVORITES_CACHE_KEY)
      if (raw) {
        const parsed = JSON.parse(raw) as FavoritesCachePayload
        const savedAt = Number(parsed?.savedAt || 0)
        const ageMs = Date.now() - savedAt
        if (ageMs >= autoRefreshMs) {
          lastAutoRefreshAtRef.current = Date.now()
          scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
          void load()
        }
      }
    } catch {
      // ignore stale-cache refresh errors
    }
  }, [autoRefreshMs, load, scheduleNextAutoRefresh])

  useEffect(() => {
    const poll = window.setInterval(() => {
      lastAutoRefreshAtRef.current = Date.now()
      scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
      void load()
    }, autoRefreshMs)
    const tick = window.setInterval(() => {
      const remain = Math.max(0, Math.ceil((nextRefreshAtRef.current - Date.now()) / 1000))
      setNextRefreshSec(remain)
    }, 1000)
    return () => {
      window.clearInterval(poll)
      window.clearInterval(tick)
    }
  }, [autoRefreshMs, load, scheduleNextAutoRefresh])

  useEffect(() => {
    if (loading) return
    try {
      const payload: FavoritesCachePayload = {
        savedAt: Date.now(),
        data: {
          allVariants,
          favoriteIds,
          query,
          authRequired,
        },
      }
      sessionStorage.setItem(FAVORITES_CACHE_KEY, JSON.stringify(payload))
    } catch {
      // cache write is best effort
    }
  }, [loading, allVariants, favoriteIds, query, authRequired])

  const favoriteMap = useMemo(() => new Set(favoriteIds), [favoriteIds])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    const rows = allVariants.filter((v) => favoriteMap.has(v.variant_id))
    if (!q) return rows
    return rows.filter((v) => {
      const bag = [v.collection_name, v.model, v.background, v.pattern, v.variant_id].join(' ').toLowerCase()
      return bag.includes(q)
    })
  }, [allVariants, favoriteMap, query])

  const candidates = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return []
    return allVariants
      .filter((v) => !favoriteMap.has(v.variant_id))
      .filter((v) => {
        const bag = [v.collection_name, v.model, v.background, v.pattern, v.variant_id].join(' ').toLowerCase()
        return bag.includes(q)
      })
      .slice(0, 10)
  }, [allVariants, favoriteMap, query])

  const toggleFavorite = useCallback(
    async (variantId: string, next: boolean) => {
      const id = String(variantId || '')
      if (!id) return
      const current = new Set(favoriteIds)
      if (next) current.add(id)
      else current.delete(id)
      const optimistic = [...current]
      setFavoriteIds(optimistic)
      writeLocalFavorites(optimistic)
      try {
        if (authRequired) return
        if (next) {
          await upsertFavorite(id)
        } else {
          await removeFavorite(id)
        }
      } catch (e) {
        const message = e instanceof Error ? e.message : ''
        if (message.includes('401') || message.includes('403')) {
          setAuthRequired(true)
          return
        }
        // rollback on non-auth errors
        setFavoriteIds(favoriteIds)
        writeLocalFavorites(favoriteIds)
      }
    },
    [favoriteIds, authRequired],
  )

  return (
    <section>
      <PageHeader
        title="Избранное"
        subtitle="Список отслеживаемых вариантов"
        right={(
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-slate-500">
              Обновление через {formatCountdown(nextRefreshSec)}
            </span>
            <button
              type="button"
              onClick={() => {
                lastAutoRefreshAtRef.current = Date.now()
                scheduleNextAutoRefresh(lastAutoRefreshAtRef.current)
                void load()
              }}
              className="gmz-btn gmz-btn-ghost px-3 py-2 text-sm"
            >
              Обновить
            </button>
          </div>
        )}
      />

      <BentoCard title="Управление избранным" className="mb-4">
        {refreshing ? <div className="mb-2 text-xs font-medium text-slate-500">Обновляем данные…</div> : null}
        <div className="grid gap-3 md:grid-cols-[1fr_auto]">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по коллекции / модели / variant_id"
            className="gmz-input"
          />
          <button
            type="button"
            onClick={() => void load()}
            className="gmz-btn gmz-btn-primary px-4 py-2 text-sm"
          >
            Обновить
          </button>
        </div>
        {authRequired ? (
          <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            Нет авторизации `/v1/favorites`, работаем во временном локальном режиме (localStorage).
          </div>
        ) : null}
      </BentoCard>

      {error ? <BentoCard className="mb-4 border-rose-200 bg-rose-50/70 text-sm text-rose-700">Ошибка: {error}</BentoCard> : null}

      {candidates.length ? (
        <BentoCard title="Добавить в избранное" className="mb-4">
          <div className="grid gap-2">
            {candidates.map((v) => (
              <div key={v.variant_id} className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-3 py-2">
                <div className="min-w-0 text-sm text-slate-700">
                  {[v.collection_name, v.model, v.background, v.pattern].filter(Boolean).join(' • ') || v.variant_id}
                </div>
                <button
                  type="button"
                  onClick={() => void toggleFavorite(v.variant_id, true)}
                  className="gmz-btn gmz-btn-ghost rounded-lg px-2 py-1 text-xs font-semibold text-[var(--accent)]"
                >
                  Добавить
                </button>
              </div>
            ))}
          </div>
        </BentoCard>
      ) : null}

      <BentoCard title={`Избранные варианты (${favoriteIds.length})`}>
        {loading ? (
          <LoadingBlock className="h-28" />
        ) : visible.length ? (
          <div className="gmz-table-wrap">
            <table className="gmz-table">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="pb-2 pr-4">Вариант</th>
                  <th className="pb-2 pr-4">Мин. цена</th>
                  <th className="pb-2 pr-4">Δ24h</th>
                  <th className="pb-2">Действия</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((v) => (
                  <tr key={v.variant_id} className="border-b border-slate-100">
                    <td className="py-2 pr-4 text-slate-700">{[v.collection_name, v.model, v.background, v.pattern].filter(Boolean).join(' • ') || v.variant_id}</td>
                    <td className="py-2 pr-4 tabular-nums">{Number(v.floor_ton || 0).toFixed(1)} TON</td>
                    <td className="py-2 pr-4 tabular-nums">{Number(v.delta_24h || 0).toFixed(1)}%</td>
                    <td className="py-2">
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => navigate(`/variant/${encodeURIComponent(v.variant_id)}`)}
                          className="gmz-btn gmz-btn-ghost rounded-lg px-2 py-1 text-xs font-semibold"
                        >
                          Карточка
                        </button>
                        <button
                          type="button"
                          onClick={() => void toggleFavorite(v.variant_id, false)}
                          className="rounded-lg border border-rose-200 px-2 py-1 text-xs font-semibold text-rose-700 hover:bg-rose-50"
                        >
                          Удалить
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-sm text-slate-500">Список избранного пуст</div>
        )}
      </BentoCard>
    </section>
  )
}
