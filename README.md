# Bangkok CCTV Image Analysis

2110403 DSDE project pipeline. Images go in `data/raw/<camera_id>/` (not tracked by git).

## Setup

```bash
uv sync
```

## Steps

1. **Inventory** – one row per image: camera, timestamp, readability, brightness, sharpness, frozen-frame flag.

   ```bash
   uv run python -m cctv.inventory
   ```

   Writes `data/interim/images.parquet` and `data/interim/camera_summary.csv` (date range and
   sampling interval per camera). Timestamps come from the filename, then EXIF. Images with
   neither are kept with an empty timestamp and `ts_source = none`.

2. **Detection** – YOLO vehicle counts per image.

   ```bash
   uv run python -m cctv.detect --limit 200   # trial run
   uv run python -m cctv.detect               # everything; resumes where it stopped
   ```

   Writes `data/interim/image_counts.parquet` (counts per class, share of frame covered) and
   `data/interim/detections.parquet` (one row per box).

## Tests

```bash
uv run pytest
```
