"""Step 5: hourly rain at every camera from Open-Meteo (free, no key).

Open-Meteo's grid is ~0.1 degrees, so cameras are snapped to a 0.05-degree grid and
each grid point is fetched once (100 cameras -> 11 points). The historical-forecast API
gave identical values for Aug 2026, so only the archive API is used.

Writes data/interim/weather.parquet: one row per camera per hour with
precipitation_mm (rain in the hour ending at `hour`).
Times are Asia/Bangkok local, matching the image timestamps.

    uv run python -m cctv.weather
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

APIS = {
    "precipitation_mm": "https://archive-api.open-meteo.com/v1/archive",
}
GRID = 0.05
BATCH = 25  # coordinates per request


def fetch(url: str, lats: list[float], lons: list[float], start: str, end: str) -> list[dict]:
    query = urllib.parse.urlencode({
        "latitude": ",".join(f"{v:.3f}" for v in lats),
        "longitude": ",".join(f"{v:.3f}" for v in lons),
        "hourly": "precipitation",
        "start_date": start, "end_date": end, "timezone": "Asia/Bangkok",
    })
    req = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "cctv-course-project"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    return data if isinstance(data, list) else [data]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cameras", type=Path, default=Path("data/raw/cctv_info.csv"))
    parser.add_argument("--images", type=Path, default=Path("data/interim/images.parquet"))
    parser.add_argument("--out", type=Path, default=Path("data/interim/weather.parquet"))
    args = parser.parse_args()

    cams = pd.read_csv(args.cameras, usecols=["camera_id", "latitude", "longitude"])
    ts = pd.read_parquet(args.images, columns=["timestamp"])["timestamp"].dropna()
    start, end = ts.min().strftime("%Y-%m-%d"), ts.max().strftime("%Y-%m-%d")
    cams["glat"] = (cams["latitude"] / GRID).round() * GRID
    cams["glon"] = (cams["longitude"] / GRID).round() * GRID
    points = cams[["glat", "glon"]].drop_duplicates().reset_index(drop=True)
    print(f"{len(cams)} cameras -> {len(points)} grid points, {start} .. {end}")

    hourly = None
    for column, url in APIS.items():
        frames = []
        for i in range(0, len(points), BATCH):
            part = points.iloc[i : i + BATCH]
            for (_, p), loc in zip(part.iterrows(), fetch(url, part["glat"].tolist(), part["glon"].tolist(), start, end)):
                frames.append(pd.DataFrame({
                    "glat": p["glat"], "glon": p["glon"],
                    "hour": pd.to_datetime(loc["hourly"]["time"]),
                    column: loc["hourly"]["precipitation"],
                }))
            time.sleep(1)
        table = pd.concat(frames, ignore_index=True)
        hourly = table if hourly is None else hourly.merge(table, on=["glat", "glon", "hour"], how="outer")
        print(f"  {column}: {table[column].notna().sum()} hours, {(table[column] > 0.1).mean():.1%} wet")

    out = cams[["camera_id", "glat", "glon"]].merge(hourly, on=["glat", "glon"]).drop(columns=["glat", "glon"])
    out.to_parquet(args.out, index=False)
    print(f"wrote {args.out}: {len(out)} rows")


if __name__ == "__main__":
    main()
