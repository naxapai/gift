from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def main(path: str) -> int:
    p = Path(path)
    if not p.exists():
        print(json.dumps({"ok": False, "error": "snapshot_missing", "path": str(p)}))
        return 1
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"invalid_json: {e}", "path": str(p)}))
        return 1

    gifts = data.get("gifts") or []
    by_collection: dict[str, list[dict]] = defaultdict(list)
    for g in gifts:
        if not isinstance(g, dict):
            continue
        slug = str(g.get("collection_slug") or "").strip().lower()
        if not slug:
            continue
        by_collection[slug].append(g)

    suspicious = []
    for slug, items in by_collection.items():
        models = {str((x.get("profile") or {}).get("model") or "").strip() for x in items}
        backgrounds = {str((x.get("profile") or {}).get("background") or "").strip() for x in items}
        patterns = {str((x.get("profile") or {}).get("pattern") or "").strip() for x in items}
        models.discard("")
        backgrounds.discard("")
        patterns.discard("")

        if len(items) >= 20 and len(models) <= 1 and len(backgrounds) <= 1 and len(patterns) <= 1:
            suspicious.append(
                {
                    "collection": slug,
                    "gifts": len(items),
                    "models": len(models),
                    "backgrounds": len(backgrounds),
                    "patterns": len(patterns),
                }
            )

    payload = {
        "ok": len(suspicious) == 0,
        "collections": len(by_collection),
        "gifts": len(gifts),
        "suspicious_collections": len(suspicious),
        "items": suspicious[:100],
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "data/verified_gifts.json"
    raise SystemExit(main(target))
