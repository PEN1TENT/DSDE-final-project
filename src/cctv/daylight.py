"""Step 7: sunrise, sunset and twilight for each day from the sunrise-sunset.org API (free, no key).

All 100 cameras lie within ~25 km of each other, which shifts sunrise by under a minute,
so one point (the camera centroid) is fetched per day. Raw responses are cached in
data/raw/external/daylight.json.

Writes data/interim/daylight.parquet: one row per date with sunrise, sunset,
civil_twilight_begin and civil_twilight_end (Asia/Bangkok, tz-naive like image timestamps).
`light_phase()` turns a timestamp into day / twilight / night.

    uv run python -m cctv.daylight
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

API = "https://api.sunrise-sunset.org/json"
FIELDS = ["sunrise", "sunset", "civil_twilight_begin", "civil_twilight_end"]


def fetch_day(lat: float, lon: float, day: str) -> dict:
    query = urllib.parse.urlencode({"lat": f"{lat:.4f}", "lng": f"{lon:.4f}", "date": day,
                                    "formatted": 0, "tzid": "Asia/Bangkok"})
    req = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": "cctv-course-project"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    if data.get("status") != "OK":
        raise RuntimeError(f"{day}: {data.get('status')}")
    return data["results"]


def light_phase(timestamps: pd.Series, daylight: pd.DataFrame) -> pd.Series:
    """'day' between sunrise and sunset, 'twilight' in civil twilight, else 'night'."""
    ts = pd.to_datetime(timestamps)
    sun = pd.DataFrame({"date": ts.dt.normalize()}).merge(daylight, on="date", how="left")
    t = ts.to_numpy()
    phase = np.where(
        (t >= sun["sunrise"].to_numpy()) & (t < sun["sunset"].to_numpy()), "day",
        np.where((t >= sun["civil_twilight_begin"].to_numpy()) & (t < sun["civil_twilight_end"].to_numpy()),
                 "twilight", "night"))
    return pd.Series(np.where(sun["sunrise"].isna().to_numpy(), None, phase), index=timestamps.index)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cameras", type=Path, default=Path("data/raw/cctv_info.csv"))
    parser.add_argument("--images", type=Path, default=Path("data/interim/images.parquet"))
    parser.add_argument("--cache", type=Path, default=Path("data/raw/external/daylight.json"))
    parser.add_argument("--out", type=Path, default=Path("data/interim/daylight.parquet"))
    args = parser.parse_args()

    cams = pd.read_csv(args.cameras, usecols=["latitude", "longitude"])
    lat, lon = cams["latitude"].mean(), cams["longitude"].mean()
    ts = pd.read_parquet(args.images, columns=["timestamp"])["timestamp"].dropna()
    days = pd.date_range(ts.min().normalize(), ts.max().normalize(), freq="D").strftime("%Y-%m-%d")

    cache = json.loads(args.cache.read_text()) if args.cache.exists() else {}
    for day in days:
        if day not in cache:
            cache[day] = fetch_day(lat, lon, day)
            time.sleep(0.5)
    args.cache.parent.mkdir(parents=True, exist_ok=True)
    args.cache.write_text(json.dumps(cache, indent=1))

    rows = [{"date": pd.Timestamp(day), **{f: pd.Timestamp(cache[day][f]).tz_localize(None) for f in FIELDS},
             "day_length_h": cache[day]["day_length"] / 3600} for day in days]
    out = pd.DataFrame(rows)
    out.to_parquet(args.out, index=False)
    print(f"centroid {lat:.4f}, {lon:.4f}; wrote {args.out}: {len(out)} days")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
