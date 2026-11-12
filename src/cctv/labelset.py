"""Step 3a: pick a stratified sample of frames to count by hand.

Strata are time band x camera busyness, so night frames and quiet cameras get as
many labels as busy daytime ones. A fixed seed keeps the sample reproducible.

    uv run python -m cctv.labelset --n-per-stratum 15 --n-zero 20
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

BANDS = [(6, 9, "morning"), (10, 16, "midday"), (17, 18, "evening"), (19, 21, "night")]
LOW_CONTRAST = 10  # below this the frame is blank / "no signal"; not worth labelling


def time_band(hour: int) -> str:
    for start, end, name in BANDS:
        if start <= hour <= end:
            return name
    return "other"


def build_sample(images: pd.DataFrame, counts: pd.DataFrame, n_per_stratum: int, n_zero: int, seed: int) -> pd.DataFrame:
    frames = counts[["path", "n_vehicles"]].merge(images[["path", "camera_id", "timestamp", "contrast"]], on="path")
    frames = frames[frames["contrast"] >= LOW_CONTRAST].copy()
    frames["band"] = frames["timestamp"].dt.hour.map(time_band)
    busyness = frames.groupby("camera_id")["n_vehicles"].mean()
    frames["busyness"] = frames["camera_id"].map(pd.qcut(busyness, 3, labels=["quiet", "medium", "busy"]))

    picked = []
    for (band, busy), group in frames.groupby(["band", "busyness"], observed=True):
        # At most 2 frames per camera per stratum, so one camera cannot dominate.
        spread = group.sample(frac=1, random_state=seed).groupby("camera_id").head(2)
        picked.append(spread.sample(min(n_per_stratum, len(spread)), random_state=seed).assign(stratum=f"{band}/{busy}"))
    sample = pd.concat(picked)

    # Daytime frames where the model saw nothing: are they really empty?
    zeros = frames[(frames["n_vehicles"] == 0) & frames["band"].isin(["morning", "midday"]) & ~frames["path"].isin(sample["path"])]
    sample = pd.concat([sample, zeros.sample(min(n_zero, len(zeros)), random_state=seed).assign(stratum="day/model_zero")])

    # Shuffle so the labeller cannot tell the stratum or model count from the order.
    sample = sample.sample(frac=1, random_state=seed).reset_index(drop=True)
    return sample[["path", "camera_id", "timestamp", "stratum"]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interim", type=Path, default=Path("data/interim"))
    parser.add_argument("--out", type=Path, default=Path("data/labels/sample.csv"))
    parser.add_argument("--n-per-stratum", type=int, default=15)
    parser.add_argument("--n-zero", type=int, default=20)
    parser.add_argument("--seed", type=int, default=403)
    args = parser.parse_args()

    images = pd.read_parquet(args.interim / "images.parquet")
    counts = pd.read_parquet(args.interim / "image_counts.parquet")
    sample = build_sample(images, counts, args.n_per_stratum, args.n_zero, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(args.out, index=False)
    print(f"{len(sample)} frames -> {args.out}")
    print(sample["stratum"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
