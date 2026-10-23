# Wind Forecast Intelligence

A full-stack analytical dashboard for evaluating **UK national wind generation forecasts** against actual generation in January 2026. It is a forecasting-*evaluation* application, not a machine-learning forecasting system.

> **Data integrity rule:** the dashboard only displays values returned by the two permitted Elexon datasets. It never fills the interface with fabricated demo metrics. If Elexon is unreachable or returns unusable data, the app shows an error and leaves measurements unavailable.

## What it does

- Select a delivery date from 1–31 January 2026.
- Choose a configurable decision cutoff interpreted on the **previous day** in `Europe/London` time. The initial `16:00` value is a demonstration assumption, not an official market deadline.
- Select the latest eligible forecast publication per half-hour delivery start, applying the cutoff **before** matching or calculating metrics.
- Join forecast and actual values using the delivery `startTime` rather than publication time.
- Show 48 expected half-hour slots, forecast/actual series, interval forecast error, an interval table, coverage, retrieval provenance, and data-quality warnings.
- Export the currently loaded interval table to CSV.
- Cache successful raw API retrievals in memory for five minutes to reduce repeated API calls. No database is required.

## Stack

| Layer | Technology | Role |
|---|---|---|
| Frontend | React, Vite, Recharts, Lucide | Responsive analytics dashboard and charts |
| Backend | Python, FastAPI, Pandas, Requests, Uvicorn | API access, time-series normalization, matching, and metrics |
| Tests | Pytest, FastAPI TestClient | Deterministic analytics and HTTP/API behaviour tests |
| Delivery | Multi-stage Docker build, Docker Compose | Build React once and serve static assets from FastAPI |
| Hosting guide | Heroku Container Registry | One web container, one origin, platform-provided `PORT` |

No ML framework, database, authentication, or third-party data provider is used.

## Architecture and data flow

```text
Browser
  └─ React dashboard (Vite production build)
       └─ GET /api/analysis?date=2026-01-14&cutoff_time=16:00
            └─ FastAPI route /backend/app/api/routes.py
                 └─ analysis service and in-memory cache
                      ├─ Elexon FUELHH stream: wind actuals for delivery date
                      └─ Elexon WINDFOR stream: historical forecast publications
                           └─ normalize timestamps → apply cutoff → pick latest eligible
                                → match on delivery-period start → metrics + provenance
```

### Project tree

```text
wind-forecast-intelligence/
├── backend/
│   ├── app/
│   │   ├── api/routes.py
│   │   ├── analysis/metrics.py
│   │   ├── analysis/normalization.py
│   │   ├── services/analysis_service.py
│   │   ├── services/elexon_client.py
│   │   └── main.py
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── src/App.jsx
│   ├── src/services/api.js
│   ├── src/styles.css
│   ├── package.json
│   └── vite.config.js
├── docs/
│   ├── demo-script.md
│   └── deployment-guide.md
├── .dockerignore
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Approved data sources

Only these two Elexon Insights endpoints are used by the application:

1. **FUELHH — half-hourly generation outturn by fuel type**: [official endpoint documentation](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream). The client uses the documented publication-time filters, then locally filters returned records to `fuelType=WIND` and the selected delivery-period date.
2. **WINDFOR — wind generation forecast**: [official endpoint documentation](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream). The client retrieves forecast rows by publication-time window to preserve historical forecast vintages, then filters locally to the selected delivery date and cutoff.

General developer portal: [Elexon Insights API Developer Portal](https://developer.data.elexon.co.uk/). The portal states that APIs are public and require no API key, and that dataset endpoints permit retrieval of superseded records by published time. Elexon stream endpoints return JSON.

### Selection rules

For selected delivery date `D` and cutoff clock `C`:

1. Convert `D - 1 day` at `C` in `Europe/London` to an absolute timestamp.
2. Query FUELHH from publication time `D 00:00` through the end of a bounded 14-day post-delivery revision window. Since the stream filters by publication time, locally retain only `fuelType=WIND` rows whose delivery period belongs to `D`.
3. Retrieve WINDFOR forecast publications over the explicit 14-day lookback through the end of `D`. The two bounded windows are MVP retrieval assumptions documented in `backend/app/services/elexon_client.py`.
4. Reject any forecast publication whose `publishTime` is after the chosen cutoff. Missing publication timestamps are invalid; a later forecast is never used as a replacement.
5. For each `startTime`, keep the latest eligible `publishTime`; break exact ties deterministically.
6. Join forecast and actual values on the normalized delivery-period `startTime`.
7. Keep missing observations as `null`; only matched finite numeric pairs contribute to metrics.

January 2026 is in UK winter time (GMT). The implementation still uses timezone-aware timestamps and `Europe/London` for business-facing times.

## Metrics

Let `F` be the selected eligible forecast generation, `A` the actual generation, `e = F - A`, and `N` the number of valid matched pairs.

- **Forecast error:** `F - A`. Positive means overforecast; negative means underforecast.
- **MAE:** `sum(abs(F - A)) / N` — average error magnitude.
- **RMSE:** `sqrt(sum((F - A)^2) / N)` — gives larger errors more influence.
- **Bias:** `sum(F - A) / N` — positive means net overforecasting; negative means net underforecasting.

When `N = 0`, MAE, RMSE, and bias are returned as `null`, not zero. Percent error is intentionally not a principal metric because actual generation can be zero.

## Local development

### Prerequisites

- Python 3.12 recommended (Python 3.11+ should work with compatible dependencies).
- Node.js 22 LTS recommended.
- Git.
- Docker Desktop only if you want the Docker workflow.

### 1. Start the backend

**Windows PowerShell** from the project root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements.txt
$env:PYTHONPATH = "backend"
python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

**macOS/Linux** from the project root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
PYTHONPATH=backend python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

Check `http://localhost:8000/api/health` and interactive API documentation at `http://localhost:8000/docs`.

### 2. Start the frontend in a second terminal

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` calls to the backend at `http://127.0.0.1:8000`.

### 3. Run tests

From the project root, with backend dependencies installed:

```bash
python -m pytest -q backend/tests
```

The unit tests use local deterministic fixtures and do not need the live Elexon API. They cover the cutoff, matching, duplicate handling, missing data, timezone parsing, metrics, documented request-parameter construction, HTTP errors, and input validation.

### 4. Run the single-container version with Docker

From the project root:

```bash
docker compose up --build
```

Open `http://localhost:8000`. The root Dockerfile builds the frontend with Vite, copies the built assets into the FastAPI static directory, installs the Python dependencies, and starts Uvicorn. Stop it with `Ctrl+C`; to remove the container, run `docker compose down`.

## API endpoints

- `GET /api/health` — health response and live-data mode label.
- `GET /api/dates` — the 31 selectable dates in January 2026.
- `GET /api/analysis?date=2026-01-14&cutoff_time=16:00` — selected interval data, metrics, coverage, warnings, and provenance.

Optional `refresh=true` bypasses the raw-data cache. The cutoff must be a 24-hour `HH:MM` clock value. The endpoint only permits delivery dates from 1–31 January 2026.

## Deployment

Read the companion [Deployment Guide](docs/deployment-guide.md) for the exact GitHub and Heroku sequence. Deployment has **not** been performed from this workspace: it requires your own accounts and credentials. The app is structured for a single Docker web process and listens on the hosting platform's `PORT`.

Suggested public GitHub repository name: `uk-wind-forecast-intelligence`.

## Known limitations and assumptions

- Live Elexon data retrieval could not be independently exercised from the current build workspace because its outbound DNS/network resolution to the Elexon host failed. The API integration is isolated and tested with mocked HTTP responses, but before presenting the project, run it from a normal internet-connected machine and verify that January 2026 rows are returned by Elexon. The UI reports API failures rather than masking them.
- The FUELHH actual-revision window (delivery day through 14 days after) and the 14-day WINDFOR forecast-publication lookback are bounded MVP assumptions. Widen either window if the assignment's expected availability horizon requires it, while respecting the source API's publication-time filters.
- `16:00` is a demo cutoff, not an official trading or procurement deadline. Use the cutoff agreed by the assignment/client.
- Cache is per process and in-memory; it is intentionally not a durable store.
- The Docker image build and frontend dependency installation could not be run in this workspace because Docker is not installed and `npm install` timed out while trying to reach the package registry. Run the documented build in an internet-connected local environment before deployment.

## AI assistance disclosure

This project was implemented with assistance from **OpenAI ChatGPT (GPT-6)**. AI assistance was used to draft and refine the application structure, frontend, backend, tests, documentation, and deployment instructions. The developer should review the generated code, verify live API results, run the build/tests in their own environment, and disclose any additional tools they actually use in the final submission.
