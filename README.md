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

3. **Detector error (golden set)** – 5 people count vehicles by hand in 1,000 frames; compare with the model.

   ```bash
   uv run python -m cctv.labelset                                   # 1,000 frames: 12 strata x 75 + 100 model-zero
   uv run python -m cctv.assign --people alice,bob,carol,dave,erin \
       --url https://cctv-label.<your-tailnet>.ts.net               # 240 frames each, prints personal links
   uv run python -m cctv.evaluate                                   # after labelling (see below)
   ```

   Each person gets 200 frames of their own plus 40 from the next person, so 200 frames are
   counted twice: that measures human-vs-human disagreement. The page never shows model boxes.
   Pickups count as cars by hand; YOLO often calls them trucks, so the evaluation also compares
   cars + trucks together (`four_wheel`). `data/labels/tokens.csv` holds the secret keys and is
   never committed; re-running `assign` keeps existing keys so sent links stay valid.

## Team labelling on the homelab

The server is standard-library Python running in a stock `python:3.13-alpine` container, with a
Tailscale sidecar that publishes it via Funnel. Friends open their link; nothing to install.

1. **Tailscale admin console**: enable HTTPS certificates (DNS page) and make sure the policy
   grants the `funnel` node attribute (the default policy does). Create a reusable auth key.
2. **Copy the bundle** to the Docker host (the Proxmox VM/LXC that Portainer manages):
   ```bash
   rsync -av deploy/build/ <user>@<docker-host>:/opt/cctv-label/
   ```
3. **Portainer** → Stacks → Add stack → Web editor: paste `deploy/docker-compose.yml`, add the
   environment variable `TS_AUTHKEY=<key>`, deploy. The app is at
   `https://cctv-label.<your-tailnet>.ts.net` (the first request may take a few seconds while
   the certificate is issued).
4. **Send links** printed by `assign`, one per person. Watch progress at `/admin?key=<admin key>`.
5. **Collect**: download the CSV from the admin page and run
   `uv run python -m cctv.evaluate --export <file>`, or copy
   `/opt/cctv-label/data/labels/labels_*.csv` into `data/labels/` and run it without `--export`.
   Commit the label files so the team has them.

Local test without Docker: `python3 deploy/build/app/label_server.py --data deploy/build/data`.

## Tests

```bash
uv run pytest
```
