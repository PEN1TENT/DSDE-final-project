# STATUS
Goal: Bangkok CCTV image analysis pipeline (2110403 DSDE) studying rain, Traffic DNA, rain vulnerability, tidal flow, spatial sync, and camera health across 100 cameras.
Check: `uv run pytest`
Updated: 2026-11-27

## Next
Just done: Prepared repo for one-click Streamlit Community Cloud deployment (`src/cctv/requirements.txt` alongside `dashboard.py` + un-ignored ~4.5 MB precomputed dashboard tables in `data/processed/{dashboard,dna,insights,audit,l640/rain_effect.csv}`), pushed to `origin/insights-and-slides`.
1. Deploy on https://share.streamlit.io (repo `PEN1TENT/DSDE-final-project`, branch `insights-and-slides`, main file `src/cctv/dashboard.py`).
2. Fill in team member names on Slide 1 (`slides.html` / `build_pptx.py`), open PR / merge `insights-and-slides`, and record the presentation video.
Blocked: none

## Rules
- Keep external API responses cached in `data/raw/external/` so the pipeline runs offline; report only statistically tested CCTV insights (no raw API averages or synthetic speed constants).
- Production YOLO detector settings are `yolo11l.pt` at `imgsz=640`, `conf=0.05` (`data/interim/l640/`).
- Exclude blank (`contrast < 10`) and watermark-frozen (`center_mad < 1`) frames via `cctv.audit` before running `cctv.rain`.
- Repo root is two levels up (`/Users/thumma/coding/grader`); push cleanly to `origin` via `git subtree split --prefix="DSDE/Final Project" HEAD`.

## Map
- `src/cctv/pipeline.py`: 14-step incremental DAG (`inventory` -> `audit` -> `detect` -> `weather` -> `osm` -> `daylight` -> `longdo` -> `rain` -> `dna` -> `shocks` -> `insights` -> `longdo_val` -> `charts` -> `mart`).
- `src/cctv/longdo.py`: Playwright scraper for Longdo Traffic interactive SPA & 2026 event/index archive + CCTV cross-validation & shock-incident matching.
- `src/cctv/audit.py`: Frame quality cleanser (`--stage frames`) and spatial-temporal shock detector (`--stage shocks`).
- `src/cctv/dna.py`: Zoom-invariant Traffic DNA clustering, structure permutation test, and external OSM validation.
- `src/cctv/insights.py`: Rain vulnerability bootstrap DiD, co-located tidal asymmetry, and Mantel spatial sync.
- `src/cctv/dashboard.py`: 8-tab Streamlit BI dashboard.
- `reports/slides/`: 22-slide deck (`slides.html`, `slides.pdf`, `slides.pptx`, `build_pptx.py`, `make_figures.py`).
