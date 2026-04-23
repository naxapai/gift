import re
import unittest
from pathlib import Path
import json


ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = ROOT / "static" / "index.html"
STYLES_CSS = ROOT / "static" / "styles.css"
BENTO_BLOCKS_JSON = Path("/Users/nexapai/Downloads/bento_ui_blocks.json")


class TestFrontendBentoTz(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not STYLES_CSS.exists() or not (ROOT / "static" / "app.js").exists():
            raise unittest.SkipTest("legacy static frontend replaced by React build; covered by test_frontend_react_stack")
        cls.html = INDEX_HTML.read_text(encoding="utf-8")
        cls.css = STYLES_CSS.read_text(encoding="utf-8")
        cls.js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    def test_required_pages_exist(self) -> None:
        for page_id in [
            "overview",
            "catalog",
            "screeners",
            "signals",
            "listing",
            "watchlist",
            "variant-details",
        ]:
            self.assertIn(f'id="{page_id}"', self.html)

    def test_overview_bento_blocks_exist(self) -> None:
        required_ids = [
            "heroCard",
            "marketFlowCard",
            "whalesCard",
            "depthVolCard",
            "volumeChartCard",
            "liquidityChartCard",
            "overviewHeatmapCard",
            "overviewSupplyCard",
            "overviewFloorHistoryCard",
            "overviewListingFeedCard",
            "topBuySignalsCard",
            "topSellSignalsCard",
            "providerHealthCard",
            "marketAiSignalCard",
            "kpiFlow",
        ]
        for block_id in required_ids:
            self.assertIn(f'id="{block_id}"', self.html)

    def test_variant_bento_blocks_exist(self) -> None:
        required_ids = [
            "variantTradeKpi",
            "variantPricingKpi",
            "variantRiskKpi",
            "variantVolumeChart",
            "variantLiquidityChart",
            "variantNewListingsKpi",
            "variantListingFeedBody",
            "variantDepthWallKpi",
            "variantWhalesKpi",
            "variantRarityKpi",
            "variantHeatmapBody",
            "variantSupplyChart",
            "variantHeatmapPeriod",
        ]
        for block_id in required_ids:
            self.assertIn(f'id="{block_id}"', self.html)

    def test_bento_blocks_json_mapped_to_dom(self) -> None:
        if not BENTO_BLOCKS_JSON.exists():
            self.skipTest("bento_ui_blocks.json not found")
        blocks = json.loads(BENTO_BLOCKS_JSON.read_text(encoding="utf-8"))
        pages = blocks.get("pages") if isinstance(blocks, dict) else {}
        page_obj = pages if isinstance(pages, dict) else {}
        expected = {
            "overview": {
                "market_index": "heroCard",
                "market_flow": "marketFlowCard",
                "whales": "whalesCard",
                "volume_chart": "volumeChartCard",
                "liquidity_chart": "liquidityChartCard",
                "liquidity_heatmap": "overviewHeatmapCard",
                "supply": "overviewSupplyCard",
                "depth": "depthVolCard",
                "top_buy": "topBuySignalsCard",
                "top_sell": "topSellSignalsCard",
            },
            "variant": {
                "trade": "variantTradeKpi",
                "pricing": "variantPricingKpi",
                "risk": "variantRiskKpi",
                "floor_history": "variantChart",
                "volume_variant": "variantVolumeChart",
                "new_listings": "variantNewListingsKpi",
                "listing_feed": "variantListingFeedBody",
                "depth_wall": "variantDepthWallKpi",
                "whales_variant": "variantWhalesKpi",
                "rarity": "variantRarityKpi",
                "heatmap_variant": "variantHeatmapBody",
                "liquidity_variant": "variantLiquidityChart",
            },
        }
        for page_key, mapping in expected.items():
            page = page_obj.get(page_key) if isinstance(page_obj, dict) else None
            self.assertTrue(isinstance(page, dict), f"page '{page_key}' missing in bento json")
            rows = (((page or {}).get("layout") or {}).get("rows") or [])
            src_ids = {
                str(block.get("id"))
                for row in rows if isinstance(row, dict)
                for block in (row.get("blocks") or [])
                if isinstance(block, dict) and block.get("id")
            }
            for block_id, dom_id in mapping.items():
                self.assertIn(block_id, src_ids, f"block '{block_id}' missing in bento json page '{page_key}'")
                self.assertIn(f'id="{dom_id}"', self.html, f"dom id '{dom_id}' missing for block '{block_id}'")

    def test_signals_filters_and_drawer_exist(self) -> None:
        for node_id in [
            "signalTypeFilter",
            "signalMinScoreFilter",
            "signalMinUndervalueFilter",
            "signalMaxRiskFilter",
            "signalOnlyNewFilter",
            "signalApplyFiltersBtn",
            "signalDrawerOverlay",
            "signalDrawerCalc",
            "signalDrawerReasons",
            "signalDrawerListings",
            "signalDrawerHistoryChart",
        ]:
            self.assertIn(f'id="{node_id}"', self.html)

    def test_signal_drawer_tabs_order(self) -> None:
        order = re.findall(r'class="signal-drawer-tab[^"]*"\s+type="button"\s+data-tab="([^"]+)"', self.html)
        self.assertEqual(order[:4], ["reasons", "calc", "listings", "history"])
        self.assertIn(
            'class="signal-drawer-section active" data-tab-panel="reasons"',
            self.html,
        )

    def test_signals_filters_panel_is_sticky(self) -> None:
        self.assertIn(".signals-grid > .signals-summary-card", self.css)
        self.assertIn("position: sticky;", self.css)
        self.assertIn("#signalsFeed", self.css)
        self.assertIn("overflow-y: auto;", self.css)

    def test_metrics_fetch_is_partial_fail_tolerant(self) -> None:
        self.assertIn("async function fetchMetricPayload(", self.js)
        self.assertIn("fetchMetricPayload(marketMetricUrl(\"WHALE_RATIO\"))", self.js)
        self.assertIn("fetchMetricPayload(variantMetricUrl(\"WHALE_RATIO\", safeVariantId))", self.js)

    def test_realtime_stream_contains_required_events(self) -> None:
        self.assertIn("types=signal.created,metric.updated,listing.event,variant.updated,collection.updated,provider.health", self.js)

    def test_fragment_buy_link_supports_underscore_slug_fallback(self) -> None:
        self.assertIn("const underscored = raw.match(/(?:^|_)([a-z0-9]+)_(\\d+)", self.js)
        self.assertIn("return `${String(underscored[1]).toLowerCase()}-${String(underscored[2])}`;", self.js)

    def test_open_variant_has_404_fallback_resolution(self) -> None:
        self.assertIn("function isVariantNotFoundError(error)", self.js)
        self.assertIn("if (_retry < 1 && isVariantNotFoundError(e))", self.js)
        self.assertIn("const retryVariantId = resolveVariantIdByTraits(", self.js)

    def test_listing_realtime_upsert_exists(self) -> None:
        self.assertIn("function upsertListingSignalFromStream(payload)", self.js)
        self.assertIn("upsertListingSignalFromStream(payload);", self.js)
        self.assertIn("if (activePage === \"listing\") {", self.js)
        self.assertIn("renderListingSignals();", self.js)

    def test_signal_created_does_not_force_full_refresh_on_all_pages(self) -> None:
        self.assertIn("if (activePage === \"overview\") {", self.js)
        self.assertIn("scheduleRealtimeRefresh();", self.js)
        self.assertIn("if (type === \"metric.updated\" || type === \"variant.updated\" || type === \"collection.updated\" || type === \"listing.event\")", self.js)

    def test_signals_use_server_prefilter_for_type_and_score(self) -> None:
        self.assertIn("const f = state.signals.filters || {};", self.js)
        self.assertIn("if (type) params.type = type;", self.js)
        self.assertIn("params.min_score = String(minScoreNorm);", self.js)
        self.assertIn("fetchAllV1Pages(\"/v1/signals\", params, cap)", self.js)

    def test_signals_and_listing_have_loading_guards(self) -> None:
        self.assertIn("loading: {\n    signals: false,\n    listing: false,", self.js)
        self.assertIn("if (state.loading.signals) return;", self.js)
        self.assertIn("if (state.loading.listing) return;", self.js)
        self.assertIn("state.loading.signals = false;", self.js)
        self.assertIn("state.loading.listing = false;", self.js)

    def test_signal_progress_is_always_rendered(self) -> None:
        self.assertIn("const scoreLabel = sparseQuality ? \"н/д\"", self.js)
        self.assertIn("const confLabel = sparseQuality ? \"н/д\"", self.js)
        self.assertIn("class=\"signal-progress ${sparseQuality ? \"is-muted\" : \"\"}\"", self.js)
        self.assertIn(".signal-progress.is-muted .signal-progress-fill", self.css)

    def test_signal_labels_are_russian(self) -> None:
        for token in [
            "КУПИТЬ",
            "ПРОДАТЬ",
            "НАБЛЮДАТЬ",
            "ПРОПУСТИТЬ",
            "Недооценка",
            "Ожидаемая прибыль",
            "Справедливая цена",
            "Уверенность",
            "Прогноз 24ч",
            "Активные лоты",
            "Ликвидность 24ч",
            "Риски",
            "Причины",
            "Купить+выставить",
            "Подробнее",
        ]:
            self.assertIn(token, self.js + self.html)

    def test_listing_placeholders_are_localized(self) -> None:
        for token in [
            'placeholder="Например: artisanbrick"',
            'placeholder="Например: Domino"',
            'placeholder="Например: 30"',
        ]:
            self.assertIn(token, self.html)

    def test_mobile_grid_is_single_column(self) -> None:
        pattern = re.compile(
            r"@media\s*\(max-width:\s*767px\)\s*\{.*?\.bento-grid\s*\{\s*grid-template-columns:\s*minmax\(0,\s*1fr\)\s*;",
            re.S,
        )
        self.assertRegex(self.css, pattern)


if __name__ == "__main__":
    unittest.main()
