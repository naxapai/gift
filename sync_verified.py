from __future__ import annotations

import json
from datetime import datetime

from market_data import fetch_verified_dataset_from_api, fetch_verified_dataset_from_fragment, save_verified_dataset


def main() -> None:
    import os

    api_url = os.getenv("VERIFIED_API_URL", "").strip()
    api_token = os.getenv("VERIFIED_API_TOKEN", "").strip()
    token_header = os.getenv("VERIFIED_API_TOKEN_HEADER", "Authorization").strip()
    token_prefix = os.getenv("VERIFIED_API_TOKEN_PREFIX", "Bearer ").strip()
    timeout_sec = int(os.getenv("VERIFIED_API_TIMEOUT_SEC", "25"))
    output_file = os.getenv("VERIFIED_DATA_FILE", "").strip() or None
    source = os.getenv("VERIFIED_SOURCE", "api").strip().lower()

    if source == "fragment":
        root_url = os.getenv("FRAGMENT_GIFTS_URL", "https://fragment.com/gifts").strip()
        max_collections = int(os.getenv("FRAGMENT_MAX_COLLECTIONS", "0"))
        max_pages_per_collection = int(os.getenv("FRAGMENT_MAX_PAGES_PER_COLLECTION", "200"))
        dataset = fetch_verified_dataset_from_fragment(
            root_url=root_url,
            timeout_sec=timeout_sec,
            max_collections=max_collections,
            max_pages_per_collection=max_pages_per_collection,
        )
    else:
        dataset = fetch_verified_dataset_from_api(
            api_url=api_url,
            api_token=api_token,
            timeout_sec=timeout_sec,
            token_header=token_header,
            token_prefix=token_prefix,
        )
    save_verified_dataset(dataset, output_file)

    print(json.dumps({
        "ok": True,
        "synced_at": datetime.utcnow().isoformat() + "Z",
        "source": source,
        "gifts": len(dataset.get("gifts", [])),
        "output": output_file or "data/verified_gifts.json",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
