"""Step 3c: compare model counts with hand counts on the labelled sample.

Pickups are counted as cars by hand but YOLO often calls them trucks, so cars and
trucks are also compared together as `four_wheel`. Counts are recomputed from
detections.parquet at each confidence threshold, to see which one fits best.

    uv run python -m cctv.evaluate
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from cctv.labelset import time_band

GROUPS = {
    "four_wheel": ["car", "truck"],
    "motorcycle": ["motorcycle"],
    "bus": ["bus"],
    "total": ["car", "truck", "motorcycle", "bus", "bicycle"],
}


def model_counts(detections: pd.DataFrame, paths: list[str], conf: float) -> pd.DataFrame:
    kept = detections[(detections["confidence"] >= conf) & detections["path"].isin(paths)]
    table = kept.groupby(["path", "vehicle"]).size().unstack(fill_value=0)
    return table.reindex(index=paths, columns=GROUPS["total"], fill_value=0)


def grouped(table: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({g: table[cols].sum(axis=1) for g, cols in GROUPS.items()})


def error_table(model: pd.DataFrame, hand: pd.DataFrame, by: pd.Series | None = None) -> pd.DataFrame:
    """MAE, mean signed error (model - hand) and recall-like ratio sum(model)/sum(hand)."""
    rows = []
    keys = by.unique() if by is not None else [None]
    for key in sorted(keys, key=str):
        mask = (by == key) if by is not None else slice(None)
        for g in GROUPS:
            m, h = model.loc[mask, g], hand.loc[mask, g]
            rows.append({
                "group": key or "all", "class": g, "frames": len(h),
                "hand_mean": h.mean(), "model_mean": m.mean(),
                "mae": (m - h).abs().mean(), "bias": (m - h).mean(),
                "ratio": m.sum() / h.sum() if h.sum() else float("nan"),
            })
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interim", type=Path, default=Path("data/interim"))
    parser.add_argument("--labels", type=Path, default=Path("data/labels"))
    parser.add_argument("--conf", type=float, nargs="+", default=[0.25, 0.35, 0.5])
    args = parser.parse_args()

    labels = pd.read_csv(args.labels / "labels.csv")
    sample = pd.read_csv(args.labels / "sample.csv", parse_dates=["timestamp"])
    labels = labels.merge(sample, on="path")
    unusable = int(labels["unusable"].sum())
    labels = labels[labels["unusable"] == 0].set_index("path")
    paths = labels.index.tolist()
    print(f"{len(paths)} labelled frames used ({unusable} marked unusable)\n")

    hand = grouped(labels[GROUPS["total"]])
    detections = pd.read_parquet(args.interim / "detections.parquet", columns=["path", "vehicle", "confidence"])
    band = labels["timestamp"].dt.hour.map(time_band)
    band[labels["stratum"] == "day/model_zero"] = "model_zero"

    pd.set_option("display.float_format", "{:.2f}".format)
    summary = []
    for conf in args.conf:
        model = grouped(model_counts(detections, paths, conf))
        overall = error_table(model, hand).assign(conf=conf)
        summary.append(overall)
        print(f"== conf >= {conf} ==")
        print(overall.drop(columns=["group", "conf"]).to_string(index=False))
        print("\nby time band (total vehicles):")
        print(error_table(model, hand, band).query("`class` == 'total'").drop(columns="class").to_string(index=False))
        print()

    out = args.labels / "evaluation.csv"
    pd.concat(summary).to_csv(out, index=False)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
