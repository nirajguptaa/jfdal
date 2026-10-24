import pytest
from fastapi.testclient import TestClient

from app import data, main
from tests.conftest import make_actuals, make_forecasts


@pytest.fixture
def client(tmp_path, monkeypatch):
    make_actuals("2026-01-01", 40).to_csv(tmp_path / "actuals.csv.gz", index=False)
    make_forecasts("2026-01-01", 32, error=150.0).to_csv(tmp_path / "forecasts.csv.gz", index=False)
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    main.get_dataset.cache_clear()
    main.cached_table.cache_clear()
    yield TestClient(main.app)
    main.get_dataset.cache_clear()
    main.cached_table.cache_clear()


def test_meta_lists_31_delivery_days(client):
    r = client.get("/api/meta").json()
    assert r["delivery_days"][0] == "2026-01-02"
    assert r["delivery_days"][-1] == "2026-02-01"
    assert len(r["delivery_days"]) == 31
    assert r["forecast_step_hours"] == 0.5


def test_decision_endpoint(client):
    r = client.get("/api/decision/2026-01-10").json()
    assert r["periods"] == 48
    assert r["step_hours"] == 0.5
    assert r["cutoff_utc"].startswith("2026-01-09T09:00")
    assert r["band"]["based_on_days"] == 7  # Jan 2 to Jan 8, newest known day is D-2
    assert r["correction"]["bias_mw"] == pytest.approx(150.0)
    assert r["metrics_for_day"]["bias"] == pytest.approx(150.0)
    first = r["series"][0]
    # Constant +150 MW error history, so the band collapses to forecast - 150
    assert first["band_low"] == pytest.approx(first["forecast"] - 150.0)
    assert first["band_high"] == pytest.approx(first["forecast"] - 150.0)
    assert first["corrected"] == pytest.approx(first["forecast"] - 150.0)


def test_early_day_has_no_band_or_correction(client):
    r = client.get("/api/decision/2026-01-03").json()
    assert r["band"] is None
    assert r["correction"] is None
    assert "band_low" not in r["series"][0]
    assert "corrected" not in r["series"][0]


def test_unknown_day_404(client):
    assert client.get("/api/decision/2025-06-01").status_code == 404


def test_bad_cutoff_422(client):
    assert client.get("/api/accuracy/summary?cutoff=nine").status_code == 422


def test_accuracy_endpoints(client):
    s = client.get("/api/accuracy/summary").json()
    assert s["overall"]["mae"] == pytest.approx(150.0)
    assert s["walk_forward"]["raw"]["mae"] == pytest.approx(150.0)
    assert s["walk_forward"]["corrected"]["mae"] == pytest.approx(0.0, abs=1e-6)
    assert len(client.get("/api/accuracy/daily").json()) == 31
    assert len(client.get("/api/accuracy/by-hour").json()) == 24
    assert client.get("/api/accuracy/by-horizon").json()[0]["horizon_from_h"] == 0
    lvl = client.get("/api/accuracy/by-level").json()
    assert "bins" in lvl and "slope" in lvl


def test_missing_data_gives_503(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    main.get_dataset.cache_clear()
    assert TestClient(main.app).get("/api/meta").status_code == 503


def test_path_is_restored_from_query_param(client):
    """Mimics Vercel handing the app the rewritten path /api/index."""
    r = client.get("/api/index?__path=/api/meta")
    assert r.status_code == 200 and "delivery_days" in r.json()
    r = client.get("/api/index?__path=/api/decision/2026-01-10&cutoff=09:00&path=api/decision/2026-01-10")
    assert r.status_code == 200 and r.json()["delivery_day"] == "2026-01-10"
    assert client.get("/api/meta").status_code == 200  # normal calls still work


def test_unknown_api_route_is_json_404_not_html(client):
    r = client.get("/api/nope")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
