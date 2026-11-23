from __future__ import annotations

import binascii
import csv
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cctv import forensics, inventory, rain  # noqa: E402


def _make_minimal_jpeg(width: int = 352, height: int = 288, payload: bytes = b"\x01\x02", with_exif: bool = False) -> bytes:
    """Build a syntactically valid JPEG byte stream (SOI + optional APP1 Exif + SOF0 + SOS + EOI)."""
    parts = [b"\xff\xd8"]
    if with_exif:
        exif_body = b"Exif\x00\x00MM\x00*\x00\x00\x00\x08\x00\x00"
        parts.append(b"\xff\xe1" + struct.pack(">H", len(exif_body) + 2) + exif_body)
    sof0_body = struct.pack(">BHHB", 8, height, width, 3) + b"\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    parts.append(b"\xff\xc0" + struct.pack(">H", len(sof0_body) + 2) + sof0_body)
    parts.append(b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00")
    parts.append(payload)
    parts.append(b"\xff\xd9")
    return b"".join(parts)


def _png_chunk(ctype: bytes, data: bytes) -> bytes:
    body = ctype + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)


def _make_png(width: int = 4, height: int = 4, rgb_byte: int = 255) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw_rows = b"".join(b"\x00" + bytes([rgb_byte]) * (width * 3) for _ in range(height))
    idat = zlib.compress(raw_rows)
    return forensics.PNG_SIG + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


def _html_tail(cam_id: str, epoch_ms: int) -> bytes:
    return (
        f'\r\n\r\n<!DOCTYPE html><html><form method="post" '
        f'action="./show.aspx?image={cam_id}&amp;time={epoch_ms}" id="form1"></form></html>'
    ).encode("ascii")


class ForensicsHelpersTests(unittest.TestCase):
    def test_parse_filename(self) -> None:
        parsed = forensics.parse_filename("150_สะพานลอย_รายละเอียด_20260825_061023.jpg")
        self.assertIsNotNone(parsed)
        cam_id, dt = parsed  # type: ignore[misc]
        self.assertEqual(cam_id, "150")
        self.assertEqual(dt.strftime("%Y-%m-%d %H:%M:%S"), "2026-08-25 06:10:23")

        self.assertIsNone(forensics.parse_filename("150_bad_20261345_061023.jpg"))
        self.assertIsNone(forensics.parse_filename("random.png"))

    def test_strip_html_tail_and_inspect_jpeg_exif_and_dimensions(self) -> None:
        jpg = _make_minimal_jpeg(348, 261, payload=b"\xaa\xbb\xcc", with_exif=False)
        f1 = jpg + _html_tail("395", 1787613003000)
        f2 = jpg + _html_tail("395", 1787613603000)

        i1 = forensics.inspect_bytes(f1)
        i2 = forensics.inspect_bytes(f2)
        self.assertEqual(i1.container, "jpeg")
        self.assertTrue(i1.has_html_tail)
        self.assertEqual(i1.tail_epoch_ms, 1787613003000)
        self.assertEqual((i1.width, i1.height), (348, 261))
        self.assertFalse(i1.has_exif)
        self.assertEqual(i1.core_md5, i2.core_md5)
        self.assertNotEqual(i1.full_md5, i2.full_md5)

        exif_jpg = _make_minimal_jpeg(352, 288, with_exif=True) + _html_tail("10", 1787613003000)
        i_exif = forensics.inspect_bytes(exif_jpg)
        self.assertTrue(i_exif.has_exif)
        self.assertEqual((i_exif.width, i_exif.height), (352, 288))

    def test_inspect_white_png_nonwhite_png_and_truncated_jpeg(self) -> None:
        white_png = _make_png(8, 6, rgb_byte=255) + _html_tail("100", 1787613003000)
        iw = forensics.inspect_bytes(white_png)
        self.assertEqual(iw.container, "png")
        self.assertTrue(iw.white_png)
        self.assertEqual((iw.width, iw.height), (8, 6))

        gray_png = _make_png(8, 6, rgb_byte=120) + _html_tail("100", 1787613003000)
        ig = forensics.inspect_bytes(gray_png)
        self.assertEqual(ig.container, "png")
        self.assertFalse(ig.white_png)

        trunc = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + _html_tail("595", 1787613003000)
        it = forensics.inspect_bytes(trunc)
        self.assertEqual(it.container, "truncated_jpeg")
        self.assertTrue(it.truncated_jpeg)
        self.assertTrue(it.has_html_tail)


class SyntheticCorpusForensicsTests(unittest.TestCase):
    def test_run_forensics_on_synthetic_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            info_csv = root / "cctv_info.csv"
            img_dir = root / "cctv_images"
            out_dir = root / "out"

            # 3 cameras: 150 (full_morning_pseudo on Thu 27), 100 (partial_white_png), 200 (zero_morning)
            rows = [
                ("150", "A", "d", "Cam 150", "d", "13.78", "100.53", "10.102.129.123", "8"),
                ("100", "B", "d", "Cam 100", "d", "13.75", "100.50", "10.128.128.10", "6"),
                ("200", "C", "d", "Cam 200", "d", "13.76", "100.51", "10.128.128.11", "4"),
            ]
            with info_csv.open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["camera_id", "location", "location_detail", "location_en", "location_detail_en", "latitude", "longitude", "ip_address", "image_count"])
                w.writerows(rows)

            for cid in ("150", "100", "200"):
                (img_dir / cid).mkdir(parents=True)

            live_a = _make_minimal_jpeg(352, 288, b"frameA")
            live_b = _make_minimal_jpeg(352, 288, b"frameB")
            live_c = _make_minimal_jpeg(352, 288, b"frameC")
            live_d = _make_minimal_jpeg(352, 288, b"frameD")
            white_png = _make_png(400, 266, 255)
            trunc_jpg = b"\xff\xd8\xff\xe0\x00\x10JFIF"

            def write_frame(cid: str, ts_str: str, body: bytes, epoch_ms: int) -> None:
                fn = f"{cid}_loc_det_{ts_str}.jpg"
                (img_dir / cid / fn).write_bytes(body + _html_tail(cid, epoch_ms))

            # Cam 150: frozen streak bridged by a white PNG on Thu 27 AM + phase switch A->B + recovery 2026-08-27 09:01
            write_frame("150", "20260826_194104", live_a, 1787748067000)
            write_frame("150", "20260827_060603", live_a, 1787785566000)  # B, strict frozen
            write_frame("150", "20260827_072606", white_png, 1787790369000)  # B, white png
            write_frame("150", "20260827_083603", live_a, 1787794566000)  # B, bridged frozen
            write_frame("150", "20260827_090100", live_b, 1787796063000)  # A (phase switch)
            write_frame("150", "20260827_091100", live_c, 1787796663000)  # A
            write_frame("150", "20260827_092600", live_d, 1787797563000)  # B (15m gap -> 12-20m + switch)
            write_frame("150", "20260827_095600", live_b, 1787799363000)  # B (30m gap -> >20m)

            # Cam 100: partial_white_png on Thu 27 AM + 1 truncated JPEG + gap >20m
            write_frame("100", "20260826_153042", trunc_jpg, 1787733045000)
            write_frame("100", "20260826_154043", trunc_jpg, 1787733646000)
            write_frame("100", "20260827_072500", white_png, 1787790303000)
            write_frame("100", "20260827_085500", live_b, 1787795703000)
            write_frame("100", "20260827_090500", live_c, 1787796303000)
            write_frame("100", "20260827_093500", live_d, 1787798103000)

            # Cam 200: zero_morning on Thu 27 AM + normal frames
            write_frame("200", "20260827_085010", live_a, 1787795413000)
            write_frame("200", "20260827_090010", live_b, 1787796013000)
            write_frame("200", "20260827_091010", live_c, 1787796613000)
            write_frame("200", "20260827_092010", live_d, 1787797213000)

            summary = forensics.run_forensics(info_csv, img_dir, out_dir)
            self.assertEqual(summary["cameras"], 3)
            self.assertEqual(summary["total_files"], 18)
            self.assertEqual(summary["white_pngs"], 2)
            self.assertEqual(summary["truncated_jpegs"], 2)
            self.assertEqual(summary["strict_frozen"], 1)
            self.assertEqual(summary["bridged_frozen"], 2)
            self.assertEqual(summary["thu_27_am_split"]["full_morning_pseudo"], 1)
            self.assertEqual(summary["thu_27_am_split"]["partial_white_png"], 1)
            self.assertEqual(summary["thu_27_am_split"]["zero_morning"], 1)
            self.assertEqual(summary["thu_27_am_split"]["live_traffic_frames"], 0)
            self.assertEqual(summary["gaps_summary"]["same_day_gt20m_non_thu27_am"], 2)
            self.assertEqual(summary["gaps_summary"]["same_day_12_20m"], 1)

            with (out_dir / "frozen_streaks.csv").open(encoding="utf-8") as f:
                streaks = list(csv.DictReader(f))
            self.assertEqual(len(streaks), 1)
            self.assertEqual(streaks[0]["camera_id"], "150")
            self.assertEqual(streaks[0]["repeat_count"], "2")
            self.assertEqual(streaks[0]["bridged_by_png"], "True")

            for name in (
                "corpus_summary.json",
                "camera_forensics.csv",
                "gap_events.csv",
                "frozen_streaks.csv",
                "subnet_summary.csv",
                "hourly_coverage.csv",
                "no_eoi_events.csv",
                "osd_evidence.csv",
            ):
                self.assertTrue((out_dir / name).exists(), f"Missing {name}")


class InventoryQCTests(unittest.TestCase):
    def test_strip_html_tail_and_flags(self) -> None:
        jpg = _make_minimal_jpeg(352, 288, b"cam1")
        ins_a = inventory.inspect_image_bytes(jpg + _html_tail("1", 1787613003000))
        ins_b = inventory.inspect_image_bytes(jpg + _html_tail("1", 1787613603000))
        self.assertEqual(ins_a["core_md5"], ins_b["core_md5"])
        self.assertNotEqual(ins_a["md5"], ins_b["md5"])
        self.assertTrue(ins_a["has_html_tail"])
        self.assertFalse(ins_a["placeholder"])

        white = inventory.inspect_image_bytes(_make_png(10, 10, 255) + _html_tail("1", 1787613003000))
        self.assertTrue(white["white_png"])
        self.assertTrue(white["placeholder"])

        trunc = inventory.inspect_image_bytes(b"\xff\xd8\xff\xe0abc" + _html_tail("595", 1787613003000))
        self.assertTrue(trunc["truncated_jpeg"])
        self.assertTrue(trunc["placeholder"])

    def test_compute_frozen_flags_bridged_vs_strict_and_excludes_placeholders(self) -> None:
        live1 = inventory.inspect_image_bytes(_make_minimal_jpeg(payload=b"v1") + _html_tail("1", 1000))
        white = inventory.inspect_image_bytes(_make_png(4, 4, 255) + _html_tail("1", 2000))
        live1_again = inventory.inspect_image_bytes(_make_minimal_jpeg(payload=b"v1") + _html_tail("1", 3000))
        live1_third = inventory.inspect_image_bytes(_make_minimal_jpeg(payload=b"v1") + _html_tail("1", 4000))
        gst = {"core_md5": inventory.GST_BARS_MD5, "white_png": False, "truncated_jpeg": False, "gst_bars": True, "placeholder": True}
        gst2 = dict(gst)

        seq = [live1, white, live1_again, live1_third, gst, gst2]
        bridged = inventory.compute_frozen_flags(seq, bridge_png=True)
        self.assertEqual([r["frozen"] for r in bridged], [False, False, True, True, False, False])

        strict = inventory.compute_frozen_flags(seq, bridge_png=False)
        self.assertEqual([r["frozen"] for r in strict], [False, False, False, True, False, False])

    @unittest.skipIf(inventory.pd is None or inventory.cv2 is None, "pandas/cv2 not installed")
    def test_build_inventory_integration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            cam_dir = raw / "150"
            cam_dir.mkdir(parents=True)
            img = _make_minimal_jpeg(32, 24, b"x")
            (cam_dir / "150_a_b_20260825_060000.jpg").write_bytes(img + _html_tail("150", 1787612403000))
            (cam_dir / "150_a_b_20260825_061000.jpg").write_bytes(img + _html_tail("150", 1787613003000))
            df = inventory.build_inventory(raw)
            self.assertEqual(len(df), 2)
            self.assertEqual(int(df["frozen"].sum()), 1)


class RainCompletenessTests(unittest.TestCase):
    def test_filter_complete_hour_records_drops_single_frame_outage_slot(self) -> None:
        # Camera 10 has 3 frames at hour 7 on Tue 25 Aug, and only 1 frame at hour 7 on Thu 27 Aug.
        rows = [
            {"camera_id": 10, "date": "2026-08-25", "hour": 7, "val": 10},
            {"camera_id": 10, "date": "2026-08-25", "hour": 7, "val": 12},
            {"camera_id": 10, "date": "2026-08-25", "hour": 7, "val": 11},
            {"camera_id": 10, "date": "2026-08-27", "hour": 7, "val": 999},
            {"camera_id": 10, "date": "2026-08-27", "hour": 8, "val": 500},
            {"camera_id": 10, "date": "2026-08-27", "hour": 8, "val": 501},
        ]
        filtered = rain.filter_complete_hour_records(rows, min_frames=3)
        self.assertEqual(len(filtered), 3)
        self.assertTrue(all(r["date"] == "2026-08-25" for r in filtered))

    @unittest.skipIf(rain.pd is None or rain.np is None, "pandas/numpy not installed")
    def test_add_excess_drops_incomplete_camera_date_hour_before_baseline(self) -> None:
        import datetime as dt
        df = rain.pd.DataFrame([
            {"path": "a1", "camera_id": 10, "date": dt.date(2026, 8, 25), "hour": 7, "daytype": "weekday",
             "n_vehicles": 10, "covered_fraction": 0.1, "n_calibrated": 10.0},
            {"path": "a2", "camera_id": 10, "date": dt.date(2026, 8, 25), "hour": 7, "daytype": "weekday",
             "n_vehicles": 10, "covered_fraction": 0.1, "n_calibrated": 10.0},
            {"path": "a3", "camera_id": 10, "date": dt.date(2026, 8, 25), "hour": 7, "daytype": "weekday",
             "n_vehicles": 10, "covered_fraction": 0.1, "n_calibrated": 10.0},
            # Incomplete Thu 27 Aug 07h slot (1 frame with extreme outlier) must NOT enter weekday baseline
            {"path": "thu1", "camera_id": 10, "date": dt.date(2026, 8, 27), "hour": 7, "daytype": "weekday",
             "n_vehicles": 999, "covered_fraction": 0.9, "n_calibrated": 999.0},
        ])
        out = rain.add_excess(df)
        self.assertEqual(len(out), 3)
        self.assertNotIn("thu1", set(out["path"]))
        self.assertTrue((out["excess_vehicles"].abs() < 1e-12).all())


class GeneratedForensicsArtifactsTests(unittest.TestCase):
    FORENSICS_DIR = ROOT / "reports" / "forensics"

    @unittest.skipUnless((ROOT / "reports" / "forensics" / "corpus_summary.json").exists(), "reports/forensics not generated")
    def test_generated_artifacts_internal_consistency(self) -> None:
        summary = json.loads((self.FORENSICS_DIR / "corpus_summary.json").read_text(encoding="utf-8"))

        with (self.FORENSICS_DIR / "camera_forensics.csv").open(encoding="utf-8") as f:
            cams = list(csv.DictReader(f))
        with (self.FORENSICS_DIR / "frozen_streaks.csv").open(encoding="utf-8") as f:
            streaks = list(csv.DictReader(f))
        with (self.FORENSICS_DIR / "gap_events.csv").open(encoding="utf-8") as f:
            gaps = list(csv.DictReader(f))
        with (self.FORENSICS_DIR / "subnet_summary.csv").open(encoding="utf-8") as f:
            subnets = list(csv.DictReader(f))
        with (self.FORENSICS_DIR / "hourly_coverage.csv").open(encoding="utf-8") as f:
            hourly = list(csv.DictReader(f))
        with (self.FORENSICS_DIR / "no_eoi_events.csv").open(encoding="utf-8") as f:
            no_eoi = list(csv.DictReader(f))
        with (self.FORENSICS_DIR / "osd_evidence.csv").open(encoding="utf-8") as f:
            osd = list(csv.DictReader(f))

        self.assertEqual(len(cams), summary["cameras"])
        self.assertEqual(sum(int(r["total_files"]) for r in cams), summary["total_files"])
        self.assertEqual(sum(int(r["valid_jpegs"]) for r in cams), summary["valid_jpegs"])
        self.assertEqual(sum(int(r["white_pngs"]) for r in cams), summary["white_pngs"])
        self.assertEqual(sum(int(r["truncated_jpegs"]) for r in cams), summary["truncated_jpegs"])
        self.assertEqual(sum(int(r["gst_bars"]) for r in cams), summary["gst_color_bars"])
        self.assertEqual(sum(int(r["strict_frozen"]) for r in cams), summary["strict_frozen"])
        self.assertEqual(sum(int(r["bridged_frozen"]) for r in cams), summary["bridged_frozen"])

        self.assertEqual(sum(int(r["repeat_count"]) for r in streaks), summary["bridged_frozen"])
        self.assertEqual(len(no_eoi), summary["no_eoi_total"])
        self.assertEqual(sum(int(r["camera_count"]) for r in subnets), summary["cameras"])
        self.assertEqual(sum(int(r["total_files"]) for r in subnets), summary["total_files"])
        self.assertEqual(sum(int(r["gaps_gt20m"]) for r in subnets), summary["gaps_summary"]["same_day_gt20m_non_thu27_am"])

        self.assertEqual(sum(int(r["total_files"]) for r in hourly), summary["total_files"])
        self.assertEqual(sum(int(r["frozen_frames"]) for r in hourly), summary["bridged_frozen"])

        self.assertEqual(sum(1 for g in gaps if g["gap_class"] == ">20m"), summary["gaps_summary"]["same_day_gt20m_non_thu27_am"])
        self.assertEqual(sum(1 for g in gaps if g["gap_class"] == "12-20m"), summary["gaps_summary"]["same_day_12_20m"])
        self.assertEqual(sum(1 for g in gaps if g["gap_class"] == "thu27_am"), summary["gaps_summary"]["thu27_am_events"])

        self.assertEqual(len(osd), len(forensics.VERIFIED_OSD_SAMPLES))
        self.assertEqual(len(osd), 12)
        v26 = {row["camera_id"] for row in osd if row["verified_year"] == "2026"}
        self.assertIn("194", v26)
        self.assertGreaterEqual(len(v26), 7)
        for row in osd:
            self.assertEqual(row["has_exif"], "False")
            if row["verified_year"]:
                self.assertEqual(row["verified_year"], "2026")


if __name__ == "__main__":
    unittest.main()
