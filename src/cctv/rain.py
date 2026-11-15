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
Rain on the lens and darkness also hide vehicles, so a third measure, "calibrated",
scales each class by hand/model from the labelled frames in the same condition
(time of day x wet/dry). Without it, wet evenings look emptier than they are.

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
MEASURES = {"vehicles": "n_vehicles", "covered": "covered_fraction", "calibrated": "n_calibrated"}
CLASSES = {"four_wheel": ["car", "truck"], "motorcycle": ["motorcycle"], "bus": ["bus"], "bicycle": ["bicycle"]}
PERIODS = ([5, 16, 19, 22], ["day 6-16", "evening 17-19", "late 20-21"])


def condition(hour: pd.Series, rain_mm: pd.Series) -> pd.Series:
    period = pd.cut(hour, PERIODS[0], labels=PERIODS[1]).astype(str)
    return period + np.where(rain_mm > 0.1, " wet", " dry")


def calibrate(df: pd.DataFrame, labels: Path, labelled: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add n_calibrated = sum over classes of model count x (hand / model) in that condition."""
    lab = pd.read_csv(labels / labelled.name).merge(
        pd.read_csv(labels / "assignments.csv")[["who", "path", "role"]], on=["who", "path"])
    lab = lab[(lab["role"] == "own") & (lab["unusable"] == 0)]
    lab = lab.merge(df[["path", "hour", "rain_now"] + [f"n_{c}" for cs in CLASSES.values() for c in cs]], on="path")
    lab["cond"] = condition(lab["hour"], lab["rain_now"])
    df["cond"] = condition(df["hour"], df["rain_now"])
    factors = {}
    df["n_calibrated"] = 0.0
    for name, cols in CLASSES.items():
        hand = lab[cols].sum(axis=1).groupby(lab["cond"]).sum()
        model = lab[[f"n_{c}" for c in cols]].sum(axis=1).groupby(lab["cond"]).sum()
        f = (hand / model.where(model > 0)).fillna(1.0)
        factors[name] = f
        df["n_calibrated"] += df[[f"n_{c}" for c in cols]].sum(axis=1) * df["cond"].map(f).fillna(1.0)
    table = pd.DataFrame(factors)
    table["frames"] = lab.groupby("cond").size()
    return df, table


def load(images: Path, counts: Path, weather: Path) -> pd.DataFrame:
    img = pd.read_parquet(images, columns=["path", "camera_id", "timestamp", "brightness", "sharpness", "frozen"])
    cnt = pd.read_parquet(counts, columns=["path", "n_vehicles", "covered_fraction",
                                           "n_motorcycle", "n_car", "n_truck", "n_bus", "n_bicycle"])
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
    df["daytype"] = np.where(df["timestamp"].dt.day_of_week >= 5, "weekend", "weekday")
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
    parser.add_argument("--labels", type=Path, default=Path("data/labels"))
    parser.add_argument("--labelled", type=Path, default=Path("export.csv"), help="hand labels file in --labels")
    parser.add_argument("--boot", type=int, default=500)
    args = parser.parse_args()

    df, factors = calibrate(load(args.images, args.counts, args.weather), args.labels, args.labelled)
    pd.set_option("display.float_format", "{:.2f}".format)
    print("calibration factors (hand / model) by condition:")
    print(factors.to_string())
    df = add_excess(df)
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
    for m in ["vehicles", "calibrated"]:
        by = 100 * np.expm1(df.groupby(["period", "wet"], observed=True)[f"excess_{m}"].mean().unstack())
        by["wet_minus_dry"] = by[True] - by[False]
        print(f"\n== wet vs dry by time of day (% vs usual, {m}) ==")
        print(by.rename(columns={False: "dry", True: "wet"}).to_string())

    # Leave one day out: a result that hinges on one day is not a rain effect.
    rows = []
    for drop in [None, *sorted(df["date"].unique())]:
        d = df if drop is None else df[df["date"] != drop]
        heavy = d["rain_now"] > 5
        late = d["hour"] >= 17
        e = d["excess_calibrated"]
        rows.append({"dropped": str(drop or "none"),
                     "heavy_vs_dry_%": 100 * (np.expm1(e[heavy].mean()) - np.expm1(e[~d["wet"]].mean())),
                     "evening_wet_vs_dry_%": 100 * (np.expm1(e[late & d["wet"]].mean()) - np.expm1(e[late & ~d["wet"]].mean()))})
    print("\n== leave one day out (calibrated) ==")
    print(pd.DataFrame(rows).to_string(index=False))

    out = args.out / "rain_effect.csv"
    pd.concat(results).to_csv(out, index=False)
    df.drop(columns=["date"]).to_parquet(args.out / "rain_snapshots.parquet", index=False)
    print(f"\nwrote {out} and {args.out / 'rain_snapshots.parquet'}")


if __name__ == "__main__":
    main()
