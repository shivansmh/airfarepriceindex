# Via.com Scraper Diagnostic Summary

**Repository:** `shivansmh/airfarepriceindex`  
**Diagnostic period:** 20 September 2026  
**Scope:** Via.com direct flight-search API used by `via/scraping/flight_scraper_multiplecities.py`  
**Author:** Manus AI

## Executive conclusion

The scraper is not primarily failing because of JSON parsing, route selection, or an ordinary HTTP error. Via.com returns valid, large flight-search payloads for the first group of high-volume routes, then begins returning HTTP 200 responses that contain only a small `webDta` object. Those fallback responses contain Via’s navigation-shell metadata but no `onwardJourneys`, so the parser correctly produces zero flights.

The observed cutoff is stable. In the largest tests, the first 10 routes returned data consistently. The eleventh route returned only one populated window, and routes after that returned no populated windows. A 60-second pause between five-route batches did not change the cutoff. Closing and recreating the HTTP client between batches also did not change it.

The strongest current hypothesis is a Via-side request policy associated with the GitHub Actions runner’s IP, request quota, or server-side risk state. The evidence does not prove which control is responsible. It does show that the issue is not reset by a new local HTTP client, a one-minute pause, or a changed user-agent alone.

## How the scraper currently works

The GitHub workflow uses Python 3.11 on a GitHub-hosted Ubuntu runner. It sends requests with `httpx.AsyncClient` to:

```text
https://in.via.com/apiv2/flight/search?&flowType=NODE&ajax=true&jsonData=true
```

The request body contains one domestic route, one travel date, one adult passenger, and the requested route-search flags. The scraper parses `onwardJourneys`, deduplicates itineraries, and retains the cheapest fare variant for an identical itinerary.

The workflow uses `MAX_CONCURRENCY=5`, but all direct API calls are serialized by a shared `asyncio.Lock`. Therefore, the effective request concurrency is one. The configured minimum gap between request starts is one second. The workflow uses `EMPTY_RESULT_RETRIES=0`, so a valid but empty Via payload is recorded immediately rather than retried.

The scraper now supports route batching, atomic checkpoints, and optional HTTP-client resets between batches. The fresh-session test used five routes per batch, a 10-second inter-batch pause, and a new HTTP client after each completed batch.

## Observed response signatures

### Normal response

A successful response has the following characteristics:

| Property | Observed value |
|---|---:|
| HTTP status | 200 |
| Approximate response size | Approximately 1.0 MB |
| Top-level keys | `isDomestic`, `onwardJourneys`, `returnJourneys`, `webDta` |
| `onwardJourneys` | Hundreds of journeys |
| Parsed flight rows | Approximately 160–175 per route/window |
| Parser result | Normal flight records with fares and schedules |

For example, DEL→BOM returned between 550 and 578 journeys per window and between 168 and 174 parsed flight rows across the five tested windows.

### Fallback response

An empty response has a materially different signature:

| Property | Observed value |
|---|---:|
| HTTP status | 200 |
| Approximate response size | 2,924–2,925 bytes |
| Top-level keys | `webDta` only |
| `webDta` type | Object/dictionary |
| `onwardJourneys` | Missing, interpreted as zero |
| Parsed flight rows | 0 |
| HTTP exception | None |
| Parser exception | None |

The stored preview begins with Via navigation metadata such as `hdr`, `priNavEl`, `dsplyNm: Flights`, and links for Flights, Hotels, and Holidays. It is a navigation shell, not a flight-search result. No explicit `captcha`, `429`, `rate limit`, or error message was present in the captured top-level payload.

The scraper therefore reports this condition as `via_json_api` with `via_journeys_found: 0`; it is not currently mislabeled as a network failure. The diagnostic metadata records `response_keys`, response size, `web_data_type`, and a bounded `web_data_preview` so future changes in the fallback response can be detected.

## Experiment results

| Run | Scope | Pacing/session change | Coverage | Flight records | Result |
|---|---|---|---:|---:|---|
| [35516966824][1] | 1 route × 1 window | Standard GitHub workflow | 1/1 | 171 | Successful |
| [35517050526][2] | 1 route × 5 windows | Standard GitHub workflow | 1/1 | 854 | All five windows successful |
| [35517234669][3] | 3 routes × 5 windows | Scrape-only workflow | 3/3 | 2,510 | All windows successful |
| [35517470359][4] | 5 routes × 5 windows | Scrape-only workflow | 5/5 | 4,092 | All windows successful |
| [35517645728][5] | 25 routes × 5 windows | No batching | 11/25 | 7,539 | First 10 routes full; route 11 partial; later routes empty |
| [35518125035][6] | 25 routes × 5 windows | Five-route batches; 60-second pauses | 11/25 | 7,539 | No improvement over unpaused run |
| [35518771325][7] | 13 routes × 5 windows | Five-route batches; 10-second pauses; new client per batch | 11/13 | 7,542 | No improvement over pause-only behavior |

The 25-route runs are especially informative. Both produced exactly 11 routes with at least one flight row and exactly 7,539 flight records, despite the second run taking approximately nine minutes and inserting four one-minute pauses.

## Route-level cutoff pattern

The 13-route fresh-session test produced this result:

| Route group | Result |
|---|---|
| Routes 1–10 | All five windows populated |
| Route 11, DEL→CCU | One of five windows populated; four returned the fallback payload |
| Route 12, CCU→DEL | Zero of five windows populated |
| Route 13, DEL→AMD | Zero of five windows populated |

The same pattern appeared in the 25-route tests. The first 10 high-volume routes were stable. DEL→CCU was partially populated. Routes after that were empty.

This pattern is not consistent with a single invalid airport code or a parser bug affecting one route. It is consistent with a stateful threshold that is reached during the run, although the threshold could be based on request count, time, IP, server-side risk scoring, or a combination of those factors.

## What has been ruled out or weakened

### JSON parser failure

The parser successfully extracted thousands of records from normal payloads. Empty responses contain no `onwardJourneys` field to parse. The issue is therefore upstream of flight-row extraction.

### Ordinary HTTP rate-limit response

No 429 response was observed. The empty responses had HTTP status 200 and no HTTP exception. This does not rule out an application-level access policy, because a service can return a normal status code with a reduced or fallback payload.

### One bad route or date window

The first 10 routes returned data across all five windows. The fallback behavior begins at a route boundary during larger batches and affects many unrelated city pairs. This is not a single route-data problem.

### A single stale HTTP client

The fresh-session experiment closed every `httpx.AsyncClient` after each five-route batch and created new clients for the next batch. Coverage remained 11/13, so client object reuse is not sufficient to resolve the issue.

### A simple elapsed-time pause

The 25-route run with four 60-second pauses had the same 11/25 coverage and 7,539 flight records as the unpaused run. Waiting without changing the server-visible source or session state did not reset the behavior.

### User-agent fingerprint alone

A separate test rotated three ordinary browser user-agent strings across 10 routes. It produced zero populated windows, with HTTP 200 and the same `webDta`-only response. User-agent rotation alone did not restore results.

## Most likely explanations

The evidence currently supports three plausible explanations, in descending order of likelihood.

First, Via may apply an IP-level or runner-level request policy. The GitHub Actions environment uses one outbound runner identity for the job. The successful one-route and five-route tests show that this environment is initially accepted, while the larger tests show a later transition to fallback responses.

Second, Via may require a browser-established session or additional state that the direct API request does not reproduce after a threshold. The fallback payload is a site navigation shell, which could indicate that the API has stopped returning search data while still returning a generic application response.

Third, the direct endpoint may enforce an undocumented request quota or risk score based on route-search volume, request sequence, or request metadata. The lack of an explicit 429 does not eliminate this possibility.

These explanations are not mutually exclusive. A server-side policy could combine IP, request sequence, session state, and endpoint behavior.

## Recommended next diagnostic steps

The next tests should remain controlled and compliant with Via’s terms and robots rules.

The highest-value comparison is to run the same 13-route or 25-route workload from a second authorized execution environment with a different outbound IP, while keeping the code, headers, pacing, and route order identical. A change in the cutoff would strongly implicate runner IP or network reputation.

The second comparison is to run the same route set through the normal Via web page flow using a real Playwright browser context, rather than the direct API alone. The purpose is to determine whether Via requires browser-generated cookies or other session state. This should not attempt to evade CAPTCHA or other access controls; if Via presents a challenge, the run should record the challenge and stop.

The third comparison is to reduce request volume further and test one route per fresh workflow job. This separates per-job limits from within-job request limits, although it is slower and more expensive operationally.

The fourth improvement is to persist checkpoints as workflow artifacts in addition to writing them to `/tmp`. The current checkpoint is atomic and safe within a runner, but `/tmp` is deleted when the job ends. Uploading each checkpoint as an artifact would make partial progress available after cancellation or failure. Automatic resume can then be implemented from the last completed route batch.

Proxy testing should only use endpoints that the project owner controls or is explicitly authorized to use. Public proxy lists should not be used to evade Via’s controls. The current evidence does not justify introducing proxy rotation as the next change.

## Current implementation status

The repository now contains the following diagnostic safeguards:

1. Direct API requests are serialized with an asynchronous lock.
2. Request starts are separated by a configurable minimum gap.
3. Transient network and HTTP failures use bounded retries with exponential backoff and jitter.
4. Empty Via payloads are retained in output rather than silently discarded.
5. Fallback response metadata includes status, size, top-level keys, payload type, and a bounded preview.
6. Routes can be processed in configurable batches.
7. A configurable pause can run between batches.
8. HTTP clients can be closed and recreated between batches.
9. Atomic checkpoint JSON is written after every completed batch.
10. Scrape-only GitHub workflow dispatches skip APIx, Gemini, Supabase, database export, and Pages deployment.

## References

[1]: https://github.com/shivansmh/airfarepriceindex/actions/runs/35516966824 "GitHub Actions one-route, one-window diagnostic run"
[2]: https://github.com/shivansmh/airfarepriceindex/actions/runs/35517050526 "GitHub Actions DEL-BOM all-window diagnostic run"
[3]: https://github.com/shivansmh/airfarepriceindex/actions/runs/35517234669 "GitHub Actions three-route scrape-only run"
[4]: https://github.com/shivansmh/airfarepriceindex/actions/runs/35517470359 "GitHub Actions five-route scrape-only run"
[5]: https://github.com/shivansmh/airfarepriceindex/actions/runs/35517645728 "GitHub Actions unbatched 25-route scrape-only run"
[6]: https://github.com/shivansmh/airfarepriceindex/actions/runs/35518125035 "GitHub Actions batched 25-route scrape-only run"
[7]: https://github.com/shivansmh/airfarepriceindex/actions/runs/35518771325 "GitHub Actions fresh-session 13-route scrape-only run"
