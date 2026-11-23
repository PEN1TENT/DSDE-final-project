"""Step 5: hourly rain at every camera from Open-Meteo (free, no key).

Open-Meteo's grid is ~0.1 degrees, so cameras are snapped to a 0.05-degree grid and
each grid point is fetched once (100 cameras -> 11 points). Raw responses are cached in
data/raw/external/ so re-runs work offline; pass --refresh to fetch again.

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

WEATHER_URLS = [
    "https://archive-api.open-meteo.com/v1/archive",
    "https://historical-forecast-api.open-meteo.com/v1/forecast",
]
WEATHER_VARS = {
    "precipitation": "precipitation_mm",
}
GRID = 0.05
BATCH = 25  # coordinates per request


def fetch(urls: list[str], fields: list[str], lats: list[float], lons: list[float], start: str, end: str) -> list[dict]:
    query = urllib.parse.urlencode({
        "latitude": ",".join(f"{v:.3f}" for v in lats),
        "longitude": ",".join(f"{v:.3f}" for v in lons),
        "hourly": ",".join(fields),
        "start_date": start, "end_date": end, "timezone": "Asia/Bangkok",
    })
    last_exc = None
    for url in urls:
        try:
            req = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "cctv-course-project"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.load(resp)
            return data if isinstance(data, list) else [data]
        except Exception as exc:
            last_exc = exc
    raise RuntimeError(f"Open-Meteo request failed: {last_exc}")


def fetch_cached(
    cache_path: Path, urls: list[str], var_map: dict[str, str], points: pd.DataFrame, start: str, end: str, refresh: bool
) -> pd.DataFrame:
    if cache_path.exists() and not refresh:
        payload = json.loads(cache_path.read_text())
    else:
        payload = []
        for i in range(0, len(points), BATCH):
            part = points.iloc[i : i + BATCH]
            locs = fetch(urls, list(var_map), part["glat"].tolist(), part["glon"].tolist(), start, end)
            for (_, p), loc in zip(part.iterrows(), locs):
                payload.append({"glat": float(p["glat"]), "glon": float(p["glon"]), "hourly": loc["hourly"]})
            if i + BATCH < len(points):
                time.sleep(1)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload))

    frames = []
    for item in payload:
        h = item["hourly"]
        row_data = {"glat": item["glat"], "glon": item["glon"], "hour": pd.to_datetime(h["time"])}
        for api_name, col_name in var_map.items():
            if api_name in h:
                row_data[col_name] = h[api_name]
        frames.append(pd.DataFrame(row_data))
    return pd.concat(frames, ignore_index=True)


def build_weather(cams: pd.DataFrame, weather_df: pd.DataFrame) -> pd.DataFrame:
    cams = cams.copy()
    cams["glat"] = (cams["latitude"] / GRID).round() * GRID
    cams["glon"] = (cams["longitude"] / GRID).round() * GRID
    return cams[["camera_id", "glat", "glon"]].merge(weather_df, on=["glat", "glon"]).drop(columns=["glat", "glon"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cameras", type=Path, default=Path("data/raw/cctv_info.csv"))
    parser.add_argument("--images", type=Path, default=Path("data/interim/images.parquet"))
    parser.add_argument("--cache", type=Path, default=Path("data/raw/external"))
    parser.add_argument("--out", type=Path, default=Path("data/interim/weather.parquet"))
    parser.add_argument("--refresh", action="store_true", help="ignore cached responses")
    args = parser.parse_args()

    cams = pd.read_csv(args.cameras, usecols=["camera_id", "latitude", "longitude"])
    ts = pd.read_parquet(args.images, columns=["timestamp"])["timestamp"].dropna()
    start, end = ts.min().strftime("%Y-%m-%d"), ts.max().strftime("%Y-%m-%d")
    cams["glat"] = (cams["latitude"] / GRID).round() * GRID
    cams["glon"] = (cams["longitude"] / GRID).round() * GRID
    points = cams[["glat", "glon"]].drop_duplicates().reset_index(drop=True)
    print(f"{len(cams)} cameras -> {len(points)} grid points, {start} .. {end}")

    weather_df = fetch_cached(args.cache / "weather.json", WEATHER_URLS, WEATHER_VARS, points, start, end, args.refresh)
    print(
        f"  precipitation_mm: {weather_df['precipitation_mm'].notna().sum()} hours, "
        f"{(weather_df['precipitation_mm'] > 0.1).mean():.1%} wet"
    )

    out = build_weather(cams, weather_df)
    out.to_parquet(args.out, index=False)
    print(f"wrote {args.out}: {len(out)} rows, columns={list(out.columns)}")


if __name__ == "__main__":
    main()
