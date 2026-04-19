import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / 'frontend-react'
CONTRACTS = ROOT / 'config' / 'contracts'


class TestFrontendReactStack(unittest.TestCase):
    def test_signals_page_uses_all_contract_filter_ids(self):
        page = (FRONT / 'src' / 'pages' / 'SignalsPage.tsx').read_text(encoding='utf-8')
        mapping = json.loads((ROOT / 'config' / 'signals' / 'signals_page_pro_ui_mapping.json').read_text(encoding='utf-8'))
        for row in mapping.get('filters', []):
            fid = str(row.get('id') or '').strip()
            if not fid:
                continue
            self.assertIn(fid, page)

    def test_required_stack_dependencies_installed(self):
        package = json.loads((FRONT / 'package.json').read_text(encoding='utf-8'))
        deps = package.get('dependencies', {})
        dev_deps = package.get('devDependencies', {})

        self.assertIn('react', deps)
        self.assertIn('react-dom', deps)
        self.assertIn('react-router-dom', deps)
        self.assertIn('framer-motion', deps)
        self.assertIn('tailwindcss', dev_deps)

    def test_app_has_main_routes(self):
        app = (FRONT / 'src' / 'App.tsx').read_text(encoding='utf-8')
        for route in ['catalog', 'screeners', 'signals', 'listing', 'trades', 'favorites', 'cabinet', 'admin', 'settings', 'variant/:variantId']:
            self.assertIn(route, app)
        self.assertIn('Failed to fetch dynamically imported module', app)
        self.assertIn('gmz:dynamic-import-reloaded', app)
        self.assertIn('Navigate to="/" replace', app)

    def test_shell_has_bento_navigation_labels(self):
        shell = (FRONT / 'src' / 'components' / 'AppShell.tsx').read_text(encoding='utf-8')
        for label in ['Обзор', 'Каталог', 'Скринеры', 'Сигналы', 'Листинг', 'Сделки', 'Избранное', 'Настройки']:
            self.assertIn(label, shell)
        self.assertNotIn("{ to: '/admin', label: 'Админ'", shell)
        self.assertIn('visibleNavItems', shell)
        self.assertNotIn('getAdminAccess', shell)
        self.assertNotIn('gmz-logo-mark.png', shell)
        self.assertNotIn('gmz-logo-wordmark.png', shell)
        self.assertIn('/logo.png', shell)
        self.assertIn('/favicon.png', shell)
        self.assertIn('TONCONNECT_UI_SRC', shell)
        self.assertIn('postTonChallenge', shell)
        self.assertIn('postTonVerify', shell)
        self.assertIn('postTonLogout', shell)
        self.assertIn('tonconnect-manifest.json', shell)
        self.assertIn('getTelegramAuthMe', shell)
        self.assertIn('getTelegramOwnedGifts', shell)
        self.assertIn('Войти через Telegram', shell)
        self.assertIn('TONCONNECT_BUTTON_ROOT_ID', shell)
        self.assertIn('Подарки в наличии', shell)

    def test_cabinet_page_contains_telegram_auth_and_owned_gifts_ui(self):
        page = (FRONT / 'src' / 'pages' / 'CabinetPage.tsx').read_text(encoding='utf-8')
        self.assertIn('Войти через Telegram', page)
        self.assertIn('getTelegramAuthBootstrap', page)
        self.assertIn('getTelegramAuthBootstrap', page)
        self.assertIn('getTelegramOwnedGifts', page)
        self.assertIn('postTelegramAuthVerify', page)
        self.assertIn('postTelegramWebAppVerify', page)
        self.assertIn('postTelegramLogout', page)
        self.assertIn('Подарки в наличии', page)
        self.assertIn('TELEGRAM_WIDGET_SRC', page)
        self.assertIn('Всего подарков', page)
        self.assertIn('Средний Floor', page)
        self.assertIn('Средний Fair', page)
        self.assertIn('Открыть variant', page)
        self.assertIn('Проверь token/endpoint для owned gifts', page)

    def test_bento_grid_component_exists_and_is_6x1(self):
        grid = (FRONT / 'src' / 'components' / 'BentoGrid.tsx').read_text(encoding='utf-8')
        css = (FRONT / 'src' / 'index.css').read_text(encoding='utf-8')
        self.assertIn('bento-grid', grid)
        self.assertIn('grid-template-columns: repeat(6, minmax(0, 1fr));', css)
        self.assertIn('grid-template-columns: minmax(0, 1fr);', css)

    def test_signal_card_uses_fragment_buy_link_pattern(self):
        card = (FRONT / 'src' / 'components' / 'SignalCard.tsx').read_text(encoding='utf-8')
        self.assertIn('https://fragment.com/gift/', card)
        self.assertIn('?collection=all&query=', card)

    def test_gmz_select_uses_native_select_for_reliable_trait_selection(self):
        component = (FRONT / 'src' / 'components' / 'GmzSelect.tsx').read_text(encoding='utf-8')
        css = (FRONT / 'src' / 'index.css').read_text(encoding='utf-8')
        self.assertIn('<select', component)
        self.assertIn('onChange={(e) => onChange(e.target.value)}', component)
        self.assertIn('gmz-select-native', component)
        self.assertIn('appearance: none;', css)
        self.assertNotIn('document.addEventListener', component)
        self.assertNotIn('gmz-select-menu', component)

    def test_signals_page_has_full_filter_set_and_drawer(self):
        page = (FRONT / 'src' / 'pages' / 'SignalsPage.tsx').read_text(encoding='utf-8')
        drawer = (FRONT / 'src' / 'components' / 'SignalDetailsDrawer.tsx').read_text(encoding='utf-8')
        trace = (FRONT / 'src' / 'components' / 'DecisionTraceCard.tsx').read_text(encoding='utf-8')
        self.assertIn('Мин. недооценка (%)', page)
        self.assertIn('Макс. риск (0..1)', page)
        self.assertIn('Только новые (1ч)', page)
        self.assertIn('SignalDetailsDrawer', page)
        self.assertIn('GmzSelect', page)
        self.assertIn('row.preview_url', page)
        self.assertIn('gmz-filters-panel', page)
        self.assertIn('justify-between gap-3', page)
        self.assertIn('xl:h-[calc(100vh-120px)]', page)
        self.assertIn('sortSignals(incoming, DEFAULT_SORT)', page)
        self.assertIn('mergeSignals(prevRows, [incoming], DEFAULT_SORT)', page)
        self.assertIn('function sortFieldValue', page)
        self.assertIn('function qualityCell', page)
        self.assertIn("qualityCell(row.score100, 'score')", page)
        self.assertIn("qualityCell(row.conf_pct, 'conf')", page)
        self.assertIn('Math.max(6, pct)', page)
        self.assertIn("'н/д'", page)
        self.assertIn("bentoBlockTitle('HEADER_MARKET_CONTEXT'", page)
        self.assertIn("bentoBlockTitle('FILTER_BAR'", page)
        self.assertIn("bentoBlockTitle('TABLE_SIGNALS_PRO'", page)
        self.assertIn('WATCH trigger', drawer)
        self.assertIn('DecisionTraceCard', drawer)
        self.assertIn('signal.watch_trigger', drawer)
        self.assertIn('DecisionTraceCard', drawer)
        self.assertIn('Не хватает до BUY', trace)
        self.assertIn('Нормализованные', trace)

    def test_screeners_page_has_required_tabs(self):
        page = (FRONT / 'src' / 'pages' / 'ScreenersPage.tsx').read_text(encoding='utf-8')
        self.assertIn("../../../config/screeners/screeners_page_pro_ui_mapping_unified_v1.json", page)
        self.assertIn('SCREENER_TYPE_OPTIONS', page)
        self.assertIn('getScreenersFeed', page)
        self.assertIn('subscribeScreenersStream', page)
        self.assertIn('Decision Trace', page)
        self.assertIn('screenerColumns', page)
        self.assertIn('SCREENERS_UI.columns', page)
        for col in ['Возраст', 'Скринер', 'Вариант', 'Цена', 'Floor', 'Fair', 'Недооценка', 'Профит', 'EdgeRank', 'Score', 'Conf', 'Ликвидность', 'Поглощение 30м', 'Давление', 'Глубина', 'Режим', 'Действие']:
            self.assertIn(col, page)
        self.assertIn('firstLoadRef', page)
        self.assertIn('refreshing', page)
        self.assertIn("const SCREENERS_CACHE_KEY = 'gmz.screeners.cache.v1'", page)
        self.assertIn('sessionStorage.getItem(SCREENERS_CACHE_KEY)', page)
        self.assertIn('sessionStorage.setItem(SCREENERS_CACHE_KEY, JSON.stringify(payload))', page)

    def test_settings_page_contains_alerts_v1_controls(self):
        page = (FRONT / 'src' / 'pages' / 'SettingsPage.tsx').read_text(encoding='utf-8')
        self.assertIn('Alerts v1', page)
        self.assertIn('getAlertsV1', page)
        self.assertIn('upsertAlertV1', page)
        self.assertIn('rule_json', page)
        self.assertIn('Telegram delivery', page)
        self.assertIn("type SettingsTab = 'general' | 'telegram' | 'admin'", page)
        self.assertIn("const TELEGRAM_DELIVERY_ALLOWED_USER_ID = '144832201'", page)
        self.assertIn("const SETTINGS_ADMIN_ALLOWED_USER_ID = '44832201'", page)
        self.assertIn('AdminPage', page)
        self.assertIn("activeTab === 'telegram' && telegramDeliveryAllowed", page)
        self.assertIn("activeTab === 'admin' && adminTabAllowed", page)
        self.assertIn('getAdminTelegramDeliveryConfig', page)
        self.assertIn('getAdminTelegramDeliveryStatus', page)
        self.assertIn('getAdminTelegramDeliveryJournal', page)
        self.assertIn('getTelegramAuthMe', page)
        self.assertIn('saveAdminTelegramDeliveryConfig', page)
        self.assertIn('resetAdminTelegramDeliveryConfig', page)
        self.assertIn('postAdminTelegramDeliveryTest', page)
        for token in ['EdgeRank ≥', 'Conf ≥', 'Profit % ≥', 'Изображение подарка в сигнале', 'Тест gift_signal', 'Тест market_status', 'Журнал отправок', 'Ошибки доставки', 'Market channel_id', 'Gift channel_id', 'Timeout sec', 'Dedupe TTL sec', 'Current gate pass', 'Recommended pass', 'Применить recommended gate']:
            self.assertIn(token, page)
        self.assertNotIn('Telegram delivery доступен только для Telegram user ID `144832201`.', page)
        for token in ['AutoSell PRO', 'Сохранить AutoSell rule', 'Trading / AutoSell сейчас открыт только для тестовой Telegram учетной записи `144832201`', 'SIGNAL_EXIT', 'AUTO_LIST', 'AUTO_SELL_NOW', 'Take Profit %', 'Stop Loss %', 'Trailing %', 'Regime list (CSV)']:
            self.assertIn(token, page)

    def test_trades_page_contains_trading_workspace_blocks(self):
        page = (FRONT / 'src' / 'pages' / 'TradesPage.tsx').read_text(encoding='utf-8')
        for token in ['FAST BUY', 'BUY+LIST', 'PnL PRO', 'Positions', 'Holdings', 'History', 'Wallet activity', 'AutoSell rules', 'LIST', 'CANCEL', 'SELL', 'TRANSFER', 'Повторить выставление', 'optimisticHistory', 'subscribeTradesStream', 'subscribePnlStream', 'seenSseKeysRef', 'scheduleSseRefresh', 'refreshWorkspace', 'stableJson', 'mockTonConnectEnabled', 'VITE_TRADE_MOCK_TONCONNECT', 'mock_tonconnect', 'decision_trace', 'reasons:', 'risk_flags:', 'sendTransaction', 'payload_hash', 'Holding не найден для выбранного варианта.', 'Подключите TON wallet перед отправкой транзакции.', 'expandedPositionId', 'expandedHoldingId', 'listing_meta:', 'transfer_meta:', 'Коллекция', 'Модель', 'Фон', 'Узор', 'variant_id будет выбран автоматически', 'resolveVariantByTraits', 'getCollections', 'getVariants', 'GmzSelect']:
            self.assertIn(token, page)
        for token in ['useLocation', 'location.search', 'variant_id', 'collection_id', 'selectedCollectionId', 'tradePrefill']:
            self.assertIn(token, page)

    def test_favorites_page_uses_non_blocking_refresh(self):
        page = (FRONT / 'src' / 'pages' / 'FavoritesPage.tsx').read_text(encoding='utf-8')
        self.assertIn('firstLoadRef', page)
        self.assertIn('refreshing', page)
        self.assertIn('Обновляем данные…', page)

    def test_catalog_has_all_trait_filters(self):
        page = (FRONT / 'src' / 'pages' / 'CatalogPage.tsx').read_text(encoding='utf-8')
        self.assertIn('Коллекция', page)
        self.assertIn('Модель', page)
        self.assertIn('Фон', page)
        self.assertIn('Узор', page)
        self.assertIn('side_panel?.data_source', page)
        self.assertIn('sidePanelVariantEndpoint', page)
        self.assertIn('Возраст', page)
        self.assertIn('GmzSelect', page)
        self.assertIn('firstLoadRef', page)
        self.assertIn('refreshing', page)
        self.assertIn("const CATALOG_CACHE_KEY = 'gmz.catalog.cache.v1'", page)
        self.assertIn('sessionStorage.getItem(CATALOG_CACHE_KEY)', page)
        self.assertIn('sessionStorage.setItem(CATALOG_CACHE_KEY, JSON.stringify(payload))', page)
        self.assertIn('subscribeRealtime', page)
        self.assertIn("types: ['market.status']", page)
        required_cols = [
            'Вариант',
            'Floor',
            'Fair',
            'Недооценка',
            'Профит',
            'EdgeRank',
            'Conf',
            'Ликвидность',
            'Поглощение 30м',
            'Давление (LP)',
            'Глубина',
            'Активные лоты',
            'Доля в продаже',
            'Режим',
            'Действие',
            'Обновлено',
            'Возраст',
        ]
        for col in required_cols:
            self.assertIn(col, page)
        for token in [
            'Поглощение 30м',
            'Давление (LP)',
            'Глубина',
            'Активные лоты',
            'Доля в продаже',
            'Режим',
            'Листинги 10м',
            'Объем 24ч (TON)',
            'buildTradesHref',
            'Купить+выставить',
            "to={`/variant/${encodeURIComponent(row.variant_id)}`",
        ]:
            self.assertIn(token, page)

    def test_variant_page_exposes_trade_entry_points(self):
        page = (FRONT / 'src' / 'pages' / 'VariantPage.tsx').read_text(encoding='utf-8')
        for token in ['buildTradesHref', 'tradeBuyHref', 'tradeBuyListHref', 'Купить', 'Купить+выставить', "intent: 'BUY'", "intent: 'BUY_AND_LIST'"]:
            self.assertIn(token, page)

    def test_listing_page_has_pro_new_race_blocks(self):
        page = (FRONT / 'src' / 'pages' / 'ListingPage.tsx').read_text(encoding='utf-8')
        self.assertIn('GmzSelect', page)
        self.assertIn('PRO Фильтры', page)
        self.assertIn('Сигналы листинга', page)
        self.assertIn('NEW Scanner', page)
        self.assertIn('RACE Scanner', page)
        self.assertIn('Execution Health', page)
        self.assertIn('getListingSignals', page)
        self.assertIn('row.preview_url', page)
        self.assertIn('source_error', page)
        self.assertIn('marketSourceWarning', page)
        self.assertIn('refreshTimerRef', page)
        self.assertIn('window.setTimeout', page)
        self.assertIn('Promise.allSettled', page)
        self.assertIn('windowKeyToSec', page)
        self.assertIn('parseSortSpec', page)
        self.assertIn('newSortSpec', page)
        self.assertIn('raceSortSpec', page)
        self.assertIn('default_sort', page)
        self.assertIn("FILTER_BAR')?.filters", page)
        self.assertIn('normalizeFilterId', page)
        self.assertIn('canonicalFilterId', page)
        self.assertIn('hasProFilter', page)
        self.assertIn('executionHealthMetrics', page)
        self.assertIn('presetItems', page)
        self.assertIn('LISTING_PROFILE_PRESETS', page)
        self.assertIn('selectedPreset', page)
        self.assertIn('listingSignalColumns', page)
        self.assertIn('listingSignalSortSpec', page)
        self.assertIn('LISTING_SIGNALS_COLUMN_LABELS', page)
        self.assertIn('sortedListingSignals', page)
        self.assertIn('listingKeyFromRow', page)
        self.assertIn('streamBurstRef', page)
        self.assertIn('firstLoadRef', page)
        self.assertIn('refreshing', page)
        self.assertIn("if (evt.type === 'listing.new')", page)
        self.assertIn("if (evt.type === 'listing.removed')", page)
        self.assertIn('subscribeSignalsStream', page)
        self.assertIn('signal.created', (FRONT / 'src' / 'lib' / 'api.ts').read_text(encoding='utf-8'))
        self.assertIn("age: 'Возраст'", page)
        self.assertIn("variant_label: 'Вариант'", page)
        self.assertIn("price_ton: 'Цена'", page)
        self.assertIn("market_regime_badge: 'Режим'", page)
        self.assertIn("action: 'Действие'", page)

    def test_listing_page_uses_direct_listing_source_status_for_realtime_availability(self):
        page = (FRONT / 'src' / 'pages' / 'ListingPage.tsx').read_text(encoding='utf-8')
        api = (FRONT / 'src' / 'lib' / 'api.ts').read_text(encoding='utf-8')
        contract = (FRONT / 'src' / 'lib' / 'openapi.ts').read_text(encoding='utf-8')
        self.assertIn('getListingSourceStatus', page)
        self.assertIn('listingSourceStatus', page)
        self.assertIn('listingPrimaryRealtimeAvailable', page)
        self.assertIn("const src = String(listingSourceStatus?.source || '').trim().toLowerCase()", page)
        self.assertIn("MetricTile label=\"Источник\" value={String(listingSourceStatus?.source || marketStatus?.source || 'n/a')}", page)
        self.assertIn("String(listingSourceStatus?.last_error || listingSourceStatus?.error || '').trim()", page)
        self.assertIn("if (!listingPrimaryRealtimeAvailable) return false", page)
        self.assertIn("NEW Scanner требует MTProto источник", page)
        self.assertIn("RACE Scanner требует MTProto источник", page)
        self.assertIn("listingsSourceStatus: '/v1/listings/source-status'", contract)
        self.assertIn('export async function getListingSourceStatus(): Promise<ListingSourceStatusResponse>', api)
        self.assertIn("return await apiGet<ListingSourceStatusResponse>(OPENAPI_V1.listingsSourceStatus)", api)
        self.assertIn("return apiGet<ListingSourceStatusResponse>('/api/listing/source-status')", api)

    def test_listing_page_merges_stream_signals_instead_of_ignoring_after_first_row(self):
        page = (FRONT / 'src' / 'pages' / 'ListingPage.tsx').read_text(encoding='utf-8')
        api_types = (FRONT / 'src' / 'types' / 'api.ts').read_text(encoding='utf-8')
        self.assertIn("setListingSignals((prev) => normalizeListingSignalsRows([sig, ...prev], 120))", page)
        self.assertNotIn("if (prev.length > 0) return prev", page)
        self.assertIn("setListingSignals((prev) => prev.filter((x) => {", page)
        self.assertIn("String(x.listing_key || '').trim() === listingKey", page)
        self.assertIn('listing_key?: string', api_types)

    def test_listing_page_prefers_backend_signal_created_over_synthetic_listing_signal(self):
        page = (FRONT / 'src' / 'pages' / 'ListingPage.tsx').read_text(encoding='utf-8')
        self.assertNotIn('function isSyntheticListingSignal', page)
        self.assertNotIn('function sameListingSignalIdentity', page)
        self.assertIn('subscribeSignalsStream', page)
        self.assertIn("setListingSignals((prev) => normalizeListingSignalsRows([sig, ...prev], 120))", page)

    def test_listing_page_synthetic_signal_maps_extended_runtime_fields(self):
        page = (FRONT / 'src' / 'pages' / 'ListingPage.tsx').read_text(encoding='utf-8')
        self.assertNotIn('listing.synthetic:', page)
        self.assertIn('sortedListingSignals', page)
        self.assertIn('LISTING_SIGNALS_COLUMN_LABELS', page)

    def test_listing_page_is_config_driven_by_new_listings_bento_contract(self):
        page = (FRONT / 'src' / 'pages' / 'ListingPage.tsx').read_text(encoding='utf-8')
        self.assertTrue((ROOT / 'config' / 'listing' / 'bento_ui_blocks_new_listings.json').exists())
        self.assertTrue((ROOT / 'config' / 'listing' / 'signal_profiles_by_regime.json').exists())
        self.assertIn("../../../config/listing/bento_ui_blocks_new_listings.json", page)
        self.assertIn("../../../config/listing/signal_profiles_by_regime.json", page)
        self.assertIn('LISTING_BENTO', page)
        self.assertIn('LISTING_PROFILE_PRESETS', page)
        self.assertIn('TABLE_NEW_LISTINGS', page)
        self.assertIn('TABLE_LISTING_SIGNALS', page)
        self.assertIn('TABLE_RACE_MODE', page)
        self.assertIn('MARKET_STATUS_ENDPOINT', page)
        self.assertIn('LISTINGS_SIGNALS_ENDPOINT', page)
        self.assertIn('LISTINGS_NEW_ENDPOINT', page)
        self.assertIn('LISTINGS_RACE_ENDPOINT', page)
        self.assertIn('LISTINGS_STREAM_EVENTS', page)
        self.assertIn('pageTitleFromBento', page)
        self.assertIn('pageSubtitleFromBento', page)
        self.assertIn('PageHeader title={pageTitle} subtitle={pageSubtitle}', page)

    def test_admin_page_present_and_uses_admin_endpoints(self):
        page = (FRONT / 'src' / 'pages' / 'AdminPage.tsx').read_text(encoding='utf-8')
        self.assertIn('PageHeader title="Админ"', page)
        self.assertIn('getAdminAccess', page)
        self.assertIn('getAdminRefreshStatus', page)
        self.assertIn('getAdminFormulaGatesStatus', page)
        self.assertIn('getAdminRuntimeHttpMetrics', page)
        self.assertIn('resetAdminRuntimeHttpMetrics', page)
        self.assertIn('getAlertsV1', page)
        self.assertIn('postAlertTestV1', page)
        self.assertIn('getAdminSignalEngineConfig', page)
        self.assertIn('saveAdminSignalEngineConfig', page)
        self.assertIn('resetAdminSignalEngineConfig', page)
        self.assertIn('getAdminSignalPreview', page)
        self.assertIn('triggerAdminRefresh', page)
        self.assertIn('interface AdminCachePayload', page)
        self.assertIn("const ADMIN_CACHE_KEY = 'gmz.admin.cache.v1'", page)
        self.assertIn('readUiAutoRefreshMinutes', page)
        self.assertIn('uiAutoRefreshMs', page)
        self.assertIn('sessionStorage.getItem(ADMIN_CACHE_KEY)', page)
        self.assertIn('sessionStorage.setItem(ADMIN_CACHE_KEY, JSON.stringify(payload))', page)
        self.assertIn('Promise.allSettled([loadConfig(), loadSignals(), loadOpsStatus(), preloadAlertRule()])', page)
        self.assertIn('Обновляем admin-данные в фоне…', page)

    def test_overview_has_advanced_bento_blocks(self):
        page = (FRONT / 'src' / 'pages' / 'OverviewPage.tsx').read_text(encoding='utf-8')
        for title in [
            'Поток рынка',
            'Киты и глубина',
            'График объема',
            'График ликвидности',
            'Тепловая карта ликвидности',
            'Лидеры движения',
            'Шок предложения',
            'Перегрев',
            'Топ BUY сигналы',
            'Топ SELL сигналы',
        ]:
            self.assertIn(title, page)
        self.assertIn('Давление листинга', page)
        self.assertIn('Реалтайм floor', page)
        self.assertIn('Волатильность', page)
        self.assertIn("(['6h', '24h'] as TimeframeKey[])", page)
        self.assertIn('<BentoGrid', page)
        self.assertIn('marketStatusSnapshot', page)
        self.assertIn('getMarketStatus', page)
        self.assertIn("from '../lib/bentoContracts'", page)
        self.assertIn("bentoTimeframes('overview'", page)
        self.assertIn("bentoBlockMetrics('overview'", page)
        self.assertIn("bentoPageMetrics('overview'", page)
        self.assertIn("bentoBlockTitle('overview', 'top_buy'", page)
        self.assertIn("bentoBlockSource('overview', 'top_buy'", page)
        self.assertIn("bentoBlockControlNumber('overview', 'top_buy'", page)
        self.assertIn("bentoBlockTitle('overview', 'market_index'", page)
        self.assertIn("bentoBlockTitle('overview', 'market_flow'", page)
        self.assertIn("bentoBlockTitle('overview', 'whales'", page)
        self.assertIn('signalTypeFromSource', page)
        self.assertIn('overviewMarketIndexMetrics', page)
        self.assertIn('overviewMarketFlowMetrics', page)
        self.assertIn('loadVolumeChartOnly', page)
        self.assertIn('loadLiquidityChartOnly', page)
        self.assertIn('loadHeatmapOnly', page)
        self.assertIn('coreFirstLoadRef', page)
        self.assertIn('metricsFirstLoadRef', page)
        self.assertIn('coreRefreshing', page)
        self.assertIn('metricsRefreshing', page)
        self.assertIn('prevTfVolumeRef', page)
        self.assertIn('prevTfLiquidityRef', page)
        self.assertIn('prevTfHeatmapRef', page)

    def test_variant_has_advanced_metric_blocks(self):
        page = (FRONT / 'src' / 'pages' / 'VariantPage.tsx').read_text(encoding='utf-8')
        for title in [
            'Ценообразование',
            'Риск',
            'История минимальной цены (floor)',
            'График объема',
            'График ликвидности',
            'График предложения',
            'Глубина и стенка',
            'Новые листинги',
            'Киты',
            'Редкость',
            'Лента листингов',
        ]:
            self.assertIn(title, page)
        self.assertIn("(['1h', '6h', '24h', '7d'] as TimeframeKey[])", page)
        self.assertIn("(['6h', '24h'] as TimeframeKey[])", page)
        self.assertIn('<BentoGrid', page)
        self.assertIn("from '../lib/bentoContracts'", page)
        self.assertIn("bentoTimeframes('variant'", page)
        self.assertIn("bentoPageMetrics('variant'", page)
        self.assertIn("bentoBlockTitle('variant', 'pricing'", page)
        self.assertIn("bentoBlockTitle('variant', 'risk'", page)
        self.assertIn("bentoBlockTitle('variant', 'listing_feed'", page)
        self.assertIn('variantMetricsFromBento', page)
        self.assertIn('loadFloorSeriesOnly', page)
        self.assertIn('loadVolumeSeriesOnly', page)
        self.assertIn('loadLiquiditySeriesOnly', page)
        self.assertIn('loadHeatSeriesOnly', page)
        self.assertIn('detailsFirstLoadRef', page)
        self.assertIn('metricsFirstLoadRef', page)
        self.assertIn('detailsRefreshing', page)
        self.assertIn('metricsRefreshing', page)
        self.assertIn('prevTfFloorRef', page)
        self.assertIn('prevTfVolumeRef', page)
        self.assertIn('VariantCachePayload', page)
        self.assertIn('sessionStorage.getItem(variantCacheKey)', page)
        self.assertIn('sessionStorage.setItem(variantCacheKey, JSON.stringify(payload))', page)
        self.assertIn('readUiAutoRefreshMinutes', page)
        self.assertIn('uiAutoRefreshMs', page)

    def test_variant_page_has_not_found_fallback_resolution(self):
        page = (FRONT / 'src' / 'pages' / 'VariantPage.tsx').read_text(encoding='utf-8')
        self.assertIn('variant_not_found_or_not_active', page)
        self.assertIn('variantFallback', page)
        self.assertIn('resolveVariantByFallback', page)
        self.assertIn('resolveVariantByTraits', page)

    def test_signal_card_prefers_server_stars_fields(self):
        card = (FRONT / 'src' / 'components' / 'SignalCard.tsx').read_text(encoding='utf-8')
        self.assertIn('signal.floor_stars', card)
        self.assertIn('signal.price_stars', card)

    def test_signal_card_has_safe_score_conf_fallbacks(self):
        card = (FRONT / 'src' / 'components' / 'SignalCard.tsx').read_text(encoding='utf-8')
        self.assertIn('finiteOrNull', card)
        self.assertIn('scoreMuted', card)
        self.assertIn('confMuted', card)
        self.assertIn("score === null ? 'н/д'", card)
        self.assertIn("conf === null ? 'н/д'", card)
        self.assertIn('~${score.toFixed(1)}%', card)
        self.assertIn('~${conf.toFixed(1)}%', card)

    def test_react_index_uses_custom_favicon(self):
        index = (FRONT / 'index.html').read_text(encoding='utf-8')
        self.assertIn('/favicon.png', index)
        self.assertTrue((FRONT / 'public' / 'tonconnect-manifest.json').exists())

    def test_main_uses_global_error_boundary(self):
        main = (FRONT / 'src' / 'main.tsx').read_text(encoding='utf-8')
        boundary = (FRONT / 'src' / 'components' / 'AppErrorBoundary.tsx').read_text(encoding='utf-8')
        self.assertIn('AppErrorBoundary', main)
        self.assertIn('<AppErrorBoundary>', main)
        self.assertIn('Ошибка интерфейса', boundary)
        self.assertIn('Попробовать снова', boundary)

    def test_api_uses_openapi_contract_module(self):
        api = (FRONT / 'src' / 'lib' / 'api.ts').read_text(encoding='utf-8')
        contract = (FRONT / 'src' / 'lib' / 'openapi.ts').read_text(encoding='utf-8')
        self.assertIn("from './openapi'", api)
        self.assertIn('OPENAPI_V1', api)
        self.assertIn('variantDetailsPath', api)
        self.assertIn('variantsResolve', contract)
        self.assertIn('resolveVariantByTraits', api)
        self.assertIn("overview: '/v1/overview'", contract)
        self.assertIn('/api/market/overview', api)
        self.assertIn('ENABLE_LEGACY_MARKET_OVERVIEW_FALLBACK', api)
        self.assertIn('if (ENABLE_LEGACY_MARKET_OVERVIEW_FALLBACK)', api)
        self.assertIn("withMode(OPENAPI_V1.overview)", api)
        self.assertIn('mapLegacyOverviewToMarketStatus', api)
        self.assertIn('mapV1OverviewToMarketStatus', api)
        self.assertNotIn("source: 'fallback.empty'", api)
        self.assertNotIn("source: 'v1.signals_fallback'", api)
        self.assertIn('normalizeListingsFeed', api)
        self.assertIn('normalizeListingsRaceFeed', api)
        self.assertIn('normalizeListingSignals', api)
        self.assertIn('normalizeListingsHistory', api)
        self.assertIn('API_TIMEOUT_MS', api)
        self.assertIn('API_RETRY_COUNT', api)
        self.assertIn('TRANSIENT_HTTP_CODES', api)
        self.assertIn('/api/auth/ton/challenge', api)
        self.assertIn('/api/auth/ton/verify', api)
        self.assertIn('/api/auth/ton/logout', api)
        self.assertIn('/api/auth/ton/balance', api)
        self.assertIn('/v1/alerts/test', api)
        self.assertIn('const pickNum = (...keys: string[]): number | null => {', api)
        self.assertIn("pickNum('conf_pct', 'confidence_pct', 'confidence')", api)
        self.assertIn("pickNum('score100', 'score_pct', 'score')", api)
        self.assertIn("pickNum('price_ton', 'price', 'listing_price_ton', 'last_price_ton')", api)

    def test_react_metric_mapping_is_canonical_and_validated(self):
        catalog = (FRONT / 'src' / 'lib' / 'metricsCatalog.ts').read_text(encoding='utf-8')
        api = (FRONT / 'src' / 'lib' / 'api.ts').read_text(encoding='utf-8')
        bento = (FRONT / 'src' / 'lib' / 'bentoContracts.ts').read_text(encoding='utf-8')
        self.assertTrue((CONTRACTS / 'frontend_metrics_mapping.json').exists())
        self.assertIn("../../../config/contracts/frontend_metrics_mapping.json", catalog)
        self.assertIn('assertMetricAllowedByMapping', api)
        self.assertIn('normalizeMetricName', api)
        self.assertIn('export function bentoPageMetrics', bento)
        self.assertIn('export function bentoBlockTitle', bento)
        self.assertIn('export function bentoBlockSource', bento)
        self.assertIn('export function bentoBlockControlNumber', bento)


if __name__ == '__main__':
    unittest.main()
