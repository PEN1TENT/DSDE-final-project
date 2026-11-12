"""Step 1: build one row per image with camera, timestamp and quality metrics.

Expected layout: <raw>/<camera_id>/<image>. The camera id is the name of the
folder that directly contains the image.

    uv run python -m cctv.inventory --raw data/raw --out data/interim
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from cctv import timestamps

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def describe_image(path: Path) -> dict:
    """Quality metrics for one image; `readable` is False if it cannot be decoded."""
    data = path.read_bytes()
    row = {"bytes": len(data), "md5": hashlib.md5(data).hexdigest(), "readable": False}
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE) if data else None
    if image is None:
        return row
    row.update(
        readable=True,
        height=image.shape[0],
        width=image.shape[1],
        brightness=float(image.mean()),  # 0-255; low at night
        contrast=float(image.std()),  # near 0 for blank / "no signal" frames
        sharpness=float(cv2.Laplacian(image, cv2.CV_64F).var()),  # low when blurred
    )
    return row


def build_inventory(raw: Path) -> pd.DataFrame:
    rows = []
    paths = sorted(p for p in raw.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
    for path in paths:
        stamp, source = timestamps.resolve(path)
        rows.append(
            {
                "camera_id": path.parent.name,
                "path": str(path.relative_to(raw)),
                "timestamp": stamp,
                "ts_source": source,
                **describe_image(path),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame = frame.sort_values(["camera_id", "timestamp", "path"], ignore_index=True)
    # A frame identical to the previous one from the same camera means the feed was frozen.
    frame["frozen"] = frame.groupby("camera_id")["md5"].shift() == frame["md5"]
    return frame


def summarise(frame: pd.DataFrame) -> pd.DataFrame:
    """Per-camera coverage: how many images, over what period, how far apart."""
    frame = frame.assign(gap_min=frame.groupby("camera_id")["timestamp"].diff().dt.total_seconds() / 60)
    return frame.groupby("camera_id").agg(
        images=("path", "size"),
        with_timestamp=("timestamp", "count"),
        unreadable=("readable", lambda s: int((~s).sum())),
        frozen=("frozen", "sum"),
        first=("timestamp", "min"),
        last=("timestamp", "max"),
        median_gap_min=("gap_min", "median"),
        max_gap_min=("gap_min", "max"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, default=Path("data/interim"))
    args = parser.parse_args()

    frame = build_inventory(args.raw)
    if frame.empty:
        raise SystemExit(f"No images found under {args.raw}")
    args.out.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.out / "images.parquet", index=False)
    summary = summarise(frame)
    summary.to_csv(args.out / "camera_summary.csv")

    total, stamped = len(frame), int(frame["timestamp"].notna().sum())
    print(f"{total} images from {frame['camera_id'].nunique()} cameras -> {args.out / 'images.parquet'}")
    print(f"timestamps: {stamped}/{total} resolved ({frame['ts_source'].value_counts().to_dict()})")
    print(f"unreadable: {int((~frame['readable']).sum())}, frozen: {int(frame['frozen'].sum())}")
    if stamped:
        print(f"period: {frame['timestamp'].min()} to {frame['timestamp'].max()}")
        print(f"median gap between frames: {summary['median_gap_min'].median():.1f} min")
    missing = summary[summary["with_timestamp"] < summary["images"]]
    if len(missing):
        print(f"{len(missing)} cameras have images without a timestamp (see camera_summary.csv)")


if __name__ == "__main__":
    main()
