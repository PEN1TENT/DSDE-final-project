"""Step 3d: compare model counts with hand counts, and humans with each other.

Hand labels are read from data/labels/labels_<who>.csv (copied back from the
homelab) or from the admin page's export (--export). Each frame's "own" label is
compared with the model; frames counted twice ("overlap") measure how much two
people disagree, which is the floor for any model error.

Pickups are counted as cars by hand but YOLO often calls them trucks, so cars and
trucks are also compared together as `four_wheel`. Counts are recomputed from
detections.parquet at each confidence threshold, to see which one fits best.

    uv run python -m cctv.evaluate
    uv run python -m cctv.evaluate --export ~/Downloads/export.csv
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


def load_labels(labels_dir: Path, export: Path | None) -> pd.DataFrame:
    if export is not None:
        return pd.read_csv(export)
    files = sorted(labels_dir.glob("labels_*.csv"))
    if not files:
        raise SystemExit(f"no labels_*.csv in {labels_dir}; copy them from the homelab or pass --export")
    return pd.concat([pd.read_csv(f).assign(who=f.stem.removeprefix("labels_")) for f in files], ignore_index=True)


def agreement(labels: pd.DataFrame) -> pd.DataFrame:
    """Human vs human on frames counted by two people."""
    usable = labels[labels["unusable"] == 0]
    own = usable[usable["role"] == "own"].set_index("path")
    second = usable[usable["role"] == "overlap"].set_index("path")
    both = own.index.intersection(second.index)
    a, b = grouped(own.loc[both, GROUPS["total"]]), grouped(second.loc[both, GROUPS["total"]])
    rows = [
        {"class": g, "pairs": len(both), "mean": (a[g] + b[g]).mean() / 2,
         "mae": (a[g] - b[g]).abs().mean(), "exact_match": (a[g] == b[g]).mean()}
        for g in GROUPS
    ]
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interim", type=Path, default=Path("data/interim"))
    parser.add_argument("--labels", type=Path, default=Path("data/labels"))
    parser.add_argument("--export", type=Path, default=None, help="CSV from the admin page instead of labels_*.csv")
    parser.add_argument("--conf", type=float, nargs="+", default=[0.25, 0.35, 0.5])
    args = parser.parse_args()

    raw = load_labels(args.labels, args.export)
    assignments = pd.read_csv(args.labels / "assignments.csv")[["who", "path", "role"]]
    sample = pd.read_csv(args.labels / "sample.csv", parse_dates=["timestamp"])
    raw = raw.merge(assignments, on=["who", "path"]).merge(sample, on="path")
    print("labels per person:", raw.groupby("who").size().to_dict())

    pd.set_option("display.float_format", "{:.2f}".format)
    print("\n== human vs human (overlap frames) ==")
    print(agreement(raw).to_string(index=False))

    own = raw[raw["role"] == "own"]
    unusable = int(own["unusable"].sum())
    labels = own[own["unusable"] == 0].set_index("path")
    paths = labels.index.tolist()
    print(f"\n{len(paths)} frames compared with the model ({unusable} marked unusable)\n")

    hand = grouped(labels[GROUPS["total"]])
    detections = pd.read_parquet(args.interim / "detections.parquet", columns=["path", "vehicle", "confidence"])
    band = labels["timestamp"].dt.hour.map(time_band)
    band[labels["stratum"] == "day/model_zero"] = "model_zero"

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
