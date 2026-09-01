
"""Extract flight details from a rendered airline booking page.

The script captures the complete post-JavaScript HTML, analyzes visible text and
structured data, then prints a JSON string containing price, flight number,
and departure/arrival timings.

Use only on pages you are permitted to access, and comply with the site's
terms, robots policy, and applicable laws. This script does not bypass login,
CAPTCHA, paywalls, or anti-bot controls.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from playwright.async_api import Browser, Page, TimeoutError as PlaywrightTimeoutError, async_playwright

SCRIPT_VERSION = "via-fixed-2026-09-01"

# -------------------- USER CONFIGURATION --------------------
# Edit only BASE_URL if you want to scrape a different route.
BASE_URL = "https://in.via.com/flight/search?returnType=one-way&destination=BLR&bdestination=BLR&destinationL=Bangalore&destinationCity=&destinationCN=&source=DEL&bsource=DEL&sourceL=Delhi&sourceCity=&sourceCN=&month=9&day=1&year=2026&date=9/1/2026&numAdults=1&numChildren=0&numInfants=0&validation_result=&domesinter=international&livequote=-1&flightClass=ALL&travType=INTL&routingType=ALL&preferredCarrier=&prefCarrier=0&isAjax=false"
# Route names and airport codes used by Via.com.
ROUTES = [
    ("Delhi - Bombay", "DEL", "BOM", "Delhi", "Bombay"),
    ("Delhi - Bengaluru", "DEL", "BLR", "Delhi", "Bangalore"),
    ("Calcutta - Bombay", "CCU", "BOM", "Kolkata", "Bombay"),
]
DATE_OFFSETS = [1, 7, 15, 30, 45]  # T+1, T+7, T+15, T+30, and T+45
SHOW_BROWSER = True         # Always open Chromium visibly
WAIT_MS = 2500              # Increase if the results take longer to load
# Explicit Windows output folder. Change `shiva` if the Windows username differs.
OUTPUT_FOLDER = Path(r"C:\Users\shiva\OneDrive\Desktop\CS")
HTML_OUTPUT_BASE = OUTPUT_FOLDER / "rendered_flight_page.html"
# This file is overwritten on every run with only the newest report.
REPORT_OUTPUT = OUTPUT_FOLDER / "target_day.txt"
# ------------------------------------------------------------


@dataclass
class FlightResult:
    url: str
    price: str | None
    flight_number: str | None
    departure_time: str | None
    arrival_time: str | None
    currency: str | None
    html_file: str | None
    analysis: dict[str, Any]
    flights: list[dict[str, Any]]


def first_match(patterns: Iterable[str], text: str, flags: int = re.IGNORECASE) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1).strip()
    return None


def unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = re.sub(r"\s+", " ", value).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            output.append(normalized)
    return output


def parse_via_rows(row_texts: list[str]) -> list[dict[str, Any]]:
    """Parse Via.com `.result` rows, whose fields are in a stable visual order."""
    flights: list[dict[str, Any]] = []
    time_pattern = r"(?:[01]?\d|2[0-3]):[0-5]\d(?:\s?(?:AM|PM))?"
    flight_pattern = r"\b[A-Z]{2}\s?-?\s?\d{1,4}\b"
    for raw in row_texts:
        text = re.sub(r"\s+", " ", raw).strip()
        times = re.findall(time_pattern, text, re.IGNORECASE)
        flight_matches = re.findall(
            r"\b[A-Z0-9]{2}\s*-\s*\d{3,4}(?:\s*,\s*[A-Z0-9]{2}\s*-\s*\d{3,4})*\b",
            text.upper(),
        )
        # Via places the fare immediately after the Flight Details label.
        # Anchoring there prevents times, durations, seat counts, and route
        # numbers from being mistaken for the ticket price.
        fare = re.search(
            r"Flight Details\s+((?:₹|Rs\.?|INR\s*)?[\d,]+(?:\.\d{1,2})?)",
            text,
            re.IGNORECASE,
        )
        fare_value = fare.group(1).strip() if fare else None
        if fare_value and not re.match(r"^(?:₹|Rs\.?|INR)", fare_value, re.IGNORECASE):
            fare_value = f"₹{fare_value}"
        # Via's row text usually looks like: depart, origin, duration, route,
        # arrival, destination, airline, flight number, seats, details, fare.
        flight_number = flight_matches[0] if flight_matches else None
        flights.append({
            "departure_time": times[0] if times else None,
            "arrival_time": times[1] if len(times) > 1 else None,
            "flight_number": flight_number,
            "price": fare_value,
            "currency": "INR" if fare_value else None,
            "raw_text": text,
        })
    return flights


def analyze_html(html: str, visible_text: str, url: str, row_texts: list[str] | None = None) -> FlightResult:
    """Analyze rendered HTML using row-level data, semantic attributes, and fallbacks."""
    combined = f"{visible_text}\n{html}"
    via_flights = parse_via_rows(row_texts or []) if row_texts else []

    # Common airline codes are two letters followed by 1-4 digits, for example AF123.
    flight_candidates = unique(
        re.findall(r"\b([A-Z0-9]{2}\s*-\s*\d{3,4}(?:\s*,\s*[A-Z0-9]{2}\s*-\s*\d{3,4})*)\b", visible_text.upper())
        + re.findall(r"(?:flight(?:\s*(?:number|no\.?)?)?|flt)\s*[:#-]?\s*([A-Z0-9]{2}\s*-\s*\d{3,4}(?:\s*,\s*[A-Z0-9]{2}\s*-\s*\d{3,4})*)", combined)
    )
    if via_flights:
        flight_candidates = unique([f["flight_number"] for f in via_flights if f.get("flight_number")]) + flight_candidates
    flight_number = flight_candidates[0] if flight_candidates else None

    # Prefer values next to price labels, then fall back to currency-formatted values.
    price = (via_flights[0].get("price") if via_flights else None) or first_match(
        [
            r"(?:total|price|fare|amount|from)\s*[:\-]?\s*((?:[$€£₹]|USD|EUR|GBP|INR)\s?[\d,]+(?:\.\d{1,2})?)",
            r"((?:[$€£₹]|USD|EUR|GBP|INR)\s?[\d,]+(?:\.\d{1,2})?)",
            r"([\d,]+(?:\.\d{1,2})?\s?(?:USD|EUR|GBP|INR|[$€£₹]))",
        ],
        visible_text,
    )
    currency = (via_flights[0].get("currency") if via_flights else None) or first_match([r"\b(USD|EUR|GBP|INR)\b", r"([$€£₹])"], price or visible_text)

    # Extract clock times, supporting 12-hour and 24-hour display formats.
    time_pattern = r"\b(?:[01]?\d|2[0-3]):[0-5]\d\s?(?:AM|PM)?\b|\b(?:0?[1-9]|1[0-2]):[0-5]\d\s?(?:AM|PM)\b"
    times = unique(re.findall(time_pattern, visible_text, re.IGNORECASE))

    departure_time = first_match(
        [
            r"(?:departure|depart|take[\s-]*off|leaving)[^\d]{0,80}(" + time_pattern + r")",
            r"(?:from)[^\d]{0,60}(" + time_pattern + r")",
        ],
        visible_text,
    )
    arrival_time = first_match(
        [
            r"(?:arrival|arrive|landing|land(?:ing)?)[^\d]{0,80}(" + time_pattern + r")",
            r"(?:to)[^\d]{0,60}(" + time_pattern + r")",
        ],
        visible_text,
    )
    departure_time = (via_flights[0].get("departure_time") if via_flights else None) or departure_time or (times[0] if times else None)
    arrival_time = (via_flights[0].get("arrival_time") if via_flights else None) or arrival_time or (times[1] if len(times) > 1 else None)

    return FlightResult(
        url=url,
        price=price,
        flight_number=flight_number,
        departure_time=departure_time,
        arrival_time=arrival_time,
        currency=currency,
        html_file=None,
        analysis={
            "html_characters": len(html),
            "visible_text_characters": len(visible_text),
            "flight_candidates": flight_candidates[:10],
            "time_candidates": times[:10],
            "structured_data_present": 'application/ld+json' in html.lower(),
            "via_rows_found": len(via_flights),
            "script_version": SCRIPT_VERSION,
        },
        flights=via_flights,
    )


async def scrape(url: str, html_path: str | None = None, wait_ms: int = 2500, headless: bool = True) -> str:
    async with async_playwright() as playwright:
        browser: Browser = await playwright.chromium.launch(headless=headless)
        page: Page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            try:
                await page.wait_for_load_state("networkidle", timeout=15_000)
            except PlaywrightTimeoutError:
                pass
            if wait_ms:
                await page.wait_for_timeout(wait_ms)

            # page.content() is the complete current DOM, including JavaScript-rendered content.
            html = await page.content()
            visible_text = await page.locator("body").inner_text(timeout=15_000)
            row_texts = await page.locator("#searchResultContainer .result").all_inner_texts()
            result = analyze_html(html, visible_text, page.url, row_texts)

            if html_path:
                destination = Path(html_path).expanduser().resolve()
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(html, encoding="utf-8")
                result.html_file = str(destination)

            return json.dumps(asdict(result), ensure_ascii=False, indent=2)
        finally:
            await browser.close()


async def scrape_many(urls: list[str], html_out: str | None = "rendered_flight_page.html", wait_ms: int = 2500, headless: bool = True) -> str:
    """Scrape multiple route pages sequentially and return one combined JSON string."""
    if len(urls) != 3:
        raise ValueError(f"Expected exactly 3 route URLs, received {len(urls)}")

    route_results: list[dict[str, Any]] = []
    for index, url in enumerate(urls, start=1):
        if html_out:
            output_path = Path(html_out).expanduser()
            if output_path.suffix:
                route_html = output_path.with_name(f"{output_path.stem}_route_{index}{output_path.suffix}")
            else:
                route_html = output_path / f"route_{index}.html"
        else:
            route_html = None
        route_results.append(json.loads(await scrape(url, str(route_html) if route_html else None, wait_ms, headless)))

    return json.dumps({
        "script_version": SCRIPT_VERSION,
        "route_count": len(route_results),
        "routes": route_results,
    }, ensure_ascii=False, indent=2)


def url_for_date(base_url: str, travel_date: date) -> str:
    """Update Via.com's date, month, day, and year query parameters."""
    parts = urlsplit(base_url)
    query = parse_qs(parts.query, keep_blank_values=True)
    # Via.com expects calendar values based on the target date, not T.
    # These assignments correctly handle month/year rollovers.
    query["date"] = [f"{travel_date.month}/{travel_date.day}/{travel_date.year}"]
    query["month"] = [str(travel_date.month)]
    query["day"] = [str(travel_date.day)]
    query["year"] = [str(travel_date.year)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))


def url_for_route(base_url: str, source: str, destination: str, source_name: str, destination_name: str) -> str:
    """Update Via.com's route query parameters while preserving other settings."""
    parts = urlsplit(base_url)
    query = parse_qs(parts.query, keep_blank_values=True)
    query["source"] = [source]
    query["bsource"] = [source]
    query["sourceL"] = [source_name]
    query["sourceCity"] = [source_name]
    query["destination"] = [destination]
    query["bdestination"] = [destination]
    query["destinationL"] = [destination_name]
    query["destinationCity"] = [destination_name]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))


async def scrape_all_routes(routes: list[tuple[str, str, str, str, str]], offsets: list[int], html_out: str | None = "rendered_flight_page.html", wait_ms: int = 2500, headless: bool = True) -> str:
    """Scrape every configured route for every configured relative date."""
    route_results: list[dict[str, Any]] = []
    for route_name, source, destination, source_name, destination_name in routes:
        route_url = url_for_route(BASE_URL, source, destination, source_name, destination_name)
        route_html_out = html_out
        if html_out:
            output_path = Path(html_out).expanduser()
            suffix = output_path.suffix or ".html"
            stem = output_path.stem if output_path.suffix else "rendered_flight_page"
            safe_route_name = re.sub(r"[^A-Za-z0-9]+", "_", route_name).strip("_").lower()
            route_html_out = str(output_path.with_name(f"{stem}_{safe_route_name}{suffix}"))
        payload = json.loads(await scrape_date_offsets(route_url, offsets, route_html_out, wait_ms, headless))
        payload["route_name"] = route_name
        route_results.append(payload)
    return json.dumps({"mode": "multi_route_relative_dates", "routes": route_results}, ensure_ascii=False, indent=2)


async def scrape_date_offsets(base_url: str, offsets: list[int] = [1, 7, 15, 30, 45], html_out: str | None = "rendered_flight_page.html", wait_ms: int = 2500, headless: bool = True) -> str:
    """Scrape one route at dates relative to the date on which the script runs."""
    run_date = date.today()
    results_by_offset: dict[str, dict[str, Any]] = {}
    for offset in offsets:
        travel_date = run_date + timedelta(days=offset)
        dated_url = url_for_date(base_url, travel_date)
        if html_out:
            output_path = Path(html_out).expanduser()
            suffix = output_path.suffix or ".html"
            stem = output_path.stem if output_path.suffix else "rendered_flight_page"
            route_html = output_path.with_name(f"{stem}_T_plus_{offset}_{travel_date.isoformat()}{suffix}")
        else:
            route_html = None
        result = json.loads(await scrape(dated_url, str(route_html) if route_html else None, wait_ms, headless))
        result["offset_days"] = offset
        result["requested_date"] = travel_date.isoformat()
        results_by_offset[f"T_plus_{offset}"] = result

    return json.dumps({
        "script_version": SCRIPT_VERSION,
        "mode": "relative_dates",
        "run_date_T": run_date.isoformat(),
        "route": base_url,
        "requested_offsets": offsets,
        "results": results_by_offset,
    }, ensure_ascii=False, indent=2)


async def scrape_date_range(base_url: str, start_date: str, end_date: str, html_out: str | None = "rendered_flight_page.html", wait_ms: int = 2500, headless: bool = True) -> str:
    """Scrape one route for every calendar date from start_date through end_date."""
    first = datetime.strptime(start_date, "%Y-%m-%d").date()
    last = datetime.strptime(end_date, "%Y-%m-%d").date()
    if last < first:
        raise ValueError("end date must be on or after start date")

    date_results: list[dict[str, Any]] = []
    current = first
    index = 1
    while current <= last:
        dated_url = url_for_date(base_url, current)
        if html_out:
            output_path = Path(html_out).expanduser()
            suffix = output_path.suffix or ".html"
            stem = output_path.stem if output_path.suffix else "rendered_flight_page"
            route_html = output_path.with_name(f"{stem}_{current.isoformat()}{suffix}")
        else:
            route_html = None
        result = json.loads(await scrape(dated_url, str(route_html) if route_html else None, wait_ms, headless))
        result["requested_date"] = current.isoformat()
        result["route_date_index"] = index
        date_results.append(result)
        current += timedelta(days=1)
        index += 1

    return json.dumps({
        "script_version": SCRIPT_VERSION,
        "mode": "date_range",
        "route": base_url,
        "start_date": start_date,
        "end_date": end_date,
        "date_count": len(date_results),
        "dates": date_results,
    }, ensure_ascii=False, indent=2)


def format_multi_route_report(payload: dict[str, Any]) -> str:
    """Format all routes, keeping each route and date window in its own section."""
    sections: list[str] = []
    for route_payload in payload.get("routes", []):
        route_name = route_payload.get("route_name", "Unnamed route")
        report = format_clean_report(route_payload)
        sections.append(f"ROUTE: {route_name}\n" + "=" * 60 + "\n" + report.split("\n", 2)[-1])
    return "\n\n".join(sections)


def format_clean_report(payload: dict[str, Any]) -> str:
    """Format relative-date results as a concise human-readable report."""
    base_url = payload.get("route", "")
    query = parse_qs(urlsplit(base_url).query)
    source = query.get("source", [""])[0] or "Unknown origin"
    destination = query.get("destination", [""])[0] or "Unknown destination"
    lines = [f"ROUTE: {source} -> {destination}", "=" * 60]

    for label, result in payload.get("results", {}).items():
        requested_date = result.get("requested_date", "unknown date")
        lines.extend(["", f"{label} ({requested_date})", "-" * 60])
        flights = result.get("flights", [])
        if not flights:
            lines.append("No flight results found.")
            continue
        for number, flight in enumerate(flights, start=1):
            lines.extend([
                f"Flight {number}",
                f"  Flight number: {flight.get('flight_number') or 'N/A'}",
                f"  Departure:     {flight.get('departure_time') or 'N/A'}",
                f"  Arrival:       {flight.get('arrival_time') or 'N/A'}",
                f"  Price:         {flight.get('price') or 'N/A'}",
                "",
            ])
    return "\n".join(lines).rstrip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape flight details from exactly three airline booking pages.")
    parser.add_argument("urls", nargs="*", help="Exactly three booking-page URLs")
    parser.add_argument("--routes-file", help="Text file containing exactly three URLs, one per line")
    parser.add_argument("--date-url", help="One base Via.com route URL to scrape across a date range")
    parser.add_argument("--start-date", help="First travel date in YYYY-MM-DD format; use with --date-url")
    parser.add_argument("--end-date", help="Last travel date in YYYY-MM-DD format, inclusive; use with --date-url")
    parser.add_argument("--offsets", default="1,7,15", help="Comma-separated day offsets for relative mode; default: 1,7,15")
    parser.add_argument("--html-out", default="rendered_flight_page.html", help="Base path for complete rendered HTML files")
    parser.add_argument("--wait-ms", type=int, default=2500, help="Additional wait after page load for results to render")
    parser.add_argument("--headed", action="store_true", help="Show Chromium while scraping")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        payload = json.loads(asyncio.run(
            scrape_all_routes(
                ROUTES,
                DATE_OFFSETS,
                str(HTML_OUTPUT_BASE),
                WAIT_MS,
                headless=not SHOW_BROWSER,
            )
        ))
        report = format_multi_route_report(payload)
        REPORT_OUTPUT.write_text(report + "\n", encoding="utf-8")
        print(report)
        print(f"\nComplete report saved to: {REPORT_OUTPUT}")
    except PlaywrightTimeoutError as exc:
        print(f"Page load timed out: {exc}")
    except Exception as exc:
        print(f"Scrape failed: {exc}")
    finally:
        input("\nScraping finished. Press Enter to close this window...")
