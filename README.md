# RouteWise — fuel-smart route planner

A Django REST API for a fixed U.S. driving route. It returns a driving route as GeoJSON, recommended fuel stops, the gallons to buy at each stop, and the estimated cost of fuel bought after departure.

This repository is structured to be easy to read and explain. The domain algorithm lives in small, mostly framework-independent functions; Django handles HTTP, persistence, validation, and configuration.

## What it does

- Accepts a U.S. starting location and destination as readable place names or addresses.
- Geocodes both locations with the OpenRouteService Geocoding API, constrained to the United States.
- Makes one OpenRouteService driving-directions request and uses its returned GeoJSON line for the map.
- Finds supplied fuel stations near the route without making a request for each station.
- Calculates a minimum-cost fuel-purchase plan under the stated vehicle assumptions.
- Returns route distance, estimated time, map geometry, stops, per-stop fuel quantity/cost, and transparent data-quality warnings.
- Caches geocoding responses for 30 days and route responses for one day.

An uncached trip therefore makes at most three routing-provider requests: two geocoding requests and one route request. A repeated trip usually makes fewer because the individual responses are cached.

## Important assumptions and data limitations

The source file `data/fuel_prices.csv` has 8,151 rows and these columns:

- `OPIS Truckstop ID`
- `Truckstop Name`
- `Address`
- `City`
- `State`
- `Rack ID`
- `Retail Price`

It does **not** contain latitude, longitude, or a price-observation timestamp. These omissions matter:

1. **Coordinates:** The importer attaches the 2025 U.S. Census Places Gazetteer internal point for each matching city/state. This is an approximate place-level location, not the exact truck-stop driveway or pump. Exact coordinates can override it with `--coordinates`.
2. **Repeated station IDs:** The CSV contains repeated station IDs with different prices. Because no timestamp is supplied, the importer keeps the lowest observed price for each ID. That is an explicit best-observed-price assumption, not a claim that the value is current.
3. **Fuel spending:** The vehicle begins with a full 50-gallon tank. The result's `fuel_cost_usd` includes purchases made after departure. It does not include the starting tank, because the source data does not tell us where or at what price that fuel was bought.
4. **Route corridor:** A representative station point must lie within `MAX_STATION_DEVIATION_MILES` (default 5) of the route. The chosen point can still be far from the real station because of the missing source coordinates.
5. **Driving profile:** The API plans a normal car route (`driving-car`). Change the ORS profile if the assessment expects heavy truck restrictions.

These are deliberate, visible constraints.

## Requirements

- Python 3.12 or later.
- Django 6.1.2.
- Django REST Framework 3.18.3.
- An OpenRouteService API key. The free Standard plan currently lists 2,000 directions requests/day and 1,000 geocoding requests/day; provider quotas can change.

Django 6.1.2 requires Python 3.12+. DRF 3.18.0 added Django 6.1 support; 3.18.3 is the patch release used here.

## Step 1 — create a virtual environment

### macOS / Linux

```bash
cd routewise_assessment
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Windows PowerShell

```powershell
cd routewise_assessment
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Python 3.12 or a later supported version is fine; use the same interpreter when creating the environment and running Django commands.

## Step 2 — configure the routing API key

1. Create a free OpenRouteService account and generate a Standard API key.
2. Copy `.env.example` to `.env`.
3. Put your key in the `ORS_API_KEY` entry.
4. Change `DJANGO_SECRET_KEY` to a long random string.

The `.env` file is read by Django settings and is ignored by Git. **Never commit `.env` or paste your API key into Postman, a Loom video, or a public GitHub repository.**

Example `.env`:

```dotenv
ORS_API_KEY=your_real_key_here
DJANGO_SECRET_KEY=a-long-random-secret-value
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
MAX_STATION_DEVIATION_MILES=5
```

## Step 3 — create the database

```bash
python manage.py migrate
```

The first migration creates the `FuelStation` table and useful indexes.

## Step 4 — import the supplied prices

```bash
python manage.py import_fuel_prices --csv data/fuel_prices.csv
```

The command downloads the U.S. Census Bureau's 2025 national Places Gazetteer ZIP into `data/` if it is not already there. It then:

- keeps only the 50 U.S. states and Washington, D.C.;
- groups repeated rows by `OPIS Truckstop ID`;
- keeps the lowest observed price within each group;
- matches city/state to a Census place point;
- inserts or updates the local station database; and
- prints how many rows received approximate coordinates and how many remain unlocated.

If the automatic download is blocked, download the **National Places Gazetteer** ZIP from the [U.S. Census Bureau Gazetteer files page](https://www.census.gov/geographies/reference-files/2025/geo/gazetter-file.html) and run:

```bash
python manage.py import_fuel_prices \
  --csv data/fuel_prices.csv \
  --gazetteer data/2025_Gaz_place_national.zip
```

### Optional — replace place points with exact station coordinates

Create a CSV with these three columns:

```csv
station_id,latitude,longitude
12345,32.123456,-96.123456
```

Use the real coordinates for the corresponding station ID, then import:

```bash
python manage.py import_fuel_prices \
  --csv data/fuel_prices.csv \
  --coordinates data/station_coordinates.csv
```

The sample row above is illustrative only. Do not copy it as a real station location. A later import without an override file preserves previously imported exact coordinates.

## Step 5 — run the application

```bash
python manage.py runserver
```

Open <http://127.0.0.1:8000/> for the browser demo.

The map uses Leaflet and OpenStreetMap tiles. It displays OpenStreetMap attribution. The standard OSM tile servers are a community service with a usage policy and no service-level guarantee; for a public production deployment, choose a tile provider appropriate for your traffic or host your own tiles.

## Step 6 — call the API

### Request

`POST http://127.0.0.1:8000/api/v1/plan/`

```json
{
  "start": "Los Angeles, CA",
  "finish": "New York, NY"
}
```

`start` and `finish` can be cities, ZIP codes, or postal addresses. The geocoder is constrained to `US`; a non-U.S. result is rejected.

### Example with curl

```bash
curl --request POST \
  --url http://127.0.0.1:8000/api/v1/plan/ \
  --header 'Content-Type: application/json' \
  --data '{"start":"Los Angeles, CA","finish":"New York, NY"}'
```

### Main response shape

The actual response contains the complete route geometry returned by ORS. GeoJSON coordinates are `[longitude, latitude]`. The main fields are:

| Field | Meaning |
|---|---|
| `origin`, `destination` | Resolved U.S. labels and latitude/longitude |
| `route.type`, `route.coordinates` | GeoJSON `LineString` and its route points |
| `route.distance_miles` | Driving distance from the routing provider, converted to miles |
| `route.duration_hours` | Provider's estimated driving time, converted to hours |
| `vehicle` | 500-mile range, 10 MPG, 50-gallon tank, and full-starting-tank assumption |
| `fuel_plan.is_feasible` | Whether the local station candidates form a valid refuelling chain |
| `fuel_plan.stops` | Only the stations where the plan actually buys fuel |
| `fuel_plan.total_fuel_used_gallons` | Route distance divided by 10 MPG |
| `fuel_plan.fuel_purchased_gallons` | Fuel purchased after departure; excludes the starting tank |
| `fuel_plan.fuel_cost_usd` | Sum of the selected en-route purchases, formatted to cents |
| `warnings` | Price freshness, approximate coordinates, route corridor, and starting-fuel assumptions |
| `provider_calls_on_cache_miss` | The two geocoding requests plus one directions request on a cold request |

Each object in `fuel_plan.stops` includes `station_id`, station name/address/city/state, map coordinates, `location_precision`, price per gallon, fuel on arrival, gallons to purchase, fuel after purchase, distance to the next selected stop, and estimated purchase cost.

For example, the stop-level fields look like this (illustrative values only):

```json
{
  "station_id": 12345,
  "name": "Example Travel Center",
  "city": "Example City",
  "state": "TX",
  "latitude": 32.12,
  "longitude": -96.12,
  "location_precision": "place_point",
  "price_per_gallon_usd": 3.25,
  "fuel_on_arrival_gallons": 8.0,
  "gallons_to_purchase": 27.0,
  "fuel_after_purchase_gallons": 35.0,
  "distance_to_next_stop_miles": 350.0,
  "estimated_purchase_cost_usd": "87.75"
}
```

If no station chain can cover the route with legs of 500 miles or less, the API still returns the route and sets `fuel_plan.is_feasible` to `false`, with an explanation. It does not invent a stop.

Other endpoints:

- `GET /api/v1/health/` — basic health check.
- `GET /` — browser demonstration.

## Step 7 — run tests

```bash
python manage.py test
```

The tests use synthetic route geometry and prices. They do not spend provider quota or depend on a live routing service. They cover fuel range, a route that needs multiple stops, cheaper-station selection, a route that is infeasible with the supplied stations, and geometry projection.

## Postman

Import `postman/RouteWise.postman_collection.json` into Postman, start the local Django server, and send the `Create fuel-smart route` request. The collection uses the same sample locations as the browser demo.

## How the optimizer works

A tempting but incorrect shortcut is “sort nearby stations by price and pick the cheapest.” That ignores how far the vehicle can travel and how much fuel is left in the tank.

The planner uses the classic greedy gas-station rule:

1. Start with 50 gallons.
2. At the current station, look forward no more than 500 miles.
3. If a cheaper station is reachable with a full tank, buy only enough fuel to reach the **nearest** cheaper station.
4. If no cheaper station is reachable, buy enough to fill the tank, then advance to the next station.
5. If the destination is reachable with the current fuel, finish; if the next required station is more than 500 miles away, report that the route is infeasible with the supplied data.

Why this is optimal under the stated assumptions: when a cheaper station is within one tank's range, every extra gallon bought now instead of there costs more. When no cheaper station is reachable, every station that can be reached before the next full-tank decision has an equal or higher price, so filling now is the least-cost choice. Repeating this exchange argument produces the minimum-cost purchase plan for a fixed route with divisible fuel, fixed prices, and no detour costs.

The algorithm is in `fuel_planner/services/optimizer.py`. It accepts plain Python dictionaries and does not know anything about Django models, HTTP, or the database. That separation makes it simple to test and explain.

## Performance decisions

- **One directions call:** the response includes the full route geometry, distance, and duration.
- **Two geocoding calls at most:** both inputs are resolved in one request each; the results are cached separately.
- **Cache:** location results live for 30 days and route results for one day. The local demo uses Django's in-memory cache. For multiple production workers, configure a shared Redis cache.
- **Local fuel data:** station records are stored in SQLite and projected onto the returned route locally. There is no external request per station.
- **Route corridor:** station points outside the configured corridor are discarded before optimization.
- **Database indexes:** state/city and latitude/longitude indexes support the local data lookups.

An uncached trip is three external calls, which is within the assessment's acceptable two-or-three-call target. Repeat requests can use cached geocoding and routing data.

## Source references

- [Django supported versions and releases](https://www.djangoproject.com/download/)
- [Django 6.1.2 release notes](https://docs.djangoproject.com/en/6.1/releases/6.1.2/)
- [Django REST Framework release notes](https://www.django-rest-framework.org/community/release-notes/)
- [OpenRouteService API docs](https://openrouteservice.org/dev/)
- [OpenRouteService free Standard plan and quotas](https://staging.openrouteservice.org/plans/)
- [OpenRouteService API restrictions](https://openrouteservice.org/restrictions/)
- [U.S. Census Bureau 2025 Gazetteer Files](https://www.census.gov/geographies/reference-files/2025/geo/gazetter-file.html)
- [OpenStreetMap tile usage policy](https://operations.osmfoundation.org/policies/tiles/)
