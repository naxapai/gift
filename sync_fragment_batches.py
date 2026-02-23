from __future__ import annotations

import json
import math
import os
import ssl
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from market_data import _fragment_parse_collections, fetch_verified_dataset_from_fragment, save_verified_dataset


def _merge_filters(dst: dict, src: dict) -> None:
    for key in ("models", "backdrops", "symbols"):
        s = src.get(key) if isinstance(src, dict) else {}
        d = dst.setdefault(key, {})
        if isinstance(s, dict):
            for k, v in s.items():
                d[k] = int(d.get(k, 0)) + int(v)

    dst_cols = {c.get("slug"): c for c in dst.get("collections", []) if c.get("slug")}
    for c in src.get("collections", []) if isinstance(src, dict) else []:
        slug = c.get("slug")
        if slug and slug not in dst_cols:
            dst_cols[slug] = c
    dst["collections"] = sorted(dst_cols.values(), key=lambda x: x.get("name", ""))


def main() -> None:
    root_url = os.getenv("FRAGMENT_GIFTS_URL", "https://fragment.com/gifts").strip()
    timeout_sec = int(os.getenv("VERIFIED_API_TIMEOUT_SEC", "10"))
    pages_per_collection = int(os.getenv("FRAGMENT_MAX_PAGES_PER_COLLECTION", "1"))
    batch_size = int(os.getenv("FRAGMENT_BATCH_SIZE", "10"))
    batch_retries = int(os.getenv("FRAGMENT_BATCH_RETRIES", "5"))
    resume_enabled = os.getenv("FRAGMENT_RESUME", "true").strip().lower() in {"1", "true", "yes", "on"}
    output_file = os.getenv("VERIFIED_DATA_FILE", "").strip() or "data/verified_gifts.json"
    wip_output_file = os.getenv("VERIFIED_DATA_WIP_FILE", "").strip() or f"{output_file}.wip"
    full_backup_file = os.getenv("VERIFIED_FULL_BACKUP_FILE", "").strip() or "data/verified_gifts_full_sync.json"
    state_file = os.getenv("FRAGMENT_SYNC_STATE_FILE", "").strip() or "data/fragment_sync_state.json"
    min_promote_gifts = int(os.getenv("FRAGMENT_MIN_PROMOTE_GIFTS", "500"))
    min_promote_ratio = float(os.getenv("FRAGMENT_MIN_PROMOTE_RATIO", "0.5"))
    ssl_no_verify = os.getenv("FRAGMENT_SSL_NO_VERIFY", "").strip().lower() in {"1", "true", "yes", "on"}
    if ssl_no_verify:
        os.environ["FRAGMENT_SSL_NO_VERIFY"] = "true"

    ssl_context = ssl._create_unverified_context() if ssl_no_verify else ssl.create_default_context()
    req = urllib.request.Request(root_url, method="GET")
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; GiftMarketZone/1.0)")
    root_html = ""
    last_root_error = ""
    for attempt in range(1, max(1, batch_retries) + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec, context=ssl_context) as resp:
                root_html = resp.read().decode("utf-8", errors="replace")
            break
        except Exception as e:
            last_root_error = str(e)
            time.sleep(min(20, attempt * 2))
    if not root_html:
        raise RuntimeError(f"Failed to load {root_url}: {last_root_error}")
    total_collections = len(_fragment_parse_collections(root_html))
    if total_collections <= 0:
        raise RuntimeError("No collections found on Fragment")

    gifts_map: dict[str, dict] = {}
    filters_agg = {"collections": [], "models": {}, "backdrops": {}, "symbols": {}}
    meta_agg = {
        "gift_mode": "",
        "total_for_sale": 0,
        "total_sold": 0,
        "total_auction": 0,
        "collections_used": 0,
    }
    previous_gifts_count = 0

    total_batches = math.ceil(total_collections / batch_size)
    start_batch = 0
    state_path = Path(state_file)
    if resume_enabled and state_path.exists():
        try:
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            start_batch = int(saved.get("next_batch", 0) or 0)
        except Exception:
            start_batch = 0
    if total_batches > 0:
        start_batch = max(0, min(start_batch, total_batches - 1))

    # Resume from partial WIP only when state says we're in the middle of a run.
    if resume_enabled and start_batch > 0 and os.path.exists(wip_output_file):
        try:
            with open(wip_output_file, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
            previous_gifts_count = len(existing.get("gifts") or [])
            for gift in existing.get("gifts", []):
                gift_id = gift.get("gift_id")
                if gift_id:
                    gifts_map[gift_id] = gift
            _merge_filters(filters_agg, existing.get("filters") or {})
            existing_meta = existing.get("meta") if isinstance(existing, dict) else {}
            meta_agg["gift_mode"] = str((existing_meta or {}).get("gift_mode") or "")
            meta_agg["total_for_sale"] = int((existing_meta or {}).get("total_for_sale") or 0)
            meta_agg["total_sold"] = int((existing_meta or {}).get("total_sold") or 0)
            meta_agg["total_auction"] = int((existing_meta or {}).get("total_auction") or 0)
            meta_agg["collections_used"] = int((existing_meta or {}).get("collections_used") or 0)
        except Exception:
            pass
    elif os.path.exists(output_file):
        # Baseline only for promote-threshold checks.
        try:
            with open(output_file, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
            previous_gifts_count = len(existing.get("gifts") or [])
        except Exception:
            previous_gifts_count = 0

    batch_order = list(range(start_batch, total_batches)) + list(range(0, start_batch))
    print(json.dumps({
        "ok": True,
        "status": "sync_start",
        "collections_total": total_collections,
        "total_batches": total_batches,
        "start_batch": start_batch + 1,
    }, ensure_ascii=False))

    failed_batches: list[dict[str, str | int]] = []
    for b in batch_order:
        start = b * batch_size
        dataset = None
        last_error = ""
        for attempt in range(1, max(1, batch_retries) + 1):
            try:
                dataset = fetch_verified_dataset_from_fragment(
                    root_url=root_url,
                    timeout_sec=timeout_sec,
                    max_collections=batch_size,
                    max_pages_per_collection=pages_per_collection,
                    collection_start=start,
                )
                break
            except Exception as e:
                last_error = str(e)
                print(json.dumps({
                    "ok": False,
                    "batch": b + 1,
                    "attempt": attempt,
                    "error": last_error,
                    "action": "retry",
                }, ensure_ascii=False))
                time.sleep(min(20, attempt * 2))
        if dataset is None:
            failed_batches.append({"batch": b + 1, "error": last_error})
            continue
        for g in dataset.get("gifts", []):
            gifts_map[g["gift_id"]] = g
        _merge_filters(filters_agg, dataset.get("filters") or {})
        ds_meta = dataset.get("meta") if isinstance(dataset, dict) else {}
        if isinstance(ds_meta, dict):
            if not meta_agg["gift_mode"]:
                meta_agg["gift_mode"] = str(ds_meta.get("gift_mode") or "")
            meta_agg["total_for_sale"] += int(ds_meta.get("total_for_sale") or 0)
            meta_agg["total_sold"] += int(ds_meta.get("total_sold") or 0)
            meta_agg["total_auction"] += int(ds_meta.get("total_auction") or 0)
            meta_agg["collections_used"] += int(ds_meta.get("collections_used") or 0)

        partial_meta = {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "collections_total": total_collections,
            "collections_used": int(meta_agg.get("collections_used") or 0),
            "collection_start": 0,
            "max_collections": total_collections,
            "max_pages_per_collection": pages_per_collection,
            "gifts": len(gifts_map),
            "gift_mode": meta_agg.get("gift_mode") or "lot",
            "total_for_sale": int(meta_agg.get("total_for_sale") or 0),
            "total_sold": int(meta_agg.get("total_sold") or 0),
            "total_auction": int(meta_agg.get("total_auction") or 0),
        }
        partial = {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "gifts": sorted(gifts_map.values(), key=lambda x: x.get("gift_id", "")),
            "filters": filters_agg,
            "meta": partial_meta,
        }
        # Never overwrite stable snapshot with partial batches.
        save_verified_dataset(partial, wip_output_file)
        print(json.dumps({
            "ok": True,
            "batch": b + 1,
            "total_batches": total_batches,
            "collections_done": min(start + batch_size, total_collections),
            "collections_total": total_collections,
            "gifts": len(partial["gifts"]),
            "output": wip_output_file,
        }, ensure_ascii=False))
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "next_batch": (b + 1) % max(total_batches, 1),
                        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "collections_total": total_collections,
                        "total_batches": total_batches,
                        "last_batch_done": b + 1,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    final_meta = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "collections_total": total_collections,
        "collections_used": int(meta_agg.get("collections_used") or 0),
        "collection_start": 0,
        "max_collections": total_collections,
        "max_pages_per_collection": pages_per_collection,
        "gifts": len(gifts_map),
        "gift_mode": meta_agg.get("gift_mode") or "lot",
        "total_for_sale": int(meta_agg.get("total_for_sale") or 0),
        "total_sold": int(meta_agg.get("total_sold") or 0),
        "total_auction": int(meta_agg.get("total_auction") or 0),
    }
    final = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "gifts": sorted(gifts_map.values(), key=lambda x: x.get("gift_id", "")),
        "filters": filters_agg,
        "meta": final_meta,
    }
    final_count = len(final["gifts"])
    promote_threshold = 0 if previous_gifts_count <= 0 else max(min_promote_gifts, int(previous_gifts_count * min_promote_ratio))
    can_promote = previous_gifts_count <= 0 or final_count >= promote_threshold
    if can_promote:
        save_verified_dataset(final, output_file)
        save_verified_dataset(final, full_backup_file)
    else:
        # Keep stable snapshot intact if sync result is suspiciously small.
        save_verified_dataset(final, wip_output_file)
    print(json.dumps({
        "ok": len(failed_batches) == 0 and can_promote,
        "status": "completed" if len(failed_batches) == 0 and can_promote else ("completed_not_promoted" if not can_promote else "completed_with_errors"),
        "collections_total": total_collections,
        "gifts": final_count,
        "output": output_file if can_promote else wip_output_file,
        "promoted": can_promote,
        "promote_threshold": promote_threshold,
        "previous_gifts": previous_gifts_count,
        "failed_batches": failed_batches,
    }, ensure_ascii=False))
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "next_batch": 0,
                    "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "collections_total": total_collections,
                    "total_batches": total_batches,
                    "last_batch_done": total_batches,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"ok": False, "status": "fatal_error", "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
        raise
