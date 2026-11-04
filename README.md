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
| Routing, weather and geocoding providers | In progress |
| REST API for planning and heatmap | In progress |
| React frontend with map and heatmap | Planned |
| Deployment | Planned |

## Design so far

The core logic lives in `backend/planner/domain/` as pure functions with no I/O, so every rule can be tested exactly.

- **`risk.py`** applies the risk table. Shared range edges such as "25–34" and "35–44" are treated as half-open bands, where the lower bound belongs to the band. The spec's ">1.00" and ">3.0" are honored, so exactly 1.00 in/hr of rain is still Severe. Load rules escalate wind only, with strict thresholds: over 30,000 lb and over 40,000 lb. A checkpoint's level is the worst of wind, rain and snow.
- **`geo.py`** places checkpoints at mile 0, every interval, and the destination, so gaps never exceed the interval. Each checkpoint covers the road halfway to its neighbors, so risk miles sum to the route length.
- **`timeline.py`** converts distance to ETA. An optional simplified FMCSA hours-of-service model inserts a 30-minute break after 8 hours of driving and a 10-hour rest after 11, so weather is sampled when the truck actually arrives.
- **`recommend.py`** ranks routes by No Travel miles, then Severe miles, High miles, average risk and travel time. Average-risk differences under 0.05 count as ties, so travel time can decide between equally safe routes.

## Running the tests

```bash
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # Windows: .venv\Scripts\pip
.venv/bin/python -m pytest
```
