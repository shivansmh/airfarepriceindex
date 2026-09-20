

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import httpx
from playwright.async_api import Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, async_playwright

SCRIPT_VERSION = "via-direct-api-2026-09-19"

# IATA-style designators used by the carriers commonly returned by Via.com.
# The fallback keeps the original code available when a new carrier appears.
AIRLINE_NAMES = {
    "6E": "IndiGo",
    "AI": "Air India",
    "QP": "Akasa Air",
    "IX": "Air India Express",
    "UK": "Vistara",
    "SG": "SpiceJet",
    "G8": "Go First",
    "I5": "AirAsia India",
    "S5": "Star Air",
    "9I": "Alliance Air",
    "2T": "TruJet",
}

BASE_URL = "https://in.via.com/flight/search?returnType=one-way&destination=BLR&bdestination=BLR&destinationL=Bangalore&destinationCity=&destinationCN=&source=DEL&bsource=DEL&sourceL=Delhi&sourceCity=&sourceCN=&month=9&day=1&year=2026&date=9/1/2026&numAdults=1&numChildren=0&numInfants=0&validation_result=&domesinter=international&livequote=-1&flightClass=ALL&travType=INTL&routingType=ALL&preferredCarrier=&prefCarrier=0&isAjax=false"
VIA_API_URL = "https://in.via.com/apiv2/flight/search?&flowType=NODE&ajax=true&jsonData=true"

DATE_OFFSETS = [int(value.strip()) for value in os.getenv("DATE_OFFSETS", "1,7,15,30,45").split(",") if value.strip()]
SHOW_BROWSER = os.getenv("SHOW_BROWSER", "false").lower() in {"1", "true", "yes"}
WAIT_MS = int(os.getenv("WAIT_MS", "3500"))
MAX_CONCURRENCY = max(1, int(os.getenv("MAX_CONCURRENCY", "1")))
API_REQUEST_GAP_SECONDS = max(0.0, float(os.getenv("API_REQUEST_GAP_SECONDS", "1.5")))
EMPTY_RESULT_RETRIES = max(0, int(os.getenv("EMPTY_RESULT_RETRIES", "2")))
API_MAX_RETRIES = max(0, int(os.getenv("API_MAX_RETRIES", "3")))
RETRY_BACKOFF_SECONDS = max(0.0, float(os.getenv("RETRY_BACKOFF_SECONDS", "2.0")))
API_TIMEOUT_SECONDS = max(1.0, float(os.getenv("API_TIMEOUT_SECONDS", "30")))
ROTATE_USER_AGENTS = os.getenv("ROTATE_USER_AGENTS", "false").lower() in {"1", "true", "yes"}
USER_AGENTS = tuple(filter(None, (value.strip() for value in os.getenv("USER_AGENTS", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36,Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/18.1 Safari/605.1.15,Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0").split(","))))
PROXY_URLS = tuple(filter(None, (value.strip() for value in os.getenv("PROXY_URLS", "").split(","))))
DEBUG_EMPTY_RESULTS = os.getenv("DEBUG_EMPTY_RESULTS", "false").lower() in {"1", "true", "yes"}
SAVE_HTML = os.getenv("SAVE_HTML", "false").lower() in {"1", "true", "yes"}
USE_DIRECT_API = os.getenv("USE_DIRECT_API", "true").lower() in {"1", "true", "yes"}
ROUTE_LIMIT = int(os.getenv("ROUTE_LIMIT", "0"))
TOP_ROUTES = max(0, int(os.getenv("TOP_ROUTES", "0")))

REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTES_FILE = REPO_ROOT / "config" / "routes.json"
ROUTES = json.loads(ROUTES_FILE.read_text(encoding="utf-8"))["routes"]
OUTPUT_FOLDER = Path(os.getenv("OUTPUT_FOLDER", str(REPO_ROOT / "dashboard"))).expanduser()
HTML_OUTPUT_BASE = OUTPUT_FOLDER / "rendered_flight_page.html"
REPORT_OUTPUT = OUTPUT_FOLDER / "target_day.txt"
JSON_OUTPUT = OUTPUT_FOLDER / "target_day.json"
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


def airline_names(flight_number: str | None) -> list[str]:
    """Return normalized airline names for all legs in a flight itinerary.

    Via.com can represent a connecting itinerary as, for example,
    ``6E-1234,AI-456``. Preserve both carriers rather than silently assigning
    only the first leg's airline.
    """
    if not flight_number:
        return []
    codes = re.findall(r"\b([A-Z0-9]{2})\s*-\s*\d{3,4}\b", flight_number.upper())
    return unique([AIRLINE_NAMES.get(code, code) for code in codes])


def airline_label(flight_number: str | None) -> str | None:
    """Return a display-friendly airline value for a flight record."""
    names = airline_names(flight_number)
    return ", ".join(names) if names else None


def _time_only(value: Any) -> str | None:
    match = re.search(r"(?:T|\s)(\d{2}:\d{2})", str(value or ""))
    return match.group(1) if match else None


def _amount(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("amount")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        match = re.search(r"[\d,]+(?:\.\d+)?", str(value or ""))
        return float(match.group(0).replace(",", "")) if match else None


def parse_via_api_response(payload: dict[str, Any], url: str) -> FlightResult:
    """Convert Via's structured ``onwardJourneys`` response into our schema."""
    best_by_itinerary: dict[tuple[str, str | None, str | None], dict[str, Any]] = {}
    for journey in payload.get("onwardJourneys", []) or []:
        legs = journey.get("flights", []) or []
        if not legs:
            continue
        flight_numbers = [
            f"{leg.get('carrier', {}).get('code', '')}-{leg.get('flightNo', '')}".strip("-")
            for leg in legs
        ]
        flight_number = ",".join(number for number in flight_numbers if number)
        first_leg, last_leg = legs[0], legs[-1]
        fare = journey.get("fares", {}).get("totalFare", {})
        baggage = []
        for leg in legs:
            checkin = leg.get("amenities", {}).get("baggage", {}).get("checkin", {}).get("adt", {})
            cabin = leg.get("amenities", {}).get("baggage", {}).get("cabin", {}).get("adt", {})
            if checkin.get("desc"):
                baggage.append(f"check-in: {checkin['desc']}")
            if cabin.get("desc"):
                baggage.append(f"cabin: {cabin['desc']}")
        departure = first_leg.get("depDetail", {})
        arrival = last_leg.get("arrDetail", {})
        carrier_names = unique([
            AIRLINE_NAMES.get(
                leg.get("carrier", {}).get("code", "").upper(),
                leg.get("carrier", {}).get("name", ""),
            )
            for leg in legs
            if leg.get("carrier", {}).get("code") or leg.get("carrier", {}).get("name")
        ])
        total = _amount(fare.get("total"))
        candidate = {
            "departure_time": _time_only(departure.get("time")),
            "arrival_time": _time_only(arrival.get("time")),
            "flight_number": flight_number or None,
            "airline": ", ".join(carrier_names) or airline_label(flight_number),
            "price": f"₹{total:,.0f}" if total is not None else None,
            "currency": "INR" if total is not None else None,
            "base_fare": _amount(fare.get("base")),
            "taxes": _amount(fare.get("tax")),
            "baggage": "; ".join(unique(baggage)) or None,
            "raw_text": None,
        }
        itinerary_key = (flight_number, candidate["departure_time"], candidate["arrival_time"])
        previous = best_by_itinerary.get(itinerary_key)
        previous_total = _amount((previous or {}).get("price"))
        if previous is None or (total is not None and (previous_total is None or total < previous_total)):
            best_by_itinerary[itinerary_key] = candidate
    flights = sorted(
        best_by_itinerary.values(),
        key=lambda item: (item.get("departure_time") or "99:99", item.get("flight_number") or ""),
    )
    first = flights[0] if flights else {}
    return FlightResult(
        url=url,
        price=first.get("price"),
        flight_number=first.get("flight_number"),
        departure_time=first.get("departure_time"),
        arrival_time=first.get("arrival_time"),
        currency=first.get("currency"),
        html_file=None,
        analysis={
            "response_type": "via_json_api",
            "via_journeys_found": len(payload.get("onwardJourneys", []) or []),
            "via_rows_found": len(flights),
            "script_version": SCRIPT_VERSION,
        },
        flights=flights,
    )


def api_payload(source: str, destination: str, source_name: str, destination_name: str, travel_date: date) -> dict[str, Any]:
    return {
        "sectorInfos": [{
            "src": {"code": source, "name": source_name, "city": source_name},
            "dest": {"code": destination, "name": destination_name, "city": destination_name},
            "date": travel_date.isoformat(),
            "debug": False,
        }],
        "prefAirlines": [],
        "class": "ALL",
        "paxCount": {"adt": 1, "chd": 0, "inf": 0},
        "route": "ALL",
        "disc": False,
        "multiHop": False,
        "multiCity": False,
        "senior": False,
        "special": False,
        "domestic": True,
        "isOfflineSearch": False,
        "isPaxWiseCommission": False,
        "isComboAllowed": False,
        "isLiveSearch": False,
    }


def select_routes(routes: list[dict[str, Any]], route_limit: int = 0, top_routes: int = 0) -> list[dict[str, Any]]:
    """Select routes deterministically, optionally prioritizing passenger volume."""
    selected = list(routes)
    if top_routes > 0:
        selected = sorted(selected, key=lambda route: route.get("passengers", 0) or 0, reverse=True)[:top_routes]
    elif route_limit > 0:
        selected = selected[:route_limit]
    return selected


def error_result(url: str, error: str, attempts: int) -> dict[str, Any]:
    """Keep one failed window in the output so a batch does not hide the cause."""
    return asdict(FlightResult(
        url=url,
        price=None,
        flight_number=None,
        departure_time=None,
        arrival_time=None,
        currency=None,
        html_file=None,
        analysis={
            "response_type": "request_error",
            "error": error,
            "attempts": attempts,
            "script_version": SCRIPT_VERSION,
        },
        flights=[],
    ))


async def scrape_api_page(client: httpx.AsyncClient, source: str, destination: str, source_name: str, destination_name: str, travel_date: date, user_agent: str | None = None) -> str:
    headers = {"User-Agent": user_agent} if user_agent else None
    response = await client.post(VIA_API_URL, json=api_payload(source, destination, source_name, destination_name, travel_date), headers=headers)
    response.raise_for_status()
    payload = response.json()
    result = parse_via_api_response(payload, VIA_API_URL)
    web_data = payload.get("webDta")
    result.analysis.update({
        "http_status": response.status_code,
        "response_bytes": len(response.content),
        "response_keys": sorted(payload.keys())[:20],
        "web_data_type": type(web_data).__name__ if web_data is not None else None,
        "web_data_preview": re.sub(r"\s+", " ", str(web_data))[:500] if web_data is not None else None,
    })
    return json.dumps(asdict(result), ensure_ascii=False, indent=2)


@asynccontextmanager
async def _null_async_context():
    yield None


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
        
        fare = re.search(
            r"Flight Details\s+((?:₹|Rs\.?|INR\s*)?[\d,]+(?:\.\d{1,2})?)",
            text,
            re.IGNORECASE,
        )
        fare_value = fare.group(1).strip() if fare else None
        if fare_value and not re.match(r"^(?:₹|Rs\.?|INR)", fare_value, re.IGNORECASE):
            fare_value = f"₹{fare_value}"
       
        flight_number = flight_matches[0] if flight_matches else None
        flights.append({
            "departure_time": times[0] if times else None,
            "arrival_time": times[1] if len(times) > 1 else None,
            "flight_number": flight_number,
            "airline": airline_label(flight_number),
            "price": fare_value,
            "currency": "INR" if fare_value else None,
            "raw_text": text,
        })
    return flights


def analyze_html(html: str, visible_text: str, url: str, row_texts: list[str] | None = None) -> FlightResult:
    """Analyze rendered HTML using row-level data, semantic attributes, and fallbacks."""
    combined = f"{visible_text}\n{html}"
    via_flights = parse_via_rows(row_texts or []) if row_texts else []

    
    flight_candidates = unique(
        re.findall(r"\b([A-Z0-9]{2}\s*-\s*\d{3,4}(?:\s*,\s*[A-Z0-9]{2}\s*-\s*\d{3,4})*)\b", visible_text.upper())
        + re.findall(r"(?:flight(?:\s*(?:number|no\.?)?)?|flt)\s*[:#-]?\s*([A-Z0-9]{2}\s*-\s*\d{3,4}(?:\s*,\s*[A-Z0-9]{2}\s*-\s*\d{3,4})*)", combined)
    )
    if via_flights:
        flight_candidates = unique([f["flight_number"] for f in via_flights if f.get("flight_number")]) + flight_candidates
    flight_number = flight_candidates[0] if flight_candidates else None

   
    price = (via_flights[0].get("price") if via_flights else None) or first_match(
        [
            r"(?:total|price|fare|amount|from)\s*[:\-]?\s*((?:[$€£₹]|USD|EUR|GBP|INR)\s?[\d,]+(?:\.\d{1,2})?)",
            r"((?:[$€£₹]|USD|EUR|GBP|INR)\s?[\d,]+(?:\.\d{1,2})?)",
            r"([\d,]+(?:\.\d{1,2})?\s?(?:USD|EUR|GBP|INR|[$€£₹]))",
        ],
        visible_text,
    )
    currency = (via_flights[0].get("currency") if via_flights else None) or first_match([r"\b(USD|EUR|GBP|INR)\b", r"([$€£₹])"], price or visible_text)

   
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


async def configure_context(context: BrowserContext) -> None:
    """Skip heavy visual assets while retaining scripts and flight result data."""
    await context.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in {"image", "media", "font", "stylesheet"}
        else route.continue_(),
    )


async def scrape_page(
    context: BrowserContext,
    url: str,
    html_path: str | None = None,
    wait_ms: int = 2500,
) -> str:
    """Scrape one result page using a page from the shared browser context."""
    page: Page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        try:
            await page.wait_for_selector("#searchResultContainer .result", timeout=15_000)
        except PlaywrightTimeoutError:
            # Some responses render an empty result state; still collect diagnostics.
            pass
        if wait_ms:
            await page.wait_for_timeout(wait_ms)

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
        await page.close()


async def scrape(url: str, html_path: str | None = None, wait_ms: int = 2500, headless: bool = True) -> str:
    """Compatibility wrapper for one-off callers."""
    async with async_playwright() as playwright:
        browser: Browser = await playwright.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        await configure_context(context)
        try:
            return await scrape_page(context, url, html_path, wait_ms)
        finally:
            await context.close()
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


async def scrape_all_routes(routes: list[dict[str, Any]], offsets: list[int], html_out: str | None = "rendered_flight_page.html", wait_ms: int = 2500, headless: bool = True) -> str:
    """Scrape all route/window pairs concurrently with bounded politeness.

    One Chromium process and one context are reused. MAX_CONCURRENCY controls the
    number of simultaneous Via.com pages; it is intentionally small by default.
    """
    run_date = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    api_request_lock = asyncio.Lock()
    empty_debug_lock = asyncio.Lock()
    empty_debug_routes: set[int] = set()
    next_api_request_at = 0.0
    route_specs = list(routes)
    route_results: list[dict[str, Any]] = [
        {
            "script_version": SCRIPT_VERSION,
            "mode": "relative_dates",
            "run_date_T": run_date.isoformat(),
            "route": url_for_route(BASE_URL, route["origin_code"], route["destination_code"], route["origin"], route["destination"]),
            "requested_offsets": offsets,
            "results": {},
            "route_name": f"{route['origin']} - {route['destination']}",
            "state": route["state"],
            "origin": route["origin"],
            "origin_code": route["origin_code"],
            "destination": route["destination"],
            "destination_code": route["destination_code"],
            "passengers": route.get("passengers"),
            "contribution": route.get("contribution"),
        }
        for route in route_specs
    ]

    api_clients: dict[str | None, httpx.AsyncClient] = {}

    def get_api_client(proxy: str | None = None) -> httpx.AsyncClient:
        if proxy not in api_clients:
            api_clients[proxy] = httpx.AsyncClient(
                timeout=httpx.Timeout(API_TIMEOUT_SECONDS, connect=min(API_TIMEOUT_SECONDS, 10.0)),
                follow_redirects=True,
                proxy=proxy,
                headers={
                    "User-Agent": USER_AGENTS[0] if USER_AGENTS else "Mozilla/5.0",
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json",
                    "Origin": "https://in.via.com",
                    "Referer": "https://in.via.com/flight/search",
                },
            )
        return api_clients[proxy]

    client = get_api_client() if USE_DIRECT_API else None

    async with async_playwright() if not USE_DIRECT_API else _null_async_context() as playwright:
        browser = None
        context = None
        if not USE_DIRECT_API:
            browser = await playwright.chromium.launch(headless=headless)
            context = await browser.new_context(viewport={"width": 1440, "height": 1000})
            await configure_context(context)

        async def one_job(route_index: int, offset: int) -> None:
            nonlocal next_api_request_at
            async with semaphore:
                route_payload = route_results[route_index]
                route = route_specs[route_index]
                source, destination = route["origin_code"], route["destination_code"]
                source_name, destination_name = route["origin"], route["destination"]
                travel_date = run_date + timedelta(days=offset)
                dated_url = url_for_date(route_payload["route"], travel_date)
                route_html = None
                if html_out and SAVE_HTML:
                    output_path = Path(html_out).expanduser()
                    suffix = output_path.suffix or ".html"
                    stem = output_path.stem if output_path.suffix else "rendered_flight_page"
                    safe_route = re.sub(r"[^A-Za-z0-9]+", "_", route_payload["route_name"]).strip("_").lower()
                    route_html = output_path.with_name(f"{stem}_{safe_route}_T_plus_{offset}_{travel_date.isoformat()}{suffix}")
                if USE_DIRECT_API:
                    result = None
                    total_attempts = 0
                    max_attempts = max(EMPTY_RESULT_RETRIES, API_MAX_RETRIES) + 1
                    for attempt in range(max_attempts):
                        total_attempts = attempt + 1
                        try:
                            identity_index = route_index * len(offsets) + offsets.index(offset)
                            user_agent = USER_AGENTS[identity_index % len(USER_AGENTS)] if ROTATE_USER_AGENTS and USER_AGENTS else None
                            proxy = PROXY_URLS[identity_index % len(PROXY_URLS)] if PROXY_URLS else None
                            async with api_request_lock:
                                loop = asyncio.get_running_loop()
                                wait_for_slot = max(0.0, next_api_request_at - loop.time())
                                if wait_for_slot:
                                    await asyncio.sleep(wait_for_slot)
                                next_api_request_at = loop.time() + API_REQUEST_GAP_SECONDS
                                request_client = get_api_client(proxy) if USE_DIRECT_API else client
                                candidate = json.loads(await scrape_api_page(request_client, source, destination, source_name, destination_name, travel_date, user_agent))
                                candidate.setdefault("analysis", {})["user_agent_rotated"] = bool(user_agent)
                                candidate["analysis"]["proxy_configured"] = bool(proxy)
                            result = candidate
                        except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                            status = getattr(getattr(exc, "response", None), "status_code", None)
                            retry_after = getattr(getattr(exc, "response", None), "headers", {}).get("Retry-After")
                            if attempt >= API_MAX_RETRIES:
                                result = error_result(VIA_API_URL, f"{type(exc).__name__}: {exc}", total_attempts)
                                print(f"REQUEST_ERROR route={source}-{destination} offset={offset} status={status} attempts={total_attempts} error={exc}")
                                break
                            try:
                                server_wait = float(retry_after) if retry_after else 0.0
                            except ValueError:
                                server_wait = 0.0
                            delay = max(server_wait, RETRY_BACKOFF_SECONDS * (2 ** attempt)) + random.uniform(0, 0.5)
                            print(f"RETRY route={source}-{destination} offset={offset} status={status} wait={delay:.2f}s error={exc}")
                            await asyncio.sleep(delay)
                            continue

                        journeys = (result.get("analysis") or {}).get("via_journeys_found")
                        if journeys == 0 and DEBUG_EMPTY_RESULTS:
                            async with empty_debug_lock:
                                analysis = result.get("analysis") or {}
                                print(
                                    "EMPTY_RESULT "
                                    f"route_index={route_index + 1}/{len(route_specs)} "
                                    f"state={route.get('state')} "
                                    f"route={source}-{destination} "
                                    f"names={source_name}->{destination_name} "
                                    f"offset={offset} date={travel_date.isoformat()} "
                                    f"attempt={attempt + 1} status={analysis.get('http_status')} "
                                    f"bytes={analysis.get('response_bytes')} "
                                    f"keys={analysis.get('response_keys')}"
                                )
                        if journeys != 0 or attempt >= EMPTY_RESULT_RETRIES:
                            break
                        await asyncio.sleep(RETRY_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, 0.5))
                else:
                    result = json.loads(await scrape_page(context, dated_url, str(route_html) if route_html else None, wait_ms))
                result["offset_days"] = offset
                result["requested_date"] = travel_date.isoformat()
                route_payload["results"][f"T_plus_{offset}"] = result

        await asyncio.gather(*(one_job(route_index, offset) for route_index in range(len(routes)) for offset in offsets))
        if context is not None:
            await context.close()
        if browser is not None:
            await browser.close()

    for api_client in api_clients.values():
        await api_client.aclose()

    for route_payload in route_results:
        route_payload["results"] = {
            f"T_plus_{offset}": route_payload["results"][f"T_plus_{offset}"]
            for offset in offsets
            if f"T_plus_{offset}" in route_payload["results"]
        }
    nonempty_routes = sum(
        any((result.get("flights") or []) for result in route_payload["results"].values())
        for route_payload in route_results
    )
    total_flights = sum(
        len(result.get("flights") or [])
        for route_payload in route_results
        for result in route_payload["results"].values()
    )
    print(
        f"Scrape coverage: {nonempty_routes}/{len(route_results)} routes returned flights; "
        f"{total_flights} flight records across {len(route_results) * len(offsets)} route/windows."
    )
    return json.dumps({"mode": "multi_route_relative_dates", "routes": route_results}, ensure_ascii=False, indent=2)


async def scrape_date_offsets(base_url: str, offsets: list[int] = [1, 7, 15, 30, 45], html_out: str | None = "rendered_flight_page.html", wait_ms: int = 2500, headless: bool = True) -> str:
    """Scrape one route at dates relative to the date on which the script runs."""
    run_date = datetime.now(ZoneInfo("Asia/Kolkata")).date()
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
        state = route_payload.get("state", "Unknown")
        sections.append(f"STATE: {state}\nROUTE: {route_name}\n" + "=" * 60 + "\n" + report.split("\n", 2)[-1])
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
                f"  Airline:       {flight.get('airline') or 'N/A'}",
                f"  Departure:     {flight.get('departure_time') or 'N/A'}",
                f"  Arrival:       {flight.get('arrival_time') or 'N/A'}",
                f"  Price:         {flight.get('price') or 'N/A'}",
                "",
            ])
    return "\n".join(lines).rstrip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Via.com flight details for configured routes.")
    parser.add_argument("urls", nargs="*", help="Exactly three booking-page URLs")
    parser.add_argument("--routes-file", help="Text file containing exactly three URLs, one per line")
    parser.add_argument("--date-url", help="One base Via.com route URL to scrape across a date range")
    parser.add_argument("--start-date", help="First travel date in YYYY-MM-DD format; use with --date-url")
    parser.add_argument("--end-date", help="Last travel date in YYYY-MM-DD format, inclusive; use with --date-url")
    parser.add_argument("--offsets", default=",".join(str(offset) for offset in DATE_OFFSETS), help="Comma-separated day offsets for relative mode")
    parser.add_argument("--html-out", default="rendered_flight_page.html", help="Base path for complete rendered HTML files")
    parser.add_argument("--wait-ms", type=int, default=2500, help="Additional wait after page load for results to render")
    parser.add_argument("--route-limit", type=int, default=None, help="Use the first N configured routes")
    parser.add_argument("--top-routes", type=int, default=None, help="Use the N highest-passenger-volume routes")
    parser.add_argument("--headed", action="store_true", help="Show Chromium while scraping")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        args = parse_args()
        offsets = [int(value.strip()) for value in args.offsets.split(",") if value.strip()]
        if not offsets:
            raise ValueError("--offsets must contain at least one integer")
        route_limit = ROUTE_LIMIT if args.route_limit is None else max(0, args.route_limit)
        top_routes = TOP_ROUTES if args.top_routes is None else max(0, args.top_routes)
        selected_routes = select_routes(ROUTES, route_limit=route_limit, top_routes=top_routes)
        print(
            f"Selected {len(selected_routes)} of {len(ROUTES)} routes; "
            f"offsets={offsets}; concurrency={MAX_CONCURRENCY}; gap={API_REQUEST_GAP_SECONDS:.2f}s"
        )
        OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
        payload = json.loads(asyncio.run(
            scrape_all_routes(
                selected_routes,
                offsets,
                args.html_out if args.html_out else None,
                args.wait_ms,
                headless=not (SHOW_BROWSER or args.headed),
            )
        ))
        report = format_multi_route_report(payload)
        REPORT_OUTPUT.write_text(report + "\n", encoding="utf-8")
        JSON_OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(report)
        print(f"\nComplete report saved to: {REPORT_OUTPUT}")
        print(f"Structured target data saved to: {JSON_OUTPUT}")
    except PlaywrightTimeoutError as exc:
        print(f"Page load timed out: {exc}")
        raise
    except Exception as exc:
        print(f"Scrape failed: {exc}")
        raise
    finally:
        if os.getenv("INTERACTIVE", "false").lower() in {"1", "true", "yes"}:
            input("\nScraping finished. Press Enter to close this window...")
