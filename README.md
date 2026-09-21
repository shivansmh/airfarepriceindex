# airfarepriceindex

Problem ID: 26056

## Focused Via.com scraper run

The multi-city scraper defaults to conservative request behavior: one in-flight request, a 1.5-second minimum gap between Via API requests, bounded retries for empty results, and exponential backoff with jitter for transient HTTP/API failures. HTTP errors that remain after retries are retained in the JSON output as `response_type: request_error` instead of silently disappearing.

The complete route basket contains 409 routes. For diagnostics, select the highest-volume routes by passenger count rather than taking the first rows in `config/routes.json`:

```bash
PYTHONPATH="$PWD" \
OUTPUT_FOLDER="$PWD/via/diagnostics/run-name" \
DEBUG_EMPTY_RESULTS=true \
python3 via/scraping/flight_scraper_multiplecities.py \
  --top-routes 10 \
  --offsets 1,7,15,30,45 \
  --html-out '' \
  --wait-ms 0
```

Useful controls are `--top-routes N`, `--route-limit N`, and `--offsets 1,7,15,30,45`. Environment variables include `API_REQUEST_GAP_SECONDS`, `MAX_CONCURRENCY`, `EMPTY_RESULT_RETRIES`, `API_MAX_RETRIES`, and `RETRY_BACKOFF_SECONDS`. Increase request volume only after confirming that the focused run returns stable data and does not trigger throttling. Scraping should remain consistent with Via.com's terms and robots rules.

The generated `target_day.json` contains one record per route/window, including the requested date, HTTP response metadata, journey counts, flight rows, and any retained error details. `target_day.txt` is the human-readable summary.

## Tests

The repository includes lightweight parser and route-selection checks:

```bash
PYTHONPATH="$PWD" python3 tests/test_airline_extraction.py
```

If `pytest` is installed, the same tests can be run with `pytest -q`.

## Project overview

The project combines Via.com airfare collection, data cleaning, an Airfare Price Index model, and a dashboard. Route definitions and passenger weights are stored in `config/routes.json` and sourced from `config/finalroutes.xlsx`.

## Provider-specific scrapers

The repository separates provider code into `via/` and `makemytrip/`. The Via implementation is stored under `via/scraping/`, and the MakeMyTrip implementation is stored under `makemytrip/scraping/`. Each provider has its own `tests/` and `diagnostics/` folders. Shared route configuration, cleaning, APIx, database, and dashboard code remains at the repository root.

Scraped data is also separated by provider. Via continues to use the root `database/` fact tables. MakeMyTrip writes its own date-stamped `raw_scraped_flights/` and `route_window_summary/` snapshots under `makemytrip/database/`, with `source_site` set to `makemytrip.com`.

MakeMyTrip runs are intentionally conservative. The default request gap is five seconds, the default route batch size is five, and the default batch pause is 60 seconds. A small first test can be run as follows:

```bash
OUTPUT_FOLDER="$PWD/makemytrip/diagnostics/makemytrip-one-route" \
MMT_REQUEST_GAP_SECONDS=5 \
ROUTE_BATCH_SIZE=1 \
BATCH_PAUSE_SECONDS=0 \
python3 makemytrip/scraping/makemytrip_scraper_multiplecities.py \
  --route-codes DEL-BOM \
  --offsets 1
```

The MakeMyTrip user agreement should be reviewed before scaling collection. The scraper does not attempt CAPTCHA bypass, private API reverse-engineering, proxy evasion, or access-control circumvention.

For Via diagnostics, an authorized proxy can be supplied as `PROXY_URLS`, a comma-separated list of `http://user:password@host:port` URLs. The GitHub workflow does not expose proxy credentials in ordinary inputs: add the single sticky Decodo endpoint as a repository secret named `DECODO_PROXY_URL`, then dispatch with `use_decodo_proxy=true`. Keep one endpoint for this comparison; do not rotate identities per request. The scraper records only `proxy_configured: true`, never the proxy URL. Proxy use must remain within the project authorization and the source site's terms.

For larger runs, the workflow processes routes in polite batches. `ROUTE_BATCH_SIZE=5` and `BATCH_PAUSE_SECONDS=60` complete five routes, write an atomic checkpoint, close the HTTP clients, pause, and then continue with a fresh HTTP session. `RESET_CLIENT_BETWEEN_BATCHES=true` controls that reset. `CHECKPOINT_OUTPUT` points to the latest incremental JSON snapshot for inspection or a future resume implementation. This is a checkpointing and load-management measure, not an attempt to bypass Via.com controls; the scraper does not implement CAPTCHA evasion or unauthorized access-control circumvention.
