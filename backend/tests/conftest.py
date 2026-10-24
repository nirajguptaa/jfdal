"""Synthetic fixtures. These are for tests only and are never shipped as app data."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def make_actuals(start="2026-01-01", days=10) -> pd.DataFrame:
    idx = pd.date_range(start, periods=days * 48, freq="30min", tz="UTC")
    return pd.DataFrame({"startTime": idx, "generation": 5000.0})


def make_forecasts(start="2026-01-01", days=10, error=100.0) -> pd.DataFrame:
    """Hourly publishes; each publish covers the next 48 h. Forecast = 5000 + error."""
    rows = []
    publishes = pd.date_range(start, periods=days * 24, freq="1h", tz="UTC")
    for p in publishes:
        for k in range(1, 97):
            rows.append((p + pd.Timedelta(minutes=30 * k), p, 5000.0 + error))
    return pd.DataFrame(rows, columns=["startTime", "publishTime", "generation"])


@pytest.fixture
def actuals():
    return make_actuals()


@pytest.fixture
def forecasts():
    return make_forecasts()
