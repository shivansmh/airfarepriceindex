"""Upsert the daily airfare outputs into Supabase PostgREST.

The writer is intentionally separate from the file exporter so GitHub Pages keeps
working as a fallback if Supabase is unavailable for a run.
"""
from __future__ import annotations

import json
import os
import statistics
import time
import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from export_daily_database import load_json, money, route_code, carrier_from_flight_number

ROOT = Path(__file__).resolve().parents[1]
TARGET_FILE = ROOT / "dashboard" / "target_day.json"
APIX_FILE = ROOT / "dashboard" / "apix_output.json"
HISTORY_FILE = ROOT / "dashboard" / "apix_history.json"
POST_BATCH_SIZE = 200

TABLE_CONFLICTS = {
    "raw_scraped_flights": "state,scrape_date,route,booking_window,flight_number,departure_time,arrival_time,price,source_site",
}


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def run_date() -> str:
    target = load_json(TARGET_FILE, {})
    return target.get("run_date_T") or datetime.now().astimezone().date().isoformat()


def build_rows() -> dict[str, list[dict[str, Any]]]:
    target = load_json(TARGET_FILE, {})
    apix = load_json(APIX_FILE, {})
    history = load_json(HISTORY_FILE, [])
    date_key = run_date()
    raw: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for route_payload in target.get("routes", []):
        state = route_payload.get("state") or "Unknown"
        origin = route_payload.get("origin") or ""
        destination = route_payload.get("destination") or ""
        origin_code = route_payload.get("origin_code") or ""
        destination_code = route_payload.get("destination_code") or ""
        route_name = route_payload.get("route_name") or route_payload.get("route", "")
        route = f"{origin_code}-{destination_code}" if origin_code and destination_code else route_code(route_name)
        for window, result in (route_payload.get("results") or {}).items():
            prices: list[float] = []
            for flight in result.get("flights", []) or []:
                price = money(flight.get("price"))
                if price is not None:
                    prices.append(price)
                raw.append({
                    "scrape_date": date_key,
                    "state": state,
                    "route": route,
                    "origin": origin,
                    "origin_code": origin_code,
                    "destination": destination,
                    "destination_code": destination_code,
                    "booking_window": window,
                    "carrier": flight.get("airline") or carrier_from_flight_number(flight.get("flight_number")),
                    "airline": flight.get("airline"),
                    "departure_date": result.get("requested_date"),
                    "departure_time": flight.get("departure_time"),
                    "arrival_time": flight.get("arrival_time"),
                    "flight_number": flight.get("flight_number"),
                    "price": price,
                    "base_fare": flight.get("base_fare"),
                    "taxes": flight.get("taxes"),
                    "baggage": flight.get("baggage"),
                    "source_site": "via.com",
                })
            summaries.append({
                "date": date_key,
                "state": state,
                "route": route,
                "origin": origin,
                "origin_code": origin_code,
                "destination": destination,
                "destination_code": destination_code,
                "booking_window": window,
                "representative_price": statistics.median(prices) if prices else None,
                "sample_size": len(prices),
            })
    route_index_map = apix.get("route_level_apix", {}) or {}
    route_indexes = [
        {
            "date": date_key,
            "state": route_payload.get("state") or "Unknown",
            "route": f"{route_payload.get('origin_code')}-{route_payload.get('destination_code')}",
            "origin": route_payload.get("origin"),
            "origin_code": route_payload.get("origin_code"),
            "destination": route_payload.get("destination"),
            "destination_code": route_payload.get("destination_code"),
            "route_level_index": route_index_map.get(route_payload.get("route_name")),
            "explanation_text": None,
        }
        for route_payload in target.get("routes", [])
    ]
    daily = apix.get("daily_apix")
    history_values = [
        item.get("daily_apix") for item in history
        if isinstance(item, dict) and isinstance(item.get("daily_apix"), (int, float))
    ]
    if isinstance(daily, (int, float)):
        history_values.append(daily)
    apix_rows = []
    for frequency, values in (("daily", [daily]), ("weekly", history_values[-7:]), ("monthly", history_values[-30:])):
        values = [value for value in values if isinstance(value, (int, float))]
        apix_rows.append({
            "date": date_key,
            "frequency": frequency,
            "apix_value": sum(values) / len(values) if values else None,
            "base_period_used": "data/base_day.txt",
        })
    return {
        "raw_scraped_flights": raw,
        "route_window_summary": summaries,
        "route_level_index": route_indexes,
        "daily_apix": apix_rows,
    }


def post_batch(client: httpx.Client, base_url: str, key: str, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        print(f"{table}: no rows")
        return
    if table == "raw_scraped_flights":
        identity = ("state", "scrape_date", "route", "booking_window", "flight_number", "departure_time", "arrival_time", "price", "source_site")
        unique_rows = {}
        for row in rows:
            unique_rows[tuple(row.get(field) for field in identity)] = row
        rows = list(unique_rows.values())
    elif table == "route_window_summary":
        # The workbook can contain the same airport pair more than once across
        # states. Supabase rejects duplicate constrained values in one upsert,
        # even when no explicit on_conflict parameter is supplied.
        identity = ("date", "route", "booking_window")
        unique_rows = {}
        for row in rows:
            unique_rows[tuple(row.get(field) for field in identity)] = row
        rows = list(unique_rows.values())
    elif table == "route_level_index":
        identity = ("date", "route")
        unique_rows = {}
        for row in rows:
            unique_rows[tuple(row.get(field) for field in identity)] = row
        rows = list(unique_rows.values())
    url = f"{base_url}/rest/v1/{table}"
    conflict = TABLE_CONFLICTS.get(table)
    if conflict:
        url += f"?on_conflict={conflict}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    total = len(rows)
    for start in range(0, total, POST_BATCH_SIZE):
        chunk = rows[start:start + POST_BATCH_SIZE]
        for attempt in range(4):
            try:
                response = client.post(url, headers=headers, json=chunk)
                if response.status_code < 500 and response.status_code != 429:
                    if response.is_error:
                        raise RuntimeError(f"Supabase {table} returned {response.status_code}: {response.text[:1000]}")
                    break
                if attempt == 3:
                    raise RuntimeError(f"Supabase {table} returned {response.status_code}: {response.text[:1000]}")
            except (httpx.HTTPError, httpx.TimeoutException):
                if attempt == 3:
                    raise
            time.sleep(2 ** attempt)
        else:
            raise RuntimeError(f"Supabase {table}: exhausted retries for rows {start}:{start + len(chunk)}")
    print(f"{table}: upserted {total} rows in {(total + POST_BATCH_SIZE - 1) // POST_BATCH_SIZE} batch(es)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true", help="Import all dated database snapshots in the repository")
    args = parser.parse_args()
    base_url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not base_url or not key:
        print("Supabase secrets are not configured; skipping remote upsert.")
        return
    base_url = base_url.rstrip("/")
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=20.0)) as client:
        if args.backfill:
            for table in ("raw_scraped_flights", "route_window_summary", "route_level_index", "daily_apix"):
                for snapshot in sorted((ROOT / "database" / table).glob("*.json")):
                    payload = load_json(snapshot, {})
                    post_batch(client, base_url, key, table, payload.get("rows", []))
        else:
            for table, table_rows in build_rows().items():
                post_batch(client, base_url, key, table, table_rows)


if __name__ == "__main__":
    main()
