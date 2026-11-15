"""Step 3e: try detector settings on the hand-labelled frames and keep the best.

Each (model, imgsz) pair is run once at a very low confidence and cached in
data/interim/bakeoff/; confidence thresholds are then swept in pandas, so trying
another threshold costs nothing.

To avoid picking settings that only fit these frames, cameras are split in two:
settings are ranked on the "tune" half and the winner is reported on the "test"
half. Score = MAE of total vehicles per frame (lower is better); the human-human
MAE from cctv.evaluate (about 2.7) is the floor.

    uv run python -m cctv.bakeoff --export data/labels/export.csv
    uv run python -m cctv.bakeoff --models yolo11s.pt yolo11x.pt --imgsz 960 1600
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

from cctv.detect import VEHICLES
from cctv.evaluate import GROUPS, error_table, grouped, load_labels, model_counts
from cctv.labelset import time_band

FLOOR_CONF = 0.05


def run_config(model_name: str, imgsz: int, paths: list[str], raw: Path, device: str | None, batch: int) -> pd.DataFrame:
    from ultralytics import YOLO

    model = YOLO(model_name)
    rows = []
    for start in range(0, len(paths), batch):
        chunk = paths[start : start + batch]
        results = model.predict(
            [str(raw / p) for p in chunk], classes=list(VEHICLES), conf=FLOOR_CONF,
            imgsz=imgsz, device=device, verbose=False,
        )
        for path, r in zip(chunk, results):
            for cls, conf in zip(r.boxes.cls.cpu().numpy().astype(int), r.boxes.conf.cpu().numpy()):
                rows.append({"path": path, "vehicle": VEHICLES[cls], "confidence": float(conf)})
    return pd.DataFrame(rows, columns=["path", "vehicle", "confidence"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, default=Path("data/raw/cctv_images"))
    parser.add_argument("--labels", type=Path, default=Path("data/labels"))
    parser.add_argument("--export", type=Path, default=Path("data/labels/export.csv"))
    parser.add_argument("--cache", type=Path, default=Path("data/interim/bakeoff"))
    parser.add_argument("--models", nargs="+", default=["yolo11s.pt", "yolo11m.pt", "yolo11l.pt", "yolo11x.pt"])
    # Frames are 352x288; 1600 only upscales blur and needs >16 GB of GPU memory with m/l/x.
    parser.add_argument("--imgsz", type=int, nargs="+", default=[640, 960])
    parser.add_argument("--conf", type=float, nargs="+", default=[0.05, 0.08, 0.1, 0.15, 0.2, 0.25])
    parser.add_argument("--device", default="mps")
    parser.add_argument("--batch", type=int, default=8)
    args = parser.parse_args()

    raw = load_labels(args.labels, args.export)
    assignments = pd.read_csv(args.labels / "assignments.csv")[["who", "path", "role"]]
    sample = pd.read_csv(args.labels / "sample.csv", parse_dates=["timestamp"])
    raw = raw.merge(assignments, on=["who", "path"]).merge(sample, on="path")
    labels = raw[(raw["role"] == "own") & (raw["unusable"] == 0)].set_index("path")
    paths = labels.index.tolist()
    hand = grouped(labels[GROUPS["total"]])

    # Split by camera so the same camera never sits in both halves.
    cams = np.sort(labels["camera_id"].unique())
    rng = np.random.default_rng(0)
    test_cams = set(rng.choice(cams, size=len(cams) // 2, replace=False))
    is_test = labels["camera_id"].isin(test_cams)
    band = labels["timestamp"].dt.hour.map(time_band)
    print(f"{len(paths)} frames: {(~is_test).sum()} tune / {is_test.sum()} test ({len(cams)} cameras)")

    args.cache.mkdir(parents=True, exist_ok=True)
    rows = []
    for model_name in args.models:
        for imgsz in args.imgsz:
            cached = args.cache / f"{Path(model_name).stem}_{imgsz}.parquet"
            if cached.exists():
                det = pd.read_parquet(cached)
            else:
                t = time.time()
                det = run_config(model_name, imgsz, paths, args.raw, args.device, args.batch)
                det.to_parquet(cached, index=False)
                print(f"  ran {cached.stem} in {time.time() - t:.0f}s", flush=True)
            for conf in args.conf:
                model = grouped(model_counts(det, paths, conf))
                err = (model - hand).abs()
                rows.append({
                    "model": Path(model_name).stem, "imgsz": imgsz, "conf": conf,
                    "tune_mae": err.loc[~is_test.values, "total"].mean(),
                    "test_mae": err.loc[is_test.values, "total"].mean(),
                    "ratio": model["total"].sum() / hand["total"].sum(),
                    "moto_ratio": model["motorcycle"].sum() / hand["motorcycle"].sum(),
                    "four_ratio": model["four_wheel"].sum() / hand["four_wheel"].sum(),
                })

    pd.set_option("display.float_format", "{:.2f}".format)
    table = pd.DataFrame(rows).sort_values("tune_mae")
    table.to_csv(args.labels / "bakeoff.csv", index=False)
    print("\n== best 15 by tune MAE (total vehicles per frame) ==")
    print(table.head(15).to_string(index=False))

    best = table.iloc[0]
    print(f"\nwinner: {best['model']} imgsz={best['imgsz']} conf={best['conf']} -> test MAE {best['test_mae']:.2f}")
    det = pd.read_parquet(args.cache / f"{best['model']}_{best['imgsz']}.parquet")
    model = grouped(model_counts(det, paths, best["conf"]))
    print("\nwinner, all frames:")
    print(error_table(model, hand).drop(columns="group").to_string(index=False))
    print("\nwinner by time band (total):")
    print(error_table(model, hand, band).query("`class` == 'total'").drop(columns="class").to_string(index=False))
    print(f"\nwrote {args.labels / 'bakeoff.csv'}")


if __name__ == "__main__":
    main()
