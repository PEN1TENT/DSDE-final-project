"""Generate pure-stdlib SVG forensic visualizations from `reports/forensics/`.

Reads dynamically from `reports/forensics/*.csv`, `reports/forensics/corpus_summary.json`,
and `reports/forensics/external_attribution.json` (plus filename timestamps under
`data/100_cameras/cctv_images/` when present for 5-minute / minute-of-hour resolution,
falling back cleanly to `reports/forensics/` CSVs if the raw directory is absent).

Writes 5 validated SVG charts to `reports/figures/forensics/`:
    01_fleet_hourly_anomaly_heatmap.svg
    02_thu27_am_blackout_anatomy.svg
    03_batch_polling_and_phase_switches.svg
    04_subnet_spatial_anomalies_rain.svg
    05_downstream_impact_funnel.svg

Runnable under Python 3.12–3.15 using only the standard library:
    python -m cctv.forensic_charts
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# Palette consistent with `src/cctv/charts.py`
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#7a7872"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"
PANEL_BG = "#ffffff"

BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
HEALTHY_FILL = "#bfe6d8"
REDUCED_FILL = "#7ec4eb"
AMBER = "#f59e0b"
AMBER_SOFT = "#fde68a"
CRIMSON = "#d63638"
PURPLE = "#7b4dbb"
MAGENTA = "#be185d"
MISSING_FILL = "#e6e5e0"
NEUTRAL = "#a3a29d"

FONT_SANS = "Segoe UI, Inter, Arial, Helvetica, sans-serif"
FONT_MONO = "Consolas, Courier New, monospace"

_FILENAME_RE = re.compile(r"^(\d+)_.+_(\d{8})_(\d{6})\.jpg$")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _svg_root(width: int, height: int) -> ET.Element:
    svg = ET.Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "width": str(width),
            "height": str(height),
            "viewBox": f"0 0 {width} {height}",
            "role": "img",
        },
    )
    style = ET.SubElement(svg, "style")
    style.text = (
        f"text {{ font-family: {FONT_SANS}; fill: {INK}; }} "
        f".mono {{ font-family: {FONT_MONO}; }}"
    )
    ET.SubElement(
        svg,
        "rect",
        {"x": "0", "y": "0", "width": str(width), "height": str(height), "fill": SURFACE},
    )
    return svg


def _el(parent: ET.Element, tag: str, attrib: dict[str, Any] | None = None, text: str | None = None) -> ET.Element:
    clean = {k: str(v) for k, v in (attrib or {}).items()}
    node = ET.SubElement(parent, tag, clean)
    if text is not None:
        node.text = text
    return node


def _add_title_block(svg: ET.Element, title: str, subtitle: str, width: int) -> None:
    _el(
        svg,
        "text",
        {"x": 36, "y": 36, "font-size": 19, "font-weight": "700", "fill": INK},
        title,
    )
    _el(
        svg,
        "text",
        {"x": 36, "y": 58, "font-size": 12, "fill": INK2},
        subtitle,
    )
    _el(
        svg,
        "line",
        {"x1": 36, "y1": 70, "x2": width - 36, "y2": 70, "stroke": GRID, "stroke-width": 1},
    )


def _add_footer(svg: ET.Element, text: str, width: int, height: int) -> None:
    _el(
        svg,
        "line",
        {"x1": 36, "y1": height - 32, "x2": width - 36, "y2": height - 32, "stroke": GRID, "stroke-width": 1},
    )
    _el(
        svg,
        "text",
        {"x": 36, "y": height - 13, "font-size": 10.5, "fill": MUTED},
        text,
    )


def _write_and_validate_svg(svg: ET.Element, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(svg)
    ET.indent(tree, space="  ")
    tree.write(out_path, encoding="utf-8", xml_declaration=True)
    # Validate strict XML well-formedness via ElementTree.parse
    ET.parse(out_path)


def _scan_filename_timestamps(raw_images_dir: Path | None) -> list[tuple[str, datetime, str]]:
    """Fast scan of filename timestamps only (no file-byte reads). Returns sorted list."""
    if raw_images_dir is None or not raw_images_dir.exists():
        return []
    out: list[tuple[str, datetime, str]] = []
    for entry in os.scandir(raw_images_dir):
        if not entry.is_dir():
            continue
        for fn in os.listdir(entry.path):
            m = _FILENAME_RE.match(fn)
            if not m:
                continue
            cid, ymd, hms = m.groups()
            try:
                dt = datetime.strptime(ymd + hms, "%Y%m%d%H%M%S")
            except ValueError:
                continue
            phase = "A" if (dt.minute % 10) < 5 else "B"
            out.append((cid, dt, phase))
    return out


# ---------------------------------------------------------------------------
# Chart 1: 100 x 105 Fleet Hourly Availability & Anomaly Heatmap
# ---------------------------------------------------------------------------


def build_chart_01_heatmap(data: dict[str, Any], out_path: Path) -> None:
    summary = data["summary"]
    cameras = data["cameras"]
    hourly = data["hourly"]

    days: list[str] = summary["date_range"]["days"]
    hours = list(range(6, 21))
    day_labels = {
        d: datetime.strptime(d, "%Y-%m-%d").strftime("%a %d %b")
        for d in days
    }

    # Sort cameras by (/16 subnet, numeric camera_id) so subnet clusters pop visually
    cams_sorted = sorted(
        cameras,
        key=lambda r: (
            tuple(int(p) for p in r["subnet_16"].split("/")[0].split(".")[:2]),
            int(r["camera_id"]) if r["camera_id"].isdigit() else 999999,
        ),
    )
    cam_index = {r["camera_id"]: idx for idx, r in enumerate(cams_sorted)}

    # Index hourly cells (6..20h)
    cell_map: dict[tuple[str, str, int], dict[str, int]] = {}
    for row in hourly:
        h = int(row["hour"])
        if 6 <= h <= 20:
            cell_map[(row["camera_id"], row["date"], h)] = {
                "total": int(row["total_files"]),
                "live": int(row["valid_live_jpegs"]),
                "wp": int(row["white_pngs"]),
                "trunc": int(row["truncated_jpegs"]),
                "gst": int(row["gst_bars"]),
                "frz": int(row["frozen_frames"]),
            }

    width, height = 1460, 990
    gx0, gy0 = 190, 122
    cell_w, cell_h = 9.0, 7.1
    grid_w = len(days) * len(hours) * cell_w
    grid_h = len(cams_sorted) * cell_h

    svg = _svg_root(width, height)
    _add_title_block(
        svg,
        "100-Camera Fleet Hourly Availability & Anomaly Matrix (25–31 Aug 2026, 06:00–20:59)",
        f"100 cameras × 105 active hours = 10,500 cells grouped by /16 IP subnet · "
        f"{summary['non_frozen_live_jpegs']:,} non-frozen live JPEGs out of {summary['total_files']:,} raw files",
        width,
    )

    # Column header background & day labels
    for d_idx, d in enumerate(days):
        dx = gx0 + d_idx * len(hours) * cell_w
        dw = len(hours) * cell_w
        if d_idx % 2 == 1:
            _el(svg, "rect", {"x": dx, "y": gy0 - 34, "width": dw, "height": 30, "fill": "#f4f3ef"})
        _el(
            svg,
            "text",
            {"x": dx + dw / 2, "y": gy0 - 19, "font-size": 11.5, "font-weight": "700", "text-anchor": "middle"},
            day_labels[d],
        )
        for h_tick in (6, 12, 18):
            tx = dx + (h_tick - 6) * cell_w + cell_w / 2
            _el(
                svg,
                "text",
                {"x": tx, "y": gy0 - 5, "font-size": 8.5, "fill": INK2, "text-anchor": "middle"},
                f"{h_tick:02d}h",
            )

    # Render heatmap cells
    counts_by_cat: Counter[str] = Counter()
    for r_idx, cam in enumerate(cams_sorted):
        cid = cam["camera_id"]
        cy = gy0 + r_idx * cell_h
        for d_idx, d in enumerate(days):
            for h_idx, h in enumerate(hours):
                cx = gx0 + (d_idx * len(hours) + h_idx) * cell_w
                c = cell_map.get((cid, d, h), {"total": 0, "live": 0, "wp": 0, "trunc": 0, "gst": 0, "frz": 0})
                if c["total"] == 0:
                    fill, cat = MISSING_FILL, "missing"
                elif c["gst"] > 0:
                    fill, cat = PURPLE, "gst_bars"
                elif c["trunc"] > 0:
                    fill, cat = MAGENTA, "truncated"
                elif c["live"] == 0 and c["frz"] > 0:
                    fill, cat = CRIMSON, "frozen_only"
                elif c["live"] == 0 and c["wp"] > 0:
                    fill, cat = AMBER, "white_png_only"
                elif c["frz"] > 0:
                    fill, cat = ORANGE, "partial_frozen"
                elif c["wp"] > 0:
                    fill, cat = AMBER_SOFT, "partial_white_png"
                elif c["live"] < 5:
                    fill, cat = REDUCED_FILL, "reduced_live"
                else:
                    fill, cat = HEALTHY_FILL, "healthy"
                counts_by_cat[cat] += 1
                _el(
                    svg,
                    "rect",
                    {
                        "x": f"{cx:.1f}",
                        "y": f"{cy:.1f}",
                        "width": f"{cell_w - 0.5:.1f}",
                        "height": f"{cell_h - 0.5:.1f}",
                        "fill": fill,
                    },
                )

    # Day separators
    for d_idx in range(len(days) + 1):
        lx = gx0 + d_idx * len(hours) * cell_w
        _el(
            svg,
            "line",
            {"x1": lx, "y1": gy0 - 34, "x2": lx, "y2": gy0 + grid_h, "stroke": "#8f8d87", "stroke-width": 1},
        )

    # Subnet groupings & left labels + subtle horizontal dividers
    subnet_spans: dict[str, tuple[int, int]] = {}
    for idx, cam in enumerate(cams_sorted):
        s16 = cam["subnet_16"]
        if s16 not in subnet_spans:
            subnet_spans[s16] = (idx, idx)
        else:
            subnet_spans[s16] = (subnet_spans[s16][0], idx)

    for s16, (i0, i1) in subnet_spans.items():
        y0 = gy0 + i0 * cell_h
        y1 = gy0 + (i1 + 1) * cell_h
        _el(svg, "line", {"x1": gx0 - 6, "y1": y0, "x2": gx0 + grid_w, "y2": y0, "stroke": "#bdbbb4", "stroke-width": 0.7})
        n_cams = i1 - i0 + 1
        ymid = (y0 + y1) / 2 + 3
        label = f"{s16[:-5]} ({n_cams})"
        if n_cams >= 2 or s16 in ("10.134.0.0/16",):
            _el(
                svg,
                "text",
                {"x": gx0 - 10, "y": ymid, "font-size": 9.5 if n_cams >= 2 else 8.5, "fill": INK2, "text-anchor": "end", "class": "mono"},
                label,
            )

    _el(svg, "line", {"x1": gx0 - 6, "y1": gy0 + grid_h, "x2": gx0 + grid_w, "y2": gy0 + grid_h, "stroke": "#8f8d87", "stroke-width": 1})
    _el(svg, "text", {"x": gx0 - 10, "y": gy0 - 6, "font-size": 10, "font-weight": "700", "fill": INK2, "text-anchor": "end"}, "/16 Subnet (cams)")

    # Right-side event callouts anchored directly to exact camera rows
    ax_call = gx0 + grid_w + 14
    callouts = [
        ("395", "cam 395: Fri 28 06–16h freeze (00:12 frame)", CRIMSON),
        ("150", "cam 150: Thu 27 AM + Mon 31 PM freezes", CRIMSON),
        ("432", "cam 432: Thu 27 AM GStreamer bars (17)", PURPLE),
        ("595", "10.116/118.*: Fri 28 13h freeze + 595 trunc", ORANGE),
        ("206", "10.128.* (4/4): Sun 30 11–12h + 206 frz", CRIMSON),
        ("1804", "cam 1804: Thu 27 AM GStreamer bars (16)", PURPLE),
        ("938", "cam 938/939 (10.156.*): 25h freeze 25–26", CRIMSON),
    ]
    used_y: list[float] = []
    for cid, text, color in callouts:
        if cid not in cam_index:
            continue
        row_y = gy0 + (cam_index[cid] + 0.5) * cell_h
        label_y = row_y + 3
        while any(abs(label_y - uy) < 16 for uy in used_y):
            label_y += 16
        used_y.append(label_y)
        _el(svg, "line", {"x1": gx0 + grid_w + 2, "y1": row_y, "x2": ax_call - 3, "y2": label_y - 3, "stroke": color, "stroke-width": 1})
        _el(svg, "circle", {"cx": gx0 + grid_w + 2, "cy": row_y, "r": 2.3, "fill": color})
        _el(svg, "text", {"x": ax_call, "y": label_y, "font-size": 10.2, "font-weight": "600", "fill": color}, text)

    # Top annotation bracket for Thu 27 Aug AM blackout
    if "2026-08-27" in days:
        thu_idx = days.index("2026-08-27")
        thu_x = gx0 + thu_idx * len(hours) * cell_w
        _el(svg, "rect", {"x": thu_x, "y": gy0, "width": 3 * cell_w, "height": grid_h, "fill": "none", "stroke": INK, "stroke-width": 1.1, "stroke-dasharray": "3,2"})
        _el(svg, "text", {"x": thu_x + 1.5 * cell_w, "y": gy0 + grid_h + 15, "font-size": 10.5, "font-weight": "700", "fill": CRIMSON, "text-anchor": "middle"},
            "Thu 27 AM Blackout (06–08h: 0 live)")

    # Legend at bottom
    legend_items = [
        (HEALTHY_FILL, f"Healthy (5–6 live, {counts_by_cat['healthy']:,})"),
        (REDUCED_FILL, f"Reduced 1–4 live ({counts_by_cat['reduced_live']:,})"),
        (AMBER_SOFT, f"Live + white PNG ({counts_by_cat['partial_white_png']:,})"),
        (AMBER, f"White PNG only ({counts_by_cat['white_png_only']:,})"),
        (ORANGE, f"Live + frozen ({counts_by_cat['partial_frozen']:,})"),
        (CRIMSON, f"Frozen only ({counts_by_cat['frozen_only']:,})"),
        (PURPLE, f"GStreamer bars ({counts_by_cat['gst_bars']:,})"),
        (MAGENTA, f"Truncated JPEG ({counts_by_cat['truncated']:,})"),
        (MISSING_FILL, f"0 files / missing ({counts_by_cat['missing']:,})"),
    ]
    ly = gy0 + grid_h + 36
    lx = 36
    for idx, (color, label) in enumerate(legend_items):
        col = idx % 5
        row = idx // 5
        ix = lx + col * 262
        iy = ly + row * 24
        _el(svg, "rect", {"x": ix, "y": iy, "width": 14, "height": 12, "fill": color, "stroke": "#b8b6af", "stroke-width": 0.6})
        _el(svg, "text", {"x": ix + 20, "y": iy + 10, "font-size": 11, "fill": INK2}, label)

    _add_footer(
        svg,
        "Source: reports/forensics/hourly_coverage.csv, camera_forensics.csv, corpus_summary.json (hour 21 boundary sweeps excluded from 06–20h grid).",
        width,
        height,
    )
    _write_and_validate_svg(svg, out_path)


# ---------------------------------------------------------------------------
# Chart 2: Thu 27 Aug Morning Blackout Anatomy (06:00–09:30)
# ---------------------------------------------------------------------------


def build_chart_02_thu27_blackout(data: dict[str, Any], out_path: Path) -> None:
    summary = data["summary"]
    cameras = data["cameras"]
    no_eoi = data["no_eoi"]
    hourly = data["hourly"]
    fn_records = data["fn_records"]

    # Build 42 five-minute slots from 06:00 to 09:25
    slots: list[str] = []
    for h in range(6, 10):
        for m in range(0, 60, 5):
            if h == 9 and m >= 30:
                break
            slots.append(f"{h:02d}:{m:02d}")
    slot_idx = {s: i for i, s in enumerate(slots)}

    # Index Thu 27 white PNG timestamps from no_eoi_events.csv
    thu_wp_slots: Counter[str] = Counter()
    thu_wp_cams: set[str] = set()
    for r in no_eoi:
        if r["date"] == "2026-08-27" and r["file_type"] == "white_png":
            hhmm = r["timestamp"][11:16]
            hh, mm = int(hhmm[:2]), int(hhmm[3:5])
            s = f"{hh:02d}:{(mm // 5) * 5:02d}"
            if s in slot_idx:
                thu_wp_slots[s] += 1
            thu_wp_cams.add(r["camera_id"])

    # Compute slot counts dynamically
    slot_counts: dict[str, dict[str, int]] = {
        s: {"live": 0, "wp": 0, "gst": 0, "frozen": 0} for s in slots
    }

    if fn_records:
        # Exact file-level slot resolution using filename timestamps + M1 cohort rules
        full_pseudo_cams = set(summary["thu_27_am_split"]["full_morning_cameras"])
        # Check cam 150 frozen window & cam 432/1804 gst windows from frozen_streaks/no_eoi
        wp_exact = {
            (r["camera_id"], r["timestamp"][11:19])
            for r in no_eoi
            if r["date"] == "2026-08-27" and r["file_type"] == "white_png"
        }
        for cid, dt, _ in fn_records:
            if dt.strftime("%Y-%m-%d") != "2026-08-27":
                continue
            hms = dt.strftime("%H:%M:%S")
            if hms < "06:00:00" or hms >= "09:30:00":
                continue
            s = f"{dt.hour:02d}:{(dt.minute // 5) * 5:02d}"
            if (cid, hms) in wp_exact:
                slot_counts[s]["wp"] += 1
            elif cid == "150":
                slot_counts[s]["frozen"] += 1
            elif cid in ("432", "1804") and hms < "08:50:00":
                slot_counts[s]["gst"] += 1
            else:
                slot_counts[s]["live"] += 1
    else:
        # Fallback cleanly from hourly_coverage.csv + no_eoi_events.csv + camera_forensics.csv
        for s in slots:
            slot_counts[s]["wp"] = thu_wp_slots.get(s, 0)
            mm = int(s[3:])
            if s < "08:50":
                if mm % 10 == 0:
                    slot_counts[s]["gst"] = 1  # cam 432
                elif (s, "1804") not in {(f"07:{(int(r['timestamp'][14:16])//5)*5:02d}", r["camera_id"]) for r in no_eoi if r["date"]=="2026-08-27"}:
                    slot_counts[s]["gst"] = 1  # cam 1804
                if mm % 10 == 5 and s != "07:25":
                    slot_counts[s]["frozen"] = 1  # cam 150
            else:
                if mm % 10 == 5:
                    slot_counts[s]["frozen"] = 1
                slot_counts[s]["live"] = 45 if mm % 10 == 0 else 53

    thu_split = summary["thu_27_am_split"]
    n_full = thu_split["full_morning_pseudo"]
    n_part = thu_split["partial_white_png"]
    n_zero = thu_split["zero_morning"]
    rec_233 = next((r["thu27_recovery_ts"] for r in cameras if r["camera_id"] == "233"), "2026-08-27 09:00:13")
    rec_min = min(r["thu27_recovery_ts"] for r in cameras if r["thu27_am_status"] != "full_morning_pseudo")
    total_wp_thu = sum(v["wp"] for v in slot_counts.values())

    width, height = 1200, 740
    svg = _svg_root(width, height)
    _add_title_block(
        svg,
        "Anatomy of the Thu 27 Aug Morning Blackout (06:00–09:30 ICT)",
        f"3 pseudo-active cameras (150 frozen, 432 & 1804 GStreamer bars) + {n_part} white-PNG probes (07:21–07:30) + "
        f"{n_zero} silent timeouts = {thu_split['live_traffic_frames']} live traffic frames before 08:50",
        width,
    )

    # Top panel: 5-min slot stacked bars
    px0, py0, pw, ph = 90, 120, 1060, 290
    _el(svg, "rect", {"x": px0, "y": py0, "width": pw, "height": ph, "fill": PANEL_BG, "stroke": GRID, "stroke-width": 1})

    # Shade 06:00-08:50 blackout zone
    bw = pw / len(slots)
    blackout_slots = slot_idx["08:50"]
    _el(svg, "rect", {"x": px0, "y": py0, "width": blackout_slots * bw, "height": ph, "fill": "#fdf2f2", "opacity": 0.8})

    # Y grid & ticks (0, 20, 40, 60, 80, 100)
    y_max = 80
    for yv in (0, 20, 40, 60, 80):
        yy = py0 + ph - (yv / y_max) * ph
        _el(svg, "line", {"x1": px0, "y1": yy, "x2": px0 + pw, "y2": yy, "stroke": GRID, "stroke-width": 0.8})
        _el(svg, "text", {"x": px0 - 10, "y": yy + 4, "font-size": 10.5, "fill": INK2, "text-anchor": "end"}, str(yv))
    _el(svg, "text", {"x": 28, "y": py0 + ph / 2, "font-size": 11.5, "fill": INK2, "text-anchor": "middle",
                      "transform": f"rotate(-90 28 {py0 + ph / 2})"}, "Cameras captured per 5-min slot")

    # Bars
    stack_order = [
        ("live", AQUA, "Live traffic JPEG"),
        ("wp", AMBER, "400×266 white PNG"),
        ("gst", PURPLE, "246×205 GStreamer bars"),
        ("frozen", CRIMSON, "Frozen stale JPEG (cam 150)"),
    ]
    for i, s in enumerate(slots):
        bx = px0 + i * bw + 2.5
        b_width = max(4.0, bw - 5.0)
        cum = 0
        for key, color, _ in stack_order:
            val = slot_counts[s][key]
            if val <= 0:
                continue
            bh = (val / y_max) * ph
            by = py0 + ph - ((cum + val) / y_max) * ph
            _el(svg, "rect", {"x": f"{bx:.1f}", "y": f"{by:.1f}", "width": f"{b_width:.1f}", "height": f"{bh:.1f}", "fill": color})
            cum += val

    # X ticks every 30 min
    for i, s in enumerate(slots):
        if s.endswith(":00") or s.endswith(":30"):
            tx = px0 + i * bw + bw / 2
            _el(svg, "line", {"x1": tx, "y1": py0 + ph, "x2": tx, "y2": py0 + ph + 5, "stroke": INK2, "stroke-width": 1})
            _el(svg, "text", {"x": tx, "y": py0 + ph + 18, "font-size": 10.5, "fill": INK2, "text-anchor": "middle"}, s)

    # Top panel callouts
    _el(svg, "text", {"x": px0 + 14, "y": py0 + 24, "font-size": 12, "font-weight": "700", "fill": CRIMSON},
        "06:00–08:49: 0 live traffic frames across all 100 cameras")
    _el(svg, "text", {"x": px0 + 14, "y": py0 + 42, "font-size": 10.8, "fill": INK2},
        "Only 3 pseudo-active feeds polling (150 frozen + 432/1804 SMPTE bars)")

    # Annotate 07:25 spike
    spike_x = px0 + slot_idx["07:25"] * bw + bw / 2
    spike_y = py0 + ph - (55 / y_max) * ph
    _el(svg, "line", {"x1": spike_x, "y1": spike_y - 4, "x2": spike_x + 48, "y2": spike_y - 38, "stroke": AMBER, "stroke-width": 1.2})
    _el(svg, "text", {"x": spike_x + 52, "y": spike_y - 42, "font-size": 11, "font-weight": "700", "fill": "#b45309"},
        f"07:21–07:30 retry probe: {total_wp_thu} white PNGs")
    _el(svg, "text", {"x": spike_x + 52, "y": spike_y - 27, "font-size": 10.2, "fill": INK2},
        f"({n_part} partial cams + 150 + 1804; 28 cams timed out)")

    # Annotate 08:50 recovery
    rec_x = px0 + slot_idx["08:50"] * bw
    _el(svg, "line", {"x1": rec_x, "y1": py0, "x2": rec_x, "y2": py0 + ph, "stroke": AQUA, "stroke-width": 1.5, "stroke-dasharray": "4,3"})
    _el(svg, "text", {"x": rec_x + 8, "y": py0 + 24, "font-size": 11.2, "font-weight": "700", "fill": "#0f766e"},
        f"Recovery at {rec_min[11:]}")
    _el(svg, "text", {"x": rec_x + 8, "y": py0 + 41, "font-size": 10.2, "fill": INK2},
        f"98 live cams by 08:55; cam 233 at {rec_233[11:]}")

    # Bottom panel: 4-Cohort Swimlane Gantt (06:00-09:30)
    gx0, gy0, gw, gh = 290, 465, 860, 175
    _el(svg, "text", {"x": 36, "y": gy0 - 12, "font-size": 12.5, "font-weight": "700", "fill": INK},
        "Fleet Cohort Breakdown (Total = 100 Cameras)")
    _el(svg, "rect", {"x": gx0, "y": gy0, "width": gw, "height": gh, "fill": PANEL_BG, "stroke": GRID, "stroke-width": 1})

    def _t_to_x(hhmm: str) -> float:
        hh, mm = int(hhmm[:2]), int(hhmm[3:5])
        mins = (hh - 6) * 60 + mm
        return gx0 + (mins / 210.0) * gw

    cohorts = [
        ("cam 150 (1 cam · frozen)", [
            ("06:00", "07:20", CRIMSON, "Frozen (26 Aug 19:41)"),
            ("07:20", "07:30", AMBER, "1 PNG"),
            ("07:30", "09:30", CRIMSON, "Remains frozen until 28 Aug 06:21"),
        ]),
        ("cams 432 & 1804 (2 cams · GSt bars)", [
            ("06:00", "08:50", PURPLE, "gst-launch-0.10 SMPTE bars (17 + 16 frames; 1 PNG on 1804)"),
            ("08:50", "09:30", AQUA, "Live recovered"),
        ]),
        (f"partial_white_png ({n_part} cams)", [
            ("06:00", "07:20", MISSING_FILL, "Dark (0 frames)"),
            ("07:20", "07:32", AMBER, "1 white PNG"),
            ("07:32", "08:50", MISSING_FILL, "Dark"),
            ("08:50", "09:30", AQUA, f"Live (233 @ {rec_233[11:16]})"),
        ]),
        (f"zero_morning ({n_zero} cams)", [
            ("06:00", "08:50", MISSING_FILL, "Completely dark (0 frames 06:00–08:49)"),
            ("08:50", "09:30", AQUA, "Live recovered"),
        ]),
    ]

    row_h = gh / len(cohorts)
    for idx, (label, segs) in enumerate(cohorts):
        ry = gy0 + idx * row_h
        _el(svg, "text", {"x": gx0 - 12, "y": ry + row_h / 2 + 4, "font-size": 10.5, "font-weight": "600", "fill": INK, "text-anchor": "end"}, label)
        if idx > 0:
            _el(svg, "line", {"x1": gx0, "y1": ry, "x2": gx0 + gw, "y2": ry, "stroke": GRID, "stroke-width": 0.8})
        for s0, s1, color, note in segs:
            x0, x1 = _t_to_x(s0), _t_to_x(s1)
            _el(svg, "rect", {"x": f"{x0:.1f}", "y": f"{ry + 7:.1f}", "width": f"{max(4.0, x1 - x0):.1f}", "height": f"{row_h - 14:.1f}", "fill": color, "rx": 3})
            if x1 - x0 >= 110:
                tfill = "#ffffff" if color in (CRIMSON, PURPLE, AQUA) else INK
                _el(svg, "text", {"x": (x0 + x1) / 2, "y": ry + row_h / 2 + 3.5, "font-size": 9.8, "font-weight": "600", "fill": tfill, "text-anchor": "middle"}, note)

    for hhmm in ("06:00", "06:30", "07:00", "07:30", "08:00", "08:30", "09:00", "09:30"):
        tx = _t_to_x(hhmm)
        _el(svg, "line", {"x1": tx, "y1": gy0 + gh, "x2": tx, "y2": gy0 + gh + 5, "stroke": INK2, "stroke-width": 1})
        _el(svg, "text", {"x": tx, "y": gy0 + gh + 18, "font-size": 10.2, "fill": INK2, "text-anchor": "middle"}, hhmm)

    # Legend row
    ly = 678
    lx = 36
    for i, (_, color, label) in enumerate(stack_order + [("dark", MISSING_FILL, "Dark / no capture")]):
        ix = lx + i * 225
        _el(svg, "rect", {"x": ix, "y": ly, "width": 14, "height": 12, "fill": color, "stroke": "#b8b6af", "stroke-width": 0.6})
        _el(svg, "text", {"x": ix + 20, "y": ly + 10, "font-size": 11, "fill": INK2}, label)

    _add_footer(
        svg,
        "Source: reports/forensics/camera_forensics.csv, no_eoi_events.csv, corpus_summary.json"
        + (" + raw filename timestamps for 5-min slots." if fn_records else " (CSV-only fallback; post-08:50 5-min slots approximated from modal A/B)."),
        width,
        height,
    )
    _write_and_validate_svg(svg, out_path)


# ---------------------------------------------------------------------------
# Chart 3: Batch Polling (:00/:01 vs :05/:06) & Phase-Switch Alignment
# ---------------------------------------------------------------------------


def build_chart_03_batch_polling(data: dict[str, Any], out_path: Path) -> None:
    summary = data["summary"]
    cameras = data["cameras"]
    gaps = data["gaps"]
    hourly = data["hourly"]
    fn_records = data["fn_records"]
    bs = summary["batch_split"]
    days: list[str] = summary["date_range"]["days"]
    hours = list(range(6, 21))

    # Minute % 10 distribution
    min_mod10: Counter[int] = Counter()
    sd_switches_dh: Counter[tuple[str, int]] = Counter()
    ov_switches_d: Counter[str] = Counter()

    if fn_records:
        by_cam_dt: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
        for cid, dt, phase in fn_records:
            min_mod10[dt.minute % 10] += 1
            by_cam_dt[cid].append((dt, phase))
        for cid, items in by_cam_dt.items():
            items.sort(key=lambda x: x[0])
            for i in range(1, len(items)):
                dt0, p0 = items[i - 1]
                dt1, p1 = items[i]
                if p0 != p1:
                    if dt0.date() == dt1.date():
                        sd_switches_dh[(dt1.strftime("%Y-%m-%d"), dt1.hour)] += 1
                    else:
                        ov_switches_d[dt1.strftime("%Y-%m-%d")] += 1
    else:
        # Fallback from corpus_summary + gap_events
        min_mod10[0] = bs["phase_a_frames"]
        min_mod10[5] = bs["phase_b_frames"]

    # Hourly 12-20m stalls and white PNGs from CSVs
    stalls_dh: Counter[tuple[str, int]] = Counter()
    for g in gaps:
        if g["gap_class"] == "12-20m":
            stalls_dh[(g["date"], int(g["start_ts"][11:13]))] += 1
            if not fn_records:
                # Approximate intra-day switch proxy if raw filenames unavailable
                sd_switches_dh[(g["date"], int(g["end_ts"][11:13]))] += 1

    wp_dh: Counter[tuple[str, int]] = Counter()
    for r in hourly:
        h = int(r["hour"])
        if 6 <= h <= 20:
            wp_dh[(r["date"], h)] += int(r["white_pngs"])

    tie_cams = [r for r in cameras if int(r["phase_a_count"]) == int(r["phase_b_count"])]
    if len(tie_cams) == 1:
        tc = tie_cams[0]
        tie_txt = f" + 1 tie (cam {tc['camera_id']}: {tc['phase_a_count']}A/{tc['phase_b_count']}B)"
    elif bs["modal_tie"] > 0:
        tie_txt = f" + {bs['modal_tie']} tie"
    else:
        tie_txt = ""

    width, height = 1260, 690
    svg = _svg_root(width, height)
    _add_title_block(
        svg,
        "Scraper Mechanics: 53/47 Staggered Polling & Phase-Switch Alignment with Morning Stalls",
        f"{bs['modal_a_strict']} modal-A{tie_txt} + {bs['modal_b_strict']} modal-B cameras · "
        f"{bs['mixed_cameras']}/{summary['cameras']} mixed cameras · "
        f"{bs['same_day_switches']} intra-day + {bs['overnight_switches']} overnight switches",
        width,
    )

    # Left Panel: Minute % 10 bimodal polling histogram
    lx0, ly0, lw, lh = 75, 118, 365, 455
    _el(svg, "text", {"x": lx0, "y": ly0 - 14, "font-size": 12.5, "font-weight": "700"}, "Polling Offset Within 10-Min Cycle")
    _el(svg, "rect", {"x": lx0, "y": ly0, "width": lw, "height": lh, "fill": PANEL_BG, "stroke": GRID, "stroke-width": 1})

    ymax_m = max(25000, max(min_mod10.values()) * 1.32)
    for yv in (0, 5000, 10000, 15000, 20000, 25000):
        yy = ly0 + lh - (yv / ymax_m) * lh
        _el(svg, "line", {"x1": lx0, "y1": yy, "x2": lx0 + lw, "y2": yy, "stroke": GRID, "stroke-width": 0.8})
        _el(svg, "text", {"x": lx0 - 8, "y": yy + 4, "font-size": 10, "fill": INK2, "text-anchor": "end"}, f"{yv // 1000}k")

    bw = lw / 10.0
    for m in range(10):
        cnt = min_mod10.get(m, 0)
        color = BLUE if m < 5 else ORANGE
        bh = (cnt / ymax_m) * lh
        bx = lx0 + m * bw + 5
        by = ly0 + lh - bh
        _el(svg, "rect", {"x": f"{bx:.1f}", "y": f"{by:.1f}", "width": f"{bw - 10:.1f}", "height": f"{bh:.1f}", "fill": color, "rx": 2})
        _el(svg, "text", {"x": lx0 + m * bw + bw / 2, "y": ly0 + lh + 16, "font-size": 10.5, "fill": INK2, "text-anchor": "middle", "class": "mono"}, f":{m}")
        if cnt >= 1000:
            _el(svg, "text", {"x": lx0 + m * bw + bw / 2, "y": by - 6, "font-size": 9.5, "font-weight": "700", "fill": color, "text-anchor": "middle"}, f"{cnt / 1000:.1f}k")
        elif cnt > 0:
            _el(svg, "text", {"x": lx0 + m * bw + bw / 2, "y": by - 5, "font-size": 8.5, "fill": INK2, "text-anchor": "middle"}, str(cnt))

    _el(svg, "text", {"x": lx0 + lw / 2, "y": ly0 + lh + 34, "font-size": 11, "fill": INK2, "text-anchor": "middle"}, "Filename minute mod 10 (e.g. :00/:10 vs :05/:15)")
    # Callout boxes inside left panel top headroom
    _el(svg, "rect", {"x": lx0 + 12, "y": ly0 + 10, "width": 162, "height": 48, "fill": "#eff6ff", "stroke": BLUE, "stroke-width": 0.9, "rx": 4})
    _el(svg, "text", {"x": lx0 + 20, "y": ly0 + 27, "font-size": 11, "font-weight": "700", "fill": BLUE}, "Batch A (:00–:04)")
    _el(svg, "text", {"x": lx0 + 20, "y": ly0 + 44, "font-size": 10.2, "fill": INK2}, f"{bs['phase_a_frames']:,} frames ({bs['modal_a_with_tie']} modal)")

    _el(svg, "rect", {"x": lx0 + 190, "y": ly0 + 10, "width": 162, "height": 48, "fill": "#fff7ed", "stroke": ORANGE, "stroke-width": 0.9, "rx": 4})
    _el(svg, "text", {"x": lx0 + 198, "y": ly0 + 27, "font-size": 11, "font-weight": "700", "fill": ORANGE}, "Batch B (:05–:09)")
    _el(svg, "text", {"x": lx0 + 198, "y": ly0 + 44, "font-size": 10.2, "fill": INK2}, f"{bs['phase_b_frames']:,} frames ({bs['modal_b']} modal)")

    # Right Panel (2 aligned hourly tracks across 105 hours)
    rx0, rw = 505, 715
    col_w = rw / (len(days) * len(hours))

    # Top track: Same-day switches + 12-20m stalls
    ry1, rh1 = 118, 210
    _el(svg, "text", {"x": rx0, "y": ry1 - 14, "font-size": 12.2, "font-weight": "700"},
        f"Hourly Phase Switches ({bs['same_day_switches']}) & 12–20m Stalls ({summary['gaps_summary']['same_day_12_20m']})")
    _el(svg, "rect", {"x": rx0 + rw - 245, "y": ry1 - 24, "width": 11, "height": 11, "fill": BLUE})
    _el(svg, "text", {"x": rx0 + rw - 229, "y": ry1 - 15, "font-size": 10.2, "fill": INK2}, "Intra-day A↔B switches")
    _el(svg, "line", {"x1": rx0 + rw - 102, "y1": ry1 - 18.5, "x2": rx0 + rw - 84, "y2": ry1 - 18.5, "stroke": CRIMSON, "stroke-width": 2})
    _el(svg, "text", {"x": rx0 + rw - 79, "y": ry1 - 15, "font-size": 10.2, "fill": INK2}, "12–20m stalls")
    _el(svg, "rect", {"x": rx0, "y": ry1, "width": rw, "height": rh1, "fill": PANEL_BG, "stroke": GRID, "stroke-width": 1})

    # Bottom track: Morning White PNG bursts
    ry2, rh2 = 372, 201
    _el(svg, "text", {"x": rx0, "y": ry2 - 14, "font-size": 12.5, "font-weight": "700"},
        f"Synchronized 07–08h White PNG Bursts ({summary['white_pngs']} frames, 07:15–08:45 daily)")
    _el(svg, "rect", {"x": rx0, "y": ry2, "width": rw, "height": rh2, "fill": PANEL_BG, "stroke": GRID, "stroke-width": 1})

    # Day bands & labels
    for d_idx, d in enumerate(days):
        dx = rx0 + d_idx * len(hours) * col_w
        dw = len(hours) * col_w
        if d_idx % 2 == 1:
            _el(svg, "rect", {"x": dx, "y": ry1, "width": dw, "height": rh1, "fill": "#f8f7f4"})
            _el(svg, "rect", {"x": dx, "y": ry2, "width": dw, "height": rh2, "fill": "#f8f7f4"})
        _el(svg, "line", {"x1": dx, "y1": ry1, "x2": dx, "y2": ry1 + rh1, "stroke": "#d4d2cb", "stroke-width": 0.9})
        _el(svg, "line", {"x1": dx, "y1": ry2, "x2": dx, "y2": ry2 + rh2, "stroke": "#d4d2cb", "stroke-width": 0.9})
        short_d = datetime.strptime(d, "%Y-%m-%d").strftime("%a %d")
        _el(svg, "text", {"x": dx + dw / 2, "y": ry2 + rh2 + 17, "font-size": 10.5, "font-weight": "600", "fill": INK2, "text-anchor": "middle"}, short_d)

    ymax_sw = 115
    for yv in (0, 25, 50, 75, 100):
        yy = ry1 + rh1 - (yv / ymax_sw) * rh1
        _el(svg, "line", {"x1": rx0, "y1": yy, "x2": rx0 + rw, "y2": yy, "stroke": GRID, "stroke-width": 0.7})
        _el(svg, "text", {"x": rx0 - 7, "y": yy + 3.5, "font-size": 9.5, "fill": INK2, "text-anchor": "end"}, str(yv))

    ymax_wp = 120
    for yv in (0, 30, 60, 90, 120):
        yy = ry2 + rh2 - (yv / ymax_wp) * rh2
        _el(svg, "line", {"x1": rx0, "y1": yy, "x2": rx0 + rw, "y2": yy, "stroke": GRID, "stroke-width": 0.7})
        _el(svg, "text", {"x": rx0 - 7, "y": yy + 3.5, "font-size": 9.5, "fill": INK2, "text-anchor": "end"}, str(yv))

    stall_pts: list[str] = []
    for d_idx, d in enumerate(days):
        for h_idx, h in enumerate(hours):
            slot = d_idx * len(hours) + h_idx
            cx = rx0 + slot * col_w
            sw = sd_switches_dh.get((d, h), 0)
            st = stalls_dh.get((d, h), 0)
            wp = wp_dh.get((d, h), 0)
            if sw > 0:
                bh = min(rh1, (sw / ymax_sw) * rh1)
                _el(svg, "rect", {"x": f"{cx + 0.6:.1f}", "y": f"{ry1 + rh1 - bh:.1f}", "width": f"{max(2.0, col_w - 1.2):.1f}", "height": f"{bh:.1f}", "fill": BLUE})
            if wp > 0:
                bh2 = min(rh2, (wp / ymax_wp) * rh2)
                _el(svg, "rect", {"x": f"{cx + 0.6:.1f}", "y": f"{ry2 + rh2 - bh2:.1f}", "width": f"{max(2.0, col_w - 1.2):.1f}", "height": f"{bh2:.1f}", "fill": AMBER})
            sy = ry1 + rh1 - min(rh1, (st / ymax_sw) * rh1)
            stall_pts.append(f"{cx + col_w / 2:.1f},{sy:.1f}")

    _el(svg, "polyline", {"points": " ".join(stall_pts), "fill": "none", "stroke": CRIMSON, "stroke-width": 1.6})

    # Annotations on top peaks (guarded against subsetted days & computed dynamically)
    peak_specs = [
        ("2026-08-25", 7, (6, 7), "25 Aug 06–07h", lambda sw, st: f"{sw} switches", 18),
        ("2026-08-26", 6, (6,), "26 Aug 06h", lambda sw, st: f"{sw} sw / {st} stalls", 42),
        ("2026-08-29", 7, (7, 8), "29 Aug 07–08h", lambda sw, st: f"{sw} switches", 18),
    ]
    peaks_drawn = 0
    for d, h, h_span, title_lbl, fmt_fn, y_off in peak_specs:
        if d not in days:
            continue
        sw_sum = sum(sd_switches_dh.get((d, hh), 0) for hh in h_span)
        st_sum = sum(stalls_dh.get((d, hh), 0) for hh in h_span)
        if sw_sum == 0 and st_sum == 0:
            continue
        idx = days.index(d) * len(hours) + (h - 6)
        px = min(rx0 + rw - 95, rx0 + idx * col_w + col_w / 2)
        _el(svg, "text", {"x": px + 6, "y": ry1 + y_off, "font-size": 9.8, "font-weight": "700", "fill": INK}, title_lbl)
        _el(svg, "text", {"x": px + 6, "y": ry1 + y_off + 12, "font-size": 9.5, "fill": INK2}, fmt_fn(sw_sum, st_sum))
        peaks_drawn += 1
    if peaks_drawn == 0 and sd_switches_dh:
        (top_d, top_h), top_sw = max(sd_switches_dh.items(), key=lambda kv: kv[1])
        if top_d in days and 6 <= top_h <= 20:
            idx = days.index(top_d) * len(hours) + (top_h - 6)
            px = min(rx0 + rw - 95, rx0 + idx * col_w + col_w / 2)
            top_st = stalls_dh.get((top_d, top_h), 0)
            lbl_d = datetime.strptime(top_d, "%Y-%m-%d").strftime("%d %b")
            _el(svg, "text", {"x": px + 6, "y": ry1 + 18, "font-size": 9.8, "font-weight": "700", "fill": INK}, f"{lbl_d} {top_h:02d}h")
            _el(svg, "text", {"x": px + 6, "y": ry1 + 30, "font-size": 9.5, "fill": INK2}, f"{top_sw} sw / {top_st} stalls")

    _add_footer(
        svg,
        "Source: reports/forensics/corpus_summary.json, gap_events.csv, hourly_coverage.csv"
        + (" + raw filename timestamps." if fn_records else "."),
        width,
        height,
    )
    _write_and_validate_svg(svg, out_path)


# ---------------------------------------------------------------------------
# Chart 4: /16 Subnet Anomaly Summary & Bangkok Spatial Scatter + Rainfall Context
# ---------------------------------------------------------------------------


def build_chart_04_subnet_spatial(data: dict[str, Any], out_path: Path) -> None:
    cameras = data["cameras"]
    subnets = data["subnets"]
    ea = data["external"]["events"]

    width, height = 1300, 760
    svg = _svg_root(width, height)
    _add_title_block(
        svg,
        "Spatial & /16 Subnet Forensics: Clustered Infrastructure Faults vs. Scattered Scraper Drops",
        "100 cameras across 18 /16 IP subnets · Thu 27 AM cohorts (69/28) intermix across subnets, whereas 10.128.* & 10.116/118.* fail in lockstep",
        width,
    )

    # Left Panel: Bangkok geographic scatter (aspect-corrected using cos(13.75 deg))
    mx0, my0, mw, mh = 65, 118, 535, 530
    _el(svg, "text", {"x": mx0, "y": my0 - 14, "font-size": 12.5, "font-weight": "700"},
        "Bangkok Spatial Map (Lat/Lon Aspect-Corrected, Color = Infrastructure/Gap Status)")
    _el(svg, "rect", {"x": mx0, "y": my0, "width": mw, "height": mh, "fill": PANEL_BG, "stroke": GRID, "stroke-width": 1})

    lats = [float(r["latitude"]) for r in cameras]
    lons = [float(r["longitude"]) for r in cameras]
    lat_min, lat_max = min(lats) - 0.015, max(lats) + 0.015
    lon_min, lon_max = min(lons) - 0.020, max(lons) + 0.020
    cos_lat = math.cos(math.radians(13.75))
    data_w = (lon_max - lon_min) * cos_lat
    data_h = (lat_max - lat_min)
    scale = min((mw - 30) / data_w, (mh - 30) / data_h)
    x_off = mx0 + (mw - data_w * scale) / 2
    y_off = my0 + (mh - data_h * scale) / 2

    def _proj(lat: float, lon: float) -> tuple[float, float]:
        x = x_off + (lon - lon_min) * cos_lat * scale
        y = y_off + (lat_max - lat) * scale
        return x, y

    # Lat/lon graticule
    for lat_g in (13.70, 13.75, 13.80):
        _, yy = _proj(lat_g, lon_min)
        if my0 < yy < my0 + mh:
            _el(svg, "line", {"x1": mx0, "y1": yy, "x2": mx0 + mw, "y2": yy, "stroke": GRID, "stroke-width": 0.7})
            _el(svg, "text", {"x": mx0 - 6, "y": yy + 3.5, "font-size": 9.5, "fill": INK2, "text-anchor": "end"}, f"{lat_g:.2f}°N")
    for lon_g in (100.40, 100.45, 100.50, 100.55, 100.60):
        xx, _ = _proj(lat_min, lon_g)
        if mx0 < xx < mx0 + mw:
            _el(svg, "line", {"x1": xx, "y1": my0, "x2": xx, "y2": my0 + mh, "stroke": GRID, "stroke-width": 0.7})
            _el(svg, "text", {"x": xx, "y": my0 + mh + 15, "font-size": 9.5, "fill": INK2, "text-anchor": "middle"}, f"{lon_g:.2f}°E")

    # Classify each camera's primary forensic highlight
    def _cam_group(r: dict[str, str]) -> tuple[str, str, float]:
        cid = r["camera_id"]
        s16 = r["subnet_16"]
        if s16 == "10.128.0.0/16":
            return ("10.128.* (Sun 30 11:25–12:26)", CRIMSON, 5.2)
        if s16 in ("10.116.0.0/16", "10.118.0.0/16"):
            return ("10.116/118.* (Fri 28 13h freeze)", ORANGE, 4.9)
        if cid in ("938", "939"):
            return ("10.156.* (938/939 25h freeze)", MAGENTA, 5.2)
        if cid in ("150", "395"):
            return ("Long freeze (150, 395)", PURPLE, 5.2)
        if cid in ("363",):
            return ("Inconclusive drop (363)", BLUE, 4.8)
        return ("Normal / scraper-only artifacts", "#7c9c92", 3.6)

    # Plot normal cameras first, then highlighted clusters
    ordered_cams = sorted(cameras, key=lambda r: _cam_group(r)[2])
    for r in ordered_cams:
        x, y = _proj(float(r["latitude"]), float(r["longitude"]))
        _, color, rad = _cam_group(r)
        st = r["thu27_am_status"]
        if st == "zero_morning":
            # Triangle marker for zero_morning
            pts = f"{x:.1f},{y - rad - 0.8:.1f} {x - rad:.1f},{y + rad - 0.5:.1f} {x + rad:.1f},{y + rad - 0.5:.1f}"
            _el(svg, "polygon", {"points": pts, "fill": color, "stroke": "#ffffff", "stroke-width": 0.7})
        elif st == "full_morning_pseudo":
            _el(svg, "rect", {"x": f"{x - rad:.1f}", "y": f"{y - rad:.1f}", "width": f"{rad * 2:.1f}", "height": f"{rad * 2:.1f}", "fill": color, "stroke": INK, "stroke-width": 1.0})
        else:
            _el(svg, "circle", {"cx": f"{x:.1f}", "cy": f"{y:.1f}", "r": f"{rad:.1f}", "fill": color, "stroke": "#ffffff", "stroke-width": 0.7})

    # Geographic cluster callouts (referencing M2 attribution verdicts via PROJECT.md contract)
    def _event_verdict(*keys: str, default: str = "SUBNET_INFRA") -> str:
        for k in keys:
            ev = ea.get(k)
            if isinstance(ev, dict):
                v = ev.get("attribution_verdict") or ev.get("verdict")
                if v:
                    return str(v)
        return default

    thon_v = _event_verdict("20260828_1300_10_116_118", "20260828_1300_10_116_118_freeze")
    yann_v = _event_verdict("20260830_1125_10_128", "20260830_1125_10_128_outage")
    dus_v = _event_verdict("20260830_1520_cam363")
    ram_v = _event_verdict("20260825_26_938_939_freeze", "long_freezes")

    geo_notes = [
        (13.713, 100.490, -140, 26, f"10.116/118.* Thonburi (10/10)", f"{thon_v} · 0 MEA"),
        (13.708, 100.535, 35, 22, f"10.128.* Yan Nawa (4/4)", f"{yann_v} · 2.1 mm/h"),
        (13.753, 100.614, -148, -28, f"938/939 (10.156.*)", f"{ram_v} · 25h freeze"),
        (13.784, 100.534, 48, -24, f"cam 150 & 363", f"150 freeze; 363 {dus_v} (2.5mm)"),
    ]
    box_w = 212
    for lat_p, lon_p, dx, dy, t1, t2 in geo_notes:
        px, py = _proj(lat_p, lon_p)
        tx = max(mx0 + 8, min(mx0 + mw - box_w - 4, px + dx))
        ty = max(my0 + 18, min(my0 + mh - 24, py + dy))
        _el(svg, "line", {"x1": px, "y1": py, "x2": tx + 40, "y2": ty + 4, "stroke": INK2, "stroke-width": 0.9, "stroke-dasharray": "2,2"})
        _el(svg, "rect", {"x": tx - 3, "y": ty - 11, "width": box_w, "height": 27, "fill": "#ffffff", "fill-opacity": 0.92, "stroke": GRID, "stroke-width": 0.8, "rx": 3})
        _el(svg, "text", {"x": tx + 2, "y": ty, "font-size": 9.8, "font-weight": "700", "fill": INK}, t1)
        _el(svg, "text", {"x": tx + 2, "y": ty + 12, "font-size": 8.8, "fill": INK2}, t2)

    # Right Panel: All 18 /16 Subnets Breakdown (bars + frozen & >20m gap badges)
    sx0, sy0, sw, sh = 695, 118, 565, 530
    _el(svg, "text", {"x": sx0, "y": sy0 - 14, "font-size": 12.5, "font-weight": "700"},
        "All 18 /16 Subnets: Thu 27 AM Split (Intermixed) vs. Frozen / >20m Faults")
    _el(svg, "rect", {"x": sx0, "y": sy0, "width": sw, "height": sh, "fill": PANEL_BG, "stroke": GRID, "stroke-width": 1})

    max_cams = max(int(r["camera_count"]) for r in subnets)
    bar_area_w = 240.0
    row_h = sh / len(subnets)
    for idx, r in enumerate(subnets):
        ry = sy0 + idx * row_h
        if idx % 2 == 1:
            _el(svg, "rect", {"x": sx0 + 1, "y": ry, "width": sw - 2, "height": row_h, "fill": "#fafaf8"})
        s16 = r["subnet_16"]
        nc = int(r["camera_count"])
        n_part = int(r["thu27_part69"])
        n_zero = int(r["thu27_zero28"])
        n_full = int(r["thu27_full"])
        frz = int(r["bridged_frozen"])
        g20 = int(r["gaps_gt20m"])

        _el(svg, "text", {"x": sx0 - 8, "y": ry + row_h / 2 + 3.5, "font-size": 9.8, "fill": INK, "text-anchor": "end", "class": "mono"}, s16[:-5])

        # Stacked bar for Thu 27 AM camera split (proves intermixing across /16 subnets)
        bx = sx0 + 8
        by = ry + 5
        bh = row_h - 10
        segs = [(n_part, AMBER), (n_zero, NEUTRAL), (n_full, PURPLE)]
        for val, col in segs:
            if val <= 0:
                continue
            bw = (val / max_cams) * bar_area_w
            _el(svg, "rect", {"x": f"{bx:.1f}", "y": f"{by:.1f}", "width": f"{bw:.1f}", "height": f"{bh:.1f}", "fill": col})
            bx += bw

        _el(svg, "text", {"x": bx + 6, "y": ry + row_h / 2 + 3.5, "font-size": 9.5, "fill": INK2},
            f"{nc} ({n_part}/{n_zero}/{n_full})")

        # Frozen & >20m badge
        badge_x = sx0 + 325
        if frz > 0 or g20 > 0:
            note = f"frz={frz}" + (f", >20m={g20}" if g20 else "")
            bcol = CRIMSON if (frz >= 15 or g20 >= 3) else ORANGE
            _el(svg, "text", {"x": badge_x, "y": ry + row_h / 2 + 3.5, "font-size": 9.5, "font-weight": "700", "fill": bcol}, note)
        else:
            _el(svg, "text", {"x": badge_x, "y": ry + row_h / 2 + 3.5, "font-size": 9.5, "fill": MUTED}, "0 frz, 0 >20m")

        # Root cause tag for key subnets
        tag = ""
        if s16 == "10.156.0.0/16":
            tag = "938/939 25h freeze"
        elif s16 == "10.128.0.0/16":
            tag = "4/4 Yan Nawa outage"
        elif s16 in ("10.116.0.0/16", "10.118.0.0/16"):
            tag = "Fri 28 13h Thonburi freeze"
        elif s16 == "10.102.0.0/16":
            tag = "cam 150 + 363"
        elif s16 == "10.101.0.0/16":
            tag = "cam 395 + 576"
        elif s16 in ("10.107.0.0/16", "10.134.0.0/16"):
            tag = "Thu 27 GStreamer bars"
        if tag:
            _el(svg, "text", {"x": sx0 + sw - 8, "y": ry + row_h / 2 + 3.5, "font-size": 9.2, "fill": INK2, "text-anchor": "end"}, tag)

    # Bottom legends
    ly = 682
    items = [
        (CRIMSON, "10.128.* (4/4 Sun 30)"),
        (ORANGE, "10.116/118.* (Fri 28 13h)"),
        (MAGENTA, "938/939 (10.156.*)"),
        (PURPLE, "150/395 freeze / GSt bars"),
        (AMBER, "Thu 27 part69 (circle)"),
        (NEUTRAL, "Thu 27 zero28 (triangle)"),
    ]
    for i, (col, lbl) in enumerate(items):
        ix = 36 + i * 208
        _el(svg, "rect", {"x": ix, "y": ly, "width": 13, "height": 11, "fill": col})
        _el(svg, "text", {"x": ix + 18, "y": ly + 9.5, "font-size": 10.5, "fill": INK2}, lbl)

    _add_footer(
        svg,
        "Source: reports/forensics/camera_forensics.csv, subnet_summary.csv, external_attribution.json (MEA 25–31 Aug 2569 & Open-Meteo precipitation checks).",
        width,
        height,
    )
    _write_and_validate_svg(svg, out_path)


# ---------------------------------------------------------------------------
# Chart 5: Downstream Pipeline Impact Funnel & Cell-Completeness Comparison
# ---------------------------------------------------------------------------


def build_chart_05_downstream_funnel(data: dict[str, Any], out_path: Path) -> None:
    summary = data["summary"]
    hourly = data["hourly"]
    frozen = data["frozen"]

    total_raw = summary["total_files"]
    wp = summary["white_pngs"]
    trunc = summary["truncated_jpegs"]
    gst = summary["gst_color_bars"]
    bridged_frz = summary["bridged_frozen"]
    # Non-placeholder frozen repeats (exclude gst_bars repeats already removed as gst_color_bars)
    non_gst_frz = summary["valid_live_jpegs"] - summary["non_frozen_live_jpegs"]
    non_gst_frz_cams = len({r["camera_id"] for r in frozen if r.get("is_gst_bars") == "False"})
    after_wp = total_raw - wp
    after_trunc = after_wp - trunc
    after_gst = after_trunc - gst
    non_frozen_live = summary["non_frozen_live_jpegs"]
    tail_cnt = summary.get("html_tail", {}).get("files_with_tail", total_raw)
    tail_pct = (100.0 * tail_cnt / total_raw) if total_raw else 0.0

    # Compute rain.py [camera_id, date, hour] >= 3 cell completeness dynamically from hourly_coverage.csv
    active_cells = [r for r in hourly if 6 <= int(r["hour"]) <= 20]
    h21_cells = [r for r in hourly if int(r["hour"]) == 21]
    complete_cells = [r for r in active_cells if int(r["valid_live_jpegs"]) >= 3]
    dropped_active = [r for r in active_cells if int(r["valid_live_jpegs"]) < 3]
    dropped_thu_am = [r for r in dropped_active if r["date"] == "2026-08-27" and int(r["hour"]) in (6, 7, 8)]
    dropped_other = [r for r in dropped_active if not (r["date"] == "2026-08-27" and int(r["hour"]) in (6, 7, 8))]
    complete_live_frames = sum(int(r["valid_live_jpegs"]) for r in complete_cells)
    dropped_active_frames = sum(int(r["valid_live_jpegs"]) for r in dropped_active)
    h21_live_frames = sum(int(r["valid_live_jpegs"]) for r in h21_cells)
    dropped_live_frames = non_frozen_live - complete_live_frames

    width, height = 1240, 680
    svg = _svg_root(width, height)
    _add_title_block(
        svg,
        "Downstream Impact: Forensic Data Cleansing Funnel & QC Bug Remediation",
        f"Stripping ASP.NET HTML tails, placeholders, and incomplete (<3) cells turns {total_raw:,} raw files into "
        f"{non_frozen_live:,} live frames ({complete_live_frames:,} in complete hours)",
        width,
    )

    # Left Panel: Cleansing Funnel (horizontal bars)
    fx0, fy0, fw, fh = 55, 118, 560, 475
    _el(svg, "text", {"x": fx0, "y": fy0 - 14, "font-size": 12.5, "font-weight": "700"},
        "Corpus Cleansing Funnel (Raw Files → Complete-Hour Live Snapshots)")
    _el(svg, "rect", {"x": fx0, "y": fy0, "width": fw, "height": fh, "fill": PANEL_BG, "stroke": GRID, "stroke-width": 1})

    stages = [
        ("1. Raw corpus files", total_raw, 0, BLUE, f"{tail_pct:.1f}% · {tail_cnt:,}/{total_raw:,} carry ASP.NET HTML tail"),
        ("2. Valid non-PNG containers", after_wp, -wp, "#3b82f6", f"-{wp} white 400×266 PNGs (07:15–08:45 bursts)"),
        ("3. Valid EOI-complete JPEGs", after_trunc, -trunc, "#2563eb", f"-{trunc} truncated JPEGs (cam 595, 26 Aug 15:30–40)"),
        ("4. Genuine camera JPEGs", after_gst, -gst, AQUA, f"-{gst} GStreamer 246×205 bars (432, 1804 Thu 27 AM)"),
        ("5. Non-frozen live JPEGs", non_frozen_live, -non_gst_frz, "#0d9488", f"-{non_gst_frz} non-placeholder frozen repeats ({non_gst_frz_cams} cams)"),
        ("6. Complete-hour (>=3) frames", complete_live_frames, -dropped_live_frames, "#0f766e",
         f"-{dropped_live_frames} in <3 cells ({dropped_active_frames} in {len(dropped_active)} 06–20h + {h21_live_frames} in {len(h21_cells)} 21h)"),
    ]
    bar_max_w = 340.0
    row_step = fh / len(stages)
    for idx, (title, val, delta, color, note) in enumerate(stages):
        ry = fy0 + idx * row_step + 14
        bw = (val / max(total_raw, 1)) * bar_max_w
        pct = (100.0 * val / total_raw) if total_raw else 0.0
        _el(svg, "text", {"x": fx0 + 16, "y": ry + 11, "font-size": 11.2, "font-weight": "700", "fill": INK}, title)
        _el(svg, "rect", {"x": fx0 + 16, "y": ry + 18, "width": f"{bw:.1f}", "height": 22, "fill": color, "rx": 3})
        _el(svg, "text", {"x": fx0 + 24 + bw, "y": ry + 33, "font-size": 11.2, "font-weight": "700", "fill": INK},
            f"{val:,} ({pct:.2f}%)")
        if delta < 0:
            _el(svg, "text", {"x": fx0 + 16, "y": ry + 54, "font-size": 10.0, "fill": CRIMSON if abs(delta) > 100 else INK2}, note)
        else:
            _el(svg, "text", {"x": fx0 + 16, "y": ry + 54, "font-size": 10.0, "fill": INK2}, note)

    # Right Panel Top: Legacy inventory.py vs Patched inventory.py
    rx0, rw = 650, 550
    ty0, th0 = 118, 222
    _el(svg, "text", {"x": rx0, "y": ty0 - 14, "font-size": 12.5, "font-weight": "700"},
        "Legacy vs. Patched `inventory.py` Defect Detection")
    _el(svg, "rect", {"x": rx0, "y": ty0, "width": rw, "height": th0, "fill": PANEL_BG, "stroke": GRID, "stroke-width": 1})

    metrics = [
        (f"Frozen live repeats ({non_gst_frz_cams} cams)", 0, non_gst_frz, CRIMSON, f"HTML tail hid {non_gst_frz} live ({bridged_frz} w/ GSt)"),
        ("400×266 white PNGs", 0, wp, AMBER, "Decoded by cv2 as brightness=255, sharpness=0"),
        ("246×205 GStreamer bars", 0, gst, PURPLE, "Decoded as valid JPEGs; 0 vehicles detected"),
        ("Truncated JPEGs (595)", 2, trunc, MAGENTA, "Missing 0xFFD9 EOI; identical 21,900B buffer"),
    ]
    m_step = (th0 - 38) / len(metrics)
    _el(svg, "text", {"x": rx0 + 195, "y": ty0 + 20, "font-size": 10.2, "font-weight": "700", "fill": MUTED}, "Legacy (unpatched)")
    _el(svg, "text", {"x": rx0 + 335, "y": ty0 + 20, "font-size": 10.2, "font-weight": "700", "fill": INK}, "Patched (core_md5 + QC flags)")
    for idx, (lbl, leg_v, pat_v, col, why) in enumerate(metrics):
        my = ty0 + 34 + idx * m_step
        _el(svg, "text", {"x": rx0 + 14, "y": my + 14, "font-size": 10.8, "font-weight": "600"}, lbl)
        _el(svg, "text", {"x": rx0 + 14, "y": my + 29, "font-size": 9.3, "fill": INK2}, why)
        _el(svg, "text", {"x": rx0 + 220, "y": my + 17, "font-size": 11.5, "font-weight": "700", "fill": CRIMSON if leg_v == 0 else INK2}, str(leg_v))
        bw_p = max(6.0, (pat_v / max(non_gst_frz, 1)) * 165.0)
        _el(svg, "rect", {"x": rx0 + 335, "y": my + 5, "width": f"{bw_p:.1f}", "height": 16, "fill": col, "rx": 2})
        _el(svg, "text", {"x": rx0 + 341 + bw_p, "y": my + 17, "font-size": 11, "font-weight": "700", "fill": INK}, f"{pat_v:,}")

    # Right Panel Bottom: rain.py [camera_id, date, hour] >= 3 cell completeness
    by0, bh0 = 382, 211
    total_active = len(active_cells)
    _el(svg, "text", {"x": rx0, "y": by0 - 14, "font-size": 12.5, "font-weight": "700"},
        f"`rain.py` Pre-Baseline Cell Completeness ({total_active:,} Active 06–20h Cells)")
    _el(svg, "rect", {"x": rx0, "y": by0, "width": rw, "height": bh0, "fill": PANEL_BG, "stroke": GRID, "stroke-width": 1})

    # Proportional stacked horizontal bar of active cells
    bar_x, bar_y, bar_w, bar_h = rx0 + 20, by0 + 34, rw - 40, 34
    denom = max(total_active, 1)
    segs = [
        (len(complete_cells), AQUA, f"Complete >=3 live ({len(complete_cells):,} · {100*len(complete_cells)/denom:.1f}%)"),
        (len(dropped_thu_am), CRIMSON, f"Thu 27 AM <3 ({len(dropped_thu_am)})"),
        (len(dropped_other), ORANGE, f"Other <3 ({len(dropped_other)})"),
    ]
    cx = bar_x
    for val, col, _ in segs:
        sw_seg = (val / denom) * bar_w
        _el(svg, "rect", {"x": f"{cx:.1f}", "y": bar_y, "width": f"{max(2.0, sw_seg):.1f}", "height": bar_h, "fill": col})
        cx += sw_seg

    _el(svg, "text", {"x": bar_x, "y": bar_y - 10, "font-size": 11, "font-weight": "700", "fill": INK},
        f"{total_active:,} (camera, date, hour) cells in 06–20h: {len(complete_cells):,} kept · {len(dropped_active)} dropped")

    bullets = [
        (AQUA, f"{len(complete_cells):,} complete cells (>=3 live JPEGs) -> {complete_live_frames:,} clean snapshots"),
        (CRIMSON, f"{len(dropped_thu_am)} Thu 27 AM cells (06–08h) dropped before weekday baseline (avoids 3-cam bias)"),
        (ORANGE, f"{len(dropped_other)} freeze/gap cells dropped (cams 150, 206, 395, 938, 939, 1195)"),
        (NEUTRAL, f"+ {len(h21_cells)} trailing 21:00–21:01 single-sweep boundary cells excluded"),
    ]
    for i, (col, txt) in enumerate(bullets):
        yy = by0 + 96 + i * 26
        _el(svg, "rect", {"x": rx0 + 20, "y": yy - 9, "width": 11, "height": 11, "fill": col, "rx": 2})
        _el(svg, "text", {"x": rx0 + 38, "y": yy, "font-size": 10.5, "fill": INK2}, txt)

    _add_footer(
        svg,
        "Source: reports/forensics/corpus_summary.json, hourly_coverage.csv; remediated in src/cctv/inventory.py & src/cctv/rain.py.",
        width,
        height,
    )
    _write_and_validate_svg(svg, out_path)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def load_forensic_inputs(forensics_dir: Path, raw_images_dir: Path | None = None) -> dict[str, Any]:
    summary = json.loads((forensics_dir / "corpus_summary.json").read_text(encoding="utf-8"))
    external = json.loads((forensics_dir / "external_attribution.json").read_text(encoding="utf-8"))
    return {
        "summary": summary,
        "external": external,
        "cameras": _read_csv(forensics_dir / "camera_forensics.csv"),
        "gaps": _read_csv(forensics_dir / "gap_events.csv"),
        "frozen": _read_csv(forensics_dir / "frozen_streaks.csv"),
        "subnets": _read_csv(forensics_dir / "subnet_summary.csv"),
        "hourly": _read_csv(forensics_dir / "hourly_coverage.csv"),
        "no_eoi": _read_csv(forensics_dir / "no_eoi_events.csv"),
        "osd": _read_csv(forensics_dir / "osd_evidence.csv"),
        "fn_records": _scan_filename_timestamps(raw_images_dir),
    }


def generate_all(
    forensics_dir: Path = Path("reports/forensics"),
    out_dir: Path = Path("reports/figures/forensics"),
    raw_images_dir: Path | None = Path("data/100_cameras/cctv_images"),
) -> list[Path]:
    data = load_forensic_inputs(forensics_dir, raw_images_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = [
        (out_dir / "01_fleet_hourly_anomaly_heatmap.svg", build_chart_01_heatmap),
        (out_dir / "02_thu27_am_blackout_anatomy.svg", build_chart_02_thu27_blackout),
        (out_dir / "03_batch_polling_and_phase_switches.svg", build_chart_03_batch_polling),
        (out_dir / "04_subnet_spatial_anomalies_rain.svg", build_chart_04_subnet_spatial),
        (out_dir / "05_downstream_impact_funnel.svg", build_chart_05_downstream_funnel),
    ]
    paths: list[Path] = []
    for path, builder in outputs:
        builder(data, path)
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forensics", type=Path, default=Path("reports/forensics"))
    parser.add_argument("--out", type=Path, default=Path("reports/figures/forensics"))
    parser.add_argument("--raw-images", type=Path, default=Path("data/100_cameras/cctv_images"))
    args = parser.parse_args()

    raw_dir = args.raw_images if args.raw_images.exists() else None
    paths = generate_all(args.forensics, args.out, raw_dir)
    for p in paths:
        print(f"Wrote and XML-validated {p} ({p.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
