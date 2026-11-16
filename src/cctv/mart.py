"""Step 8: join every source into the tables the dashboard reads.

Inputs: rain snapshots (detections + Open-Meteo rain, from cctv.rain), camera metadata
(cctv_info.csv), OpenStreetMap road context (cctv.osm) and daylight (cctv.daylight).
The OSM and daylight inputs are optional; their columns are left empty when missing.

Writes data/processed/dashboard/:
  snapshots.parquet  one row per usable image, with rain level, light phase and road class
  cameras.parquet    one row per camera: location, road context, traffic level, rain effect

    uv run python -m cctv.mart
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from cctv.daylight import light_phase
from cctv.rain import BINS, LEVELS

SNAP_COLS = ["camera_id", "timestamp", "hour", "daytype", "period", "rain_now", "wet", "n_vehicles",
             "n_calibrated", "covered_fraction", "n_car", "n_motorcycle", "n_truck", "n_bus", "n_bicycle",
             "excess_vehicles", "excess_calibrated", "excess_covered", "brightness", "path"]


def build(snaps: pd.DataFrame, info: pd.DataFrame, osm: pd.DataFrame | None, daylight: pd.DataFrame | None):
    s = snaps[[c for c in SNAP_COLS if c in snaps.columns]].copy()
    s["date"] = s["timestamp"].dt.normalize()
    s["weekday"] = s["timestamp"].dt.day_name().str[:3]
    s["rain_level"] = pd.cut(s["rain_now"], BINS, labels=LEVELS).astype(str)
    s["period"] = s["period"].astype(str)
    s["light"] = light_phase(s["timestamp"], daylight) if daylight is not None else None

    cams = info[["camera_id", "location", "location_en", "location_detail_en", "latitude", "longitude"]].copy()
    cams["name"] = np.where(cams["location_en"].str.contains("connect BMAcctv", na=True),
                            cams["location"], cams["location_en"])
    if osm is not None:
        cams = cams.merge(osm, on="camera_id", how="left")
    s = s.merge(cams[["camera_id", "name"] + (["road_class"] if osm is not None else [])], on="camera_id", how="left")

    g = s.groupby("camera_id")
    stats = pd.DataFrame({
        "snapshots": g.size(),
        "mean_vehicles": g["n_vehicles"].mean(),
        "mean_calibrated": g["n_calibrated"].mean(),
        "mean_covered_pct": 100 * g["covered_fraction"].mean(),
        "peak_hour": s.groupby(["camera_id", "hour"])["n_calibrated"].mean().unstack().idxmax(axis=1),
        "wet_share_pct": 100 * g["wet"].mean(),
    })
    # Per-camera rain effect: % above usual when wet minus when dry (same baseline as cctv.rain).
    e = s.groupby(["camera_id", "wet"])["excess_calibrated"].agg(["mean", "size"]).unstack()
    ok = (e[("size", True)] >= 10) & (e[("size", False)] >= 10)
    stats["rain_effect_pct"] = (100 * (np.expm1(e[("mean", True)]) - np.expm1(e[("mean", False)]))).where(ok)
    stats["wet_snapshots"] = e[("size", True)].fillna(0).astype(int)
    stats = stats.join(weekend_kept(s))
    cams = cams.merge(stats.reset_index(), on="camera_id", how="left")
    return s, cams


def weekend_kept(s: pd.DataFrame) -> pd.DataFrame:
    """Per camera: weekend traffic as a % of weekday traffic, compared hour by hour.

    Only hours seen on both day types count, so a camera with missing weekday mornings is not
    compared on its busy weekday hours alone. All weather is used: rain moves counts by a few
    percent, the weekday/weekend gap is about 30%.
    """
    h = s.groupby(["camera_id", "daytype", "hour"])["n_calibrated"].mean().unstack("daytype")
    h = h.dropna(subset=["weekday", "weekend"])
    g = h.groupby("camera_id")[["weekday", "weekend"]].sum()
    hours = h.groupby("camera_id").size()
    out = pd.DataFrame({
        "weekday_mean": s[s["daytype"] == "weekday"].groupby("camera_id")["n_calibrated"].mean(),
        "weekend_mean": s[s["daytype"] == "weekend"].groupby("camera_id")["n_calibrated"].mean(),
        "weekend_kept_pct": (100 * g["weekend"] / g["weekday"]).where(hours >= 10),
    })
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshots", type=Path, default=Path("data/processed/l640/rain_snapshots.parquet"))
    parser.add_argument("--cameras", type=Path, default=Path("data/raw/cctv_info.csv"))
    parser.add_argument("--osm", type=Path, default=Path("data/interim/osm_context.parquet"))
    parser.add_argument("--daylight", type=Path, default=Path("data/interim/daylight.parquet"))
    parser.add_argument("--out", type=Path, default=Path("data/processed/dashboard"))
    args = parser.parse_args()

    load = lambda p: pd.read_parquet(p) if p.exists() else print(f"  (missing {p}, columns left empty)")
    snaps, cams = build(pd.read_parquet(args.snapshots), pd.read_csv(args.cameras), load(args.osm), load(args.daylight))
    args.out.mkdir(parents=True, exist_ok=True)
    snaps.to_parquet(args.out / "snapshots.parquet", index=False)
    cams.to_parquet(args.out / "cameras.parquet", index=False)
    print(f"wrote {args.out}: {len(snaps)} snapshots, {len(cams)} cameras")


if __name__ == "__main__":
    main()
