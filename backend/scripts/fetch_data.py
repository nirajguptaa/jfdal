"""Download the Elexon wind data for January 2026 decisions and save a snapshot.

Run from the repo root:  python backend/scripts/fetch_data.py

Needs internet access to data.elexon.co.uk. Uses only the standard library plus pandas.
The app reads the saved files, so it never calls Elexon at request time.

Window:
  * forecasts: publishTime from 2026-01-01 to 2026-01-31 (all decisions made in January)
  * actuals:   2026-01-01 to 2026-02-15 (covers every target half hour of those forecasts,
               as far as the data goes)
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

BASE = "https://data.elexon.co.uk/bmrs/api/v1/datasets"
OUT = Path(__file__).resolve().parents[1] / "data"

PUBLISH_FROM = datetime(2026, 1, 1, tzinfo=timezone.utc)
PUBLISH_TO = datetime(2026, 2, 1, tzinfo=timezone.utc)
ACTUALS_FROM = datetime(2026, 1, 1, tzinfo=timezone.utc)
ACTUALS_TO = datetime(2026, 2, 16, tzinfo=timezone.utc)


def get_json(url: str, retries: int = 4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)
        except Exception as exc:  # network or HTTP error
            wait = 2 ** attempt
            print(f"  retry in {wait}s after error: {exc}", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"Failed after {retries} attempts: {url}")


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def chunks(start: datetime, end: datetime, days: int):
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=days), end)
        yield cur, nxt
        cur = nxt


def fetch_forecasts() -> pd.DataFrame:
    rows = []
    for a, b in chunks(PUBLISH_FROM, PUBLISH_TO, 1):
        q = urllib.parse.urlencode({"publishDateTimeFrom": iso(a), "publishDateTimeTo": iso(b), "format": "json"})
        data = get_json(f"{BASE}/WINDFOR/stream?{q}")
        print(f"WINDFOR publish {a.date()}: {len(data)} rows")
        rows.extend(data)
    df = pd.DataFrame(rows)
    return df[["startTime", "publishTime", "generation"]]


def fetch_actuals() -> pd.DataFrame:
    rows = []
    for a, b in chunks(ACTUALS_FROM, ACTUALS_TO, 7):
        q = urllib.parse.urlencode(
            {
                "settlementDateFrom": a.date().isoformat(),
                "settlementDateTo": (b - timedelta(days=1)).date().isoformat(),
                "fuelType": "WIND",
                "format": "json",
            }
        )
        data = get_json(f"{BASE}/FUELHH/stream?{q}")
        print(f"FUELHH {a.date()}..{b.date()}: {len(data)} rows")
        rows.extend(data)
    df = pd.DataFrame(rows)
    df = df[df["fuelType"] == "WIND"]  # belt and braces in case the filter is ignored
    return df[["startTime", "generation"]]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fc = fetch_forecasts().drop_duplicates(["startTime", "publishTime"])
    ac = fetch_actuals().drop_duplicates("startTime")
    fc.to_csv(OUT / "forecasts.csv.gz", index=False)
    ac.to_csv(OUT / "actuals.csv.gz", index=False)
    print(f"Saved {len(fc):,} forecast rows and {len(ac):,} actual rows to {OUT}")


if __name__ == "__main__":
    main()
