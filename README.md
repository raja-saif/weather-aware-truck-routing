# Weather-Aware Truck Routing

A React + Django web app that helps a truck driver choose the safest route based on **weather**, **load weight** and **travel time**.

The driver enters an origin, destination, departure time and load weight. The app generates three route options, samples the forecast every 10, 25 or 50 miles at the truck's estimated arrival time, classifies risk with the provided rules, and recommends the best route. It also shows a 0–48 hour weather heatmap along the trip corridor.

## Status

| Area | State |
|---|---|
| Risk classification (risk table and load rules) | Done, unit-tested |
| Route geometry (checkpoints, overlap, simplification) | Done, unit-tested |
| ETA timeline with hours-of-service rest stops | Done, unit-tested |
| Route ranking and recommendation | Done, unit-tested |
| Routing, weather and geocoding providers | Done, tested with mocked HTTP |
| REST API for planning and heatmap | Done, tested |
| React frontend with map, checkpoints and heatmap | Done |
| Deployment | Planned |

## Design so far

The frontend (React, TypeScript, MapLibre GL) is in `frontend/`. The core logic lives in `backend/planner/domain/` as pure functions with no I/O, so every rule can be tested exactly. Third-party calls live in `backend/planner/services/`, and `planning.py` ties the two together.

- **`risk.py`** applies the risk table. Shared range edges such as "25–34" and "35–44" are treated as half-open bands, where the lower bound belongs to the band. The spec's ">1.00" and ">3.0" are honored, so exactly 1.00 in/hr of rain is still Severe. Load rules escalate wind only, with strict thresholds: over 30,000 lb and over 40,000 lb. A checkpoint's level is the worst of wind, rain and snow.
- **`geo.py`** places checkpoints at mile 0, every interval, and the destination, so gaps never exceed the interval. Each checkpoint covers the road halfway to its neighbors, so risk miles sum to the route length.
- **`timeline.py`** converts distance to ETA. An optional simplified FMCSA hours-of-service model inserts a 30-minute break after 8 hours of driving and a 10-hour rest after 11, so weather is sampled when the truck actually arrives.
- **`recommend.py`** ranks routes by No Travel miles, then Severe miles, High miles, average risk and travel time. Average-risk differences under 0.05 count as ties, so travel time can decide between equally safe routes.
- **`services/routing.py`** always returns three distinct truck routes. Valhalla `truck` costing is called with the gross weight (load plus a 35,000 lb tractor-trailer). When fewer than three alternatives come back, detours are generated through via points on either side of the trip's midsection. A candidate is kept only if it overlaps an accepted route by at most 80%, takes no more than 1.6 times the fastest route's time, and doesn't double back. OSRM is the fallback for long trips or when Valhalla is unavailable.
- **`services/weather.py`** fetches Open-Meteo hourly forecasts. Locations snap to a 0.05° grid, requests are batched 100 locations at a time in parallel, and results are cached for 30 minutes. Wind is interpolated between hours; rain and snow use the hour the truck is driving through.
- **`domain/corridor.py`** builds the heatmap grid along all three routes, with rows spaced evenly in Web Mercator so every cell is a square on the map.

## API

| Method and path | Purpose |
|---|---|
| `POST /api/plan` | `{origin, destination, departure_time, load_weight_lb, interval_miles: 10/25/50, hos_breaks}` returns three routes, checkpoints with weather and risk at each ETA, summaries and the recommendation. |
| `POST /api/heatmap` | `{departure_time, load_weight_lb, routes: [[lon,lat]...]}` returns the corridor grid and 49 hourly frames (0–48 h). |
| `GET /api/geocode?q=` | Place suggestions. |
| `GET /api/rules` | Risk table, load rules and ranking criteria. |
| `GET /api/health` | Liveness check. |

Errors are always shaped as `{"error": {"code", "message", "fields?"}}`. Validation errors return 400, unplannable trips 422, and provider problems 502 or 503.

## Frontend

- **Map.** All three routes, with every checkpoint colored by its risk level. Hover a checkpoint for a summary, or click it for full detail: wind, rain and snow at the ETA, the level of each, and any load rule applied. Each route has a label with its distance, trip time and risk miles.
- **Results panel.** The **Routes** tab shows the recommendation with a plain-English reason for each comparison, and the three route options. The **Checkpoints** tab shows the selected route's risk profile, HOS stops and a checkpoint table.
- **Heatmap.** A 0–48 h slider over the trip corridor, with Risk, Wind, Rain and Snow views. All 49 frames are pre-rendered, so the slider and playback never wait on the network. A truck for each route moves along with the slider.

## Running locally

Prerequisites are Python 3.10+ and Node 20+.

```bash
# backend
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # Windows: .venv\Scripts\pip
.venv/bin/python manage.py runserver                                    # http://127.0.0.1:8000

# frontend (second terminal)
cd frontend
npm ci
npm run dev                                                             # http://localhost:5173, proxies /api to Django
```

To run the production build locally, run `npm run build` in `frontend`. Django then serves the app at `http://127.0.0.1:8000`.

### Tests

```bash
cd backend && .venv/bin/python -m pytest      # no network needed (providers are mocked)
cd frontend && npx vitest run && npx tsc -b && npx eslint .
```
