# Wind Forecast Desk

A small web app for a GB energy utility's day-ahead buying team. It answers two questions about national wind power (Elexon data only):

1. What is the latest wind forecast I can use at the moment I have to decide?
2. How wrong have those forecasts been, in numbers?

Scope: purchase decisions made in **January 2026**, so delivery days are 2 January to 1 February 2026.

**Live app:** `https://jfdal.vercel.app/`

## AI disclosure

AI tools, including Claude (Anthropic), were used to assist with code, test and documentation development. I reviewed the implementation, ran the application and tests and take responsibility for the submitted work.

## How the decision logic works

- A buyer deciding on day D-1 can only use forecasts published before the day-ahead cut-off.
- For each half hour of delivery day D, the app takes the forecast with the **latest `publishTime` at or before the cut-off**.
- The cut-off is **09:00 London time on D-1**. This is my assumption, because the brief does not give one. It can be changed in the UI.
- Error = forecast minus actual. Positive means the forecast was too high.
- Wind forecasts from Elexon are hourly but actuals are half hourly. Each forecast point is compared with the **average actual over the period it covers**.
- The "likely range" on the forecast chart uses error quantiles (5th and 95th percentile) from earlier delivery days only.
- "Earlier" means up to **D-2**. At 09:00 on D-1, day D-1 is still being delivered, so its results are not known yet. Using it would be look-ahead.
- The **bias-corrected forecast** subtracts the average past error, using the same D-2 rule. The Accuracy tab backtests it day by day, so you can see if it really helps.
- The "bigger miss at higher wind?" chart checks whether the error grows with the forecast level. A growing error hints at curtailment or mismatched datasets. It does not prove either.

## Metrics

| Metric | Meaning |
|---|---|
| MAE | Average size of the miss, in MW |
| RMSE | Like MAE but punishes big misses more |
| Bias | Average of forecast minus actual. Shows over or under forecasting |
| MAE as % of output | MAE divided by average actual wind. Used instead of MAPE, which explodes when wind is near zero |
| P5 / P95 error | 90% of misses fall between these two values |
| Error by hour / by horizon | Shows when and how far ahead the forecasts are weakest |

## Files and directories

```
backend/
  app/
    analysis.py      Pure functions: pick latest forecast, errors, metrics, range. No I/O.
    data.py          Loads the saved data snapshot.
    main.py          FastAPI routes. Also serves the built React app when present.
  scripts/
    fetch_data.py    Downloads the Elexon data and saves it to backend/data/
  data/              actuals.csv.gz and forecasts.csv.gz (created by fetch_data.py)
  tests/             pytest tests using synthetic data
frontend/
  src/               React app (Vite + Recharts)
api/index.py         Vercel entry point for the backend
Dockerfile           Builds the React app, then runs the API plus the app on one port
docker-compose.yml   One-command local start
heroku.yml           Heroku container deploy
vercel.json          Vercel config
```

## How to start

### 1. Get the data (once)

The app reads a saved snapshot, so it never calls Elexon while running.

```bash
pip install -r backend/requirements.txt
python backend/scripts/fetch_data.py
```

This writes `backend/data/actuals.csv.gz` and `backend/data/forecasts.csv.gz`. Commit them, so the deployed app has data.

### 2a. With Docker

```bash
docker compose up --build
```

Open http://localhost:8000

### 2b. Without Docker (development)

```bash
# terminal 1
pip install -r backend/requirements-dev.txt
cd backend && uvicorn app.main:app --reload --port 8000

# terminal 2
cd frontend && npm install && npm run dev
```

Open http://localhost:5173

### Tests

```bash
cd backend && python -m pytest
```

## Deploying

**Heroku (Docker):**

```bash
heroku create
heroku stack:set container
git push heroku main
```

**Vercel:** import the repo. `vercel.json` builds the frontend and routes `/api/*` to `api/index.py`.

## API

| Route | What it returns |
|---|---|
| `GET /api/meta` | Delivery days, data ranges, assumptions |
| `GET /api/decision/{YYYY-MM-DD}?cutoff=09:00` | Decision-time forecast, actuals, range, summary |
| `GET /api/accuracy/summary` | Overall metrics and error histogram |
| `GET /api/accuracy/daily` | Metrics per delivery day |
| `GET /api/accuracy/by-hour` | Metrics per hour of day |
| `GET /api/accuracy/by-horizon` | Metrics by how far ahead the forecast was made |

## Limits

- Wind only, national level. No demand data, so the app does not compute how much to buy. It gives the wind number and its likely error.
- The 09:00 cut-off is an assumption.
- Actuals are the FUELHH half-hourly figures. They are not final settlement data.
- Day-ahead and intraday market prices are out of scope.
