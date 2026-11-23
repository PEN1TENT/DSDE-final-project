"""Pure-stdlib verification suite for Bangkok geospatial, intersection, and storytelling insights."""

from __future__ import annotations

import csv
import json
import math
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cctv.external_enrich import _parse_traffy_categories, _snap_grid  # noqa: E402
from cctv.spatial_charts import generate_all  # noqa: E402
from cctv.spatial_insights import run_analysis  # noqa: E402
from cctv.spatio_temporal import point_in_ring  # noqa: E402

INSIGHTS_DIR = ROOT / "reports" / "insights"
FIG_DIR = ROOT / "reports" / "figures" / "spatial_insights"
DASHBOARD_HTML = ROOT / "reports" / "bangkok_spatial_dashboard.html"
REPORT_MD = ROOT / "reports" / "spatial_storytelling_insights.md"

EXPECTED_SVGS = [
    "01_two_bangkoks_hotspots_map.svg",
    "02_intersection_compound_friction.svg",
    "03_weekend_immunity_and_modal_shift.svg",
    "04_multivariate_drivers_and_ai_blindspots.svg",
    "05_camera_health_paradox_and_next10.svg",
    "06_executive_infographic.svg",
]


class TestSpatialInsightsArtifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.summary = json.loads((INSIGHTS_DIR / "insights_summary.json").read_text(encoding="utf-8"))
        cls.clusters = json.loads(
            (INSIGHTS_DIR / "spatial_clusters_and_blindspots.json").read_text(encoding="utf-8")
        )
        with (INSIGHTS_DIR / "camera_spatial_profile.csv").open(encoding="utf-8", newline="") as f:
            cls.cams = list(csv.DictReader(f))
        with (INSIGHTS_DIR / "intersection_analysis.csv").open(encoding="utf-8", newline="") as f:
            cls.inter = list(csv.DictReader(f))
        with (INSIGHTS_DIR / "landmark_dynamics.csv").open(encoding="utf-8", newline="") as f:
            cls.landmarks = list(csv.DictReader(f))

    def test_camera_spatial_profile_completeness(self) -> None:
        self.assertEqual(len(self.cams), 100)
        ids = {int(r["camera_id"]) for r in self.cams}
        self.assertEqual(len(ids), 100)
        for r in self.cams:
            lat, lon = float(r["latitude"]), float(r["longitude"])
            self.assertTrue(13.6 <= lat <= 13.95, f"bad lat {lat}")
            self.assertTrue(100.3 <= lon <= 100.85, f"bad lon {lon}")
            self.assertTrue(r["road_class"])
            self.assertIn(
                r["junction_type"],
                {"mid-block", "3-way / junction", "4-way crossroad", "5+-way mega"},
            )
            self.assertIn(r["busyness_tercile"], {"busy", "medium", "quiet"})
            self.assertTrue(math.isfinite(float(r["band_w_mean"])))
            self.assertTrue(math.isfinite(float(r["gi_star_z"])))
            self.assertTrue(math.isfinite(float(r["upgrade_priority_score"])))

    def test_golden_and_forensic_reconciliation(self) -> None:
        g = self.summary["golden_reconciliation"]
        self.assertEqual(g["sampled_paths"], 1000)
        self.assertEqual(g["stratified_usable"], 891)
        self.assertEqual(g["model_zero_usable"], 98)
        self.assertEqual(g["usable_total"], 989)
        self.assertEqual(g["unusable_frames"], 11)
        self.assertEqual(g["double_counted_usable"], 199)

        c = self.summary["corpus"]
        self.assertEqual(c["cameras"], 100)
        self.assertEqual(c["raw_files"], 61319)
        self.assertEqual(c["clean_live_jpegs"], 60227)
        self.assertEqual(c["clean_complete_snapshots"], 59774)
        self.assertEqual(c["bridged_frozen_total"], 584)
        self.assertEqual(c["white_pngs_total"], 504)
        self.assertEqual(sum(int(r["bridged_frozen"]) for r in self.cams), 584)
        self.assertEqual(sum(int(r["white_pngs"]) for r in self.cams), 504)

    def test_spatial_and_statistical_invariants(self) -> None:
        mor = self.summary["moran_i"]["traffic_band_w"]
        self.assertGreater(mor["morans_i"], 0.3)
        self.assertLess(mor["p_value"], 0.05)

        corridors = self.clusters["dbscan"]["corridors"]
        self.assertEqual(len(corridors), 4)

        iso = next(
            r for r in self.summary["compound_friction_2x2"] if r["segment"] == "Mid-block, No Mall/Rail"
        )
        self.assertEqual(iso["busy_pct"], 0.0)

        hot = next(
            r for r in self.summary["compound_friction_2x2"] if r["segment"] == "Intersection + Mall/Rail"
        )
        self.assertGreater(hot["mean_total"], iso["mean_total"])
        self.assertGreater(hot["busy_pct"], 35.0)

        self.assertGreater(self.summary["ols_base"]["r2"], 0.0)
        self.assertLess(self.summary["ols_base"]["r2"], 1.0)
        self.assertGreaterEqual(
            self.summary["ols_spatial_controlled"]["r2"], self.summary["ols_base"]["r2"]
        )
        self.assertAlmostEqual(
            self.summary["camera_health_paradox"]["intersection_share_of_frozen_pct"], 98.5, places=1
        )
        self.assertEqual(len(self.summary["top10_upgrade_priority"]), 10)

    def test_svg_charts_valid_and_in_bounds(self) -> None:
        for name in EXPECTED_SVGS:
            p = FIG_DIR / name
            self.assertTrue(p.exists(), f"Missing SVG {p}")
            self.assertGreater(p.stat().st_size, 5000, f"Too small: {p}")
            root = ET.fromstring(p.read_text(encoding="utf-8"))
            self.assertIn("viewBox", root.attrib)
            _, _, width, height = (float(v) for v in root.attrib["viewBox"].split())
            for t in root.findall(".//{http://www.w3.org/2000/svg}text"):
                tx = float(t.attrib.get("x", "0"))
                ty = float(t.attrib.get("y", "0"))
                self.assertTrue(0.0 <= tx <= width, f"{name} text x out of bounds: {tx}")
                self.assertTrue(0.0 <= ty <= height, f"{name} text y out of bounds: {ty}")

    def test_interactive_dashboard_html_valid(self) -> None:
        self.assertTrue(DASHBOARD_HTML.exists())
        self.assertGreater(DASHBOARD_HTML.stat().st_size, 40_000)
        text = DASHBOARD_HTML.read_text(encoding="utf-8")
        for tab_id in ("tab-story", "tab-pulse", "tab-map", "tab-intersections", "tab-modal", "tab-policy"):
            self.assertIn(f'id="{tab_id}"', text)
        m = re.search(r"const DASHBOARD_DATA = (.+?);\s*\nconst CAMS =", text, re.DOTALL)
        self.assertIsNotNone(m, "Could not extract DASHBOARD_DATA JSON")
        payload_raw = m.group(1)
        self.assertNotIn("</script>", payload_raw.lower())
        payload = json.loads(payload_raw.replace("<\\/", "</"))
        self.assertEqual(len(payload["cameras"]), 100)
        self.assertEqual(len(payload["summary"]["top10_upgrade_priority"]), 10)
        self.assertEqual(payload["pulse"]["meta"]["total_districts"], 50)
        self.assertEqual(payload["pulse"]["meta"]["covered_districts"], 19)
        self.assertEqual(payload["pulse"]["meta"]["live_stratified_frames"], 881)
        self.assertEqual(payload["pulse"]["meta"]["excluded_frozen_golden"], 10)

    def test_storytelling_report_links_all_svgs(self) -> None:
        self.assertTrue(REPORT_MD.exists())
        md = REPORT_MD.read_text(encoding="utf-8")
        for name in [*EXPECTED_SVGS, "07_bangkok_daily_pulse_by_district.svg"]:
            self.assertIn(name, md, f"Report missing SVG link: {name}")
        self.assertIn("bangkok_spatial_dashboard.html", md)

    def test_spatio_temporal_50_districts_and_chart7(self) -> None:
        geojson_path = ROOT / "data" / "raw" / "external" / "bangkok_districts.geojson"
        self.assertTrue(geojson_path.exists())
        geojson = json.loads(geojson_path.read_text(encoding="utf-8"))
        self.assertEqual(len(geojson["features"]), 50)

        with (INSIGHTS_DIR / "district_time_profile.csv").open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 50)
        covered = [r for r in rows if int(r["camera_count"]) > 0]
        self.assertEqual(len(covered), 19)
        self.assertEqual(sum(int(r["camera_count"]) for r in rows), 100)

        pulse = json.loads((INSIGHTS_DIR / "spatio_temporal_pulse.json").read_text(encoding="utf-8"))
        self.assertEqual(pulse["meta"]["live_stratified_frames"], 881)
        self.assertEqual(pulse["meta"]["excluded_frozen_golden"], 10)

        chart7 = FIG_DIR / "07_bangkok_daily_pulse_by_district.svg"
        self.assertTrue(chart7.exists())
        self.assertGreater(chart7.stat().st_size, 5000)
        root = ET.fromstring(chart7.read_text(encoding="utf-8"))
        self.assertIn("viewBox", root.attrib)
        _, _, width, height = (float(v) for v in root.attrib["viewBox"].split())
        for t in root.findall(".//{http://www.w3.org/2000/svg}text"):
            tx = float(t.attrib.get("x", "0"))
            ty = float(t.attrib.get("y", "0"))
            self.assertTrue(0.0 <= tx <= width, f"Chart 7 text x out of bounds: {tx}")
            self.assertTrue(0.0 <= ty <= height, f"Chart 7 text y out of bounds: {ty}")

        square = [[100.0, 13.0], [100.1, 13.0], [100.1, 13.1], [100.0, 13.1], [100.0, 13.0]]
        self.assertTrue(point_in_ring(100.05, 13.05, square))
        self.assertFalse(point_in_ring(100.2, 13.05, square))

    def test_external_enrich_helpers_and_tempdir_determinism(self) -> None:
        self.assertEqual(_parse_traffy_categories("{น้ำท่วม,ถนน}"), ["น้ำท่วม", "ถนน"])
        self.assertEqual(_parse_traffy_categories(["จราจร"]), ["จราจร"])
        self.assertEqual(_snap_grid(13.7465, 100.5347), (13.75, 100.55))

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_ins = tmp_path / "insights"
            out_fig = tmp_path / "figs"
            s2 = run_analysis(
                cameras_path=ROOT / "data/100_cameras/cctv_info.csv",
                sample_path=ROOT / "data/labels/sample.csv",
                export_path=ROOT / "data/labels/export.csv",
                osm_roads_path=ROOT / "data/raw/external/osm_roads.json",
                osm_pois_path=ROOT / "data/raw/external/osm_pois.json",
                daylight_path=ROOT / "data/raw/external/daylight.json",
                forensics_cam_path=ROOT / "reports/forensics/camera_forensics.csv",
                corpus_summary_path=ROOT / "reports/forensics/corpus_summary.json",
                external_dir=ROOT / "data/raw/external",
                out_dir=out_ins,
            )
            self.assertEqual(s2["moran_i"], self.summary["moran_i"])
            self.assertEqual(s2["ols_spatial_controlled"], self.summary["ols_spatial_controlled"])
            svgs = generate_all(out_ins, out_fig)
            self.assertEqual(len(svgs), 6)
            for p in svgs:
                self.assertEqual(
                    p.read_text(encoding="utf-8"),
                    (FIG_DIR / p.name).read_text(encoding="utf-8"),
                    f"SVG mismatch on regeneration: {p.name}",
                )


if __name__ == "__main__":
    unittest.main()
