# airfarepriceindex

Problem ID: 26056

## Focused Via.com scraper run

The multi-city scraper defaults to conservative request behavior: one in-flight request, a 1.5-second minimum gap between Via API requests, bounded retries for empty results, and exponential backoff with jitter for transient HTTP/API failures. HTTP errors that remain after retries are retained in the JSON output as `response_type: request_error` instead of silently disappearing.

The complete route basket contains 409 routes. For diagnostics, select the highest-volume routes by passenger count rather than taking the first rows in `config/routes.json`:

```bash
PYTHONPATH="$PWD" \
OUTPUT_FOLDER="$PWD/diagnostics/run-name" \
DEBUG_EMPTY_RESULTS=true \
python3 scraping/flight_scraper_multiplecities.py \
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
