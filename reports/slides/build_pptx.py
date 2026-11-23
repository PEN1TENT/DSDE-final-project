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


def header(s, kicker, title, title_size=22):
    text(s, 72, 38, 1136, 20, kicker.upper(), 12, BLUE, bold=True)
    text(s, 72, 60, 1136, 78, title, title_size, INK, bold=True, spacing=0)


def stat(s, x, y, w, h, v, label):
    box(s, x, y, w, h)
    text(s, x + 18, y + 12, w - 36, 44, v, 28, INK, bold=True)
    text(s, x + 18, y + 58, w - 36, h - 62, label, 12, INK2)


def card(s, x, y, w, h, title, body, size=14, title_size=15):
    box(s, x, y, w, h)
    text(s, x + 18, y + 14, w - 36, 24, title, title_size, INK, bold=True, spacing=0)
    text(s, x + 18, y + 40, w - 36, h - 50, body, size, INK2, spacing=2)


def takeaway_cards(s, items, y=534, h=136):
    """Three horizontal cards across x=72..1208 under wide 2-panel figures."""
    for i, (t, b) in enumerate(items):
        card(s, 72 + i * 384, y, 368, h, t, b, size=11.5, title_size=13)


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
text(s, 88, 370, 760, 56, "A one-week study of 61,319 CCTV snapshots (60,053 audited) from 100 BMA traffic cameras", 17, "#b9c2cf")
text(s, 88, 450, 120, 18, "GROUP", 10, "#8693a6", bold=True)
text(s, 88, 470, 160, 30, "Jarn Touz", 15, "#dfe5ee")
text(s, 260, 450, 120, 18, "MEMBERS", 10, "#8693a6", bold=True)
text(s, 260, 470, 560, 56, ["[name 1] · [name 2] · [name 3]", "[name 4] · [name 5] · [name 6]"], 15, "#dfe5ee", spacing=2)

# 2 Short answer ----------------------------------------------------------
s = new_slide(page=2)
header(s, "The short answer", "Heavy rain adds +5.6 pts of vehicles — and auditing the feeds unlocks 5 insights")
for i, (v, l) in enumerate([("+5.6 pts", "heavy rain (>5 mm/h) vs dry hours, same camera & hour"),
                            ("1,086", "corrupted frames removed: 507 blank + 579 frozen"),
                            ("7 / 21", "co-located pairs with AM↔PM tidal flip (FDR q < 0.05)"),
                            ("≤ 1 km", "local spatial spillover radius (Mantel p = 0.0005)")]):
    stat(s, 72 + i * 289, 152, 271, 114, v, l)
bullets(s, 72, 296, 1136, 330, [
    [("Traffic DNA (k=3)", True), (" splits Bangkok into all-day retail (n=44), morning-commute arterial (n=43), and evening-peak office (n=13) cameras (bootstrap ARI 0.92, OSM p = 0.011).", False)],
    [("Only heavy rain in the same hour", True), (" raises counts (+6.6% vs +1.0% dry); signalized intersections (+10.1 pts) and surface roads (+6.6 pts) absorb the hit.", False)],
    [("Trustworthy counts first: ", True), ("1,000 hand labels calibrated the detector, and feed audit isolated Monday 31 Aug's citywide evening anomaly (−17.8%).", False)],
], 16)

# 3 Data ------------------------------------------------------------------
s = new_slide(page=3)
header(s, "1 · Data", "One CCTV dataset plus three outside sources and our own labels")
rows = [("Source", "How we got it", "What it adds"),
        ("BMA CCTV images", "Provided (scraped)", "100 cameras, 25–31 Aug 2026, 61,319 raw → 60,053 audited snapshots (~1 / 10 min, 352×288 px)"),
        ("Open-Meteo archive", "REST API", "Hourly modelled rainfall at each camera's coordinates → rain level per snapshot (lag 0, 1 h, 2 h)"),
        ("OpenStreetMap", "Overpass API (QL)", "Nearest road: class, lanes, speed limit, one-way, bridge; signals (100 m / 500 m), schools, hospitals, malls, rail stations & bus stops within 500 m"),
        ("sunrise-sunset.org", "REST API", "Sunrise, sunset, civil twilight per day → day / twilight / night label per snapshot"),
        ("Team hand labels", "Our labelling web app", "1,000 frames counted by 5 people (199 counted twice) → ground truth for detector selection & calibration")]
tbl = s.shapes.add_table(len(rows), 3, px(72), px(146), px(1136), px(440)).table
for j, w in enumerate([230, 210, 696]):
    tbl.columns[j].width = px(w)
for i, row in enumerate(rows):
    for j, val in enumerate(row):
        c = tbl.cell(i, j)
        c.fill.solid()
        c.fill.fore_color.rgb = rgb(CARD if i == 0 else SURFACE)
        c.text = val
        for p in c.text_frame.paragraphs:
            for r in p.runs:
                r.font.size, r.font.name = Pt(12 if i == 0 else 13.5), FONT
                r.font.bold = i == 0 or j == 0
                r.font.color.rgb = rgb(MUTED if i == 0 else (INK if j == 0 else INK2))
text(s, 72, 608, 1136, 26, [[("All API responses are cached in ", False), ("data/raw/external/", True),
                              (", so the whole 12-step pipeline re-runs offline.", False)]], 14)

# 4 Architecture ----------------------------------------------------------
s = new_slide(page=4)
header(s, "2 · How the components connect", "From raw images to insight models & an 8-tab dashboard in one command")
for x, t, c in [(72, "SOURCES", MUTED), (316, "COMPONENT 1 · DATA ENGINEERING", MUTED), (620, "· COMPONENT 2 · DATA SCIENCE", "#c24f1f"), (998, "COMPONENT 3 & 4", MUTED)]:
    text(s, x, 134, 210 if x == 998 else 300, 18, t, 10, c, bold=True)
srcs = [("CCTV images", "61.3k JPEGs, 100 cams"), ("Open-Meteo", "hourly rain grid"), ("OpenStreetMap", "roads, signals, POIs"),
        ("sunrise-sunset", "light phase"), ("Hand labels", "1,000 frames")]
for i, (t, d) in enumerate(srcs):
    y = 158 + i * 100
    box(s, 72, y, 210, 88, fill="#f2f7fd", line="#b8d1f0")
    text(s, 86, y + 14, 186, 70, [[(t, True)], d], 12.5, INK2, spacing=2)
text(s, 284, 396, 30, 30, "→", 22, MUTED, align=PP_ALIGN.CENTER)
cells = [("inventory & audit", "timestamps, blank/whiteout & watermark-frozen feed check", "de"),
         ("detect", "YOLO11-L vehicle boxes & counts per class", "de"),
         ("weather · osm · daylight", "fetch, cache, join to camera & hour", "de"),
         ("mart", "clean parquet tables for dashboard & insights", "de"),
         ("bake-off & rain", "calibration, excess over usual, DiD & LODO checks", "ds"),
         ("dna · shocks · insights", "clustering, |z|≥2.5 shocks, tidal flow, Mantel sync", "ds")]
for i, (t, d, k) in enumerate(cells):
    x, y = 316 + (i % 2) * 330, 158 + (i // 2) * 116
    fill, line = ("#f1faf6", "#c7e9da") if k == "de" else ("#fdf4f0", "#f4cdbd")
    box(s, x, y, 320, 106, fill=fill, line=line)
    text(s, x + 14, y + 12, 292, 84, [[(t, True)], d], 12.5, INK2, spacing=2)
box(s, 316, 514, 650, 140, fill=SURFACE, line="#1baf7a", dash=True)
text(s, 332, 526, 620, 118, [
    [("cctv.pipeline", True), (" runs 12 incremental steps and skips any whose outputs are newer than their inputs:", False)],
    "inventory → audit → detect → weather → osm → daylight →",
    "rain → dna → shocks → insights → charts → mart",
], 12, GREEN, spacing=4)
text(s, 966, 396, 30, 30, "→", 22, MUTED, align=PP_ALIGN.CENTER)
for i, (t, d) in enumerate([("8-tab Streamlit dashboard", "overview · map · rain · OSM · DNA · corridors · audit · explorer"),
                            ("Insights", "8 figures + report: DNA, rain DiD, tidal pairs, spillover, shocks")]):
    y = 158 + i * 252
    box(s, 998, y, 210, 240, fill="#f6f2fd", line="#d6c8f0")
    text(s, 1012, y + 14, 182, 210, [[(t, True)], d], 12.5, INK2, spacing=4)

# 5 DE --------------------------------------------------------------------
s = new_slide(page=5)
header(s, "Component 1 · Data engineering & feed audit", "Two-stage image auditing catches corrupted feeds missed by MD5 hashes")
bullets(s, 72, 152, 564, 500, [
    [("Timestamps", True), (" parsed from filename, then EXIF; camera/hour cells with ", False), ("< 3 snapshots", True), (" dropped.", False)],
    [("Stage-1 Feed Audit", True), (" removed ", False), ("1,086 bad frames", True), (" from 61,319: ", False), ("507 blank", True), (" (504 morning whiteouts) + ", False), ("579 frozen", True), (" whose moving watermark tricked MD5 (center MAD < 1.0).", False)],
    [("Audit payoff:", True), (" cleaned heavy-rain gap strengthens from ", False), ("+3.7 → +5.6 pts", True), (", DNA ARI improves ", False), ("0.85 → 0.92", True), (", and Cam 206's weekend slump corrects (95 frozen frames removed).", False)],
    [("Outside data", True), (" joined on camera coordinates + hour; road attributes, bridges and signal proximity from OSM.", False)],
], 15)
for i, (t, b) in enumerate([("Reproducible", "uv run python -m cctv.pipeline runs the 12-step DAG and rebuilds only what is out of date; --dry-run previews the plan."),
                            ("Resumable detection", "YOLO runs at ~10 images/s on an Apple GPU and resumes from checkpoints cleanly."),
                            ("Tested (30 tests)", "30 pytest tests cover timestamps, OSM, daylight, labelling, DNA stability, blank/frozen detection, shocks, DiD, tidal flips & Mantel sync.")]):
    card(s, 672, 152 + i * 156, 536, 140, t, b, size=13.5)

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
for i, (t, b) in enumerate([("Why a zoom-free baseline?", "Rush hour, camera zoom and road size differ far more than rain does. Subtracting the camera-hour mean isolates within-camera shifts cleanly."),
                            ("Rain levels & timing", "dry · light 0.1–2 · moderate 2–5 · heavy >5 mm/h, tested at lag 0 h, 1 h earlier, and 2 h earlier across OSM & DNA groups."),
                            ("Honest uncertainty", "2,000 camera-day cluster bootstraps (rain & DiD), 5,000 tidal / 2,000 Mantel & day-block permutations, and Benjamini-Hochberg FDR.")]):
    card(s, 72 + i * 386, 280, 364, 210, t, b, 14)

# 10 Divider --------------------------------------------------------------
s = new_slide(DARK, page=10)
text(s, 72, 280, 1000, 22, "COMPONENT 4", 12, "#7fb2ef", bold=True)
text(s, 72, 306, 1000, 70, "What we found", 40, "#ffffff", bold=True)
text(s, 72, 380, 1040, 36, "Traffic DNA archetypes, rain impact & road vulnerability, tidal corridors, spatial spillover, and anomaly audit.", 17, "#b9c2cf")

# 11 Patterns -------------------------------------------------------------
s = new_slide(page=11)
header(s, "Traffic patterns", "Clear weekday rush hours; cars dominate what the cameras see")
image(s, FIG / "hourly_profile.png", 72, 150, 554, 380, crop_top=True)
image(s, FIG / "vehicle_mix.png", 654, 150, 554, 380, crop_top=True)
text(s, 72, 560, 554, 60, [[("Weekday evening peak at ", False), ("17:00", True), (" (~23.0 vehicles/frame), morning peak at 08:00 (~19.1). Weekends are lower (−22%) and flatter.", False)]], 13)
text(s, 654, 560, 554, 60, "Motorcycles are under-detected (small, often hidden), which is why calibration is done per class.", 13)

# 12 Weekday vs weekend ---------------------------------------------------
s = new_slide(page=12)
header(s, "Traffic patterns · Weekday vs weekend", "Weekends empty the office districts, not the shopping areas")
image(s, FIG / "weekend_map.png", 72, 150, 640, 500, crop_top=True)
image(s, FIG / "weekend_by_mall.png", 740, 150, 468, 220, crop_top=True)
bullets(s, 740, 382, 468, 215, [
    [("Weekends carry ", False), ("22% less traffic", True), (" (13.1 vs 16.7 vehicles/frame). The 06–08 commute peak vanishes; middays match weekdays.", False)],
    [("3+ malls nearby keep ", False), ("81%", True), (" vs ", False), ("72%", True), (" with none (permutation p = 0.005).", False)],
    [("Narathiwas & Sathorn offices keep ", False), ("35–38%", True), (", Chitralada ", False), ("39%", True), ("; Phra Athit keeps ", False), ("117%", True), (" and Pratunam ", False), ("100%", True), (".", False)],
], 12.5)
callout(s, 740, 608, 468, 52, "One weekend only. Compared hour by hour after removing 95 frozen frames on Cam 206.", BLUE, "#f2f7fd")

# 13 NEW: Finding 1 - Traffic DNA -----------------------------------------
s = new_slide(page=13)
header(s, "Finding 1 · Traffic DNA clustering", "Unsupervised rhythms split Bangkok into 3 distinct road archetypes", title_size=21)
image(s, REP / "traffic_dna.png", 72, 138, 1136, 384)
takeaway_cards(s, [
    ("All-day retail (n=44)", "Keeps 86% weekend volume (77% on weekend mornings). Highest mall density (3.02 / 500 m) and dense urban core POIs (4.89)."),
    ("Commute arterials (n=43 + 13)", "Morning arterials (n=43) peak at 07–08 h (1.15×) in lower-POI corridors (2.58). Evening/office (n=13) surge 1.45× at PM near hospitals (1.92)."),
    ("Validated structure & land use", "k=3 structure is non-random (R²=0.44, p=0.003, ARI=0.92); held-out OSM urban_core_pois differs across clusters (KW H=8.43, p=0.011)."),
])

# 14 Rain levels ----------------------------------------------------------
s = new_slide(page=14)
header(s, "Finding 2 · Rain level and timing", "Only heavy rain, in the same hour, comes with more vehicles")
image(s, REP / "rain_levels.png", 72, 150, 700, 480, crop_top=True)
bullets(s, 800, 160, 408, 340, [
    [("Heavy rain now (>5 mm/h): +6.6%", True), (" vs usual (95% CI [+2.9, +10.0]); dry +1.0% → ", False), ("+5.6 points", True), (" (n=445).", False)],
    "Light (−1.0%) and moderate rain (−1.3%) sit within noise of zero.",
    [("Rain ", False), ("1 hour earlier", True), (": −1.2% (zero). Traffic builds during the downpour, not after it.", False)],
    "Heavy rain 2 h earlier (−4.9%, n=454) hints at clearing afterward.",
], 14)
callout(s, 800, 520, 408, 64, "Same conclusion without calibration: raw counts give +7.0% (+3.2 to +10.5%) for heavy rain.", BLUE, "#f2f7fd")

# 15 Time of day + LODO ---------------------------------------------------
s = new_slide(page=15)
header(s, "Finding 3 · Does it hold up?", "Heavy rain survives leaving out any day; wet evenings collapse to Mon 31 Aug")
image(s, REP / "wet_dry_by_hour.png", 72, 150, 554, 400, crop_top=True)
image(s, REP / "leave_one_day_out.png", 654, 150, 554, 400, crop_top=True)
text(s, 72, 570, 554, 60, "Wet and dry track each other until 18–20 h, where wet hours plunge — driven by 100% light-wet Mon 31 Aug evening (−17.8% vs usual).", 12.5)
text(s, 654, 570, 554, 60, [[("Heavy rain stays ", False), ("+4.3 to +6.9 pts", True), (" across all 7 drops. Dropping Mon 31 Aug flips wet evenings from ", False), ("−6.5 to +3.0 pts", True), (".", False)]], 12.5)

# 16 Map ------------------------------------------------------------------
s = new_slide(page=16)
header(s, "Finding 4 · Where", "Per camera, “any rain” looks negative because 85% of wet hours are light rain")
image(s, FIG / "camera_map.png", 72, 150, 620, 500, crop_top=True)
text(s, 730, 160, 478, 300, [
    [("The map compares ", False), ("all wet hours", True), (" with dry hours at each camera. Average: ", False), ("−1.9%", True), (", with ", False), ("59 of 100 cameras", True), (" below zero.", False)],
    [("That is not a contradiction of +5.6 pts. Of 30,570 wet snapshots, ", False), ("25,924 are light rain", True), (" (−1.0%) and only ", False), ("445 are heavy", True), (" (+6.6%), so “any wet” blends away heavy storms.", False)],
], 15, spacing=14)
callout(s, 730, 420, 478, 96, "Lesson: rain impact depends nonlinearly on intensity — pooling light drizzle with downpours hides the congestion spike.")

# 17 NEW: Finding 5 - Rain Vulnerability DiD ------------------------------
s = new_slide(page=17)
header(s, "Finding 5 · Infrastructure rain vulnerability (DiD)", "Signalized intersections & surface roads take 2× the heavy-rain hit", title_size=21)
image(s, REP / "rain_vulnerability.png", 72, 138, 1136, 384)
takeaway_cards(s, [
    ("Signalized & surface hotspots", "Signals (≤100 m): +10.1 pts [+4.5, +15.7] vs Mid-block +4.3 pts (DiD +5.8). Surface roads: +6.6 pts [+2.6, +10.7] vs Bridges −1.3 pts (DiD +7.9)."),
    ("Nulls that protect rigor", "BTS/MRT proximity shows zero protection (+5.8 vs +5.5 pts, p=0.958); primary highways (+5.3) vs secondary roads (+7.0) do not differ (p=0.648)."),
    ("DNA split & statistical power", "Morning-commute arterials spike +6.7 pts vs All-day retail +5.3 pts. Interaction DiD CIs cross zero (p=0.112, 0.157) with 445 heavy frames."),
])

# 18 NEW: Finding 6 - Tidal Flow ------------------------------------------
s = new_slide(page=18)
header(s, "Finding 6 · Tidal flow & directional asymmetry", "Opposite-direction cameras reveal statistically significant reversible-lane corridors", title_size=21)
image(s, REP / "tidal_flow.png", 72, 138, 1136, 384)
takeaway_cards(s, [
    ("Consistent citywide reversal", "Among 21 co-located pairs (≤100 m), 14 flip sign between AM (06–09 h) and PM (16–19 h), and 7 survive BH FDR q < 0.05 (5,000 permutations)."),
    ("Ratchadaphisek flagships", "224–225 (Criminal Court, 22 m): swing 0.270 (4/5 weekdays, q=0.004). 124–125 (Police Box, 40 m): swing 0.238, flips 5/5 weekdays (q=0.004)."),
    ("CBD & river-bridge candidates", "603–604 Silom–Naradhiwas (25 m, swing 0.225, q=0.019), 1132–1078 Wat Suwan (q=0.019), 1368–546 Lan Phra Rup (q=0.033) & 26–1195 Mahai Sawan (q=0.047)."),
])

# 19 NEW: Finding 7 - Spatial Spillover & Feed Audit ----------------------
s = new_slide(page=19)
header(s, "Finding 7 · Spatial spillover & anomaly audit", "Local congestion decays within 1 km; 262 shocks isolate Mon 31 Aug", title_size=21)
image(s, REP / "spatial_and_audit.png", 72, 138, 1136, 384)
takeaway_cards(s, [
    ("True spillover radius ≤ 1 km", "Removing citywide hours shrinks raw r (0.093 at >10 km) to local residual r: +0.065 (<0.5 km) → +0.042 (0.5–1 km) → +0.003 (1–2 km). Mantel p = 0.0005."),
    ("Honest pairwise FDR limit", "Nearest neighbors (≤2 km, n=95) show median local lag-0 r=0.057, lag-1h=0.039; 0/442 individual links clear day-block FDR <0.05 (top: 119–1112 r=0.46, q=0.32)."),
    ("262 traffic shocks (|z| ≥ 2.5)", "207 localized surges (Triam Udom 239 z=+4.87), 18 corridor, and 37 citywide shocks led by Mon 31 Aug evening (−17.8%; Cam 414 z=−7.36)."),
])

# 20 Dashboard ------------------------------------------------------------
s = new_slide(page=20)
header(s, "Component 3 · BI dashboard", "Explore every camera, DNA archetype, tidal pair and snapshot yourself")
image(s, FIG / "dash_overview_crop.png", 72, 150, 640, 425, crop_top=True)
image(s, FIG / "dash_map_crop.png", 740, 150, 468, 205, crop_top=True)
image(s, FIG / "dash_explorer_crop.png", 740, 368, 468, 207, crop_top=True)
cap(s, 72, 582, 640, "Overview: KPIs and traffic vs rain through the week")
cap(s, 740, 582, 468, "Camera map and camera explorer (raw image for any snapshot)")
text(s, 72, 616, 1136, 56, "8 Tabs: overview · map · rain vs congestion · road context (OSM) · traffic DNA · vulnerability & corridors · anomalies & CCTV audit · camera explorer. Filters: dates, day type, light phase, road class. Run: uv run streamlit run src/cctv/dashboard.py", 11.5)

# 21 Limits ---------------------------------------------------------------
s = new_slide(page=21)
header(s, "Limits", "A well-checked case study — honest about sample size & power")
bullets(s, 72, 156, 650, 490, [
    [("One week (445 heavy-rain snapshots):", True), (" sufficient for the main +5.6 pt effect and Mantel test, but widens interaction DiD CIs (signal/bridge p=0.11–0.16) and restricts per-link day-block FDR power (7 blocks).", False)],
    [("Area-level hourly rain:", True), (" Open-Meteo is gridded and averages short downpours over the full hour.", False)],
    [("Counts ≠ speed:", True), (" more vehicles can signal slower queues or higher throughput; 10-min snapshots cannot measure speed directly.", False)],
    [("Imperfect human labels & lens blur:", True), (" human disagreement averages 2.7 vehicles/frame.", False)],
], 15)
card(s, 756, 156, 452, 265, "Next steps", "Extend scraping across a full monsoon season with TMD rain gauges to unlock per-corridor FDR power; pilot AM/PM reversible-lane & signal-timing adjustments on Ratchadaphisek (224–225, 124–125) and Silom–Naradhiwas (603–604).", 14)

# 22 Summary --------------------------------------------------------------
s = new_slide(page=22)
header(s, "Summary", "What we built and what we learned")
for i, (t, b) in enumerate([("Data engineering", "Audited 61.3k frames down to 60,053 usable snapshots (−1,086 blank/frozen), YOLO11-L + 3 APIs in a 12-step pipeline with 30 pytest tests."),
                            ("Data science", "1,000 hand labels, cross-fitted calibration, Traffic DNA (ARI 0.92), cluster-bootstrap DiD, 5,000-perm tidal asymmetry, Mantel sync & FDR."),
                            ("Dashboard", "8-tab Streamlit app covering maps, OSM context, DNA clusters, tidal pairs, spatial links, shocks and raw frame inspection."),
                            ("Key insights", "Heavy rain → +5.6 pts (signals +10.1, surface +6.6). 3 road archetypes. 7/21 FDR tidal corridors (5/5 days on Ratchada). ≤1 km spillover. 262 shocks.")]):
    card(s, 72 + i * 289, 156, 271, 290, t, b, 13.5)
text(s, 72, 480, 1136, 30, "Code, slides and video: see the Google Drive link on myCourseVille. Thank you!", 15)

out = HERE / "slides.pptx"
prs.save(out)
print("wrote", out)
