"""Export the daily scraper/APIx outputs into append-only database snapshots.

The repository database is intentionally file-based so GitHub Pages and Git history
remain the source of truth. Each daily run writes one date-stamped JSON document in
each fact-table folder; rerunning the same date replaces only that date's snapshot.
"""
from __future__ import annotations

import csv
import json
import re
import statistics
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TARGET_FILE = ROOT / "dashboard" / "target_day.json"
APIX_FILE = ROOT / "dashboard" / "apix_output.json"
HISTORY_FILE = ROOT / "dashboard" / "apix_history.json"
DATABASE = ROOT / "database"

RAW_DIR = DATABASE / "raw_scraped_flights"
SUMMARY_DIR = DATABASE / "route_window_summary"
ROUTE_INDEX_DIR = DATABASE / "route_level_index"
APIX_DIR = DATABASE / "daily_apix"
FESTIVAL_FILE = DATABASE / "festival_calendar" / "festival_calendar.csv"
FUEL_FILE = DATABASE / "fuel_prices" / "fuel_prices.csv"
IST = ZoneInfo("Asia/Kolkata")

CSV_SCHEMAS = {
    FESTIVAL_FILE: ["date_start", "date_end", "festival_name"],
    FUEL_FILE: ["month", "atf_price"],
}


def load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback


def scrape_date(payload: dict[str, Any]) -> str:
    # Use India time because the scheduled run is defined in IST, not UTC.
    return datetime.now(IST).date().isoformat()


def money(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"[\d,]+(?:\.\d+)?", str(value))
    return float(match.group(0).replace(",", "")) if match else None


def route_code(route_name: str) -> str:
    codes = {
        "Delhi - Bombay": "DEL-BOM",
        "Delhi - Bengaluru": "DEL-BLR",
        "Calcutta - Bombay": "CCU-BOM",
    }
    return codes.get(route_name, route_name)


def carrier_from_flight_number(value: Any) -> str | None:
    if not value:
        return None
    match = re.search(r"([A-Z0-9]{2})\s*-", str(value).upper())
    return match.group(1) if match else None


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def ensure_csv(path: Path, fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        with path.open("w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, fieldnames=fields).writeheader()


def export_daily_database() -> dict[str, Any]:
    target = load_json(TARGET_FILE, {})
    apix = load_json(APIX_FILE, {})
    history = load_json(HISTORY_FILE, [])
    run_date = scrape_date(target)

    raw_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    routes = target.get("routes", []) if isinstance(target, dict) else []
    for route_payload in routes:
        route_name = route_payload.get("route_name") or route_code(route_payload.get("route", ""))
        route = route_code(route_name)
        for booking_window, result in (route_payload.get("results") or {}).items():
            departure_date = result.get("requested_date")
            flights = result.get("flights") or []
            prices: list[float] = []
            for flight in flights:
                price = money(flight.get("price"))
                if price is not None:
                    prices.append(price)
                raw_rows.append({
                    "scrape_date": run_date,
                    "route": route,
                    "booking_window": booking_window,
                    "carrier": carrier_from_flight_number(flight.get("flight_number")),
                    "departure_date": departure_date,
                    "departure_time": flight.get("departure_time"),
                    "price": price,
                    "base_fare": None,
                    "taxes": None,
                    "source_site": "via.com",
                    "flight_number": flight.get("flight_number"),
                    "arrival_time": flight.get("arrival_time"),
                })
            summary_rows.append({
                "date": run_date,
                "route": route,
                "booking_window": booking_window,
                "representative_price": round(statistics.median(prices), 2) if prices else None,
                "sample_size": len(prices),
            })

    route_indices = apix.get("route_level_apix", {}) if isinstance(apix, dict) else {}
    route_index_rows = [
        {
            "date": run_date,
            "route": route_code(route),
            "route_level_index": value,
            "explanation_text": None,
        }
        for route, value in route_indices.items()
    ]

    # Daily is the headline value. Weekly/monthly are rolling means of available
    # daily observations, so the table is useful immediately and improves over time.
    daily_value = apix.get("daily_apix") if isinstance(apix, dict) else None
    history_values = [
        item.get("daily_apix") for item in history
        if isinstance(item, dict) and isinstance(item.get("daily_apix"), (int, float))
    ]
    if isinstance(daily_value, (int, float)):
        history_values.append(daily_value)
    apix_rows = []
    for frequency, values in (
        ("daily", [daily_value] if isinstance(daily_value, (int, float)) else []),
        ("weekly", history_values[-7:]),
        ("monthly", history_values[-30:]),
    ):
        valid = [value for value in values if isinstance(value, (int, float))]
        apix_rows.append({
            "date": run_date,
            "frequency": frequency,
            "apix_value": round(statistics.mean(valid), 6) if valid else None,
            "base_period_used": "data/base_day.txt",
        })

    atomic_json(RAW_DIR / f"{run_date}.json", {
        "table": "raw_scraped_flights",
        "schema": ["scrape_date", "route", "booking_window", "carrier", "departure_date", "departure_time", "price", "base_fare", "taxes", "source_site"],
        "rows": raw_rows,
    })
    atomic_json(SUMMARY_DIR / f"{run_date}.json", {
        "table": "route_window_summary",
        "schema": ["date", "route", "booking_window", "representative_price", "sample_size"],
        "rows": summary_rows,
    })
    atomic_json(ROUTE_INDEX_DIR / f"{run_date}.json", {
        "table": "route_level_index",
        "schema": ["date", "route", "route_level_index", "explanation_text"],
        "rows": route_index_rows,
    })
    atomic_json(APIX_DIR / f"{run_date}.json", {
        "table": "daily_apix",
        "schema": ["date", "frequency", "apix_value", "base_period_used"],
        "rows": apix_rows,
    })
    ensure_csv(FESTIVAL_FILE, CSV_SCHEMAS[FESTIVAL_FILE])
    ensure_csv(FUEL_FILE, CSV_SCHEMAS[FUEL_FILE])

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "date": run_date,
        "raw_flight_count": len(raw_rows),
        "summary_count": len(summary_rows),
        "route_index_count": len(route_index_rows),
        "apix_frequency_count": len(apix_rows),
        "source_files": [str(TARGET_FILE.relative_to(ROOT)), str(APIX_FILE.relative_to(ROOT))],
    }
    atomic_json(DATABASE / "manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    result = export_daily_database()
    print(json.dumps(result, indent=2))
