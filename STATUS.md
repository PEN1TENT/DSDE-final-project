# STATUS
Goal: Bangkok CCTV image analysis pipeline (2110403 DSDE) studying rain, Traffic DNA, rain vulnerability, tidal flow, spatial sync, and camera health across 100 cameras.
Check: `uv run pytest`
Updated: 2026-11-23

## Next
Just done: Implemented Ideas 1, 2, 4, 6, 7 (`cctv.audit`, `cctv.dna`, `cctv.insights`), 8-tab dashboard, and updated the 22-slide deck (`slides.html`, `slides.pptx`, `slides.pdf`), `reports/report.md`, and `README.md` on branch `insights-and-slides`.
1. Fill in team member names on Slide 1 (`slides.html` / `build_pptx.py`) and optionally retake `reports/slides/fig/dash_*_crop.png` screenshots from the 8-tab dashboard.
2. Open PR / merge `insights-and-slides` into `dsde-cctv-pipeline`, record the presentation video, and submit deliverables to Google Drive / myCourseVille.
Blocked: none

## Rules
- Keep external API responses cached in `data/raw/external/` so the pipeline runs offline; report only statistically tested CCTV insights (no raw API averages or synthetic speed constants).
- Production YOLO detector settings are `yolo11l.pt` at `imgsz=640`, `conf=0.05` (`data/interim/l640/`).
- Exclude blank (`contrast < 10`) and watermark-frozen (`center_mad < 1`) frames via `cctv.audit` before running `cctv.rain`.
- Repo root is two levels up (`/Users/thumma/coding/grader`); push cleanly to `origin` via `git subtree split --prefix="DSDE/Final Project" HEAD`.

## Map
- `src/cctv/pipeline.py`: 12-step incremental DAG (`inventory` -> `audit` -> `detect` -> `weather` -> `osm` -> `daylight` -> `rain` -> `dna` -> `shocks` -> `insights` -> `charts` -> `mart`).
- `src/cctv/audit.py`: Frame quality cleanser (`--stage frames`) and spatial-temporal shock detector (`--stage shocks`).
- `src/cctv/dna.py`: Zoom-invariant Traffic DNA clustering, structure permutation test, and external OSM validation.
- `src/cctv/insights.py`: Rain vulnerability bootstrap DiD, co-located tidal asymmetry, and Mantel spatial sync.
- `src/cctv/dashboard.py`: 8-tab Streamlit BI dashboard.
- `reports/slides/`: 22-slide deck (`slides.html`, `slides.pdf`, `slides.pptx`, `build_pptx.py`, `make_figures.py`).
