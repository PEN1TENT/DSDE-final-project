"""Tier 5 white-box adversarial & coverage-hardening tests for CCTV forensics.

Executable under stdlib-only Python 3.12-3.15:
    python -m unittest tests/test_forensics_adversarial.py -v
"""

from __future__ import annotations

import binascii
import csv
import json
import re
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zlib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cctv import forensic_charts, forensics, inventory, rain  # noqa: E402


def _make_jpeg(
    width: int = 352,
    height: int = 288,
    payload: bytes = b"\x01\x02\x03",
    *,
    sof_marker: int = 0xC0,
    with_exif: bool = False,
    ff_padding: bool = False,
    with_rst: bool = False,
) -> bytes:
    parts = [b"\xff\xd8"]
    if ff_padding:
        parts.append(b"\xff\xff")
    if with_exif:
        exif_body = b"Exif\x00\x00MM\x00*\x00\x00\x00\x08\x00\x00"
        parts.append(b"\xff\xe1" + struct.pack(">H", len(exif_body) + 2) + exif_body)
    if with_rst:
        parts.append(b"\xff\xd0")
    sof_body = struct.pack(">BHHB", 8, height, width, 3) + b"\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    parts.append(bytes([0xFF, sof_marker]) + struct.pack(">H", len(sof_body) + 2) + sof_body)
    parts.append(b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00")
    parts.append(payload)
    parts.append(b"\xff\xd9")
    return b"".join(parts)


def _png_chunk(ctype: bytes, data: bytes) -> bytes:
    body = ctype + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)


def _paeth_pred(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _encode_png_rows(
    pixels: list[list[int]],
    width: int,
    height: int,
    *,
    color_type: int = 2,
    filter_type: int = 0,
    split_idat: bool = False,
) -> bytes:
    bpp = {0: 1, 2: 3, 6: 4}[color_type]
    stride = width * bpp
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    raw_lines: list[bytes] = []
    prev = [0] * stride
    for r in range(height):
        cur = pixels[r]
        assert len(cur) == stride
        filtered = bytearray([filter_type])
        for i in range(stride):
            left = cur[i - bpp] if i >= bpp else 0
            up = prev[i]
            up_left = prev[i - bpp] if i >= bpp else 0
            if filter_type == 0:
                pred = 0
            elif filter_type == 1:
                pred = left
            elif filter_type == 2:
                pred = up
            elif filter_type == 3:
                pred = (left + up) >> 1
            elif filter_type == 4:
                pred = _paeth_pred(left, up, up_left)
            else:
                raise ValueError(filter_type)
            filtered.append((cur[i] - pred) & 0xFF)
        raw_lines.append(bytes(filtered))
        prev = cur
    compressed = zlib.compress(b"".join(raw_lines))
    if split_idat and len(compressed) > 4:
        mid = len(compressed) // 2
        idat_chunks = _png_chunk(b"IDAT", compressed[:mid]) + _png_chunk(b"IDAT", compressed[mid:])
    else:
        idat_chunks = _png_chunk(b"IDAT", compressed)
    return forensics.PNG_SIG + _png_chunk(b"IHDR", ihdr) + idat_chunks + _png_chunk(b"IEND", b"")


def _html_tail(cam_id: str, epoch_ms: int, *, extra_bytes: bytes = b"") -> bytes:
    return (
        f'\r\n\r\n<!DOCTYPE html><html><form method="post" '
        f'action="./show.aspx?image={cam_id}&amp;time={epoch_ms}" id="form1">'
    ).encode("ascii") + extra_bytes + b"</form></html>"


class StripHtmlTailAdversarialTests(unittest.TestCase):
    def test_eoi_before_soi_is_rejected_as_unknown(self) -> None:
        malformed = b"\xff\xd9\xff\xd8\xff\xe0\x00\x10JFIF\xff\xd9" + _html_tail("10", 1787613003000)
        f_ins = forensics.inspect_bytes(malformed)
        i_ins = inventory.inspect_image_bytes(malformed)
        self.assertEqual(f_ins.container, "unknown")
        self.assertEqual(i_ins["container"], "unknown")
        self.assertFalse(f_ins.truncated_jpeg)

    def test_eoi_inside_trailing_html_does_not_mask_truncated_jpeg(self) -> None:
        trunc_body = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        fake_html = _html_tail("595", 1787613003000, extra_bytes=b"junk\xff\xd9tail")
        data = trunc_body + fake_html

        f_ins = forensics.inspect_bytes(data)
        i_ins = inventory.inspect_image_bytes(data)
        self.assertEqual(f_ins.container, "truncated_jpeg")
        self.assertEqual(i_ins["container"], "truncated_jpeg")
        self.assertEqual(f_ins.core_bytes, trunc_body)
        self.assertEqual(i_ins["core_md5"], f_ins.core_md5)

    def test_eoi_inside_trailing_html_does_not_corrupt_valid_jpeg_core(self) -> None:
        jpg = _make_jpeg(352, 288, payload=b"\x11\x22\x33")
        data_clean = jpg + _html_tail("150", 1787613003000)
        data_with_html_eoi = jpg + _html_tail("150", 1787613003000, extra_bytes=b"\xff\xd9")

        self.assertEqual(
            forensics.inspect_bytes(data_clean).core_md5,
            forensics.inspect_bytes(data_with_html_eoi).core_md5,
        )
        self.assertEqual(
            inventory.inspect_image_bytes(data_clean)["core_md5"],
            inventory.inspect_image_bytes(data_with_html_eoi)["core_md5"],
        )

    def test_fake_iend_inside_trailing_html_does_not_mask_truncated_png(self) -> None:
        # BUG REPRO (forensics.py:234 & inventory.py:53):
        # JPEG search uses `search_limit = html_pos`, but PNG uses unbounded `data.find(PNG_IEND)`.
        ihdr = struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)
        trunc_png = forensics.PNG_SIG + _png_chunk(b"IHDR", ihdr) + b"\x00\x00\x00\x10IDATpartial"
        data = trunc_png + _html_tail("100", 1787613003000, extra_bytes=forensics.PNG_IEND)

        f_core, _, f_kind = forensics.strip_html_tail(data)
        i_core, _, i_kind = inventory.strip_html_tail(data)
        self.assertEqual(f_kind, "truncated_png", "Fake PNG IEND inside HTML tail misclassified truncated PNG as 'png'")
        self.assertEqual(i_kind, "truncated_png", "Fake PNG IEND inside HTML tail misclassified truncated PNG as 'png'")
        self.assertEqual(f_core, trunc_png)
        self.assertEqual(i_core, trunc_png)

    def test_whitespace_between_eoi_and_doctype_has_consistent_html_tail_flag(self) -> None:
        # BUG REPRO (inventory.py:160 vs forensics.py:385-393):
        # If a space sits between JPEG EOI and <!DOCTYPE html>, inventory._HTML_TAIL_RE.match(tail)
        # returns False while forensics._TAIL_ACTION_RE.search(tail) returns True.
        jpg = _make_jpeg(352, 288, payload=b"\xaa\xbb")
        data = jpg + b"  " + _html_tail("150", 1787613003000)
        f_ins = forensics.inspect_bytes(data)
        i_ins = inventory.inspect_image_bytes(data)
        self.assertTrue(f_ins.has_html_tail)
        self.assertTrue(i_ins["has_html_tail"], "inventory.py missed HTML tail when whitespace followed EOI")


class PngAndJpegParserEdgeTests(unittest.TestCase):
    def test_single_dark_pixel_in_4x4_png_is_not_white_png(self) -> None:
        for dark_pos in (0, 5, 15):
            for flt in range(5):
                rows = []
                idx = 0
                for _ in range(4):
                    row: list[int] = []
                    for _ in range(4):
                        if idx == dark_pos:
                            row.extend([254, 255, 255])  # 1-bit darker in R channel
                        else:
                            row.extend([255, 255, 255])
                        idx += 1
                    rows.append(row)
                png = _encode_png_rows(rows, 4, 4, color_type=2, filter_type=flt) + _html_tail("1", 1000)
                f_ins = forensics.inspect_bytes(png)
                i_ins = inventory.inspect_image_bytes(png)
                self.assertEqual(f_ins.container, "png")
                self.assertFalse(f_ins.white_png, f"False positive white_png at pos={dark_pos}, filter={flt}")
                self.assertFalse(i_ins["white_png"], f"inventory false positive white_png at pos={dark_pos}, filter={flt}")

    def test_all_five_png_filters_white_and_color_types_and_split_idat(self) -> None:
        for flt in range(5):
            rows = [[255] * (4 * 3) for _ in range(4)]
            png = _encode_png_rows(rows, 4, 4, color_type=2, filter_type=flt, split_idat=(flt == 4))
            self.assertTrue(forensics.inspect_bytes(png).white_png, f"Failed white PNG filter={flt}")
            self.assertTrue(inventory.inspect_image_bytes(png)["white_png"], f"inventory failed filter={flt}")

        # Grayscale (color_type=0): white vs 1 dark pixel
        gray_white = _encode_png_rows([[255] * 4 for _ in range(4)], 4, 4, color_type=0, filter_type=1)
        gray_dark = _encode_png_rows([[255, 255, 255, 255], [255, 0, 255, 255], [255] * 4, [255] * 4], 4, 4, color_type=0, filter_type=1)
        self.assertTrue(forensics.inspect_bytes(gray_white).white_png)
        self.assertFalse(forensics.inspect_bytes(gray_dark).white_png)

        # RGBA (color_type=6): opaque white vs transparent (alpha=0)
        rgba_white = _encode_png_rows([[255] * (4 * 4) for _ in range(4)], 4, 4, color_type=6, filter_type=3)
        rgba_trans = _encode_png_rows([[255, 255, 255, 0] * 4 for _ in range(4)], 4, 4, color_type=6, filter_type=3)
        self.assertTrue(forensics.inspect_bytes(rgba_white).white_png)
        self.assertFalse(forensics.inspect_bytes(rgba_trans).white_png)

        # Corrupt zlib IDAT must return white_png=False without raising
        ihdr = struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)
        bad_png = forensics.PNG_SIG + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", b"not-zlib") + _png_chunk(b"IEND", b"")
        ins_bad = forensics.inspect_bytes(bad_png)
        self.assertEqual((ins_bad.width, ins_bad.height), (4, 4))
        self.assertFalse(ins_bad.white_png)

        # Cache-hit path in inspect_bytes
        cache: dict[str, bool] = {}
        first = forensics.inspect_bytes(gray_dark, png_white_cache=cache)
        second = forensics.inspect_bytes(gray_dark, png_white_cache=cache)
        self.assertEqual((first.width, first.height, first.white_png), (second.width, second.height, second.white_png))

    def test_jpeg_metadata_progressive_padding_restart_and_truncated_segments(self) -> None:
        prog = _make_jpeg(348, 261, sof_marker=0xC2, ff_padding=True, with_rst=True, with_exif=True)
        ins = forensics.inspect_bytes(prog)
        self.assertEqual((ins.width, ins.height, ins.has_exif), (348, 261, True))

        # Truncated segment length inside header must not crash
        malformed = b"\xff\xd8\xff\xe0\x00\x01\xff\xd9"
        w, h, has_exif = forensics.parse_jpeg_metadata(malformed)
        self.assertEqual((w, h, has_exif), (None, None, False))
        self.assertEqual(forensics.parse_jpeg_metadata(b"\xff\xd8"), (None, None, False))


class FrozenStreakAndGapBoundaryTests(unittest.TestCase):
    def test_cross_day_and_png_bridged_frozen_streaks_and_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            info_csv = root / "cctv_info.csv"
            img_dir = root / "cctv_images"
            out_dir = root / "out"

            with info_csv.open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["camera_id", "location", "location_detail", "location_en", "location_detail_en", "latitude", "longitude", "ip_address", "image_count"])
                # Intentional image_count mismatch on cam 395 (6 vs 5) to exercise counter
                w.writerow(["395", "A", "d", "Cam 395", "d", "13.75", "100.50", "10.101.101.104", "6"])
                w.writerow(["938", "B", "d", "Cam 938", "d", "13.75", "100.61", "10.156.102.38", "5"])

            (img_dir / "395").mkdir(parents=True)
            (img_dir / "938").mkdir(parents=True)

            img_a = _make_jpeg(348, 261, b"freezeA")
            img_b = _make_jpeg(352, 288, b"freezeB")
            img_c = _make_jpeg(352, 288, b"liveC")
            white_png = _encode_png_rows([[255] * 12 for _ in range(4)], 4, 4, color_type=2)
            trunc_jpg = b"\xff\xd8\xff\xe0\x00\x10JFIF"

            def put(cid: str, ts: str, body: bytes, epoch_ms: int) -> None:
                (img_dir / cid / f"{cid}_loc_det_{ts}.jpg").write_bytes(body + _html_tail(cid, epoch_ms))

            # Cross-day strict frozen streak on cam 395 (no Thu 27 in this synthetic corpus!)
            put("395", "20260825_205500", img_a, 1787666103000)
            put("395", "20260826_055500", img_a, 1787698503000)  # before 06:00 -> cross-day strict frozen
            put("395", "20260826_060700", img_c, 1787699223000)  # exactly 12.00 min same-day gap
            put("395", "20260826_062700", img_c, 1787700423000)  # 20.00 min same-day gap + strict frozen
            put("395", "20260826_210200", img_a, 1787752923000)  # after 21:01

            # Unparseable / wrong-cam-id filename
            (img_dir / "395" / "999_wrong_20260826_070000.jpg").write_bytes(img_c)

            # Cam 938: cross-day PNG + truncated-JPEG bridged streak
            put("938", "20260825_205000", img_b, 1787665803000)
            put("938", "20260826_072500", white_png, 1787703903000)
            put("938", "20260826_073500", trunc_jpg, 1787704503000)
            put("938", "20260826_083500", img_b, 1787708103000)  # bridged across midnight + white_png + trunc_jpg
            put("938", "20260826_210030", img_c, 1787752833000)  # 21:00-21:01 boundary

            summary = forensics.run_forensics(info_csv, img_dir, out_dir)
            self.assertEqual(summary["image_count_mismatches"], 1)
            self.assertEqual(summary["unparseable_filenames"], 1)
            self.assertEqual(summary["daily_window"]["before_0600"], 1)
            self.assertEqual(summary["daily_window"]["between_2100_2101"], 1)
            self.assertEqual(summary["daily_window"]["after_2101"], 1)
            self.assertEqual(summary["strict_frozen"], 2)   # 395: 1 cross-day + 1 at 06:27
            self.assertEqual(summary["bridged_frozen"], 3)  # +1 on 938 bridged across day+PNG+trunc
            self.assertEqual(summary["thu_27_am_split"]["live_traffic_frames"], 0)

            with (out_dir / "frozen_streaks.csv").open(encoding="utf-8") as f:
                streaks = {(r["camera_id"], r["start_ts"]): r for r in csv.DictReader(f)}
            self.assertIn(("395", "2026-08-25 20:55:00"), streaks)
            self.assertEqual(streaks[("395", "2026-08-25 20:55:00")]["bridged_by_png"], "False")
            self.assertIn(("938", "2026-08-25 20:50:00"), streaks)
            self.assertEqual(streaks[("938", "2026-08-25 20:50:00")]["bridged_by_png"], "True")

            with (out_dir / "gap_events.csv").open(encoding="utf-8") as f:
                gaps = list(csv.DictReader(f))
            # 06:07 -> 06:27 is 20.00 min (classified as 12-20m); 06:27 -> 21:02 is >20m
            classes = Counter(g["gap_class"] for g in gaps)
            self.assertEqual(classes["12-20m"], 1)  # 05:55->06:07 (exact 12.00m) excluded; 06:07->06:27 (20.00m) included
            self.assertEqual(classes[">20m"], 3)  # 395 (06:27->21:02) + 938 (07:35->08:35, 08:35->21:00)

            self.assertEqual(forensics.ip_subnets("invalid"), ("", ""))


class RainCompletenessAdversarialTests(unittest.TestCase):
    def test_weekday_with_1_thu27_am_and_25_tue_mon_frames_rejects_only_thu27(self) -> None:
        # Grouping by (camera_id, hour, daytype='weekday') would see 26 >= 3 frames and keep
        # the corrupted Thu 27 AM outlier; grouping by (camera_id, date, hour) must drop ONLY Thu 27.
        rows = []
        for d in ("2026-08-25", "2026-08-26", "2026-08-28", "2026-08-31"):
            n_frames = 6 if d != "2026-08-31" else 7  # 6 + 6 + 6 + 7 = 25 healthy weekday frames
            for i in range(n_frames):
                rows.append({"camera_id": 150, "date": d, "hour": 7, "daytype": "weekday", "n_vehicles": 20 + i})
        # Add 1 Thu 27 AM outlier frame in the exact same (camera_id=150, hour=7, daytype='weekday') bucket
        rows.append({"camera_id": 150, "date": "2026-08-27", "hour": 7, "daytype": "weekday", "n_vehicles": 0})

        filtered = rain.filter_complete_hour_records(rows, min_frames=3)
        self.assertEqual(len(filtered), 25)
        self.assertFalse(any(r["date"] == "2026-08-27" for r in filtered))

    def test_complete_hour_cell_keys_boundaries(self) -> None:
        keys = [
            ("10", "2026-08-25", 7),
            ("10", "2026-08-25", 7),  # count=2 -> excluded
            ("10", "2026-08-25", 8),
            ("10", "2026-08-25", 8),
            ("10", "2026-08-25", 8),  # count=3 -> included
        ]
        self.assertEqual(rain.complete_hour_cell_keys(keys, min_frames=3), {("10", "2026-08-25", 8)})
        self.assertEqual(rain.filter_complete_hour_records([]), [])


class ForensicChartsAdversarialTests(unittest.TestCase):
    FIG_DIR = ROOT / "reports" / "figures" / "forensics"
    FORENSICS_DIR = ROOT / "reports" / "forensics"
    NS = "{http://www.w3.org/2000/svg}"

    def _check_svg_xml_and_text_layout(self, svg_path: Path) -> None:
        tree = ET.parse(svg_path)
        root = tree.getroot()
        self.assertTrue(root.tag.endswith("svg"))
        vb = [float(v) for v in root.attrib["viewBox"].split()]
        vw, vh = vb[2], vb[3]

        boxes: list[tuple[str, float, float, float, float]] = []
        for el in root.iter():
            if el.tag.replace(self.NS, "") != "text":
                continue
            if "rotate" in el.attrib.get("transform", ""):
                continue
            txt = (el.text or "").strip()
            if not txt:
                continue
            x = float(el.attrib.get("x", 0))
            y = float(el.attrib.get("y", 0))
            fs = float(el.attrib.get("font-size", 12))
            anchor = el.attrib.get("text-anchor", "start")
            factor = 0.60 if ("mono" in el.attrib.get("class", "") or el.attrib.get("font-weight") == "700") else 0.54
            w = len(txt) * fs * factor
            h = fs * 0.95
            if anchor == "middle":
                x0, x1 = x - w / 2, x + w / 2
            elif anchor == "end":
                x0, x1 = x - w, x
            else:
                x0, x1 = x, x + w
            y0, y1 = y - h * 0.8, y + h * 0.2
            self.assertGreaterEqual(x0, 0.0, f"{svg_path.name}: text clipped left: {txt!r}")
            self.assertLessEqual(x1, vw, f"{svg_path.name}: text clipped right: {txt!r}")
            self.assertGreaterEqual(y0, 0.0, f"{svg_path.name}: text clipped top: {txt!r}")
            self.assertLessEqual(y1, vh, f"{svg_path.name}: text clipped bottom: {txt!r}")
            boxes.append((txt, x0, y0, x1, y1))

        for i in range(len(boxes)):
            t1, ax0, ay0, ax1, ay1 = boxes[i]
            for j in range(i + 1, len(boxes)):
                t2, bx0, by0, bx1, by1 = boxes[j]
                overlaps = ax0 < bx1 and ax1 > bx0 and ay0 < by1 and ay1 > by0
                self.assertFalse(overlaps, f"{svg_path.name}: overlapping text {t1!r} vs {t2!r}")

    @unittest.skipUnless((ROOT / "reports" / "forensics" / "corpus_summary.json").exists(), "forensics artifacts missing")
    def test_svgs_deterministic_xml_valid_and_zero_text_overlaps(self) -> None:
        raw_dir = ROOT / "data" / "100_cameras" / "cctv_images"
        raw_arg = raw_dir if raw_dir.exists() else None
        with tempfile.TemporaryDirectory() as tmp:
            out1 = Path(tmp) / "run1"
            out2 = Path(tmp) / "run2"
            out_fb = Path(tmp) / "fallback"
            p1 = forensic_charts.generate_all(self.FORENSICS_DIR, out1, raw_arg)
            forensic_charts.generate_all(self.FORENSICS_DIR, out2, raw_arg)
            p_fb = forensic_charts.generate_all(self.FORENSICS_DIR, out_fb, None)

            self.assertEqual(len(p1), 5)
            for gen1 in p1:
                gen2 = out2 / gen1.name
                self.assertEqual(gen1.read_bytes(), gen2.read_bytes(), f"Non-deterministic SVG: {gen1.name}")
                repo_svg = self.FIG_DIR / gen1.name
                self.assertTrue(repo_svg.is_file(), f"Missing repo SVG: {repo_svg}")
                self.assertEqual(gen1.read_bytes(), repo_svg.read_bytes(), f"Repo SVG out of sync: {gen1.name}")
                self._check_svg_xml_and_text_layout(gen1)

            for fb_svg in p_fb:
                self._check_svg_xml_and_text_layout(fb_svg)

    @unittest.skipUnless((ROOT / "reports" / "figures" / "forensics" / "05_downstream_impact_funnel.svg").exists(), "Chart 5 missing")
    def test_chart5_does_not_double_count_gst_bars_or_overstate_non_placeholder_cams(self) -> None:
        # BUG REPRO (forensic_charts.py:1051, 1077):
        # 1) cam 432 has 16 GStreamer-bar repeats and 0 non-placeholder frozen repeats,
        #    so the 553 non-placeholder repeats span 20 cameras, NOT 21.
        # 2) Patched inventory.py excludes gst_bars (placeholder=True) from frozen flags,
        #    so inventory.py detects 553 frozen frames + 33 gst_bars, NOT 584 + 33.
        with (self.FORENSICS_DIR / "frozen_streaks.csv").open(encoding="utf-8") as f:
            non_gst_cams = {r["camera_id"] for r in csv.DictReader(f) if r["is_gst_bars"] == "False"}
        self.assertEqual(len(non_gst_cams), 20)

        svg5_txt = (self.FIG_DIR / "05_downstream_impact_funnel.svg").read_text(encoding="utf-8")
        self.assertNotIn(
            "-553 non-placeholder frozen repeats (21 cams)",
            svg5_txt,
            "Chart 5 Stage 5 misstates 21 cams for the 553 non-placeholder repeats (true count is 20)",
        )
        self.assertNotIn(
            ">584</text>",
            svg5_txt,
            "Chart 5 'Legacy vs. Patched inventory.py' panel attributes 584 frozen repeats alongside 33 gst_bars (double-counting 31 GSt repeats)",
        )


class ReportVsCsvNumericCrossCheckTests(unittest.TestCase):
    REPORT_MD = ROOT / "reports" / "data_quality_forensics.md"
    FORENSICS_DIR = ROOT / "reports" / "forensics"

    @unittest.skipUnless((ROOT / "reports" / "data_quality_forensics.md").exists(), "Report missing")
    def test_report_numbers_match_forensics_json_and_csvs(self) -> None:
        report = self.REPORT_MD.read_text(encoding="utf-8")
        summary = json.loads((self.FORENSICS_DIR / "corpus_summary.json").read_text(encoding="utf-8"))
        attr = json.loads((self.FORENSICS_DIR / "external_attribution.json").read_text(encoding="utf-8"))

        with (self.FORENSICS_DIR / "camera_forensics.csv").open(encoding="utf-8") as f:
            cams = list(csv.DictReader(f))
        with (self.FORENSICS_DIR / "frozen_streaks.csv").open(encoding="utf-8") as f:
            streaks = list(csv.DictReader(f))
        with (self.FORENSICS_DIR / "gap_events.csv").open(encoding="utf-8") as f:
            gaps = list(csv.DictReader(f))
        with (self.FORENSICS_DIR / "hourly_coverage.csv").open(encoding="utf-8") as f:
            hourly = list(csv.DictReader(f))
        with (self.FORENSICS_DIR / "no_eoi_events.csv").open(encoding="utf-8") as f:
            no_eoi = list(csv.DictReader(f))
        with (self.FORENSICS_DIR / "osd_evidence.csv").open(encoding="utf-8") as f:
            osd = list(csv.DictReader(f))

        # Core corpus metrics
        for token in (
            f"`{summary['cameras']}`",
            f"`{summary['total_files']:,}`",
            f"`{summary['valid_jpegs']:,}`",
            f"`{summary['non_frozen_live_jpegs']:,}`",
            f"`{summary['white_pngs']}`",
            f"`{summary['truncated_jpegs']}`",
            f"`{summary['no_eoi_total']}`",
            f"`{summary['gst_color_bars']}`",
            f"`{summary['strict_frozen']}`",
            f"`{summary['bridged_frozen']}`",
            f"`{summary['phase_a_frames']:,}`",
            f"`{summary['phase_b_frames']:,}`",
            f"`{summary['batch_split']['same_day_switches']}`",
            f"`{summary['batch_split']['overnight_switches']}`",
            f"`{summary['gaps_summary']['same_day_12_20m']}`",
            f"`{summary['gaps_summary']['same_day_gt20m_non_thu27_am']}`",
            f"`{summary['daily_window']['between_2100_2101']}`",
        ):
            self.assertIn(token, report, f"Report missing verified token {token}")

        # Hourly completeness numbers
        active = [r for r in hourly if 6 <= int(r["hour"]) <= 20]
        complete = [r for r in active if int(r["valid_live_jpegs"]) >= 3]
        dropped = [r for r in active if int(r["valid_live_jpegs"]) < 3]
        complete_frames = sum(int(r["valid_live_jpegs"]) for r in complete)
        self.assertIn(f"`{len(complete):,} / {len(active):,}`", report)
        self.assertIn(f"`{complete_frames:,}`", report)
        self.assertIn(f"`{len(dropped)}` incomplete `06–20h` cells", report)

        # Daily white-PNG counts in Section 2.2
        wp_by_day = Counter(r["date"] for r in no_eoi if r["file_type"] == "white_png")
        for day, label in [
            ("2026-08-25", "Tue 25"),
            ("2026-08-26", "Wed 26"),
            ("2026-08-27", "Thu 27"),
            ("2026-08-28", "Fri 28"),
            ("2026-08-29", "Sat 29"),
            ("2026-08-30", "Sun 30"),
            ("2026-08-31", "Mon 31"),
        ]:
            self.assertIn(f"`{wp_by_day[day]}` ({label})", report)

        # Min/max files per camera & phase switches
        min_files, min_cam = min((int(c["total_files"]), c["camera_id"]) for c in cams)
        max_files, max_cam = max((int(c["total_files"]), c["camera_id"]) for c in cams)
        self.assertIn(f"`{min_files}` (`cam {min_cam}`) to `{max_files}` (`cam {max_cam}`)", report)
        self.assertIn(f"`{len(streaks)}` frozen streaks", report)
        self.assertIn(f"`{len(osd)}` visually verified samples", report)

        # All 16 >20m gaps referenced by camera & duration
        gt20_gaps = [g for g in gaps if g["gap_class"] == ">20m"]
        self.assertEqual(len(gt20_gaps), 16)
        for g in gt20_gaps:
            self.assertIn(g["camera_id"], report)

        # All Section 4.2 contract event_ids & verdicts match external_attribution.json
        for eid, ev in attr["events"].items():
            if eid in ("20260825_26_938_939_freeze", "other_20min_drops"):
                continue
            self.assertIn(f"`{eid}`", report)
            self.assertIn(f"`{ev['attribution_verdict']}`", report)

    @unittest.skipUnless((ROOT / "reports" / "data_quality_forensics.md").exists(), "Report missing")
    def test_report_section5_inventory_frozen_claim_matches_inventory_logic(self) -> None:
        # BUG REPRO (reports/data_quality_forensics.md:154):
        # Section 5 item 1 states `inventory.py — HTML Tail Defeated Frozen Detection (0 -> 584)`,
        # but `inventory.compute_frozen_flags()` excludes `gst_bars` placeholders and yields 553.
        report = self.REPORT_MD.read_text(encoding="utf-8")
        self.assertNotIn(
            "HTML Tail Defeated Frozen Detection (`0` -> `584`)",
            report,
            "Section 5.1 attributes forensics.py's 584 (incl. 31 GSt repeats) to inventory.py instead of 553",
        )


if __name__ == "__main__":
    unittest.main()
