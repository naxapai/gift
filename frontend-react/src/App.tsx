import { Suspense, lazy, type ReactElement, useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'

const OverviewPage = lazy(async () => ({ default: (await import('./pages/OverviewPage')).OverviewPage }))
const CatalogPage = lazy(async () => ({ default: (await import('./pages/CatalogPage')).CatalogPage }))
const ScreenersPage = lazy(async () => ({ default: (await import('./pages/ScreenersPage')).ScreenersPage }))
const SignalsPage = lazy(async () => ({ default: (await import('./pages/SignalsPage')).SignalsPage }))
const ListingPage = lazy(async () => ({ default: (await import('./pages/ListingPage')).ListingPage }))
const TradesPage = lazy(async () => ({ default: (await import('./pages/TradesPage')).TradesPage }))
const FavoritesPage = lazy(async () => ({ default: (await import('./pages/FavoritesPage')).FavoritesPage }))
const SettingsPage = lazy(async () => ({ default: (await import('./pages/SettingsPage')).SettingsPage }))
const AdminPage = lazy(async () => ({ default: (await import('./pages/AdminPage')).AdminPage }))
const VariantPage = lazy(async () => ({ default: (await import('./pages/VariantPage')).VariantPage }))

function RouteFallback() {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white/70 p-4 text-sm text-slate-600">
      Загрузка раздела…
    </div>
  )
}

function lazyRoute(element: ReactElement) {
  return <Suspense fallback={<RouteFallback />}>{element}</Suspense>
}

function NotFoundRedirect() {
  return <Navigate to="/" replace />
}

function DynamicImportRecovery() {
  useEffect(() => {
    const key = 'gmz:dynamic-import-reloaded'
    const handler = (event: PromiseRejectionEvent) => {
      const reason = String((event.reason && (event.reason.message || event.reason)) || '')
      if (!reason.includes('Failed to fetch dynamically imported module')) return
      if (sessionStorage.getItem(key) === '1') return
      sessionStorage.setItem(key, '1')
      window.location.reload()
    }
    window.addEventListener('unhandledrejection', handler)
    return () => window.removeEventListener('unhandledrejection', handler)
  }, [])
  return null
}

export default function App() {
  return (
    <>
      <DynamicImportRecovery />
      <Routes>
        <Route element={<AppShell />}>
        <Route index element={lazyRoute(<OverviewPage />)} />
        <Route path="catalog" element={lazyRoute(<CatalogPage />)} />
        <Route path="screeners" element={lazyRoute(<ScreenersPage />)} />
        <Route path="signals" element={lazyRoute(<SignalsPage />)} />
        <Route path="listing" element={lazyRoute(<ListingPage />)} />
        <Route path="trades" element={lazyRoute(<TradesPage />)} />
        <Route path="favorites" element={lazyRoute(<FavoritesPage />)} />
        <Route path="cabinet" element={<Navigate to="/" replace />} />
        <Route path="settings" element={lazyRoute(<SettingsPage />)} />
        <Route path="admin" element={lazyRoute(<AdminPage />)} />
        <Route path="variant/:variantId" element={lazyRoute(<VariantPage />)} />
        </Route>
        <Route path="*" element={<NotFoundRedirect />} />
      </Routes>
    </>
  )
}
