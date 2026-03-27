import unittest

from sync_fragment_batches import _promotion_guard


class TestSyncFragmentBatchesPromotionGuard(unittest.TestCase):
    def _base_kwargs(self) -> dict:
        return {
            "previous_gifts_count": 20000,
            "final_count": 19800,
            "baseline_stats": {"gifts": 20000, "collections": 100, "models": 1000, "backdrops": 70, "symbols": 120},
            "final_stats": {"gifts": 19800, "collections": 98, "models": 940, "backdrops": 68, "symbols": 114},
            "failed_batches_count": 0,
            "total_batches": 14,
            "suspicious_collections": 0,
            "min_promote_gifts": 500,
            "min_promote_ratio": 0.5,
            "min_promote_collections_ratio": 0.55,
            "min_promote_models_ratio": 0.45,
            "min_promote_backdrops_ratio": 0.45,
            "min_promote_symbols_ratio": 0.45,
            "max_suspicious_collections": 3,
            "max_failed_batches": 2,
            "max_failed_batch_ratio": 0.05,
            "min_promote_ratio_when_errors": 0.9,
        }

    def test_guard_allows_healthy_snapshot(self) -> None:
        guard = _promotion_guard(**self._base_kwargs())
        self.assertTrue(bool(guard.get("can_promote")))
        self.assertTrue(bool(guard.get("failed_batches_ok")))

    def test_guard_blocks_when_failed_batches_ratio_exceeds_limit(self) -> None:
        kwargs = self._base_kwargs()
        kwargs["failed_batches_count"] = 3
        kwargs["total_batches"] = 14
        kwargs["max_failed_batches"] = 2
        kwargs["max_failed_batch_ratio"] = 0.05
        guard = _promotion_guard(**kwargs)
        self.assertFalse(bool(guard.get("can_promote")))
        self.assertFalse(bool(guard.get("failed_batches_ok")))

    def test_guard_blocks_large_drop_when_errors_present(self) -> None:
        kwargs = self._base_kwargs()
        kwargs["failed_batches_count"] = 1
        kwargs["final_count"] = 15000
        kwargs["min_promote_ratio_when_errors"] = 0.9
        guard = _promotion_guard(**kwargs)
        self.assertFalse(bool(guard.get("can_promote")))
        self.assertFalse(bool(guard.get("ratio_on_errors_ok")))


if __name__ == "__main__":
    unittest.main()

