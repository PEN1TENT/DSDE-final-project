# Bangkok CCTV Image Analysis

2110403 DSDE project pipeline. Images go in `data/raw/cctv_images/<camera_id>/` (not tracked by git).
Commands below pass `--raw data/raw/cctv_images` where they read images.

## Setup

```bash
uv sync
```

## Steps

1. **Inventory** – one row per image: camera, timestamp, readability, brightness, sharpness, frozen-frame flag.

   ```bash
   uv run python -m cctv.inventory --raw data/raw/cctv_images
   ```

   Writes `data/interim/images.parquet` and `data/interim/camera_summary.csv` (date range and
   sampling interval per camera). Timestamps come from the filename, then EXIF. Images with
   neither are kept with an empty timestamp and `ts_source = none`.

2. **Detection** – YOLO vehicle counts per image.

   ```bash
   uv run python -m cctv.detect --raw data/raw/cctv_images --device mps --limit 200   # trial run
   uv run python -m cctv.detect --raw data/raw/cctv_images --device mps               # everything; resumes
   ```

   Writes `data/interim/image_counts.parquet` (counts per class, share of frame covered) and
   `data/interim/detections.parquet` (one row per box). About 10 images/s on an Apple GPU.

3. **Detector error** – count vehicles by hand in a sample and compare with the model.

   ```bash
   uv run python -m cctv.labelset       # 200 frames: time band x camera busyness, + 20 model-zero frames
   uv run python -m cctv.label_server   # open http://127.0.0.1:8765 and count
   uv run python -m cctv.evaluate       # MAE, bias, model/hand ratio per class and time band
   ```

   Hand counts go to `data/labels/labels.csv` on every save. The page never shows model boxes,
   so the counts stay independent of the model. Pickups count as cars by hand; YOLO often calls
   them trucks, so the evaluation also compares cars + trucks together (`four_wheel`).

## Tests

```bash
uv run pytest
```
