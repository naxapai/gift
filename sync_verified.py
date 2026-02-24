from __future__ import annotations

import json
from datetime import datetime, timezone

from market_data import load_verified_dataset_source, save_verified_dataset


def main() -> None:
    import os

    output_file = os.getenv("VERIFIED_DATA_FILE", "").strip() or None
    source = os.getenv("VERIFIED_SOURCE", "hybrid").strip().lower()

    dataset = load_verified_dataset_source()
    save_verified_dataset(dataset, output_file)

    print(json.dumps({
        "ok": True,
        "synced_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": source,
        "gifts": len(dataset.get("gifts", [])),
        "output": output_file or "data/verified_gifts.json",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
