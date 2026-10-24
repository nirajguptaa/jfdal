"""Load the Elexon snapshot (produced by scripts/fetch_data.py)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[1] / "data"))


class DataMissing(RuntimeError):
    pass


@dataclass
class Dataset:
    actuals: pd.DataFrame  # startTime, generation
    forecasts: pd.DataFrame  # startTime, publishTime, generation


def _read(name: str) -> pd.DataFrame:
    path = DATA_DIR / name
    if not path.exists():
        raise DataMissing(
            f"{path} not found. Run `python backend/scripts/fetch_data.py` first."
        )
    return pd.read_csv(path)


def load_dataset() -> Dataset:
    actuals = _read("actuals.csv.gz")
    forecasts = _read("forecasts.csv.gz")
    for df in (actuals, forecasts):
        df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    forecasts["publishTime"] = pd.to_datetime(forecasts["publishTime"], utc=True)
    actuals = actuals.drop_duplicates("startTime", keep="last").sort_values("startTime")
    forecasts = forecasts.drop_duplicates(["startTime", "publishTime"], keep="last")
    return Dataset(actuals=actuals.reset_index(drop=True), forecasts=forecasts.reset_index(drop=True))
