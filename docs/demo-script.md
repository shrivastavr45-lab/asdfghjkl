# Wind Forecast Intelligence — demo script

The complete recording must be no longer than ten minutes. Use live API results if the deployed app can reach Elexon. If Elexon is unavailable, show the honest error state and explain the retry path; do not substitute fictional readings.

## 1. Customer presentation (maximum 5 minutes)

**0:00–0:40 — Business problem**
Explain that the procurement team needs to understand the national wind generation forecast available at a decision cutoff, then compare that exact forecast vintage with actual generation after delivery.

**0:40–1:20 — Controls and assumptions**
Select a January 2026 delivery date and a cutoff. Explain that the cutoff is interpreted on the previous day in Europe/London time. The default 16:00 cutoff is a configurable demonstration assumption, not a claimed official market deadline.

**1:20–2:15 — Accuracy cards**
Explain MAE as average absolute error, RMSE as a measure that penalizes larger misses more strongly, and bias as signed forecast minus actual. Mention that all metrics use only matched, non-missing half-hour periods.

**2:15–3:10 — Charts**
Compare forecast and actual values across 48 half-hour periods. Then explain positive error (overforecast) and negative error (underforecast) around the zero line.

**3:10–4:00 — Interval table**
Show the publication timestamp separately from delivery-period time. Identify how missing actuals or forecasts are displayed without treating missing observations as zero.

**4:00–5:00 — Provenance and caveat**
Show the two allowed data sources, retrieval timestamp, applied cutoff, row counts, and warnings. Note that results depend on data available from Elexon and documented assumptions.

## 2. Technical review (maximum 5 minutes)

**0:00–0:50 — Architecture**
Show React/Vite/Recharts in `frontend/`, FastAPI routes in `backend/app/api/`, Elexon access in `backend/app/services/elexon_client.py`, and selection/normalization in `backend/app/analysis/normalization.py`.

**0:50–2:00 — Data selection logic**
Explain how actual records are filtered to WIND and the selected delivery date. Explain how forecasts are filtered by publication timestamp at or before the prior-day cutoff, with the latest eligible `publishTime` selected per `startTime`.

**2:00–3:00 — Metrics and missing data**
Show `backend/app/analysis/metrics.py` and point to MAE, RMSE, and bias. Demonstrate that no valid matched pairs yields `null` metrics rather than fake zeros.

**3:00–4:00 — Tests**
Run `cd backend` then `python -m pytest -q`. Mention deterministic fixtures, cutoff exclusion, timestamp joins, duplicate records, missing values, and API parameter tests.

**4:00–5:00 — Docker and deployment**
Show the multi-stage root `Dockerfile`: Vite production build, static assets copied into FastAPI, and Uvicorn listening on `$PORT`. Show the commands and the deployed URL only if the deployment has actually completed.
