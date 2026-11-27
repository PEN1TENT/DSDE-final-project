# STATUS
Goal: Bangkok CCTV image analysis pipeline (2110403 DSDE) studying rain, Traffic DNA, rain vulnerability, tidal flow, spatial sync, and camera health across 100 cameras.
Check: `uv run pytest`
Updated: 2026-11-27

## Next
Just done: Added Playwright interactive web scraper for Longdo Traffic (`src/cctv/longdo.py`), statistical cross-validation (`dry ρ=0.88 → wet 0.44`, Mon 31 Aug glare proof `CCTV −17.7%` vs `Longdo +11.1%`, Bridges `3.1×` accidents `p<0.001`, Traffic DNA `KW p=0.027`, `11` shock-incident matches), `reports/figures/longdo_validation.png`, and expanded the slide deck to 23 slides (`slides.html`, `slides.pptx`, `slides.pdf`) on branch `insights-and-slides`.
1. Fill in team member names on Slide 1 (`slides.html` / `build_pptx.py`), open PR / merge `insights-and-slides`, and record the presentation video.
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
