from datetime import date, time

import pandas as pd
import pytest

from app import analysis


def test_cutoff_is_day_before_in_utc_for_january():
    c = analysis.cutoff_utc(date(2026, 1, 5), time(9, 0))
    assert c == pd.Timestamp("2026-01-04T09:00:00Z")


def test_latest_forecast_respects_cutoff(forecasts):
    p = analysis.pick_latest_forecast(forecasts, date(2026, 1, 5), time(9, 0))
    assert len(p) == 48
    assert (p["publishTime"] <= pd.Timestamp("2026-01-04T09:00:00Z")).all()


def test_latest_means_most_recent_publish(forecasts):
    p = analysis.pick_latest_forecast(forecasts, date(2026, 1, 5), time(9, 0))
    assert (p["publishTime"] == pd.Timestamp("2026-01-04T09:00:00Z")).all()


def test_changing_cutoff_changes_publish_time(forecasts):
    early = analysis.pick_latest_forecast(forecasts, date(2026, 1, 5), time(6, 0))
    late = analysis.pick_latest_forecast(forecasts, date(2026, 1, 5), time(11, 0))
    assert early["publishTime"].max() < late["publishTime"].max()


def test_no_forecast_returns_empty(forecasts):
    assert analysis.pick_latest_forecast(forecasts, date(2025, 6, 1), time(9, 0)).empty


def test_error_sign_and_metrics(forecasts, actuals):
    t = analysis.decision_table(forecasts, actuals, [date(2026, 1, 5)], time(9, 0))
    assert (t["error"] == 100.0).all()  # forecast 5100, actual 5000
    m = analysis.metrics(t)
    assert m["mae"] == pytest.approx(100.0)
    assert m["rmse"] == pytest.approx(100.0)
    assert m["bias"] == pytest.approx(100.0)
    assert m["nmae_pct"] == pytest.approx(2.0)


def test_metrics_ignore_missing_actuals(forecasts, actuals):
    t = analysis.decision_table(forecasts, actuals, [date(2026, 1, 5)], time(9, 0))
    t.loc[:9, "actual"] = float("nan")
    t.loc[:9, "error"] = float("nan")
    assert analysis.metrics(t)["n"] == 38


def test_mixed_errors_rmse_above_mae():
    df = pd.DataFrame({"forecast": [110.0, 80.0], "actual": [100.0, 100.0]})
    df["error"] = df["forecast"] - df["actual"]
    m = analysis.metrics(df)
    assert m["mae"] == pytest.approx(15.0)
    assert m["rmse"] == pytest.approx((250) ** 0.5)
    assert m["bias"] == pytest.approx(-5.0)


# ---- hourly forecasts against half-hourly actuals -------------------------------
def hourly_inputs():
    times = pd.date_range("2026-01-01", periods=24 * 10, freq="1h", tz="UTC")
    rows = [(t + pd.Timedelta(hours=k), t, 6000.0) for t in times for k in range(1, 49)]
    fc = pd.DataFrame(rows, columns=["startTime", "publishTime", "generation"])
    half = pd.date_range("2026-01-01", periods=48 * 12, freq="30min", tz="UTC")
    # alternate 5000 / 5200 so the hourly average is 5100
    act = pd.DataFrame({"startTime": half, "generation": [5000.0, 5200.0] * (len(half) // 2)})
    return fc, act


def test_hourly_forecast_is_compared_with_hourly_average_actual():
    fc, act = hourly_inputs()
    assert analysis.forecast_step_hours(fc) == 1.0
    t = analysis.decision_table(fc, act, [date(2026, 1, 5)], time(9, 0))
    assert len(t) == 24
    assert (t["actual"] == 5100.0).all()  # not 5000 (first half hour only)
    assert (t["error"] == 900.0).all()


def test_energy_for_hourly_forecasts():
    """5000 MW all day must be 120,000 MWh, not 60,000."""
    times = pd.date_range("2026-01-05", periods=24, freq="1h", tz="UTC")
    g = pd.DataFrame({"startTime": times, "forecast": 5000.0})
    assert analysis.step_hours(g["startTime"]) == 1.0
    assert analysis.energy_mwh(g, "forecast") == pytest.approx(120_000)


def test_daily_metrics_energy_hourly():
    fc, act = hourly_inputs()
    t = analysis.decision_table(fc, act, [date(2026, 1, 5)], time(9, 0))
    d = analysis.daily_metrics(t)[0]
    assert d["forecast_mwh"] == pytest.approx(6000 * 24)
    assert d["actual_mwh"] == pytest.approx(5100 * 24)


def test_daily_metrics_energy(forecasts, actuals):
    t = analysis.decision_table(forecasts, actuals, [date(2026, 1, 5)], time(9, 0))
    d = analysis.daily_metrics(t)[0]
    assert d["forecast_mwh"] == pytest.approx(5100 * 48 * 0.5)
    assert d["actual_mwh"] == pytest.approx(5000 * 48 * 0.5)


# ---- no look-ahead ---------------------------------------------------------------
def test_history_stops_at_d_minus_2(forecasts, actuals):
    days = [date(2026, 1, d) for d in range(2, 10)]
    t = analysis.decision_table(forecasts, actuals, days, time(9, 0))
    h = analysis.usable_history(t, date(2026, 1, 8))
    assert h["delivery_day"].max() == date(2026, 1, 6)  # Jan 7 is still running at the cut-off


def test_band_needs_three_known_days(forecasts, actuals):
    days = [date(2026, 1, d) for d in range(2, 10)]
    t = analysis.decision_table(forecasts, actuals, days, time(9, 0))
    assert analysis.uncertainty_band(t, date(2026, 1, 5)) is None  # only Jan 2, 3 known
    band = analysis.uncertainty_band(t, date(2026, 1, 6))  # Jan 2, 3, 4 known
    assert band["based_on_days"] == 3
    # error is a constant +100, so actual = forecast - 100 at every quantile
    assert band["lower_offset_mw"] == pytest.approx(-100.0)
    assert band["upper_offset_mw"] == pytest.approx(-100.0)


def test_future_errors_do_not_change_the_band(forecasts, actuals):
    days = [date(2026, 1, d) for d in range(2, 12)]
    t = analysis.decision_table(forecasts, actuals, days, time(9, 0))
    before = analysis.bias_correction(t, date(2026, 1, 8))
    t.loc[t["delivery_day"] >= date(2026, 1, 7), "error"] = 9999.0  # wreck days that are not known yet
    after = analysis.bias_correction(t, date(2026, 1, 8))
    assert before == after


def test_bias_correction_and_floor_at_zero():
    s = pd.Series([100.0, 5000.0])
    out = analysis.apply_correction(s, 300.0)
    assert out.tolist() == [0.0, 4700.0]


def test_walk_forward_removes_constant_bias(forecasts, actuals):
    days = [date(2026, 1, d) for d in range(2, 11)]  # actuals fixture ends on Jan 10
    t = analysis.decision_table(forecasts, actuals, days, time(9, 0))
    wf = analysis.walk_forward_correction(t)
    assert wf["days_evaluated"] == 5  # Jan 6 to Jan 10
    assert wf["raw"]["mae"] == pytest.approx(100.0)
    assert wf["corrected"]["mae"] == pytest.approx(0.0, abs=1e-6)


def test_level_profile_detects_error_growing_with_level():
    n = 200
    f = pd.Series(range(n)) * 100.0 + 1000.0
    a = f - 0.2 * f  # actual always 20% below forecast
    df = pd.DataFrame({"forecast": f, "actual": a})
    df["error"] = df["forecast"] - df["actual"]
    out = analysis.level_profile(df)
    assert out["slope"] == pytest.approx(0.2)
    assert out["r"] == pytest.approx(1.0)
    assert out["bins"][0]["bias"] < out["bins"][-1]["bias"]


def test_horizon_profile_bins(forecasts, actuals):
    prof = analysis.horizon_profile(forecasts, actuals)
    assert prof[0]["horizon_from_h"] == 0
    assert all(b["mae"] == pytest.approx(100.0) for b in prof)
