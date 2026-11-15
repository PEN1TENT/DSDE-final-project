"""Step 6: does rain change how congested Bangkok roads look?

Each snapshot is compared with its own baseline: the same camera at the same hour
of day (and weekday vs weekend). That removes rush hour, camera placement and zoom,
so what is left is "more or less crowded than usual for this spot and time".

    excess = log(1 + count) - mean over the snapshot's (camera, hour, daytype) cell

exp(excess) - 1 is then roughly "% above usual". Snapshots are grouped by rain in the
hour around them (mm/h, Open-Meteo): dry, light, moderate, heavy. Confidence
intervals come from resampling camera-days (snapshots from one camera on one day
are not independent).

Two measures are used: vehicle count, and the share of the frame covered by
vehicle boxes, which is less sensitive to the detector missing small vehicles.
Rain on the lens can also hide vehicles, so image sharpness is reported per rain
level as a check.

    uv run python -m cctv.rain
    uv run python -m cctv.rain --counts data/interim/image_counts_best.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

BINS = [-0.01, 0.1, 2.0, 5.0, np.inf]
LEVELS = ["dry", "light (0.1-2)", "moderate (2-5)", "heavy (>5)"]
MEASURES = {"vehicles": "n_vehicles", "covered": "covered_fraction"}


def load(images: Path, counts: Path, weather: Path) -> pd.DataFrame:
    img = pd.read_parquet(images, columns=["path", "camera_id", "timestamp", "brightness", "sharpness", "frozen"])
    cnt = pd.read_parquet(counts, columns=["path", "n_vehicles", "covered_fraction", "n_motorcycle", "n_car", "n_truck"])
    df = img.merge(cnt, on="path").dropna(subset=["timestamp"])
    df = df[~df["frozen"]]
    df["camera_id"] = df["camera_id"].astype(int)

    w = pd.read_parquet(weather)
    w["camera_id"] = w["camera_id"].astype(int)
    # Open-Meteo `hour` H holds rain from H-1 to H. "now" = the hour the snapshot falls in,
    # "before" = the hour before that, "after2h" = the two hours before "now" (lag check).
    rain = w.set_index(["camera_id", "hour"])["precipitation_mm"]
    now_end = df["timestamp"].dt.ceil("h")

    def lookup(end: pd.Series) -> np.ndarray:
        return rain.reindex(pd.MultiIndex.from_arrays([df["camera_id"], end])).to_numpy()

    df["rain_now"] = lookup(now_end)
    df["rain_before"] = lookup(now_end - pd.Timedelta(hours=1))
    df["rain_2h_before"] = lookup(now_end - pd.Timedelta(hours=2))
    df["hour"] = df["timestamp"].dt.hour
    df["date"] = df["timestamp"].dt.date
    df["daytype"] = np.where(df["timestamp"].dt.dayofweek >= 5, "weekend", "weekday")
    return df.dropna(subset=["rain_now"])


def add_excess(df: pd.DataFrame) -> pd.DataFrame:
    cell = [df["camera_id"], df["hour"], df["daytype"]]
    for name, col in MEASURES.items():
        y = np.log1p(df[col] * (100 if name == "covered" else 1))  # covered: percent of frame
        df[f"excess_{name}"] = y - y.groupby(cell).transform("mean")
    # Cells with one snapshot have zero excess by construction; drop them.
    df = df[df.groupby(cell)["path"].transform("size") >= 3].copy()
    return df


def effect_table(df: pd.DataFrame, rain_col: str, n_boot: int, seed: int = 0) -> pd.DataFrame:
    df = df.assign(level=pd.cut(df[rain_col], BINS, labels=LEVELS))
    cluster = df["camera_id"].astype(str) + "_" + df["date"].astype(str)
    clusters = cluster.unique()
    rng = np.random.default_rng(seed)
    cols = [f"excess_{m}" for m in MEASURES]
    # Per-cluster sums let each bootstrap draw be a cheap weighted sum.
    sums = df.groupby([cluster, "level"], observed=False)[cols].sum()
    sizes = df.groupby([cluster, "level"], observed=False).size()

    point = df.groupby("level", observed=False)[cols].mean()
    draws = []
    for _ in range(n_boot):
        pick = pd.Series(rng.choice(clusters, size=len(clusters))).value_counts()
        wts = pick.reindex(sums.index.get_level_values(0)).fillna(0).to_numpy()
        s = (sums.mul(wts, axis=0)).groupby(level="level", observed=False).sum()
        n = (sizes * wts).groupby(level="level", observed=False).sum()
        draws.append(s.div(n, axis=0))
    draws = pd.concat(draws, keys=range(n_boot))

    rows = []
    for level in LEVELS:
        row = {"rain": level, "snapshots": int((df["level"] == level).sum()),
               "sharpness": df.loc[df["level"] == level, "sharpness"].median()}
        for m, c in zip(MEASURES, cols):
            d = draws.xs(level, level="level")[c]
            row[f"{m}_%"] = 100 * np.expm1(point.loc[level, c])
            row[f"{m}_lo"] = 100 * np.expm1(d.quantile(0.025))
            row[f"{m}_hi"] = 100 * np.expm1(d.quantile(0.975))
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--images", type=Path, default=Path("data/interim/images.parquet"))
    parser.add_argument("--counts", type=Path, default=Path("data/interim/image_counts.parquet"))
    parser.add_argument("--weather", type=Path, default=Path("data/interim/weather.parquet"))
    parser.add_argument("--out", type=Path, default=Path("data/processed"))
    parser.add_argument("--boot", type=int, default=500)
    args = parser.parse_args()

    df = add_excess(load(args.images, args.counts, args.weather))
    print(f"{len(df)} snapshots, {df['camera_id'].nunique()} cameras, "
          f"{df['date'].nunique()} days, {(df['rain_now'] > 0.1).mean():.0%} in wet hours")
    pd.set_option("display.float_format", "{:.1f}".format)
    pd.set_option("display.width", 160)

    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    for col, title in [("rain_now", "rain in the snapshot's hour"),
                       ("rain_before", "rain in the hour before"),
                       ("rain_2h_before", "rain two hours before")]:
        table = effect_table(df, col, args.boot)
        results.append(table.assign(timing=col))
        print(f"\n== {title}: % vs usual for that camera/hour (95% CI) ==")
        print(table.to_string(index=False))

    # Is the effect bigger at rush hour? (rain_now, wet = > 0.1 mm)
    df["wet"] = df["rain_now"] > 0.1
    df["period"] = pd.cut(df["hour"], [5, 9, 16, 19, 22], labels=["morning 6-9", "midday 10-16", "evening 17-19", "late 20-21"], right=True)
    by = df.groupby(["period", "wet"], observed=True)["excess_vehicles"].mean().unstack()
    by = 100 * np.expm1(by)
    by["wet_minus_dry"] = by[True] - by[False]
    print("\n== wet vs dry by time of day (% vs usual, vehicles) ==")
    print(by.rename(columns={False: "dry", True: "wet"}).to_string())

    out = args.out / "rain_effect.csv"
    pd.concat(results).to_csv(out, index=False)
    df.drop(columns=["date"]).to_parquet(args.out / "rain_snapshots.parquet", index=False)
    print(f"\nwrote {out} and {args.out / 'rain_snapshots.parquet'}")


if __name__ == "__main__":
    main()
