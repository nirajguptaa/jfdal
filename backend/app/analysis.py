"""Pure analysis functions. No I/O, no FastAPI, so they are easy to test.

Key ideas
---------
1. A buyer deciding on day D-1 can only use forecasts published before the
   day-ahead cut-off. For every point of delivery day D we pick the latest
   forecast with publishTime <= cut-off.
2. Forecasts can be hourly while actuals are half hourly. Each forecast point is
   compared with the AVERAGE actual over the period it covers.
3. Anything learned from past errors (range, bias correction) may only use days
   whose actuals were already known at the cut-off. That is delivery days up to
   D-2, because D-1 is still running when the decision is made.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

LONDON = ZoneInfo("Europe/London")
MIN_DAYS_FOR_BAND = 3
LAG_DAYS = 2  # newest delivery day whose actuals are fully known: D - 2
HORIZON_BIN_HOURS = 6
LEVEL_BIN_MW = 2500
HALF_HOUR = pd.Timedelta(minutes=30)


# ---------------------------------------------------------------- time helpers
def local_day_bounds_utc(day: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Start and end of a London calendar day, as UTC timestamps."""
    start = datetime.combine(day, time(0, 0), tzinfo=LONDON)
    end = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=LONDON)
    return pd.Timestamp(start).tz_convert("UTC"), pd.Timestamp(end).tz_convert("UTC")


def cutoff_utc(delivery_day: date, cutoff: time) -> pd.Timestamp:
    """Decision time: `cutoff` (London clock) on the day before delivery."""
    local = datetime.combine(delivery_day - timedelta(days=1), cutoff, tzinfo=LONDON)
    return pd.Timestamp(local).tz_convert("UTC")


# ------------------------------------------------------------ resolution helpers
def step_hours(times: pd.Series, default: float = 0.5) -> float:
    """Length of one data point in hours, read from the data itself."""
    t = pd.Series(times).drop_duplicates().sort_values()
    if len(t) < 2:
        return default
    return float(t.diff().dropna().median().total_seconds() / 3600)


def forecast_step_hours(forecasts: pd.DataFrame) -> float:
    return step_hours(forecasts["startTime"])


def energy_mwh(g: pd.DataFrame, column: str) -> float:
    """Energy in MWh: sum of MW times the hours each point covers."""
    return float(g[column].sum() * step_hours(g["startTime"]))


def attach_actuals(df: pd.DataFrame, actuals: pd.DataFrame, step_h: float) -> pd.DataFrame:
    """Add `actual`: mean actual MW over the period each forecast point covers.

    Hourly forecast at 10:00 covers the 10:00 and 10:30 half hours, so it is
    compared with their average. If any half hour is missing the result is NaN.
    """
    a = actuals.set_index("startTime")["generation"]
    k = max(1, int(round(step_h / 0.5)))
    acc = np.zeros(len(df))
    for i in range(k):
        idx = pd.DatetimeIndex(df["startTime"] + i * HALF_HOUR)
        acc = acc + a.reindex(idx).to_numpy()
    return df.assign(actual=acc / k)


# ---------------------------------------------------------------- core tables
def pick_latest_forecast(forecasts: pd.DataFrame, delivery_day: date, cutoff: time) -> pd.DataFrame:
    """Latest forecast per point that was available at the cut-off."""
    start, end = local_day_bounds_utc(delivery_day)
    cut = cutoff_utc(delivery_day, cutoff)
    m = forecasts[
        (forecasts["startTime"] >= start)
        & (forecasts["startTime"] < end)
        & (forecasts["publishTime"] <= cut)
    ]
    if m.empty:
        return m.assign(horizon_h=pd.Series(dtype=float))
    idx = m.groupby("startTime")["publishTime"].idxmax()
    out = m.loc[idx].sort_values("startTime").copy()
    out["horizon_h"] = (out["startTime"] - out["publishTime"]).dt.total_seconds() / 3600
    return out


def decision_table(
    forecasts: pd.DataFrame,
    actuals: pd.DataFrame,
    delivery_days: list[date],
    cutoff: time,
) -> pd.DataFrame:
    """One row per forecast point per delivery day: decision-time forecast vs actual."""
    cols = ["startTime", "publishTime", "forecast", "actual", "error", "horizon_h", "delivery_day"]
    parts = []
    for d in delivery_days:
        p = pick_latest_forecast(forecasts, d, cutoff)
        if not p.empty:
            parts.append(p.assign(delivery_day=d))
    if not parts:
        return pd.DataFrame(columns=cols)
    df = pd.concat(parts, ignore_index=True).rename(columns={"generation": "forecast"})
    df = attach_actuals(df, actuals, forecast_step_hours(forecasts))
    df["error"] = df["forecast"] - df["actual"]  # positive = forecast too high
    return df[cols]


# --------------------------------------------------------------------- metrics
def metrics(df: pd.DataFrame) -> dict:
    """Error metrics in MW. Rows missing an actual are ignored."""
    d = df.dropna(subset=["forecast", "actual"])
    if d.empty:
        return {"n": 0}
    e = d["error"]
    mean_actual = float(d["actual"].mean())
    mae = float(e.abs().mean())
    return {
        "n": int(len(d)),
        "mae": mae,
        "rmse": float(np.sqrt((e**2).mean())),
        "bias": float(e.mean()),
        "mean_actual": mean_actual,
        # MAE as % of average output. Used instead of MAPE, which blows up
        # when wind output is close to zero.
        "nmae_pct": (mae / mean_actual * 100) if mean_actual > 0 else None,
        "p05_error": float(e.quantile(0.05)),
        "p50_error": float(e.quantile(0.50)),
        "p95_error": float(e.quantile(0.95)),
        "max_over": float(e.max()),
        "max_under": float(e.min()),
    }


def daily_metrics(table: pd.DataFrame) -> list[dict]:
    rows = []
    for day, g in table.groupby("delivery_day"):
        m = metrics(g)
        if m["n"] == 0:
            continue
        m["forecast_mwh"] = energy_mwh(g, "forecast")
        m["actual_mwh"] = energy_mwh(g.dropna(subset=["actual"]), "actual")
        m["step_hours"] = step_hours(g["startTime"])
        m["delivery_day"] = day.isoformat()
        rows.append(m)
    return rows


def hourly_profile(table: pd.DataFrame) -> list[dict]:
    """Error by London hour of day, to show if some hours are worse."""
    d = table.dropna(subset=["actual"]).copy()
    if d.empty:
        return []
    d["hour"] = d["startTime"].dt.tz_convert(LONDON).dt.hour
    out = []
    for h, g in d.groupby("hour"):
        m = metrics(g)
        out.append({"hour": int(h), "mae": m["mae"], "bias": m["bias"], "rmse": m["rmse"], "n": m["n"]})
    return out


def horizon_profile(forecasts: pd.DataFrame, actuals: pd.DataFrame) -> list[dict]:
    """Accuracy of ALL forecasts grouped by how far ahead they were made."""
    if forecasts.empty:
        return []
    d = forecasts.rename(columns={"generation": "forecast"})
    d = attach_actuals(d, actuals, forecast_step_hours(forecasts)).dropna(subset=["actual"])
    if d.empty:
        return []
    d["horizon_h"] = (d["startTime"] - d["publishTime"]).dt.total_seconds() / 3600
    d = d[d["horizon_h"] >= 0]
    d["error"] = d["forecast"] - d["actual"]
    d["bin"] = (d["horizon_h"] // HORIZON_BIN_HOURS).astype(int) * HORIZON_BIN_HOURS
    out = []
    for b, g in d.groupby("bin"):
        m = metrics(g)
        out.append(
            {
                "horizon_from_h": int(b),
                "horizon_to_h": int(b + HORIZON_BIN_HOURS),
                "mae": m["mae"],
                "rmse": m["rmse"],
                "bias": m["bias"],
                "n": m["n"],
            }
        )
    return out


def error_histogram(table: pd.DataFrame, bin_mw: int = 250) -> list[dict]:
    d = table.dropna(subset=["error"])
    if d.empty:
        return []
    lo = np.floor(d["error"].min() / bin_mw) * bin_mw
    hi = np.ceil(d["error"].max() / bin_mw) * bin_mw + bin_mw
    edges = np.arange(lo, hi + bin_mw, bin_mw)
    counts, edges = np.histogram(d["error"], bins=edges)
    return [
        {"from_mw": float(edges[i]), "to_mw": float(edges[i + 1]), "count": int(c)}
        for i, c in enumerate(counts)
    ]


def level_profile(table: pd.DataFrame, bin_mw: int = LEVEL_BIN_MW, min_points: int = 10) -> dict:
    """Does the error depend on how much wind is forecast?

    A rising bias with the forecast level would point to curtailment (farms told
    to switch off on very windy days) or a scale mismatch between the datasets.
    """
    d = table.dropna(subset=["actual"]).copy()
    if len(d) < min_points:
        return {"bins": [], "slope": None, "intercept": None, "r": None}
    d["bin"] = (d["forecast"] // bin_mw).astype(int) * bin_mw
    bins = []
    for b, g in d.groupby("bin"):
        if len(g) < min_points:
            continue
        m = metrics(g)
        bins.append(
            {
                "from_mw": int(b),
                "to_mw": int(b + bin_mw),
                "n": m["n"],
                "mae": m["mae"],
                "bias": m["bias"],
            }
        )
    slope, intercept = np.polyfit(d["forecast"], d["error"], 1)
    r = np.corrcoef(d["forecast"], d["error"])[0, 1]
    return {"bins": bins, "slope": float(slope), "intercept": float(intercept), "r": float(r)}


# ------------------------------------------- learning from the past, no look-ahead
def usable_history(table: pd.DataFrame, delivery_day: date) -> pd.DataFrame:
    """Rows whose actuals were fully known at the cut-off for `delivery_day`.

    The decision is taken on D-1, while D-1 is still being delivered. So the
    newest complete day is D-2.
    """
    newest = delivery_day - timedelta(days=LAG_DAYS)
    return table[table["delivery_day"] <= newest].dropna(subset=["error"])


def uncertainty_band(table: pd.DataFrame, delivery_day: date, lo_q=0.05, hi_q=0.95) -> dict | None:
    """90% range for actual output, built only from days known at the cut-off.

    error = forecast - actual, so actual is in [forecast - q_hi, forecast - q_lo].
    """
    prior = usable_history(table, delivery_day)
    n_days = prior["delivery_day"].nunique()
    if n_days < MIN_DAYS_FOR_BAND:
        return None
    return {
        "lower_offset_mw": float(-prior["error"].quantile(hi_q)),
        "upper_offset_mw": float(-prior["error"].quantile(lo_q)),
        "based_on_days": int(n_days),
        "based_on_points": int(len(prior)),
    }


def bias_correction(table: pd.DataFrame, delivery_day: date) -> dict | None:
    """Average past error, to subtract from the forecast. Same history rule as the band."""
    prior = usable_history(table, delivery_day)
    n_days = prior["delivery_day"].nunique()
    if n_days < MIN_DAYS_FOR_BAND:
        return None
    return {"bias_mw": float(prior["error"].mean()), "based_on_days": int(n_days)}


def apply_correction(forecast: pd.Series, bias_mw: float) -> pd.Series:
    """Subtract the bias. Wind output cannot be negative, so floor at zero."""
    return (forecast - bias_mw).clip(lower=0)


def walk_forward_correction(table: pd.DataFrame) -> dict:
    """Raw vs bias-corrected accuracy on the same days, using only past days each time."""
    raw_parts, corr_parts = [], []
    for day in sorted(table["delivery_day"].unique()):
        c = bias_correction(table, day)
        if c is None:
            continue
        g = table[table["delivery_day"] == day].dropna(subset=["actual"]).copy()
        if g.empty:
            continue
        raw_parts.append(g)
        fixed = apply_correction(g["forecast"], c["bias_mw"])
        corr_parts.append(g.assign(forecast=fixed, error=fixed - g["actual"]))
    if not raw_parts:
        return {"days_evaluated": 0, "raw": {"n": 0}, "corrected": {"n": 0}}
    raw = pd.concat(raw_parts)
    corr = pd.concat(corr_parts)
    return {
        "days_evaluated": int(raw["delivery_day"].nunique()),
        "raw": metrics(raw),
        "corrected": metrics(corr),
    }
