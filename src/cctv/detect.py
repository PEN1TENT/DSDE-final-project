"""Step 2: detect vehicles in every readable image from the inventory.

Writes two tables to the output folder:
  detections.parquet    one row per detected vehicle (box, class, confidence)
  image_counts.parquet  one row per image (count per class, share of frame covered)

Safe to re-run: images already present in image_counts.parquet are skipped.

    uv run python -m cctv.detect --raw data/raw --out data/interim
    # settings chosen by cctv.bakeoff, into their own folder:
    uv run python -m cctv.detect --raw data/raw/cctv_images --out data/interim/l640 \
        --inventory data/interim/images.parquet --model yolo11l.pt --imgsz 640 --conf 0.05 --device mps
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

# COCO class ids kept as vehicles.
VEHICLES = {1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
MASK_SIZE = 256  # resolution of the grid used to measure covered area


def covered_fraction(boxes: np.ndarray, width: int, height: int) -> float:
    """Share of the frame covered by the union of the boxes (overlaps counted once)."""
    mask = np.zeros((MASK_SIZE, MASK_SIZE), dtype=bool)
    for x1, y1, x2, y2 in boxes:
        c1, c2 = int(x1 / width * MASK_SIZE), int(np.ceil(x2 / width * MASK_SIZE))
        r1, r2 = int(y1 / height * MASK_SIZE), int(np.ceil(y2 / height * MASK_SIZE))
        mask[max(r1, 0) : r2, max(c1, 0) : c2] = True
    return float(mask.mean())


def summarise_result(path: str, result) -> tuple[dict, list[dict]]:
    """Turn one ultralytics result into an image-level row and per-box rows."""
    height, width = result.orig_shape
    xyxy = result.boxes.xyxy.cpu().numpy()
    classes = result.boxes.cls.cpu().numpy().astype(int)
    confidences = result.boxes.conf.cpu().numpy()

    boxes = [
        {
            "path": path,
            "vehicle": VEHICLES[cls],
            "confidence": float(conf),
            "x1": float(box[0]),
            "y1": float(box[1]),
            "x2": float(box[2]),
            "y2": float(box[3]),
        }
        for box, cls, conf in zip(xyxy, classes, confidences)
    ]
    counts = {f"n_{name}": int((classes == cls).sum()) for cls, name in VEHICLES.items()}
    image = {
        "path": path,
        **counts,
        "n_vehicles": len(boxes),
        "covered_fraction": covered_fraction(xyxy, width, height),
        "mean_confidence": float(confidences.mean()) if len(confidences) else np.nan,
    }
    return image, boxes


def _append(path: Path, rows: list[dict]) -> None:
    frame = pd.DataFrame(rows)
    if path.exists():
        frame = pd.concat([pd.read_parquet(path), frame], ignore_index=True)
    frame.to_parquet(path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, default=Path("data/interim"))
    parser.add_argument("--inventory", type=Path, default=None, help="images.parquet; default <out>/images.parquet")
    parser.add_argument("--model", default="yolo11s.pt", help="ultralytics weights; downloaded on first use")
    parser.add_argument("--conf", type=float, default=0.25, help="minimum detection confidence")
    parser.add_argument("--imgsz", type=int, default=960, help="inference size; larger finds small, distant vehicles")
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", default=None, help="e.g. mps, cuda, cpu; default lets ultralytics choose")
    parser.add_argument("--limit", type=int, default=None, help="process at most this many images (for a trial run)")
    args = parser.parse_args()

    from ultralytics import YOLO  # imported late so --help stays fast

    args.out.mkdir(parents=True, exist_ok=True)
    inventory = pd.read_parquet(args.inventory or args.out / "images.parquet")
    todo = inventory.loc[inventory["readable"], "path"].tolist()
    counts_path, boxes_path = args.out / "image_counts.parquet", args.out / "detections.parquet"
    if counts_path.exists():
        done = set(pd.read_parquet(counts_path, columns=["path"])["path"])
        todo = [p for p in todo if p not in done]
    todo = todo[: args.limit]
    print(f"{len(todo)} images to process")
    if not todo:
        return

    model = YOLO(args.model)
    # Save every `chunk` images so an interrupted run loses little work.
    chunk = args.batch * 20
    for start in range(0, len(todo), chunk):
        image_rows, box_rows = [], []
        part = todo[start : start + chunk]
        for offset in range(0, len(part), args.batch):
            paths = part[offset : offset + args.batch]
            results = model.predict(
                [str(args.raw / p) for p in paths],
                classes=list(VEHICLES),
                conf=args.conf,
                imgsz=args.imgsz,
                device=args.device,
                verbose=False,
            )
            for path, result in zip(paths, results):
                image, boxes = summarise_result(path, result)
                image_rows.append(image)
                box_rows.extend(boxes)
        _append(counts_path, image_rows)
        if box_rows:
            _append(boxes_path, box_rows)
        print(f"  {min(start + chunk, len(todo))}/{len(todo)}")
    print(f"wrote {counts_path} and {boxes_path}")


if __name__ == "__main__":
    main()
