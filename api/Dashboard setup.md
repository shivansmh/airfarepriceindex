# Dashboard setup

Place `index.html` and the scraper-generated `target_day.json` in the same folder. The dashboard reads the JSON file from that folder, refreshes immediately when opened, and checks for a newer file every 30 seconds. The **Refresh now** button can force an immediate reload.

Because browsers commonly block `fetch()` requests from `file://` pages, serve the folder through a local web server. In PowerShell, open the dashboard folder and run:

```powershell
cd "C:\Users\shiva\OneDrive\Desktop\CS"
py -m http.server 8000
```

Then open `http://localhost:8000/index.html` in the browser. Keep the server running while using the dashboard. Every time the scraper updates `target_day.json`, the dashboard will pick up the new data on its next refresh.

The dashboard expects the scraper JSON structure with `routes`, route-level `route_name`, date-window keys such as `T_plus_1`, and flight fields such as `flight_number`, `departure_time`, `time_slot`, `arrival_time`, `price`, and `baggage`.
