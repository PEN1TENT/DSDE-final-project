"""Editable PowerPoint version of the deck (text and diagram are native shapes).

    uv run --with python-pptx python reports/slides/build_pptx.py

Writes reports/slides/slides.pptx. Opens in PowerPoint, Google Slides, Keynote,
and can be imported into Canva (Create -> Import file). Content mirrors slides.html.
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Pt
from PIL import Image

HERE = Path(__file__).parent
FIG, REP = HERE / "fig", HERE.parent / "figures"
PX = 9525  # EMU per CSS px; slide is 1280x720 px like the HTML deck


def rgb(h: str) -> RGBColor:
    return RGBColor.from_string(h.lstrip("#"))


INK, INK2, MUTED, LINE = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df"
SURFACE, CARD, DARK = "#fcfcfb", "#f3f2ee", "#10161f"
BLUE, ORANGE, GREEN = "#2a78d6", "#eb6834", "#12875d"
FONT = "Arial"

prs = Presentation()
prs.slide_width, prs.slide_height = Emu(1280 * PX), Emu(720 * PX)
BLANK = prs.slide_layouts[6]


def px(v: float) -> Emu:
    return Emu(int(v * PX))


def new_slide(bg: str = SURFACE, page: int | None = None):
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = rgb(bg)
    if page:
        text(s, 1180, 690, 60, 20, str(page), 10, MUTED, align=PP_ALIGN.RIGHT)
    return s


def text(s, x, y, w, h, runs, size=16, color=INK2, bold=False, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, bullets=False, spacing=6):
    """runs: str, or list of paragraphs; each paragraph is str or list of (text, bold) pairs."""
    tb = s.shapes.add_textbox(px(x), px(y), px(w), px(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for side in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, side, 0)
    paras = [runs] if isinstance(runs, str) else runs
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(spacing)
        parts = [(para, bold)] if isinstance(para, str) else para
        if bullets:
            parts = [("•  ", False)] + list(parts)
        for t, b in parts:
            r = p.add_run()
            r.text = t
            r.font.size, r.font.bold, r.font.name = Pt(size), b, FONT
            r.font.color.rgb = rgb(INK if b and color == INK2 else color)
    return tb


def box(s, x, y, w, h, fill=CARD, line=None, radius=True, dash=False):
    shp = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
                             px(x), px(y), px(w), px(h))
    if radius:
        shp.adjustments[0] = min(0.5, 10 / min(w, h))
    shp.fill.solid()
    shp.fill.fore_color.rgb = rgb(fill)
    if line:
        shp.line.color.rgb = rgb(line)
        shp.line.width = Pt(1.2)
        if dash:
            shp.line.dash_style = 4
    else:
        shp.line.fill.background()
    shp.shadow.inherit = False
    shp.text_frame.text = ""
    return shp


def image(s, path, x, y, w, h, crop_top=False):
    """Fit image inside the box keeping aspect ratio (centred, or top-aligned)."""
    iw, ih = Image.open(path).size
    k = min(w / iw, h / ih)
    dw, dh = iw * k, ih * k
    s.shapes.add_picture(str(path), px(x + (w - dw) / 2), px(y if crop_top else y + (h - dh) / 2), px(dw), px(dh))


def header(s, kicker, title):
    text(s, 72, 40, 1136, 20, kicker.upper(), 12, BLUE, bold=True)
    text(s, 72, 62, 1136, 80, title, 22, INK, bold=True, spacing=0)


def stat(s, x, y, w, h, v, label):
    box(s, x, y, w, h)
    text(s, x + 18, y + 12, w - 36, 44, v, 28, INK, bold=True)
    text(s, x + 18, y + 58, w - 36, h - 62, label, 12, INK2)


def card(s, x, y, w, h, title, body, size=14):
    box(s, x, y, w, h)
    text(s, x + 20, y + 16, w - 40, 26, title, 15, INK, bold=True)
    text(s, x + 20, y + 46, w - 40, h - 56, body, size, INK2)


def callout(s, x, y, w, h, body, color=ORANGE, fill="#fdf4f0"):
    box(s, x, y, w, h, fill=fill, radius=False)
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, px(x), px(y), px(4), px(h))
    bar.fill.solid()
    bar.fill.fore_color.rgb = rgb(color)
    bar.line.fill.background()
    text(s, x + 18, y + 10, w - 30, h - 16, body, 13, INK2, anchor=MSO_ANCHOR.MIDDLE)


def bullets(s, x, y, w, h, items, size=16):
    text(s, x, y, w, h, items, size, INK2, bullets=True, spacing=10)


def cap(s, x, y, w, t):
    text(s, x, y, w, 20, t, 11, MUTED)


# 1 Title -----------------------------------------------------------------
s = new_slide(DARK)
image(s, FIG / "frame_dry_day.png", 920, 0, 360, 360)
image(s, FIG / "frame_wet_night.png", 920, 360, 360, 360)
text(s, 88, 190, 760, 22, "2110403 DSDE · FINAL PROJECT 2026/1", 12, "#7fb2ef", bold=True)
text(s, 88, 220, 760, 140, "Does rain make Bangkok roads look more congested?", 40, "#ffffff", bold=True)
text(s, 88, 370, 760, 56, "A one-week study of 61,143 CCTV snapshots from 100 BMA traffic cameras", 17, "#b9c2cf")
text(s, 88, 450, 120, 18, "GROUP", 10, "#8693a6", bold=True)
text(s, 88, 470, 160, 30, "Jarn Touz", 15, "#dfe5ee")
text(s, 260, 450, 120, 18, "MEMBERS", 10, "#8693a6", bold=True)
text(s, 260, 470, 560, 56, ["[name 1] · [name 2] · [name 3]", "[name 4] · [name 5] · [name 6]"], 15, "#dfe5ee", spacing=2)

# 2 Short answer ----------------------------------------------------------
s = new_slide(page=2)
header(s, "The short answer", "Heavy rain comes with about 4% more vehicles in view, during the downpour only")
for i, (v, l) in enumerate([("+3.7 pts", "heavy rain (>5 mm/h) vs dry hours, same camera & hour"),
                            ("+2.5 to +4.9", "range when any one day is left out"),
                            ("0", "effect from rain 1–2 hours earlier"),
                            ("37% → 100%", "vehicles found by detector, first run → calibrated")]):
    stat(s, 72 + i * 289, 160, 271, 110, v, l)
bullets(s, 72, 310, 1136, 300, [
    [("Light rain", True), (" comes with slightly fewer vehicles (about −2%), close to zero.", False)],
    [("The apparent ", False), ("drop on wet evenings", True), (" comes from one day (Mon 31 Aug); without it the sign flips.", False)],
    [("Much of the work was making the counts trustworthy: ", False), ("1,000 frames counted by hand", True), (" to pick and correct the detector.", False)],
], 17)

# 3 Data ------------------------------------------------------------------
s = new_slide(page=3)
header(s, "1 · Data", "One CCTV dataset plus three outside sources and our own labels")
rows = [("Source", "How we got it", "What it adds"),
        ("BMA CCTV images", "Provided (scraped)", "100 cameras, 25–31 Aug 2026, ~1 image / 10 min, 352×288 px, ~611 images per camera"),
        ("Open-Meteo archive", "REST API", "Hourly modelled rainfall at each camera's coordinates → rain level per snapshot"),
        ("OpenStreetMap", "Overpass API (QL)", "Nearest road: class, lanes, speed limit, one-way; schools, hospitals, malls, rail stations within 500 m"),
        ("sunrise-sunset.org", "REST API", "Sunrise, sunset, civil twilight per day → day / twilight / night label per snapshot"),
        ("Team hand labels", "Our labelling web app", "1,000 frames counted by 5 people (199 counted twice) → ground truth for the detector")]
tbl = s.shapes.add_table(len(rows), 3, px(72), px(150), px(1136), px(420)).table
for j, w in enumerate([230, 220, 686]):
    tbl.columns[j].width = px(w)
for i, row in enumerate(rows):
    for j, val in enumerate(row):
        c = tbl.cell(i, j)
        c.fill.solid()
        c.fill.fore_color.rgb = rgb(CARD if i == 0 else SURFACE)
        c.text = val
        for p in c.text_frame.paragraphs:
            for r in p.runs:
                r.font.size, r.font.name = Pt(12 if i == 0 else 14), FONT
                r.font.bold = i == 0 or j == 0
                r.font.color.rgb = rgb(MUTED if i == 0 else (INK if j == 0 else INK2))
text(s, 72, 600, 1136, 24, [[("All API responses are cached in ", False), ("data/raw/external/", True),
                             (", so the whole pipeline re-runs offline.", False)]], 14)

# 4 Architecture ----------------------------------------------------------
s = new_slide(page=4)
header(s, "2 · How the components connect", "From raw images to a dashboard in one command")
for x, t, c in [(72, "SOURCES", MUTED), (316, "COMPONENT 1 · DATA ENGINEERING", MUTED), (620, "· COMPONENT 2 · DATA SCIENCE", "#c24f1f"), (998, "COMPONENT 3 & 4", MUTED)]:
    text(s, x, 140, 210 if x == 998 else 300, 18, t, 10, c, bold=True)
srcs = [("CCTV images", "61k JPEGs, 100 cameras"), ("Open-Meteo", "hourly rain"), ("OpenStreetMap", "road context"),
        ("sunrise-sunset", "light phase"), ("Hand labels", "1,000 frames")]
for i, (t, d) in enumerate(srcs):
    y = 166 + i * 100
    box(s, 72, y, 210, 88, fill="#f2f7fd", line="#b8d1f0")
    text(s, 86, y + 14, 186, 70, [[(t, True)], d], 13, INK2, spacing=2)
text(s, 284, 400, 30, 30, "→", 22, MUTED, align=PP_ALIGN.CENTER)
cells = [("inventory", "timestamps, readability, brightness, frozen-frame flag", "de"),
         ("detect", "YOLO11-L vehicle boxes & counts per class", "de"),
         ("weather · osm · daylight", "fetch, cache, join to camera & hour", "de"),
         ("mart", "clean tables for the dashboard", "de"),
         ("bake-off & evaluate", "pick detector, measure error vs hand counts", "ds"),
         ("rain", "calibrate, excess over usual, bootstrap CIs", "ds")]
for i, (t, d, k) in enumerate(cells):
    x, y = 316 + (i % 2) * 330, 166 + (i // 2) * 120
    fill, line = ("#f1faf6", "#c7e9da") if k == "de" else ("#fdf4f0", "#f4cdbd")
    box(s, x, y, 320, 110, fill=fill, line=line)
    text(s, x + 14, y + 14, 292, 84, [[(t, True)], d], 13, INK2, spacing=2)
box(s, 316, 532, 650, 124, fill=SURFACE, line="#1baf7a", dash=True)
text(s, 332, 544, 620, 100, [[("cctv.pipeline", True), (" runs the steps in order and skips any whose outputs are newer than their inputs", False)],
                             "inventory → detect → weather → osm → daylight → rain → charts → mart"], 13, GREEN, spacing=8)
text(s, 966, 400, 30, 30, "→", 22, MUTED, align=PP_ALIGN.CENTER)
for i, (t, d) in enumerate([("Streamlit dashboard", "overview · camera map · rain vs congestion · road context · camera explorer"),
                            ("Insights", "report + charts: rain effect, timing, robustness")]):
    y = 166 + i * 250
    box(s, 998, y, 210, 240, fill="#f6f2fd", line="#d6c8f0")
    text(s, 1012, y + 14, 182, 210, [[(t, True)], d], 13, INK2, spacing=4)

# 5 DE --------------------------------------------------------------------
s = new_slide(page=5)
header(s, "Component 1 · Data engineering", "Cleaning the images before counting anything")
bullets(s, 72, 160, 560, 480, [
    [("Timestamps", True), (" parsed from the filename, then EXIF; images with neither kept and flagged.", False)],
    [("Frozen frames", True), (" (camera stuck on the same picture) detected and removed.", False)],
    [("Readability, brightness, sharpness", True), (" stored per image, so dark or blurred frames can be filtered.", False)],
    [("Camera/hour cells with ", False), ("fewer than 3 snapshots", True), (" dropped before comparing.", False)],
    [("Outside data joined on ", False), ("camera location + hour", True), ("; road attributes on the nearest OSM way.", False)],
], 16)
for i, (t, b) in enumerate([("Reproducible", "uv run python -m cctv.pipeline rebuilds only what is out of date; --dry-run shows the plan."),
                            ("Resumable detection", "YOLO runs at ~10 images/s on an Apple GPU and picks up where it stopped."),
                            ("Tested", "20 pytest tests cover timestamp parsing, OSM road matching, light phases and the labelling app.")]):
    card(s, 672, 160 + i * 150, 536, 136, t, b)

# 6 Detection examples ----------------------------------------------------
s = new_slide(page=6)
header(s, "Component 1 · From pixels to counts", "YOLO11 turns each frame into vehicle counts by class")
image(s, FIG / "frame_dry_day.png", 72, 150, 554, 450)
image(s, FIG / "frame_wet_night.png", 654, 150, 554, 450)
cap(s, 72, 606, 554, "Dry morning, 31 Aug 09:10")
cap(s, 654, 606, 554, "Wet evening, 28 Aug 19:25: glare and reflections make misses more likely")
text(s, 72, 640, 1136, 22, "Blue = car · green = truck · orange = motorcycle. Boxes shown at confidence ≥ 0.25 for readability; counting uses 0.05.", 12, INK2)

# 7 Golden set ------------------------------------------------------------
s = new_slide(page=7)
header(s, "Component 2 · How good are the counts?", "We counted 1,000 frames by hand to measure the detector")
bullets(s, 72, 160, 660, 480, [
    [("Stratified sample: ", True), ("12 strata (time of day × rain × traffic) × 75 frames, plus 100 frames where the model saw nothing.", False)],
    [("5 people, 240 frames each", True), (", through a small labelling web app on our homelab (Docker + Tailscale Funnel). The page never shows model boxes.", False)],
    [("199 frames counted twice", True), (" → two people differ by ", False), ("2.7 vehicles", True), (" per frame. No detector can look better than that.", False)],
    [("Pickups count as cars by hand; YOLO calls many of them trucks, so we also compare ", False), ("cars + trucks", True), (".", False)],
], 16)
for i, (v, l) in enumerate([("1,000", "hand-counted frames (12 unusable)"), ("2.7", "vehicles: human vs human disagreement"),
                            ("4.9", "vehicles: MAE of the chosen detector")]):
    stat(s, 790, 170 + i * 135, 418, 115, v, l)

# 8 Detector error --------------------------------------------------------
s = new_slide(page=8)
header(s, "Component 2 · Detector bake-off and calibration", "The first detector missed 63% of vehicles, worst at night in rain")
image(s, REP / "detector_error.png", 72, 150, 680, 480, crop_top=True)
bullets(s, 790, 160, 418, 340, [
    [("Tried YOLO11 ", False), ("s / m / l / x", True), (" at 640 / 960 / 1280 px and several thresholds, tune/test split.", False)],
    [("yolo11l, 640 px, conf 0.05", True), (" wins. Bigger inputs don't help on 352×288 frames.", False)],
    [("Calibration", True), (": per condition (day/evening/late × wet/dry) and class, scale by hand ÷ model.", False)],
    [("Bars are ", False), ("cross-fitted", True), (": each person's frames are corrected with factors from everyone else.", False)],
], 14)
callout(s, 790, 520, 418, 96, "Late wet hours (34 frames) stay unreliable. No headline number depends on them: raw counts give the same result.")

# 9 Method ----------------------------------------------------------------
s = new_slide(page=9)
header(s, "Component 2 · Analysis method", "Compare each snapshot with what is usual for that camera and hour")
box(s, 72, 150, 1136, 96, fill=DARK)
text(s, 94, 166, 1100, 70, ["excess = log(1 + count) − mean log(1 + count) in (camera, hour, weekday/weekend)",
                            "exp(excess) − 1 ≈ “% above usual”"], 16, "#e9eef5", spacing=8)
for i, (t, b) in enumerate([("Why a baseline?", "Rush hour, camera zoom and road size differ far more than rain does. Subtracting the camera-hour mean removes them."),
                            ("Rain levels", "dry · light 0.1–2 · moderate 2–5 · heavy >5 mm/h, for the same hour and 1 or 2 hours before."),
                            ("Honest uncertainty", "95% CIs from resampling whole camera-days, since snapshots from one camera on one day are not independent.")]):
    card(s, 72 + i * 386, 280, 364, 200, t, b, 15)

# 10 Divider --------------------------------------------------------------
s = new_slide(DARK, page=10)
text(s, 72, 280, 1000, 22, "COMPONENT 4", 12, "#7fb2ef", bold=True)
text(s, 72, 306, 1000, 70, "What we found", 40, "#ffffff", bold=True)
text(s, 72, 380, 1000, 30, "Traffic patterns first, then the rain effect and the checks behind it.", 18, "#b9c2cf")

# 11 Patterns -------------------------------------------------------------
s = new_slide(page=11)
header(s, "Traffic patterns", "Clear weekday rush hours; cars dominate what the cameras see")
image(s, FIG / "hourly_profile.png", 72, 150, 554, 380, crop_top=True)
image(s, FIG / "vehicle_mix.png", 654, 150, 554, 380, crop_top=True)
text(s, 72, 560, 554, 60, [[("Weekday evening peak at ", False), ("17:00", True), (" (~23 vehicles per frame), morning peak at 08:00. Weekends are lower and flatter.", False)]], 13)
text(s, 654, 560, 554, 60, "Motorcycles are under-detected (small, often hidden), which is why calibration is done per class.", 13)

# 12 Rain levels ----------------------------------------------------------
s = new_slide(page=12)
header(s, "Finding 1 · Rain level and timing", "Only heavy rain, in the same hour, comes with more vehicles")
image(s, REP / "rain_levels.png", 72, 150, 700, 480, crop_top=True)
bullets(s, 800, 160, 408, 340, [
    [("Heavy rain now: +5.8%", True), (" vs usual; dry hours +2.0% → ", False), ("+3.7 points", True), (".", False)],
    "Light and moderate rain sit slightly below usual.",
    [("Rain ", False), ("1 hour earlier", True), (": nothing. Traffic builds up during the downpour, not after it.", False)],
    "Heavy rain 2 h earlier hints at fewer vehicles (−4.8%), but only 454 snapshots.",
], 14)
callout(s, 800, 520, 408, 64, "Same answer without calibration: raw counts give +6.2% for heavy rain.", BLUE, "#f2f7fd")

# 13 Robustness -----------------------------------------------------------
s = new_slide(page=13)
header(s, "Finding 2 · Does it hold up?", "The heavy-rain effect survives dropping any day; the evening dip does not")
image(s, REP / "wet_dry_by_hour.png", 72, 150, 554, 400, crop_top=True)
image(s, REP / "leave_one_day_out.png", 654, 150, 554, 400, crop_top=True)
text(s, 72, 570, 554, 60, "Wet and dry hours track each other until 19–20 h, where wet hours fall to about −10%.", 13)
text(s, 654, 570, 554, 60, [[("Heavy rain stays ", False), ("+2.5 to +4.9", True), (". Dropping Mon 31 Aug flips wet evenings from ", False), ("−7.1 to +1.6", True), (".", False)]], 13)

# 14 Map ------------------------------------------------------------------
s = new_slide(page=14)
header(s, "Finding 3 · Where", "Per camera, “any rain” looks negative because most rain is light")
image(s, FIG / "camera_map.png", 72, 150, 620, 500, crop_top=True)
text(s, 730, 160, 478, 300, [
    [("The map compares ", False), ("all wet hours", True), (" with dry hours at each camera. Average: ", False), ("−3.9%", True), (", and 74 of 100 cameras are below zero.", False)],
    [("That is not a contradiction of +3.7. Of the 31k wet snapshots, ", False), ("26k are light rain", True), (" and only ", False), ("450 are heavy", True), (", so the map is mostly the light-rain effect.", False)],
], 15, spacing=14)
callout(s, 730, 420, 478, 96, "Lesson: the rain effect depends on how hard it rains. Splitting by level is what reveals the heavy-rain increase.")

# 15 Dashboard ------------------------------------------------------------
s = new_slide(page=15)
header(s, "Component 3 · BI dashboard", "Explore every camera, hour and rain level yourself")
image(s, FIG / "dash_overview_crop.png", 72, 150, 640, 440, crop_top=True)
image(s, FIG / "dash_map_crop.png", 740, 150, 468, 210, crop_top=True)
image(s, FIG / "dash_explorer_crop.png", 740, 375, 468, 215, crop_top=True)
cap(s, 72, 596, 640, "Overview: KPIs and traffic vs rain through the week")
cap(s, 740, 596, 468, "Camera map and camera explorer (raw image for any snapshot)")
text(s, 72, 630, 1136, 40, "Tabs: overview · map · rain vs congestion · road context (OSM) · camera explorer. Filters: dates, weekday/weekend, light phase, road class. Run: uv run streamlit run src/cctv/dashboard.py", 12)

# 16 Limits ---------------------------------------------------------------
s = new_slide(page=16)
header(s, "Limits", "A well-checked case study, not a general law")
bullets(s, 72, 160, 640, 480, [
    [("One week", True), (", 450 heavy-rain snapshots. Scraping more in Nov–Dec wouldn't help: it's the dry season.", False)],
    [("Rain is area-level and hourly", True), (": modelled on a grid, and a 20-minute storm spreads over its hour.", False)],
    [("Counts ≠ congestion.", True), (" More vehicles in view can mean slower traffic or just more traffic; snapshots 10 min apart can't measure speed.", False)],
    [("Hand labels are imperfect", True), (" (2.7 vehicles between people), and rain on the lens blurs single frames.", False)],
], 16)
card(s, 752, 160, 456, 220, "Next steps", "Repeat over a full rainy season; use rain-gauge data; track vehicles across consecutive frames for a speed proxy; use OSM context to see which road types react most.", 15)

# 17 Summary --------------------------------------------------------------
s = new_slide(page=17)
header(s, "Summary", "What we built and what we learned")
for i, (t, b) in enumerate([("Data engineering", "Inventory and cleaning of 61k images, YOLO detection, 3 outside sources, one incremental pipeline."),
                            ("Data science", "1,000 hand labels, detector bake-off, cross-fitted calibration, baseline-adjusted rain effect with bootstrap CIs."),
                            ("Dashboard", "Streamlit app with five tabs and filters, down to the raw image of any snapshot."),
                            ("Insight", "Heavy rain → ~4% more vehicles in the same hour. Light rain and earlier rain: no increase.")]):
    card(s, 72 + i * 289, 160, 271, 260, t, b, 14)
text(s, 72, 460, 1136, 30, "Code, slides and video: see the Google Drive link on myCourseVille. Thank you!", 15)

out = HERE / "slides.pptx"
prs.save(out)
print("wrote", out)
