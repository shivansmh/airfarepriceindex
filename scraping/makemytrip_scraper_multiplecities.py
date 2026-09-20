from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTES = json.loads((REPO_ROOT / "config" / "routes.json").read_text(encoding="utf-8"))["routes"]
DATE_OFFSETS = [int(value.strip()) for value in os.getenv("DATE_OFFSETS", "1,7,15,30,45").split(",") if value.strip()]
MAX_CONCURRENCY = max(1, int(os.getenv("MAX_CONCURRENCY", "1")))
REQUEST_GAP_SECONDS = max(0.0, float(os.getenv("MMT_REQUEST_GAP_SECONDS", "5")))
WAIT_MS = max(0, int(os.getenv("MMT_WAIT_MS", "3000")))
ROUTE_BATCH_SIZE = max(1, int(os.getenv("ROUTE_BATCH_SIZE", "5")))
BATCH_PAUSE_SECONDS = max(0.0, float(os.getenv("BATCH_PAUSE_SECONDS", "60")))
OUTPUT_FOLDER = Path(os.getenv("OUTPUT_FOLDER", str(REPO_ROOT / "diagnostics" / "makemytrip"))).expanduser()
CHECKPOINT_OUTPUT = os.getenv("CHECKPOINT_OUTPUT", str(OUTPUT_FOLDER / "checkpoint.json"))
SCRIPT_VERSION = "makemytrip-playwright-2026-09-20"


def select_routes(routes: list[dict[str, Any]], top_routes: int = 0, route_limit: int = 0) -> list[dict[str, Any]]:
    if top_routes > 0:
        return sorted(routes, key=lambda route: route.get("passengers", 0) or 0, reverse=True)[:top_routes]
    if route_limit > 0:
        return routes[:route_limit]
    return list(routes)


def filter_exact_routes(routes: list[dict[str, Any]], route_codes: str | None) -> list[dict[str, Any]]:
    if not route_codes:
        return routes
    requested = {code.strip().upper().replace("→", "-") for code in route_codes.split(",") if code.strip()}
    selected = [
        route for route in routes
        if f"{route['origin_code']}-{route['destination_code']}".upper() in requested
    ]
    found = {f"{route['origin_code']}-{route['destination_code']}".upper() for route in selected}
    missing = requested - found
    if missing:
        raise ValueError(f"Route code(s) not found in config/routes.json: {', '.join(sorted(missing))}")
    return selected


def mmt_url(source: str, destination: str, travel_date: date) -> str:
    # This is the normal public MakeMyTrip flight-search page flow, not a private API.
    itinerary = f"{source}-{destination}-{travel_date.strftime('%Y%m%d')}"
    return (
        "https://www.makemytrip.com/flight/search?"
        f"itinerary={quote(itinerary)}&tripType=O&paxType=A-1_C-0_I-0&intl=false&cabinClass=E&lang=eng"
    )


def first_match(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return None


def parse_card(text: str) -> dict[str, Any]:
    clean = re.sub(r"\s+", " ", text).strip()
    price = first_match([r"((?:₹|Rs\.?|INR\s*)[\s\d,]+)", r"(₹\s*[\d,]+)", r"([\d,]+\s*(?:INR|₹))"], clean)
    times = re.findall(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", clean)
    flight_number = first_match([r"\b([A-Z0-9]{2}\s*[- ]\s*\d{2,4})\b"], clean)
    airline = first_match([r"^([A-Za-z][A-Za-z &.'-]{2,40})\s+(?:\d{2}\s*[- ]\s*\d{2,4})\b"], clean)
    return {
        "airline": airline,
        "flight_number": flight_number,
        "departure_time": times[0] if times else None,
        "arrival_time": times[1] if len(times) > 1 else None,
        "price": price,
        "currency": "INR" if price else None,
        "raw_text": clean[:2000],
    }


def request_error(url: str, exc: Exception) -> dict[str, Any]:
    return {
        "url": url,
        "price": None,
        "flight_number": None,
        "departure_time": None,
        "arrival_time": None,
        "currency": None,
        "html_file": None,
        "analysis": {
            "response_type": "makemytrip_request_error",
            "error_type": type(exc).__name__,
            "error": str(exc)[:1000],
            "script_version": SCRIPT_VERSION,
        },
        "flights": [],
    }


async def extract_page(page, url: str, source: str, destination: str, travel_date: date) -> dict[str, Any]:
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeoutError:
        pass
    if WAIT_MS:
        await page.wait_for_timeout(WAIT_MS)

    body_text = await page.locator("body").inner_text(timeout=15_000)
    html = await page.content()
    card_selectors = [
        "[data-testid='listing-card']",
        "[data-cy='flight-card']",
        "div[class*='listingCard']",
        "div[class*='listing-card']",
        "div[class*='flightCard']",
    ]
    cards = []
    for selector in card_selectors:
        cards = await page.locator(selector).all_inner_texts()
        if cards:
            break
    flights = [parse_card(text) for text in cards if text.strip()]
    if not flights:
        # Keep a bounded diagnostic preview; do not treat generic page text as a flight.
        fallback = {
            "response_type": "makemytrip_page_no_cards",
            "html_characters": len(html),
            "visible_text_characters": len(body_text),
            "body_preview": re.sub(r"\s+", " ", body_text)[:1000],
            "card_selectors_checked": card_selectors,
            "script_version": SCRIPT_VERSION,
        }
    else:
        fallback = {
            "response_type": "makemytrip_rendered_cards",
            "cards_found": len(flights),
            "script_version": SCRIPT_VERSION,
        }
    return {
        "url": url,
        "price": flights[0].get("price") if flights else None,
        "flight_number": flights[0].get("flight_number") if flights else None,
        "departure_time": flights[0].get("departure_time") if flights else None,
        "arrival_time": flights[0].get("arrival_time") if flights else None,
        "currency": flights[0].get("currency") if flights else None,
        "html_file": None,
        "analysis": fallback,
        "flights": flights,
    }


async def scrape_routes(routes: list[dict[str, Any]], offsets: list[int], headless: bool = True) -> dict[str, Any]:
    run_date = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
    results = [
        {
            "script_version": SCRIPT_VERSION,
            "mode": "makemytrip_relative_dates",
            "run_date_T": run_date.isoformat(),
            "route_name": f"{route['origin']} - {route['destination']}",
            "origin": route["origin"],
            "origin_code": route["origin_code"],
            "destination": route["destination"],
            "destination_code": route["destination_code"],
            "passengers": route.get("passengers"),
            "contribution": route.get("contribution"),
            "requested_offsets": offsets,
            "results": {},
        }
        for route in routes
    ]
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    request_lock = asyncio.Lock()
    next_request_at = 0.0

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        try:
            async def one_job(route_index: int, offset: int) -> None:
                nonlocal next_request_at
                async with semaphore:
                    route = routes[route_index]
                    travel_date = run_date + timedelta(days=offset)
                    url = mmt_url(route["origin_code"], route["destination_code"], travel_date)
                    async with request_lock:
                        loop = asyncio.get_running_loop()
                        delay = max(0.0, next_request_at - loop.time())
                        if delay:
                            await asyncio.sleep(delay)
                        next_request_at = loop.time() + REQUEST_GAP_SECONDS
                        page = await context.new_page()
                        try:
                            try:
                                result = await extract_page(page, url, route["origin_code"], route["destination_code"], travel_date)
                            except Exception as exc:
                                result = request_error(url, exc)
                                print(
                                    f"REQUEST_ERROR route={route['origin_code']}-{route['destination_code']} "
                                    f"offset={offset} error={type(exc).__name__}: {exc}",
                                    flush=True,
                                )
                        finally:
                            await page.close()
                    result["offset_days"] = offset
                    result["requested_date"] = travel_date.isoformat()
                    results[route_index]["results"][f"T_plus_{offset}"] = result

            async def checkpoint() -> None:
                path = Path(CHECKPOINT_OUTPUT).expanduser()
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_name(path.name + ".tmp")
                temp.write_text(json.dumps({"mode": "makemytrip_relative_dates", "routes": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                temp.replace(path)

            for start in range(0, len(routes), ROUTE_BATCH_SIZE):
                end = min(start + ROUTE_BATCH_SIZE, len(routes))
                print(f"Starting MakeMyTrip batch: routes {start + 1}-{end} of {len(routes)}", flush=True)
                await asyncio.gather(*(one_job(index, offset) for index in range(start, end) for offset in offsets))
                await checkpoint()
                print(f"Completed MakeMyTrip batch: routes {start + 1}-{end} of {len(routes)}", flush=True)
                if end < len(routes) and BATCH_PAUSE_SECONDS:
                    print(f"Pausing {BATCH_PAUSE_SECONDS:.0f}s before the next MakeMyTrip batch", flush=True)
                    await asyncio.sleep(BATCH_PAUSE_SECONDS)
        finally:
            await context.close()
            await browser.close()

    total_flights = sum(len(result.get("flights", [])) for route in results for result in route["results"].values())
    nonempty_routes = sum(any(result.get("flights") for result in route["results"].values()) for route in results)
    print(f"MakeMyTrip coverage: {nonempty_routes}/{len(results)} routes returned cards; {total_flights} flight records.", flush=True)
    return {"mode": "makemytrip_relative_dates", "routes": results}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape MakeMyTrip rendered flight cards with conservative pacing.")
    parser.add_argument("--top-routes", type=int, default=int(os.getenv("TOP_ROUTES", "0")))
    parser.add_argument("--route-limit", type=int, default=int(os.getenv("ROUTE_LIMIT", "0")))
    parser.add_argument("--route-codes", help="Comma-separated exact route codes, for example DEL-BOM")
    parser.add_argument("--offsets", default=",".join(str(offset) for offset in DATE_OFFSETS))
    parser.add_argument("--headed", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    offsets = [int(value.strip()) for value in args.offsets.split(",") if value.strip()]
    selected = filter_exact_routes(ROUTES, args.route_codes)
    selected = select_routes(selected, top_routes=args.top_routes, route_limit=args.route_limit)
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    payload = asyncio.run(scrape_routes(selected, offsets, headless=not args.headed))
    (OUTPUT_FOLDER / "target_day.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Structured MakeMyTrip data saved to: {OUTPUT_FOLDER / 'target_day.json'}")
