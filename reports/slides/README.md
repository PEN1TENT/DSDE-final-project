# Slides

`slides.html` is the deck (17 slides, 1280×720). `slides.pdf` is the file to submit.

```bash
uv run python reports/slides/make_figures.py   # camera map, hourly profile, vehicle mix, example frames
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --no-pdf-header-footer \
  --print-to-pdf=reports/slides/slides.pdf "file://$PWD/reports/slides/slides.html"
```

The report charts come from `uv run python -m cctv.charts`. The `fig/dash_*_crop.png` files are
screenshots of the Streamlit dashboard; retake them by hand if the dashboard changes.
Fill in the member names on slide 1 before exporting.
