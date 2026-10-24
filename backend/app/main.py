from __future__ import annotations

from datetime import date, time, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urlencode

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import analysis
from .data import DataMissing, Dataset, load_dataset

DEFAULT_CUTOFF = "09:00"  # London time on the day before delivery (assumption, adjustable in UI)
DECISION_MONTH_START = date(2026, 1, 1)
DECISION_MONTH_END = date(2026, 1, 31)

app = FastAPI(title="Wind forecast portal", version="1.1.0")


class RestorePathMiddleware:
    """Vercel rewrites every request to one function. vercel.json passes the real path
    as ?__path=... and this puts it back, so routing works even if the platform
    hands us the rewritten path. Without the parameter it does nothing."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            qs = parse_qs(scope.get("query_string", b"").decode(), keep_blank_values=True)
            if "__path" in qs:
                path = qs["__path"][0]
                path = path if path.startswith("/") else "/" + path
                rest = [(k, v) for k, vs in qs.items() if k not in ("__path", "path") for v in vs]
                scope = dict(scope)
                scope["path"] = path
                scope["raw_path"] = path.encode()
                scope["query_string"] = urlencode(rest).encode()
        await self.inner(scope, receive, send)


app.add_middleware(RestorePathMiddleware)


@lru_cache(maxsize=1)
def get_dataset() -> Dataset:
    return load_dataset()


def ds() -> Dataset:
    try:
        return get_dataset()
    except DataMissing as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def parse_cutoff(value: str) -> time:
    try:
        hh, mm = value.split(":")
        return time(int(hh), int(mm))
    except Exception:
        raise HTTPException(status_code=422, detail="cutoff must look like HH:MM, e.g. 09:00")


def january_decision_days() -> list[date]:
    """Delivery days D whose decision day (D-1) falls in January 2026."""
    n = (DECISION_MONTH_END - DECISION_MONTH_START).days + 1
    return [DECISION_MONTH_START + timedelta(days=i + 1) for i in range(n)]


@lru_cache(maxsize=32)
def cached_table(cutoff: str) -> pd.DataFrame:
    d = ds()
    return analysis.decision_table(d.forecasts, d.actuals, january_decision_days(), parse_cutoff(cutoff))


def _clean(obj):
    """Make NaN JSON safe."""
    if isinstance(obj, float) and obj != obj:
        return None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/meta")
def meta(cutoff: str = DEFAULT_CUTOFF):
    d = ds()
    table = cached_table(cutoff)
    days = sorted(table["delivery_day"].unique()) if not table.empty else []
    return {
        "default_cutoff": DEFAULT_CUTOFF,
        "delivery_days": [x.isoformat() for x in days],
        "actuals_range": [d.actuals["startTime"].min().isoformat(), d.actuals["startTime"].max().isoformat()],
        "forecast_rows": int(len(d.forecasts)),
        "actual_rows": int(len(d.actuals)),
        "forecast_step_hours": analysis.forecast_step_hours(d.forecasts),
        "notes": {
            "decision_rule": "For each point of delivery day D, use the latest forecast published at or before the cut-off on D-1 (London time).",
            "error_sign": "error = forecast - actual. Positive means the forecast was too high.",
            "units": "MW for generation. MWh = MW x hours each data point covers, read from the data.",
            "matching": "Each forecast point is compared with the average actual over the period it covers.",
            "no_lookahead": f"Range and bias correction use only delivery days up to D-{analysis.LAG_DAYS}, which is what is known at the cut-off.",
        },
    }


@app.get("/api/decision/{delivery_day}")
def decision(delivery_day: date, cutoff: str = DEFAULT_CUTOFF):
    table = cached_table(cutoff)
    day = table[table["delivery_day"] == delivery_day]
    if day.empty:
        raise HTTPException(status_code=404, detail="No forecast was available at the cut-off for that day.")
    band = analysis.uncertainty_band(table, delivery_day)
    corr = analysis.bias_correction(table, delivery_day)
    corrected = analysis.apply_correction(day["forecast"], corr["bias_mw"]) if corr else None
    series = []
    for i, r in enumerate(day.itertuples()):
        row = {
            "startTime": r.startTime.isoformat(),
            "publishTime": r.publishTime.isoformat(),
            "forecast": r.forecast,
            "actual": r.actual,
            "horizon_h": r.horizon_h,
        }
        if band:
            row["band_low"] = r.forecast + band["lower_offset_mw"]
            row["band_high"] = r.forecast + band["upper_offset_mw"]
        if corrected is not None:
            row["corrected"] = float(corrected.iloc[i])
        series.append(row)
    cut = analysis.cutoff_utc(delivery_day, parse_cutoff(cutoff))
    pub = day["publishTime"]
    return _clean(
        {
            "delivery_day": delivery_day.isoformat(),
            "cutoff_utc": cut.isoformat(),
            "forecast_published_range": [pub.min().isoformat(), pub.max().isoformat()],
            "forecast_mean_mw": float(day["forecast"].mean()),
            "forecast_min_mw": float(day["forecast"].min()),
            "forecast_max_mw": float(day["forecast"].max()),
            "forecast_mwh": analysis.energy_mwh(day, "forecast"),
            "corrected_mwh": (
                float(corrected.sum() * analysis.step_hours(day["startTime"])) if corrected is not None else None
            ),
            "step_hours": analysis.step_hours(day["startTime"]),
            "periods": int(len(day)),
            "band": band,
            "correction": corr,
            "metrics_for_day": analysis.metrics(day),
            "series": series,
        }
    )


@app.get("/api/accuracy/summary")
def accuracy_summary(cutoff: str = DEFAULT_CUTOFF):
    table = cached_table(cutoff)
    return _clean(
        {
            "cutoff": cutoff,
            "overall": analysis.metrics(table),
            "histogram": analysis.error_histogram(table),
            "walk_forward": analysis.walk_forward_correction(table),
        }
    )


@app.get("/api/accuracy/daily")
def accuracy_daily(cutoff: str = DEFAULT_CUTOFF):
    return _clean(analysis.daily_metrics(cached_table(cutoff)))


@app.get("/api/accuracy/by-hour")
def accuracy_by_hour(cutoff: str = DEFAULT_CUTOFF):
    return _clean(analysis.hourly_profile(cached_table(cutoff)))


@app.get("/api/accuracy/by-level")
def accuracy_by_level(cutoff: str = DEFAULT_CUTOFF):
    return _clean(analysis.level_profile(cached_table(cutoff)))


@app.get("/api/accuracy/by-horizon")
def accuracy_by_horizon():
    d = ds()
    start, _ = analysis.local_day_bounds_utc(DECISION_MONTH_START)
    jan_published = d.forecasts[d.forecasts["publishTime"] >= start]
    return _clean(analysis.horizon_profile(jan_published, d.actuals))


# Serve the built React app when it is present (Docker image / Heroku).
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Unknown API route")
        f = STATIC_DIR / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(STATIC_DIR / "index.html")
