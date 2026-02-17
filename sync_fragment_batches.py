from __future__ import annotations

import json
import math
import os
import ssl
import urllib.request
from datetime import datetime

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
    output_file = os.getenv("VERIFIED_DATA_FILE", "").strip() or "data/verified_gifts.json"
    ssl_no_verify = os.getenv("FRAGMENT_SSL_NO_VERIFY", "").strip().lower() in {"1", "true", "yes", "on"}
    if ssl_no_verify:
        os.environ["FRAGMENT_SSL_NO_VERIFY"] = "true"

    ssl_context = ssl._create_unverified_context() if ssl_no_verify else ssl.create_default_context()
    req = urllib.request.Request(root_url, method="GET")
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; GiftMarketZone/1.0)")
    with urllib.request.urlopen(req, timeout=timeout_sec, context=ssl_context) as resp:
        root_html = resp.read().decode("utf-8", errors="replace")
    total_collections = len(_fragment_parse_collections(root_html))
    if total_collections <= 0:
        raise RuntimeError("No collections found on Fragment")

    gifts_map: dict[str, dict] = {}
    filters_agg = {"collections": [], "models": {}, "backdrops": {}, "symbols": {}}

    total_batches = math.ceil(total_collections / batch_size)
    for b in range(total_batches):
        start = b * batch_size
        dataset = fetch_verified_dataset_from_fragment(
            root_url=root_url,
            timeout_sec=timeout_sec,
            max_collections=batch_size,
            max_pages_per_collection=pages_per_collection,
            collection_start=start,
        )
        for g in dataset.get("gifts", []):
            gifts_map[g["gift_id"]] = g
        _merge_filters(filters_agg, dataset.get("filters") or {})

        partial = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "gifts": sorted(gifts_map.values(), key=lambda x: x.get("gift_id", "")),
            "filters": filters_agg,
        }
        save_verified_dataset(partial, output_file)
        print(json.dumps({
            "ok": True,
            "batch": b + 1,
            "total_batches": total_batches,
            "collections_done": min(start + batch_size, total_collections),
            "collections_total": total_collections,
            "gifts": len(partial["gifts"]),
            "output": output_file,
        }, ensure_ascii=False))

    final = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "gifts": sorted(gifts_map.values(), key=lambda x: x.get("gift_id", "")),
        "filters": filters_agg,
    }
    save_verified_dataset(final, output_file)
    print(json.dumps({
        "ok": True,
        "status": "completed",
        "collections_total": total_collections,
        "gifts": len(final["gifts"]),
        "output": output_file,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
