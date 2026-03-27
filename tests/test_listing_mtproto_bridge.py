import unittest

from listing_mtproto_bridge import MTProtoListingBridgeState


class TestListingMtprotoBridge(unittest.TestCase):
    def test_removed_requires_confirmed_misses(self) -> None:
        state = MTProtoListingBridgeState()
        state.removed_confirm_misses = 3
        key = "berryboxes:123"
        now_iso = "2026-03-04T00:00:00Z"
        state.dataset = {
            "updated_at": now_iso,
            "items": [
                {
                    "listing_key": key,
                    "gift_type_id": "42",
                    "gift_id": "berryboxes",
                    "collection_id": "berryboxes",
                    "unique_id": "123",
                    "variant_id": "berryboxes|clarity|black|baphomet",
                    "resell_amount_ton": 10.0,
                }
            ],
        }
        state.tracker_by_key[key] = {
            "first_seen_at": now_iso,
            "last_seen_at": now_iso,
            "relist_count": 0,
            "active": True,
            "last_relisted_at": None,
            "absent_streak": 0,
        }

        out1 = state._apply_tracker([], polled_gift_type_ids={"42"}, full_scan=True)  # noqa: SLF001
        self.assertEqual(len(out1), 1)
        self.assertEqual(int(state.tracker_by_key[key].get("absent_streak") or 0), 1)

        out2 = state._apply_tracker([], polled_gift_type_ids={"42"}, full_scan=True)  # noqa: SLF001
        self.assertEqual(len(out2), 1)
        self.assertEqual(int(state.tracker_by_key[key].get("absent_streak") or 0), 2)

        out3 = state._apply_tracker([], polled_gift_type_ids={"42"}, full_scan=True)  # noqa: SLF001
        self.assertEqual(len(out3), 0)
        self.assertFalse(bool(state.tracker_by_key[key].get("active")))


if __name__ == "__main__":
    unittest.main()

