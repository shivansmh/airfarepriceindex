"""Persist the latest APIx result for the dashboard's rolling 30-day heatmap."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APIX_FILE = ROOT / "dashboard" / "apix_output.json"
HISTORY_FILE = ROOT / "dashboard" / "apix_history.json"


def main() -> None:
    current = json.loads(APIX_FILE.read_text(encoding="utf-8"))
    generated_at = current.get("generated_at") or datetime.now(timezone.utc).isoformat()
    date_key = generated_at[:10]
    history = []
    if HISTORY_FILE.exists():
        try:
            loaded = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                history = loaded
        except json.JSONDecodeError:
            history = []

    snapshot = {
        "date": date_key,
        "generated_at": generated_at,
        "daily_apix": current.get("daily_apix"),
        "price_change_from_base_percent": current.get("price_change_from_base_percent"),
        "direction": current.get("direction"),
        "route_level_apix": current.get("route_level_apix", {}),
    }
    by_date = {item.get("date"): item for item in history if isinstance(item, dict) and item.get("date")}
    by_date[date_key] = snapshot
    output = sorted(by_date.values(), key=lambda item: item["date"])[-30:]
    HISTORY_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(output)} APIx history entries to {HISTORY_FILE}")


if __name__ == "__main__":
    main()
