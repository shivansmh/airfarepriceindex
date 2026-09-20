# Airfare price database

This folder is the repository-backed historical store for the daily flight tracker. The nightly GitHub Action runs the scraper, calculates APIx, generates the briefing, and then runs `api/export_daily_database.py`.

Each fact table receives one date-stamped JSON snapshot per India calendar day. Re-running a day replaces that day’s snapshot rather than appending duplicate rows. This keeps retries idempotent while preserving every completed day in Git history.

| Folder | Contents |
|---|---|
| `raw_scraped_flights/` | One row per observed flight, including route, booking window, carrier, travel date, times, price, and source site. `base_fare` and `taxes` are null until exposed by the source. |
| `route_window_summary/` | One row per route and booking window with the median observed price and `sample_size`. |
| `route_level_index/` | One row per route and date with the computed route-level APIx and a reserved explanation field. |
| `daily_apix/` | Daily, weekly, and monthly rows in one table shape, with the base period recorded. |
| `festival_calendar/` | Maintained CSV reference table: `date_start,date_end,festival_name`. |
| `fuel_prices/` | Maintained CSV reference table: `month,atf_price`. |

The generated `manifest.json` records the run date and row counts, which makes failed or partial exports easy to diagnose from Actions logs.

All date keys use the India calendar date (`Asia/Kolkata`) because the workflow runs at 00:00 IST.

## Supabase storage

The production database schema is also provisioned in Supabase. The nightly workflow runs `api/write_supabase.py` after the local JSON export and batch-upserts the four fact tables. To enable that step in GitHub Actions, add repository secrets named `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`. Until both secrets exist, the workflow deliberately skips the remote write and continues publishing the GitHub JSON fallback.

The one-time `--backfill` mode imports all dated JSON snapshots already present in this folder. Raw-flight records are deduplicated by date, route, booking window, itinerary, times, price, and source before upload.

## Statewise route source

The active route manifest is generated from `config/finalroutes.xlsx` and stored in `config/routes.json`. It contains **409 directional routes across 32 states**, in the workbook's original statewise order. Every target route, raw flight, route/window summary, and route-level index carries `state`, `origin`, `origin_code`, `destination`, and `destination_code`, allowing the dashboard to aggregate indexes by state without parsing display strings. Regenerate the manifest after replacing the workbook with `python tools/build_route_manifest.py`.

## Adding supporting data

Append festival ranges or monthly ATF prices to the corresponding CSV. The nightly exporter creates the headers if the files do not yet exist and does not overwrite user-maintained rows.
