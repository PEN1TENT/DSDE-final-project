"""Pure-stdlib Interactive Web Dashboard & Storytelling Studio Generator.

Reads ``reports/insights/*`` and ``reports/figures/spatial_insights/06_executive_infographic.svg``
and emits a single, self-contained, 100%-offline interactive HTML dashboard at
``reports/bangkok_spatial_dashboard.html``.

Usage:
    python -m cctv.dashboard_html --in-dir reports/insights --fig-dir reports/figures/spatial_insights --out reports/bangkok_spatial_dashboard.html
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any


def _to_num(v: Any) -> Any:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if s in ("True", "False"):
        return s == "True"
    try:
        if "." in s or "e" in s.lower():
            return float(s)
        return int(s)
    except ValueError:
        return s


def _load_dashboard_payload(in_dir: Path) -> dict[str, Any]:
    with (in_dir / "camera_spatial_profile.csv").open(encoding="utf-8", newline="") as f:
        cameras = [{k: _to_num(v) for k, v in row.items()} for row in csv.DictReader(f)]
    clusters = json.loads((in_dir / "spatial_clusters_and_blindspots.json").read_text(encoding="utf-8"))
    summary = json.loads((in_dir / "insights_summary.json").read_text(encoding="utf-8"))
    pulse_path = in_dir / "spatio_temporal_pulse.json"
    pulse = json.loads(pulse_path.read_text(encoding="utf-8")) if pulse_path.exists() else None
    if pulse:
        by_cid = {int(c["camera_id"]): c for c in pulse.get("cameras_pulse", [])}
        for cam in cameras:
            pc = by_cid.get(int(cam["camera_id"]), {})
            cam["district_th"] = pc.get("district_th", "")
            cam["district_en"] = pc.get("district_en", "")
            cam["archetype"] = pc.get("archetype", "")
            cam["peak_band"] = pc.get("peak_band", "")
    return {
        "cameras": cameras,
        "clusters": clusters,
        "summary": summary,
        "pulse": pulse,
    }


def _safe_json_for_html(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False)
    return raw.replace("</", "<\\/")


def _load_inline_infographic(fig_dir: Path) -> str:
    p = fig_dir / "06_executive_infographic.svg"
    if not p.exists():
        return '<div class="muted">Executive infographic SVG not found.</div>'
    txt = p.read_text(encoding="utf-8")
    txt = re.sub(r"<\?xml[^>]*\?>\s*", "", txt)
    txt = txt.replace("<svg ", '<svg style="width:100%;height:auto;border-radius:12px;display:block;" ', 1)
    return txt


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Bangkok CCTV · Geospatial & Urban Mobility Studio</title>
<style>
  :root {
    --bg: #0b1120;
    --bg2: #111827;
    --card: #172033;
    --card-hover: #1e293b;
    --border: #2b3952;
    --text: #f8fafc;
    --text2: #cbd5e1;
    --muted: #94a3b8;
    --accent: #f59e0b;
    --blue: #3b82f6;
    --coral: #f43f5e;
    --teal: #14b8a6;
    --emerald: #10b981;
    --purple: #a855f7;
    --map-bg: #080d19;
  }
  [data-theme="light"] {
    --bg: #faf9f5;
    --bg2: #f3f1ea;
    --card: #ffffff;
    --card-hover: #f8fafc;
    --border: #e2dfd7;
    --text: #0f172a;
    --text2: #334155;
    --muted: #64748b;
    --accent: #d97706;
    --blue: #2563eb;
    --coral: #e11d48;
    --teal: #0d9488;
    --emerald: #059669;
    --purple: #7c3aed;
    --map-bg: #f1f5f9;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', 'Noto Sans Thai', Tahoma, system-ui, sans-serif;
    line-height: 1.45;
  }
  header {
    background: var(--bg2);
    border-bottom: 1px solid var(--border);
    padding: 16px 28px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    position: sticky;
    top: 0;
    z-index: 20;
  }
  .brand h1 { margin: 0; font-size: 20px; font-weight: 800; letter-spacing: -0.02em; }
  .brand .kicker { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent); font-weight: 700; }
  .brand .sub { font-size: 12.5px; color: var(--muted); margin-top: 2px; }
  .controls-top { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .btn {
    background: var(--card);
    color: var(--text);
    border: 1px solid var(--border);
    padding: 7px 13px;
    border-radius: 8px;
    font-size: 12.5px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s ease;
  }
  .btn:hover { background: var(--card-hover); border-color: var(--accent); }
  .btn.primary { background: var(--blue); color: #fff; border-color: var(--blue); }
  .tabs {
    display: flex;
    gap: 6px;
    padding: 10px 28px 0;
    background: var(--bg2);
    border-bottom: 1px solid var(--border);
    overflow-x: auto;
  }
  .tab {
    background: transparent;
    color: var(--muted);
    border: none;
    border-bottom: 3px solid transparent;
    padding: 10px 16px;
    font-size: 13.5px;
    font-weight: 700;
    cursor: pointer;
    white-space: nowrap;
  }
  .tab:hover { color: var(--text); }
  .tab.active { color: var(--accent); border-bottom-color: var(--accent); }
  main { max-width: 1460px; margin: 0 auto; padding: 22px 28px 48px; }
  .panel { display: none; }
  .panel.active { display: block; }
  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-bottom: 22px; }
  .kpi {
    background: var(--card);
    border: 1px solid var(--border);
    border-top: 4px solid var(--accent);
    border-radius: 12px;
    padding: 15px 18px;
  }
  .kpi .val { font-size: 24px; font-weight: 800; letter-spacing: -0.02em; }
  .kpi .lbl { font-size: 13px; font-weight: 700; margin-top: 4px; }
  .kpi .sub { font-size: 11.5px; color: var(--muted); margin-top: 3px; }
  .grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(460px, 1fr)); gap: 18px; margin-bottom: 20px; }
  .grid-3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; margin-bottom: 20px; }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 20px;
  }
  .card h2 { margin: 0 0 6px; font-size: 16px; font-weight: 800; }
  .card h3 { margin: 0 0 8px; font-size: 14px; font-weight: 700; }
  .muted { color: var(--muted); font-size: 12.5px; }
  .story-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-left: 4px solid var(--blue);
    border-radius: 12px;
    padding: 16px 18px;
    cursor: pointer;
    transition: transform 0.12s ease, border-color 0.12s ease;
  }
  .story-card:hover { transform: translateY(-2px); border-color: var(--accent); }
  .story-card .tag { font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.06em; color: var(--accent); }
  .story-card .headline { font-size: 15.5px; font-weight: 800; margin: 4px 0 6px; }
  .story-card .desc { font-size: 12.5px; color: var(--text2); }
  .pill {
    display: inline-block;
    padding: 3px 9px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    border: 1px solid var(--border);
    background: var(--bg2);
    color: var(--text2);
    margin: 2px 4px 2px 0;
  }
  .pill.ok { border-color: var(--emerald); color: var(--emerald); }
  .pill.warn { border-color: var(--accent); color: var(--accent); }
  .pill.bad { border-color: var(--coral); color: var(--coral); }

  /* Map Layout */
  .map-layout { display: grid; grid-template-columns: 1fr 390px; gap: 18px; align-items: start; }
  @media (max-width: 1080px) { .map-layout { grid-template-columns: 1fr; } }
  .map-toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 12px;
    align-items: center;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 14px;
  }
  select, input[type="text"] {
    background: var(--bg2);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 7px;
    padding: 6px 10px;
    font-size: 12.5px;
  }
  .map-box {
    background: var(--map-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
    position: relative;
  }
  #mapSvg { width: 100%; height: 610px; display: block; cursor: grab; user-select: none; }
  #mapSvg:active { cursor: grabbing; }
  .map-float {
    position: absolute;
    top: 12px;
    right: 12px;
    display: flex;
    gap: 6px;
  }
  .inspector {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px;
    max-height: 675px;
    overflow-y: auto;
  }
  .stat-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 12.5px; }
  .stat-row span:first-child { color: var(--muted); }
  .stat-row b { color: var(--text); }
  .bar-track { background: var(--bg2); border-radius: 6px; height: 14px; overflow: hidden; display: flex; }
  .bar-seg { height: 100%; }

  /* Tables */
  .tbl-wrap { overflow-x: auto; max-height: 480px; border: 1px solid var(--border); border-radius: 10px; }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  th {
    position: sticky; top: 0;
    background: var(--bg2);
    color: var(--muted);
    text-align: left;
    padding: 9px 10px;
    border-bottom: 1px solid var(--border);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    cursor: pointer;
  }
  td { padding: 8px 10px; border-bottom: 1px solid var(--border); color: var(--text2); }
  tr:hover td { background: var(--card-hover); cursor: pointer; }
  .num { font-variant-numeric: tabular-nums; text-align: right; }

  .chart-bar-row { display: grid; grid-template-columns: 185px 1fr 90px; gap: 10px; align-items: center; margin: 9px 0; font-size: 12.5px; }
  .chart-fill { height: 20px; border-radius: 5px; transition: width 0.25s ease; }
  .matrix-2x2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
  .mcell { border-radius: 10px; padding: 14px; border: 1.5px solid var(--border); background: var(--bg2); }
  .mcell .big { font-size: 26px; font-weight: 800; }
  .tooltip-float {
    position: fixed;
    pointer-events: none;
    background: rgba(15, 23, 42, 0.96);
    color: #f8fafc;
    border: 1px solid #475569;
    border-radius: 8px;
    padding: 8px 11px;
    font-size: 12px;
    z-index: 99;
    display: none;
    max-width: 300px;
  }
</style>
</head>
<body>
<header>
  <div class="brand">
    <div class="kicker">2110403 DSDE · BANGKOK URBAN MOBILITY & GEOSPATIAL STUDIO</div>
    <h1>Bangkok 100-Camera Traffic Anatomy & Spatial Storytelling</h1>
    <div class="sub" id="headerSub">100 BMA Cameras · 61,319 Raw Images (25–31 Aug 2026) · 989 Human-Verified Frames · 435 OSM POIs · Open-Meteo Rain & DEM</div>
  </div>
  <div class="controls-top">
    <button class="btn" id="themeBtn" onclick="toggleTheme()">☀️ Light / Dark</button>
    <button class="btn primary" onclick="exportFilteredCsv()">⬇ Export Cameras CSV</button>
  </div>
</header>

<nav class="tabs" id="tabNav">
  <button class="tab active" data-tab="story">1. Executive Story & Infographic</button>
  <button class="tab" data-tab="pulse">2. Daily Pulse (ชีพจรคนกรุงตามเวลา)</button>
  <button class="tab" data-tab="map">3. Bangkok Geospatial Lab</button>
  <button class="tab" data-tab="intersections">4. Intersections & Landmarks</button>
  <button class="tab" data-tab="modal">5. Modal Shift, Rain & AI Blind-Spots</button>
  <button class="tab" data-tab="policy">6. Camera Health & Policy Blueprint</button>
</nav>

<main>
  <!-- TAB 1: EXECUTIVE STORY -->
  <section id="tab-story" class="panel active">
    <div class="kpi-grid" id="heroKpis"></div>

    <div class="card" style="margin-bottom: 18px;">
      <h2>External Data Provenance (Honest Live Enrichment Audit)</h2>
      <div class="muted" style="margin-bottom: 8px;">All available sources loaded without fabrication; timed-out public endpoints remain transparently marked.</div>
      <div id="sourceBadges"></div>
    </div>

    <h2 style="margin: 8px 0 12px; font-size: 17px;">7 Data-Storytelling Discoveries (คลิกการ์ดเพื่อเจาะลึกแต่ละบท)</h2>
    <div class="grid-3" id="storyCards"></div>

    <div class="card" style="margin-top: 20px;">
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:12px;">
        <div>
          <h2>Executive Infographic Poster (Full High-Resolution Vector)</h2>
          <div class="muted">Generated reproducibly by <code>src/cctv/spatial_charts.py</code> from <code>reports/insights/</code></div>
        </div>
      </div>
      <div id="inlineInfographicWrap" style="max-width: 1120px; margin: 0 auto;">__INLINE_INFOGRAPHIC__</div>
    </div>
  </section>

  <!-- TAB 2: DAILY PULSE (SPATIO-TEMPORAL 50 DISTRICTS) -->
  <section id="tab-pulse" class="panel">
    <div class="map-toolbar">
      <button class="btn primary" id="pulsePlayBtn" onclick="togglePulsePlay()">▶ Play Time Animation</button>
      <div style="display:flex; gap:4px; flex-wrap:wrap;" id="pulseBandBtns">
        <button class="btn primary" data-band="morning" onclick="setPulseBand('morning')">เช้า 06–09</button>
        <button class="btn" data-band="midday" onclick="setPulseBand('midday')">กลางวัน 10–16</button>
        <button class="btn" data-band="evening" onclick="setPulseBand('evening')">เย็น 17–18</button>
        <button class="btn" data-band="night" onclick="setPulseBand('night')">ค่ำ–ดึก 19–21</button>
      </div>
      <label class="muted">Days:
        <select id="pulseDaytype" onchange="renderPulse()">
          <option value="all">ทุกวัน (All Days)</option>
          <option value="weekday">วันทำงาน (Weekday)</option>
          <option value="weekend">เสาร์-อาทิตย์ (Weekend)</option>
        </select>
      </label>
      <button class="btn" id="pulseExtentBtn" onclick="togglePulseExtent()">View: Full 50 Districts</button>
      <label style="font-size:12px;"><input type="checkbox" id="pulseChkDistLbl" checked onchange="renderPulse()" /> ชื่อเขต (50 เขต)</label>
      <label style="font-size:12px;"><input type="checkbox" id="pulseChkCamLbl" onchange="renderPulse()" /> รหัสกล้อง</label>
    </div>

    <div class="card" id="pulseStoryBox" style="margin-bottom:14px; border-left:4px solid var(--accent);"></div>

    <div class="map-layout">
      <div class="map-box">
        <svg id="pulseSvg" viewBox="0 0 920 620" style="width:100%; height:610px; display:block;"></svg>
      </div>
      <div class="inspector" id="pulseInspector"></div>
    </div>
  </section>

  <!-- TAB 3: GEOSPATIAL MAP -->
  <section id="tab-map" class="panel">
    <div class="map-toolbar">
      <label class="muted">Color by:
        <select id="mapColorMode" onchange="renderMap()">
          <option value="gi">Getis-Ord Gi* Hotspots / Coldspots</option>
          <option value="traffic">Traffic Volume (veh/frame)</option>
          <option value="dbscan">DBSCAN Busy Corridors</option>
          <option value="junction">Intersection Geometry</option>
          <option value="health">Camera Health (Frozen Frames)</option>
          <option value="elevation">Ground Elevation (DEM m)</option>
        </select>
      </label>
      <label class="muted">Zone:
        <select id="filterZone" onchange="renderMap()">
          <option value="all">All Bangkok (100)</option>
          <option value="Modern CBD / Arterial">Modern CBD / Arterial (71)</option>
          <option value="Old City (Rattanakosin-Dusit)">Old City Rattanakosin-Dusit (29)</option>
        </select>
      </label>
      <label class="muted">Junction:
        <select id="filterJunction" onchange="renderMap()">
          <option value="all">All Geometries</option>
          <option value="5+-way mega">5+-way mega</option>
          <option value="4-way crossroad">4-way crossroad</option>
          <option value="3-way / junction">3-way / junction</option>
          <option value="mid-block">mid-block</option>
        </select>
      </label>
      <label class="muted">Busyness:
        <select id="filterBusy" onchange="renderMap()">
          <option value="all">All Terciles</option>
          <option value="busy">Busy (33)</option>
          <option value="medium">Medium (33)</option>
          <option value="quiet">Quiet (34)</option>
        </select>
      </label>
      <input type="text" id="mapSearch" placeholder="Search camera ID, road, Thai name..." oninput="renderMap()" style="min-width:210px;" />
      <label style="font-size:12px;"><input type="checkbox" id="chkMall" onchange="renderMap()" /> Near Mall</label>
      <label style="font-size:12px;"><input type="checkbox" id="chkRail" onchange="renderMap()" /> Near Rail</label>
      <label style="font-size:12px;"><input type="checkbox" id="chkDistricts" checked onchange="renderMap()" /> 50 Districts</label>
      <label style="font-size:12px;"><input type="checkbox" id="chkCamLabels" onchange="renderMap()" /> Cam IDs</label>
      <label style="font-size:12px;"><input type="checkbox" id="chkKde" checked onchange="renderMap()" /> KDE Surface</label>
      <label style="font-size:12px;"><input type="checkbox" id="chkCorridors" checked onchange="renderMap()" /> DBSCAN Hulls</label>
      <label style="font-size:12px;"><input type="checkbox" id="chkPois" onchange="renderMap()" /> OSM POIs (435)</label>
      <button class="btn" id="mapExtentBtn" onclick="toggleMapExtent()">Extent: Inner Core</button>
    </div>

    <div class="map-layout">
      <div class="map-box">
        <svg id="mapSvg" viewBox="0 0 920 620"></svg>
        <div class="map-float">
          <button class="btn" onclick="zoomMap(1.25)">＋</button>
          <button class="btn" onclick="zoomMap(0.8)">－</button>
          <button class="btn" onclick="resetMapView()">Reset</button>
        </div>
      </div>

      <div class="inspector" id="camInspector">
        <div class="muted">Click any camera circle on the map to inspect its landmarks, intersection geometry, traffic & forensic health.</div>
      </div>
    </div>
  </section>

  <!-- TAB 3: INTERSECTIONS & LANDMARKS -->
  <section id="tab-intersections" class="panel">
    <div class="grid-2">
      <div class="card">
        <h2>Intersection Geometry & Traffic Volume</h2>
        <div class="muted">Mean vehicles/frame (stratified n = 891) across OSM 18m-consolidated junction topologies</div>
        <div id="junctionChart" style="margin-top:14px;"></div>
      </div>
      <div class="card">
        <h2>2×2 Compound Friction Matrix (Geometry × Mall/Rail)</h2>
        <div class="muted">Isolated mid-blocks away from malls & rail have <b>0.0% busy cameras</b> (0/16) vs <b>44.2% busy</b> at mall/rail intersections</div>
        <div class="matrix-2x2" id="compoundMatrix"></div>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <h2>Distance-Decay: How Landmarks Reshape Nearby Roads</h2>
        <div style="margin:8px 0 12px;">
          <button class="btn primary" id="btnDecayMall" onclick="renderDecay('mall_decay')">Shopping Malls (500m Decay)</button>
          <button class="btn" id="btnDecayRail" onclick="renderDecay('rail_decay')">BTS / MRT Stations (Feeder Ring)</button>
        </div>
        <div id="decayChart"></div>
      </div>
      <div class="card">
        <h2>Multivariate OLS Driver Decomposition (n = 100 Cameras)</h2>
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:10px;">
          <div class="muted" id="olsMeta">R² = 0.265 · Spatial-Controlled</div>
          <div>
            <button class="btn" id="btnOlsBase" onclick="renderOls('base')">Base (8 vars)</button>
            <button class="btn primary" id="btnOlsSpatial" onclick="renderOls('spatial')">Spatial-Controlled (+Old City & DEM)</button>
          </div>
        </div>
        <div id="olsChart"></div>
      </div>
    </div>
  </section>

  <!-- TAB 4: MODAL SHIFT, RAIN & AI BLIND-SPOTS -->
  <section id="tab-modal" class="panel">
    <div class="grid-2">
      <div class="card">
        <h2>Mega-Mall Weekend Immunity vs. Everywhere Else</h2>
        <div class="muted">Weekday vs weekend vehicles/frame; ≥3 malls lose only -5.6% on weekends while 1–2 mall sites drop -33.5%</div>
        <div id="weekendChart" style="margin-top:12px;"></div>
      </div>
      <div class="card">
        <h2>Bangkok's Dual Identity & Evening Rain Moto Exodus</h2>
        <div class="muted">Weekday morning 34.2% motorcycle commuter wave vs weekend midday car takeover (+6.6%)</div>
        <div id="bandModalChart" style="margin-top:12px;"></div>
        <div id="rainShiftBox" style="margin-top:14px; padding:12px 14px; border-radius:10px; background:var(--bg2); border:1px solid var(--blue);"></div>
      </div>
    </div>

    <div class="card">
      <h2>The 92.9% Invisible Traffic Problem (`day/model_zero` AI Blind-Spots)</h2>
      <div class="muted" id="mzSummaryLine" style="margin-bottom:10px;"></div>
      <div class="tbl-wrap" style="max-height: 320px;">
        <table id="mzTable">
          <thead><tr><th>Cam ID</th><th>Location</th><th>Timestamp</th><th>Junction</th><th class="num">Human Total</th><th class="num">Cars</th><th class="num">Motorcycles</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- TAB 5: CAMERA HEALTH & POLICY BLUEPRINT -->
  <section id="tab-policy" class="panel">
    <div class="grid-2">
      <div class="card">
        <h2>Camera Health Paradox ("ดับตรงที่รถติดที่สุด")</h2>
        <div class="muted">Share of cameras with bridged frozen frames; 98.5% of all 584 frozen frames hit intersections</div>
        <div id="healthParadoxChart" style="margin-top:12px;"></div>
      </div>
      <div class="card">
        <h2>Outer-Bangkok Blind Zones (Where to Deploy Next)</h2>
        <div class="muted">The 100-camera fleet spans only a 27 × 14 km central core (lat 13.70–13.82, lon 100.39–100.63)</div>
        <div id="blindSpotGrid" class="matrix-2x2" style="margin-top:12px;"></div>
      </div>
    </div>

    <div class="card" style="margin-bottom:18px;">
      <h2>Top 10 "Upgrade First" Priority Cameras (Click to Inspect on Geospatial Map)</h2>
      <div class="muted" style="margin-bottom:12px;">Weighted score = 0.40·z(traffic) + 0.25·z(malls + rail + junction) + 0.35·z(freeze / white-PNG / AI-miss severity)</div>
      <div class="grid-2" id="top10Cards"></div>
    </div>

    <div class="card">
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:10px;">
        <div>
          <h2>100-Camera Master Spatial Explorer</h2>
          <div class="muted">Click any column header to sort; click any row to open in the Geospatial Map</div>
        </div>
        <input type="text" id="tableSearch" placeholder="Filter 100 cameras..." oninput="renderMasterTable()" style="min-width:240px;" />
      </div>
      <div class="tbl-wrap">
        <table id="masterTable">
          <thead>
            <tr>
              <th onclick="sortTable('upgrade_rank')">Rank</th>
              <th onclick="sortTable('camera_id')">ID</th>
              <th onclick="sortTable('name')">Location</th>
              <th onclick="sortTable('zone')">Zone</th>
              <th onclick="sortTable('junction_type')">Geometry</th>
              <th class="num" onclick="sortTable('band_w_mean')">Traffic</th>
              <th class="num" onclick="sortTable('n_mall_500m')">Malls</th>
              <th class="num" onclick="sortTable('n_rail_500m')">Rail</th>
              <th class="num" onclick="sortTable('elevation_m')">Elev(m)</th>
              <th class="num" onclick="sortTable('bridged_frozen')">Frozen</th>
              <th class="num" onclick="sortTable('gi_star_z')">Gi* z</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </div>
  </section>
</main>

<div class="tooltip-float" id="tooltip"></div>

<script>
const DASHBOARD_DATA = __JSON_PAYLOAD__;

const CAMS = DASHBOARD_DATA.cameras;
const CLUSTERS = DASHBOARD_DATA.clusters;
const SUMMARY = DASHBOARD_DATA.summary;
const PULSE = DASHBOARD_DATA.pulse;

let selectedCamId = SUMMARY.top10_upgrade_priority[0].camera_id;
let mapZoom = 1.0, mapPanX = 0.0, mapPanY = 0.0, isDragging = false, dragMoved = false, dragStartX = 0, dragStartY = 0;
let mapFullExtent = false;
let pulseBand = 'morning', pulseFullExtent = true, pulseTimer = null, selectedDistrictTh = 'ราชเทวี';
let sortKey = 'upgrade_rank', sortAsc = true;

function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function toggleTheme() {
  const root = document.documentElement;
  root.setAttribute('data-theme', root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
}

function switchTab(tabId) {
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
  document.querySelectorAll('.panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + tabId));
}

document.querySelectorAll('.tab').forEach(b => b.addEventListener('click', () => switchTab(b.dataset.tab)));

function initStoryTab() {
  const corp = SUMMARY.corpus;
  const mor = SUMMARY.moran_i.traffic_band_w;
  const ob = SUMMARY.two_bangkoks['Old City (All)'];
  const mb = SUMMARY.two_bangkoks['Modern CBD / Arterial (All)'];
  const cHot = SUMMARY.compound_friction_2x2.find(x => x.segment.includes('Intersection + Mall'));
  const cIso = SUMMARY.compound_friction_2x2.find(x => x.segment.includes('Mid-block, No'));
  const mega = SUMMARY.landmarks.find(x => x.segment.includes('Mega-Mall'));
  const mz = SUMMARY.ai_blind_spots;
  const chp = SUMMARY.camera_health_paradox;

  const kpis = [
    { val: `${corp.raw_files.toLocaleString()} → ${corp.clean_complete_snapshots.toLocaleString()}`, lbl: 'Clean Complete-Hour Snapshots', sub: 'After stripping 584 freezes & 504 white PNGs', color: 'var(--accent)' },
    { val: `I = +${mor.morans_i.toFixed(3)}`, lbl: `Global Moran's I (p = ${mor.p_value})`, sub: `CBD ${mb.mean_total.toFixed(1)} vs Old City ${ob.mean_total.toFixed(1)} veh/frame`, color: 'var(--blue)' },
    { val: `${cIso.busy_pct.toFixed(0)}% → ${cHot.busy_pct.toFixed(1)}%`, lbl: 'Compound Friction Busy Share', sub: 'Isolated mid-block vs Mall/Rail intersection', color: 'var(--coral)' },
    { val: `${mega.we_minus_wd_pct >= 0 ? '+' : ''}${mega.we_minus_wd_pct.toFixed(1)}%`, lbl: 'Mega-Mall Weekend Retention', sub: '≥3 malls never sleep (vs -33.5% at 1–2 malls)', color: 'var(--emerald)' },
    { val: `${chp.intersection_share_of_frozen_pct}% / ${mz.false_empty_pct}%`, lbl: 'Frozen Intersections / AI Blind', sub: '575/584 freezes & 91/98 false-empty frames', color: 'var(--purple)' },
  ];
  document.getElementById('heroKpis').innerHTML = kpis.map(k => `
    <div class="kpi" style="border-top-color:${k.color}">
      <div class="val" style="color:${k.color}">${k.val}</div>
      <div class="lbl">${k.lbl}</div>
      <div class="sub">${k.sub}</div>
    </div>
  `).join('');

  const src = SUMMARY.external_sources || {};
  const badges = [
    { name: 'OSM Roads & POIs', st: 'cached (1,258 ways · 435 POIs)', cls: 'ok' },
    { name: 'Sunrise-Sunset Daylight', st: 'cached (7 days)', cls: 'ok' },
    ...Object.entries(src).map(([k, v]) => ({
      name: k,
      st: `${v.status} (${v.records} records)`,
      cls: v.status === 'fetched_live' || v.status === 'cached' ? 'ok' : 'warn'
    }))
  ];
  document.getElementById('sourceBadges').innerHTML = badges.map(b =>
    `<span class="pill ${b.cls}">${esc(b.name)}: ${esc(b.st)}</span>`
  ).join('');

  const stories = [
    { tab: 'pulse', tag: '0 · Daily Pulse (50 เขต)', title: 'ชีพจรคนกรุง เช้า → กลางวัน → เย็น → ดึก', desc: `เช้าคนฝั่งธนฯ/บางกะปิแห่เข้าเมือง (มไหสวรรย์ 52.5); เย็นเขตราชเทวีระเบิด 38.8 คัน; ดึกเมืองเก่าหลับแต่เขตดินแดง–ห้วยขวางยังพุ่ง 28.4 คัน!` },
    { tab: 'map', tag: '1 · Spatial Clustering', title: 'The Two Bangkoks (สองกรุงเทพฯ)', desc: `CBD/Arterial (18.00 veh/fr) runs +87% denser than Historic Rattanakosin-Dusit (9.62), even across identical 4-way intersections (Moran's I = +0.603, p = 0.020).` },
    { tab: 'intersections', tag: '2 · Road Geometry', title: 'The Compound Friction Law', desc: `0% of isolated mid-block cameras (0/16) are busy, vs 44.2% at Mall/Rail intersections (+57% traffic). 5+-way mega-interchanges average 19.57 veh/fr.` },
    { tab: 'modal', tag: '3 · Urban Rhythm', title: 'Mega-Mall Weekend Immunity', desc: `Hubs with ≥3 malls lose just -5.6% traffic on weekends (Pratunam, Siam, Victory Monument), while 1–2 mall areas drop -33.5%.` },
    { tab: 'intersections', tag: '4 · Transit Feeders', title: 'BTS/MRT Win-Moto Ring & 5.5× Bus Magnet', desc: `Cameras within 0–150m of rail are 41.7% motorcycles (feeder taxis), with volume peaking at 150–300m (19.07). Mall entrances carry 5.5× more buses.` },
    { tab: 'modal', tag: '5 · Weather & AI Audit', title: 'Evening Rain Moto Exodus & 92.9% AI Blind-Spot', desc: `Open-Meteo shows evening rain cuts human-counted motorcycles -31.9% (6.42→4.37), while raw YOLO missed cars on 91/98 zero-count frames (Rama 9 up to 40).` },
    { tab: 'policy', tag: '6 · Infrastructure Paradox', title: 'ดับตรงที่รถติดที่สุด (Camera Health Paradox)', desc: `Busy cameras freeze 3.1× more often than quiet ones (36.4% vs 11.8%, p=0.019), and 98.5% of all 584 frozen frames sit at intersections.` },
    { tab: 'policy', tag: '7 · Policy Blueprint', title: 'Upgrade Top 10 Before Expanding Outward', desc: `Repair high-friction failing junctions (#1 Cam 150 Rama 6, #2 Cam 938, #3 Cam 500 Pratunam) and cover outer North/South 0-camera blind zones.` },
  ];
  document.getElementById('storyCards').innerHTML = stories.map(st => `
    <div class="story-card" onclick="switchTab('${st.tab}')">
      <div class="tag">${esc(st.tag)}</div>
      <div class="headline">${esc(st.title)}</div>
      <div class="desc">${esc(st.desc)}</div>
    </div>
  `).join('');
}

// ---- TAB 2 & 3: PROJECTION & INTERACTIVE 50-DISTRICT BANGKOK MAP ----
function makeProjector(fullExtent) {
  let lon0 = 100.38, lon1 = 100.655, lat0 = 13.685, lat1 = 13.842;
  if (fullExtent && PULSE && PULSE.districts) {
    lon0 = 100.32; lon1 = 100.95; lat0 = 13.48; lat1 = 13.965;
  }
  const scale = Math.min(860 / (lon1 - lon0), 570 / (lat1 - lat0));
  const xOff = 30 + (860 - (lon1 - lon0) * scale) / 2;
  const yOff = 25 + (570 - (lat1 - lat0) * scale) / 2;
  return (lat, lon) => [xOff + (lon - lon0) * scale, yOff + (lat1 - lat) * scale];
}

function toggleMapExtent() {
  mapFullExtent = !mapFullExtent;
  document.getElementById('mapExtentBtn').textContent = mapFullExtent ? 'Extent: Full 50 Districts' : 'Extent: Inner Core';
  resetMapView();
}

function getCamColor(c, mode) {
  if (mode === 'gi') {
    if (c.gi_star_z >= 1.96) return '#ef4444';
    if (c.gi_star_z >= 1.2) return '#fb923c';
    if (c.gi_star_z <= -1.96) return '#3b82f6';
    if (c.gi_star_z <= -1.2) return '#60a5fa';
    return '#94a3b8';
  }
  if (mode === 'traffic') {
    const t = Math.min(1, Math.max(0, (c.band_w_mean - 5) / 34));
    return t > 0.72 ? '#e11d48' : (t > 0.45 ? '#f59e0b' : (t > 0.25 ? '#38bdf8' : '#64748b'));
  }
  if (mode === 'dbscan') {
    const cols = { 1: '#f43f5e', 2: '#f59e0b', 3: '#a855f7', 4: '#14b8a6', '-1': '#fbbf24', 0: '#475569' };
    return cols[String(c.dbscan_cluster)] || '#64748b';
  }
  if (mode === 'junction') {
    return { '5+-way mega': '#e11d48', '4-way crossroad': '#f59e0b', '3-way / junction': '#38bdf8', 'mid-block': '#94a3b8' }[c.junction_type] || '#94a3b8';
  }
  if (mode === 'health') {
    if (c.bridged_frozen >= 50) return '#e11d48';
    if (c.bridged_frozen > 0) return '#f59e0b';
    return '#10b981';
  }
  if (mode === 'elevation') {
    const e = c.elevation_m || 6;
    return e <= 3 ? '#ef4444' : (e <= 6 ? '#f59e0b' : '#10b981');
  }
  return '#3b82f6';
}

function getFilteredCams() {
  const z = document.getElementById('filterZone').value;
  const j = document.getElementById('filterJunction').value;
  const b = document.getElementById('filterBusy').value;
  const q = document.getElementById('mapSearch').value.trim().toLowerCase();
  const nearMall = document.getElementById('chkMall').checked;
  const nearRail = document.getElementById('chkRail').checked;
  return CAMS.filter(c => {
    if (z !== 'all' && c.zone !== z) return false;
    if (j !== 'all' && c.junction_type !== j) return false;
    if (b !== 'all' && c.busyness_tercile !== b) return false;
    if (nearMall && c.n_mall_500m < 1) return false;
    if (nearRail && c.n_rail_500m < 1) return false;
    if (q) {
      const hay = `${c.camera_id} ${c.name} ${c.location_th} ${c.road_name} ${c.top_malls_500m} ${c.district_th}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

function renderMap() {
  const svg = document.getElementById('mapSvg');
  const proj = makeProjector(mapFullExtent);
  const mode = document.getElementById('mapColorMode').value;
  const showKde = document.getElementById('chkKde').checked;
  const showCor = document.getElementById('chkCorridors').checked;
  const showPois = document.getElementById('chkPois').checked;
  const showDists = document.getElementById('chkDistricts').checked;
  const showCamLbl = document.getElementById('chkCamLabels').checked;
  const filtered = new Set(getFilteredCams().map(c => c.camera_id));

  let out = `<g id="mapViewport" transform="translate(${mapPanX.toFixed(1)},${mapPanY.toFixed(1)}) scale(${mapZoom.toFixed(3)})">`;

  // 50 Bangkok Districts base polygons
  if (showDists && PULSE && PULSE.districts) {
    for (const d of PULSE.districts) {
      const hasCam = d.camera_count > 0;
      const fill = hasCam ? 'rgba(148,163,184,0.08)' : 'rgba(148,163,184,0.02)';
      const stroke = hasCam ? '#64748b' : '#334155';
      for (const poly of d.polys) {
        const pts = poly[0].map(p => proj(p[1], p[0]).map(v => v.toFixed(1)).join(',')).join(' ');
        out += `<polygon points="${pts}" fill="${fill}" stroke="${stroke}" stroke-width="${hasCam ? 1.1 : 0.7}" opacity="0.85"/>`;
      }
    }
    for (const d of PULSE.districts) {
      if (!mapFullExtent && (d.centroid_lon < 100.38 || d.centroid_lon > 100.655 || d.centroid_lat < 13.685 || d.centroid_lat > 13.842)) continue;
      const [lx, ly] = proj(d.centroid_lat, d.centroid_lon);
      out += `<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" font-size="${d.camera_count > 0 ? 9.5 : 8.5}" fill="#94a3b8" text-anchor="middle" opacity="0.78" style="pointer-events:none">${esc(d.name_th)}</text>`;
    }
  }

  // KDE grid
  if (showKde) {
    for (const cell of CLUSTERS.kde_grid) {
      if (cell.traf_kde_norm < 0.1) continue;
      const [x, y] = proj(cell.lat, cell.lon);
      const col = cell.traf_kde_norm > 0.68 ? '#ef4444' : (cell.traf_kde_norm > 0.42 ? '#f97316' : '#facc15');
      const op = (cell.traf_kde_norm * 0.22).toFixed(2);
      out += `<rect x="${(x-16).toFixed(1)}" y="${(y-16).toFixed(1)}" width="34" height="34" fill="${col}" opacity="${op}" rx="6"/>`;
    }
  }

  // Chao Phraya River
  const river = [[13.835,100.514],[13.800,100.516],[13.775,100.502],[13.758,100.491],[13.744,100.492],[13.729,100.512],[13.704,100.502],[13.688,100.534]];
  out += `<polyline points="${river.map(([a,b]) => proj(a,b).map(n => n.toFixed(1)).join(',')).join(' ')}" fill="none" stroke="#3b82f6" stroke-width="6" opacity="0.35" stroke-linecap="round" stroke-linejoin="round"/>`;

  // Old City Box
  const [ox1, oy1] = proj(13.790, 100.490);
  const [ox2, oy2] = proj(13.735, 100.525);
  out += `<rect x="${ox1.toFixed(1)}" y="${oy1.toFixed(1)}" width="${(ox2-ox1).toFixed(1)}" height="${(oy2-oy1).toFixed(1)}" fill="#3b82f6" fill-opacity="0.06" stroke="#3b82f6" stroke-width="1.4" stroke-dasharray="5,3" rx="6"/>`;
  out += `<text x="${(ox1+6).toFixed(1)}" y="${(oy1+15).toFixed(1)}" font-size="10.5" fill="#60a5fa" font-weight="700">Old City Rattanakosin-Dusit (9.6 veh/fr)</text>`;

  // DBSCAN Corridor Circles/Labels
  if (showCor) {
    const ccols = ['#f43f5e', '#f59e0b', '#a855f7', '#14b8a6'];
    CLUSTERS.dbscan.corridors.forEach((cor, idx) => {
      const [cx, cy] = proj(cor.centroid_lat, cor.centroid_lon);
      const col = ccols[idx % ccols.length];
      out += `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="46" fill="${col}" fill-opacity="0.09" stroke="${col}" stroke-width="1.8" stroke-dasharray="5,3"/>`;
      out += `<text x="${cx.toFixed(1)}" y="${(cy-50).toFixed(1)}" font-size="10.5" fill="${col}" font-weight="700" text-anchor="middle">${esc(cor.name.split(' ')[0] + ' ' + cor.name.split(' ')[1])}</text>`;
    });
  }

  // Optional OSM POIs
  if (showPois) {
    const pcol = { mall: '#ec4899', rail: '#22d3ee', hospital: '#10b981', school: '#fde047', market: '#fb923c' };
    for (const p of CLUSTERS.pois) {
      const [px, py] = proj(p.lat, p.lon);
      out += `<circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="2.6" fill="${pcol[p.cat] || '#fff'}" opacity="0.7" data-poi="${esc(p.cat + ': ' + p.name)}" onmousemove="showTip(event, this.dataset.poi)" onmouseout="hideTip()"/>`;
    }
  }

  // Outer Blind-Spot Edge Notes
  out += `<text x="460" y="18" font-size="11" fill="#f87171" font-weight="700" text-anchor="middle">▲ NORTH BLIND ZONE (&gt;13.84°N): 0 CAMERAS (Don Mueang / Sai Mai)</text>`;
  out += `<text x="460" y="612" font-size="11" fill="#f87171" font-weight="700" text-anchor="middle">▼ SOUTH BLIND ZONE (&lt;13.68°N): 0 CAMERAS (Bang Khun Thian / Thung Khru)</text>`;

  // 100 Cameras
  for (const c of CAMS) {
    const [px, py] = proj(c.latitude, c.longitude);
    const inFilt = filtered.has(c.camera_id);
    const isSel = c.camera_id === selectedCamId;
    const rad = Math.max(4, Math.min(15, 3.6 + 0.24 * c.band_w_mean));
    const col = getCamColor(c, mode);
    const op = inFilt ? '0.92' : '0.12';
    const sw = isSel ? '3' : '0.9';
    const sc = isSel ? '#ffffff' : '#020617';
    out += `<circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="${rad.toFixed(1)}" fill="${col}" fill-opacity="${op}" stroke="${sc}" stroke-width="${sw}" style="cursor:pointer" onclick="selectCamera(${c.camera_id})" onmousemove="showCamTip(event, ${c.camera_id})" onmouseout="hideTip()"/>`;
    if (showCamLbl && inFilt) {
      out += `<text x="${px.toFixed(1)}" y="${(py - rad - 2).toFixed(1)}" font-size="8.5" fill="#f8fafc" text-anchor="middle" style="pointer-events:none">${c.camera_id}</text>`;
    }
  }

  out += '</g>';
  svg.innerHTML = out;
}

function zoomMap(factor) {
  mapZoom = Math.max(0.8, Math.min(4.5, mapZoom * factor));
  renderMap();
}
function resetMapView() {
  mapZoom = 1.0; mapPanX = 0.0; mapPanY = 0.0;
  renderMap();
}

const mapEl = document.getElementById('mapSvg');
mapEl.addEventListener('mousedown', e => { isDragging = true; dragMoved = false; dragStartX = e.clientX - mapPanX; dragStartY = e.clientY - mapPanY; });
window.addEventListener('mousemove', e => {
  if (!isDragging) return;
  dragMoved = true;
  mapPanX = e.clientX - dragStartX;
  mapPanY = e.clientY - dragStartY;
  const vp = document.getElementById('mapViewport');
  if (vp) vp.setAttribute('transform', `translate(${mapPanX.toFixed(1)},${mapPanY.toFixed(1)}) scale(${mapZoom.toFixed(3)})`);
});
window.addEventListener('mouseup', () => { isDragging = false; });
mapEl.addEventListener('wheel', e => { e.preventDefault(); zoomMap(e.deltaY < 0 ? 1.12 : 0.89); }, { passive: false });

function showTip(ev, text) {
  const tip = document.getElementById('tooltip');
  tip.textContent = text;
  tip.style.display = 'block';
  tip.style.left = (ev.clientX + 12) + 'px';
  tip.style.top = (ev.clientY + 12) + 'px';
}
function showCamTip(ev, cid) {
  const c = CAMS.find(x => x.camera_id === cid);
  if (!c) return;
  const tip = document.getElementById('tooltip');
  tip.innerHTML = `<b>Cam ${c.camera_id}: ${esc(c.name)}</b><br>Traffic: ${c.band_w_mean.toFixed(1)} veh/fr (${esc(c.busyness_tercile)})<br>${esc(c.junction_type)} · ${c.n_mall_500m} malls · ${c.n_rail_500m} rail<br>Gi* z = ${c.gi_star_z >= 0 ? '+' : ''}${c.gi_star_z} · Frozen: ${c.bridged_frozen}`;
  tip.style.display = 'block';
  tip.style.left = (ev.clientX + 12) + 'px';
  tip.style.top = (ev.clientY + 12) + 'px';
}
function hideTip() { document.getElementById('tooltip').style.display = 'none'; }

function selectCamera(cid) {
  selectedCamId = cid;
  renderInspector();
  renderMap();
}

function inspectCameraOnMap(cid) {
  selectedCamId = cid;
  switchTab('map');
  renderInspector();
  renderMap();
}

function renderInspector() {
  const c = CAMS.find(x => x.camera_id === selectedCamId) || CAMS[0];
  const tot = Math.max(0.01, c.mean_car + c.mean_motorcycle + c.mean_bus + c.mean_truck);
  const pCar = (100 * c.mean_car / tot).toFixed(1);
  const pMoto = (100 * c.mean_motorcycle / tot).toFixed(1);
  const pHeavy = (100 * (c.mean_bus + c.mean_truck) / tot).toFixed(1);

  document.getElementById('camInspector').innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <span class="pill ok">Upgrade Rank #${c.upgrade_rank}</span>
      <span class="pill">${esc(c.busyness_tercile.toUpperCase())}</span>
    </div>
    <h2 style="margin:8px 0 4px; font-size:17px;">Cam ${c.camera_id} · ${esc(c.name)}</h2>
    <div class="muted" style="margin-bottom:10px;">${esc(c.location_th)}</div>

    <div style="margin:10px 0;">
      <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:4px;">
        <span><b>${c.band_w_mean.toFixed(1)}</b> band-weighted veh/fr</span>
        <span class="muted">Cars ${pCar}% · Moto ${pMoto}% · Bus/Trk ${pHeavy}%</span>
      </div>
      <div class="bar-track">
        <div class="bar-seg" style="width:${pCar}%; background:var(--blue)"></div>
        <div class="bar-seg" style="width:${pMoto}%; background:var(--accent)"></div>
        <div class="bar-seg" style="width:${pHeavy}%; background:var(--teal)"></div>
      </div>
    </div>

    <h3 style="margin-top:14px; color:var(--accent);">Urban & Road Context</h3>
    <div class="stat-row"><span>District / Zone</span><b>เขต${esc(c.district_th || '—')} · ${esc(c.zone)}</b></div>
    <div class="stat-row"><span>Daily Rhythm</span><b>${esc(c.archetype || '—')}</b></div>
    <div class="stat-row"><span>Road & Class</span><b>${esc(c.road_name || '—')} (${esc(c.road_class)})</b></div>
    <div class="stat-row"><span>Intersection</span><b>${esc(c.junction_type)} (deg ${c.junction_degree})</b></div>
    <div class="stat-row"><span>Overpass / Lanes</span><b>${c.has_overpass ? 'Near Bridge/Overpass' : 'At Grade'} · ${c.lanes || '—'} lanes</b></div>
    <div class="stat-row"><span>Elevation (DEM) / Rain (7d)</span><b>${c.elevation_m ?? '—'} m · ${c.rain_week_mm ?? '—'} mm (${c.wet_hours_week ?? '—'} wet hrs)</b></div>

    <h3 style="margin-top:14px; color:var(--teal);">Nearby Landmarks (500m & Nearest)</h3>
    <div class="stat-row"><span>Malls in 500m (${c.n_mall_500m})</span><b>${esc(c.top_malls_500m || (c.nearest_mall_name ? c.nearest_mall_name + ' (' + c.nearest_mall_m + 'm)' : 'None'))}</b></div>
    <div class="stat-row"><span>Nearest BTS/MRT (${c.n_rail_500m})</span><b>${esc(c.nearest_rail_name || '—')} (${c.nearest_rail_m ?? '—'} m)</b></div>
    <div class="stat-row"><span>Nearest Hospital (${c.n_hospital_500m})</span><b>${esc(c.nearest_hospital_name || '—')} (${c.nearest_hospital_m ?? '—'} m)</b></div>
    <div class="stat-row"><span>Nearest School (${c.n_school_500m})</span><b>${esc(c.nearest_school_name || '—')} (${c.nearest_school_m ?? '—'} m)</b></div>

    <h3 style="margin-top:14px; color:var(--coral);">Spatial Stats & Forensic Health</h3>
    <div class="stat-row"><span>Getis-Ord Gi* / LISA</span><b>z = ${c.gi_star_z >= 0 ? '+' : ''}${c.gi_star_z} (${esc(c.gi_star_class)}, ${esc(c.lisa_quadrant)})</b></div>
    <div class="stat-row"><span>Weekday vs Weekend</span><b>${c.weekday_mean ?? '—'} vs ${c.weekend_mean ?? '—'} (${c.weekend_retention_pct ?? '—'}%)</b></div>
    <div class="stat-row"><span>Subnet / Thu 27 AM</span><b>${esc(c.subnet_16)} · ${esc(c.thu27_am_status)}</b></div>
    <div class="stat-row"><span>Frozen / White PNGs</span><b>${c.bridged_frozen} frozen · ${c.white_pngs} white PNGs</b></div>
    <div class="stat-row"><span>AI Model-Zero Max Missed</span><b>${c.model_zero_max_human} human vehicles</b></div>
  `;
}

// ---- TAB 3: INTERSECTIONS & LANDMARKS ----
function initIntersectionsTab() {
  const maxJ = 22.0;
  document.getElementById('junctionChart').innerHTML = SUMMARY.intersections.map(r => `
    <div class="chart-bar-row">
      <div><b>${esc(r.segment)}</b><div class="muted">${r.cameras} cams · ${r.busy_pct}% busy</div></div>
      <div style="background:var(--bg2); border-radius:6px; height:22px; overflow:hidden; display:flex;">
        <div style="width:${(r.mean_car/maxJ*100).toFixed(1)}%; background:var(--blue);" title="Car ${r.mean_car}"></div>
        <div style="width:${(r.mean_motorcycle/maxJ*100).toFixed(1)}%; background:var(--accent);" title="Moto ${r.mean_motorcycle}"></div>
        <div style="width:${((r.mean_bus+r.mean_truck)/maxJ*100).toFixed(1)}%; background:var(--teal);" title="Bus/Truck"></div>
      </div>
      <div class="num"><b>${r.mean_total.toFixed(2)}</b><div class="muted">${r.ci_low}–${r.ci_high}</div></div>
    </div>
  `).join('') + `<div class="muted" style="margin-top:10px;">Blue: Cars · Amber: Motorcycles · Teal: Bus+Truck. Hover bars for values.</div>`;

  const cols = {
    'Mid-block, No Mall/Rail': 'var(--muted)',
    'Mid-block + Mall/Rail': 'var(--accent)',
    'Intersection, No Mall/Rail': 'var(--blue)',
    'Intersection + Mall/Rail': 'var(--coral)'
  };
  document.getElementById('compoundMatrix').innerHTML = [...SUMMARY.compound_friction_2x2].reverse().map(r => `
    <div class="mcell" style="border-color:${cols[r.segment] || 'var(--border)'}">
      <div style="font-size:12px; font-weight:700; color:${cols[r.segment]}">${esc(r.segment)}</div>
      <div class="big">${r.mean_total.toFixed(2)} <span style="font-size:12px; font-weight:400;" class="muted">veh/fr</span></div>
      <div style="margin-top:4px;"><span class="pill">${r.busy_pct}% busy (${r.busy_cameras}/${r.cameras} cams)</span></div>
      <div class="muted" style="margin-top:4px;">95% CI ${r.ci_low}–${r.ci_high} · ${r.frozen_frames} frozen</div>
    </div>
  `).join('');

  renderDecay('mall_decay');
  renderOls('spatial');
}

function renderDecay(kind) {
  document.getElementById('btnDecayMall').classList.toggle('primary', kind === 'mall_decay');
  document.getElementById('btnDecayRail').classList.toggle('primary', kind === 'rail_decay');
  const rows = SUMMARY.distance_decay.filter(r => r.category === kind);
  const note = kind === 'mall_decay'
    ? 'Monotonic mall proximity spike (19.67 → 14.00) & 5.5× bus clustering (0.72 → 0.13 buses/fr).'
    : 'BTS/MRT 0–150m has 41.7% motorcycles (win-moto feeder ring); total volume peaks at 150–300m approach (19.07).';
  document.getElementById('decayChart').innerHTML = `<div class="muted" style="margin-bottom:8px;">${note}</div>` + rows.map(r => `
    <div class="chart-bar-row">
      <div><b>${esc(r.segment)}</b><div class="muted">${r.cameras} cams · moto ${r.moto_share_pct}% · bus ${r.bus_mean}</div></div>
      <div style="background:var(--bg2); border-radius:6px; height:20px; overflow:hidden;">
        <div class="chart-fill" style="width:${(r.all_mean/22*100).toFixed(1)}%; background:${kind==='mall_decay' ? 'var(--coral)' : 'var(--teal)'};"></div>
      </div>
      <div class="num"><b>${r.all_mean.toFixed(2)}</b></div>
    </div>
  `).join('');
}

function renderOls(which) {
  document.getElementById('btnOlsBase').classList.toggle('primary', which === 'base');
  document.getElementById('btnOlsSpatial').classList.toggle('primary', which === 'spatial');
  const m = which === 'base' ? SUMMARY.ols_base : SUMMARY.ols_spatial_controlled;
  document.getElementById('olsMeta').textContent = `R² = ${m.r2.toFixed(3)} · Adj-R² = ${m.adj_r2.toFixed(3)} · RMSE = ${m.rmse.toFixed(2)}`;
  document.getElementById('olsChart').innerHTML = m.coefficients.map(c => {
    const pct = Math.min(48, Math.abs(c.beta) / 4.5 * 48);
    const col = c.beta >= 0 ? (c.significant_05 ? 'var(--coral)' : 'var(--blue)') : 'var(--teal)';
    return `
      <div style="display:grid; grid-template-columns:150px 1fr 90px; gap:8px; align-items:center; margin:6px 0; font-size:12px;">
        <div><b>${esc(c.feature)}</b></div>
        <div style="position:relative; height:16px; background:var(--bg2); border-radius:4px;">
          <div style="position:absolute; left:50%; top:0; bottom:0; width:1px; background:var(--muted);"></div>
          <div style="position:absolute; top:2px; height:12px; border-radius:3px; background:${col}; ${c.beta>=0 ? 'left:50%' : 'right:50%'}; width:${pct.toFixed(1)}%;"></div>
        </div>
        <div class="num">${c.beta >= 0 ? '+' : ''}${c.beta.toFixed(2)} (t=${c.t_stat.toFixed(1)})</div>
      </div>
    `;
  }).join('');
}

// ---- TAB 4: MODAL SHIFT, RAIN & AI BLIND-SPOTS ----
function initModalTab() {
  document.getElementById('weekendChart').innerHTML = SUMMARY.landmarks.map(r => `
    <div class="chart-bar-row">
      <div><b>${esc(r.segment)}</b><div class="muted">WD ${r.weekday_mean} → WE ${r.weekend_mean}</div></div>
      <div style="background:var(--bg2); border-radius:6px; height:20px; overflow:hidden; position:relative;">
        <div style="height:100%; width:${(r.weekend_mean/r.weekday_mean*100).toFixed(1)}%; background:${Math.abs(r.we_minus_wd_pct)<10 ? 'var(--emerald)' : 'var(--blue)'};"></div>
      </div>
      <div class="num"><b>${r.we_minus_wd_pct >= 0 ? '+' : ''}${r.we_minus_wd_pct.toFixed(1)}%</b></div>
    </div>
  `).join('');

  document.getElementById('bandModalChart').innerHTML = SUMMARY.modal_by_band_daytype.map(r => `
    <div style="display:grid; grid-template-columns:130px 1fr 90px; gap:8px; align-items:center; margin:6px 0; font-size:12px;">
      <div><b>${esc(r.band)} · ${r.daytype === 'weekday' ? 'WD' : 'WE'}</b></div>
      <div style="background:var(--bg2); border-radius:5px; height:16px; display:flex; overflow:hidden;">
        <div style="width:${(r.mean_car/22*100).toFixed(1)}%; background:var(--blue);"></div>
        <div style="width:${(r.mean_motorcycle/22*100).toFixed(1)}%; background:var(--accent);"></div>
      </div>
      <div class="num">${r.mean_total.toFixed(1)} (${r.motorcycle_share_pct}% moto)</div>
    </div>
  `).join('');

  const rm = SUMMARY.rain_modal_shift;
  if (rm && rm.available && rm.evening_wet_vs_dry) {
    const ev = rm.evening_wet_vs_dry;
    document.getElementById('rainShiftBox').innerHTML = `
      <b>Open-Meteo Evening Rush (17:00–18:59) Rain Modal Shift (Human-Counted, n=${ev.dry_frames + ev.wet_frames})</b><br>
      <span class="muted">Dry (${ev.dry_frames}): ${ev.dry_car} cars · <b>${ev.dry_moto} motos (${ev.dry_moto_share_pct}%)</b> &nbsp;|&nbsp;
      Wet (${ev.wet_frames}): ${ev.wet_car} cars · <b>${ev.wet_moto} motos (${ev.wet_moto_share_pct}%)</b></span><br>
      <b style="color:var(--blue)">Motorcycles drop ${ev.moto_diff} /frame (-31.9%, 95% CI ${ev.moto_diff_ci[0]} to ${ev.moto_diff_ci[1]})</b> while cars stay near flat (-7.8%).
    `;
  }

  const mz = SUMMARY.ai_blind_spots;
  document.getElementById('mzSummaryLine').textContent =
    `Out of ${mz.total_usable_model_zero} usable frames where YOLO predicted 0 vehicles, humans counted >0 vehicles in ${mz.nonzero_human_frames} (${mz.false_empty_pct}%) — mean ${mz.mean_human_total}, max ${mz.max_human_total}.`;
  document.querySelector('#mzTable tbody').innerHTML = mz.top_frames.map(f => `
    <tr onclick="inspectCameraOnMap(${f.camera_id})">
      <td><b>${f.camera_id}</b></td>
      <td>${esc(f.name)}</td>
      <td>${esc(f.timestamp)}</td>
      <td>${esc(f.junction_type)}</td>
      <td class="num"><b>${f.human_total}</b></td>
      <td class="num">${f.human_car}</td>
      <td class="num">${f.human_motorcycle}</td>
    </tr>
  `).join('');
}

// ---- TAB 5: CAMERA HEALTH & POLICY BLUEPRINT ----
function initPolicyTab() {
  const chp = SUMMARY.camera_health_paradox;
  document.getElementById('healthParadoxChart').innerHTML = chp.groups.map(g => {
    const col = g.frozen_camera_pct >= 26 ? 'var(--coral)' : (g.frozen_camera_pct >= 14 ? 'var(--accent)' : 'var(--teal)');
    return `
      <div class="chart-bar-row">
        <div><b>${esc(g.segment)}</b><div class="muted">${g.frozen_cameras}/${g.cameras} cams</div></div>
        <div style="background:var(--bg2); border-radius:6px; height:20px; overflow:hidden;">
          <div class="chart-fill" style="width:${(g.frozen_camera_pct/40*100).toFixed(1)}%; background:${col};"></div>
        </div>
        <div class="num"><b>${g.frozen_camera_pct}%</b> (${g.total_frozen_frames} fr)</div>
      </div>
    `;
  }).join('') + `<div class="muted" style="margin-top:8px;">Permutation p: Busy vs Quiet = ${chp.busy_vs_quiet_perm_p}, Intersection vs Mid-block = ${chp.inter_vs_mid_perm_p}.</div>`;

  const bs = CLUSTERS.outer_blind_spots;
  const bsList = [
    ['North (>13.84°N)', bs.north_gt_13_84.cameras, bs.north_gt_13_84.districts, 'var(--coral)'],
    ['South (<13.68°N)', bs.south_lt_13_68.cameras, bs.south_lt_13_68.districts, 'var(--coral)'],
    ['East (>100.62°E)', bs.east_gt_100_62.cameras, bs.east_gt_100_62.districts, 'var(--accent)'],
    ['West (<100.45°E)', bs.west_lt_100_45.cameras, bs.west_lt_100_45.districts, 'var(--accent)'],
  ];
  document.getElementById('blindSpotGrid').innerHTML = bsList.map(([t, cnt, dist, col]) => `
    <div class="mcell" style="border-color:${col}">
      <div style="font-size:12px; font-weight:700;">${esc(t)}</div>
      <div class="big" style="color:${col}">${cnt} cameras</div>
      <div class="muted">${esc(dist)}</div>
    </div>
  `).join('');

  document.getElementById('top10Cards').innerHTML = SUMMARY.top10_upgrade_priority.map(it => `
    <div class="story-card" onclick="inspectCameraOnMap(${it.camera_id})">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span class="tag">#${it.rank} · Cam ${it.camera_id} · Score ${it.upgrade_priority_score}</span>
        <span class="pill ${it.bridged_frozen > 20 ? 'bad' : 'warn'}">${it.bridged_frozen} frozen frames</span>
      </div>
      <div class="headline">${esc(it.name)}</div>
      <div class="desc">${esc(it.junction_type)} (${esc(it.road_class)}) · Traffic <b>${it.band_w_mean.toFixed(1)}</b> · ${it.n_mall_500m} malls (${esc(it.top_malls_500m || it.nearest_rail_name)})</div>
    </div>
  `).join('');

  renderMasterTable();
}

function sortTable(key) {
  if (sortKey === key) sortAsc = !sortAsc;
  else { sortKey = key; sortAsc = key === 'upgrade_rank' || key === 'camera_id' || key === 'name'; }
  renderMasterTable();
}

function renderMasterTable() {
  const q = document.getElementById('tableSearch').value.trim().toLowerCase();
  const rows = CAMS.filter(c => {
    if (!q) return true;
    return `${c.camera_id} ${c.name} ${c.location_th} ${c.zone} ${c.top_malls_500m}`.toLowerCase().includes(q);
  }).sort((a, b) => {
    const va = a[sortKey] ?? -999999, vb = b[sortKey] ?? -999999;
    if (typeof va === 'string') return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
    return sortAsc ? va - vb : vb - va;
  });

  document.querySelector('#masterTable tbody').innerHTML = rows.map(c => `
    <tr onclick="inspectCameraOnMap(${c.camera_id})">
      <td><b>#${c.upgrade_rank}</b></td>
      <td>${c.camera_id}</td>
      <td>${esc(c.name)}</td>
      <td>${c.is_old_city ? 'Old City' : 'Modern CBD'}</td>
      <td>${esc(c.junction_type)}</td>
      <td class="num"><b>${c.band_w_mean.toFixed(1)}</b></td>
      <td class="num">${c.n_mall_500m}</td>
      <td class="num">${c.n_rail_500m}</td>
      <td class="num">${c.elevation_m ?? '—'}</td>
      <td class="num" style="color:${c.bridged_frozen > 0 ? 'var(--coral)' : 'inherit'}">${c.bridged_frozen}</td>
      <td class="num">${c.gi_star_z >= 0 ? '+' : ''}${c.gi_star_z}</td>
    </tr>
  `).join('');
}

function exportFilteredCsv() {
  const cols = ['upgrade_rank','camera_id','name','zone','road_class','junction_type','band_w_mean','n_mall_500m','n_rail_500m','nearest_mall_name','nearest_mall_m','nearest_rail_name','nearest_rail_m','elevation_m','bridged_frozen','gi_star_z','upgrade_priority_score'];
  const rows = [cols.join(',')];
  for (const c of getFilteredCams()) {
    rows.push(cols.map(k => `"${String(c[k] ?? '').replace(/"/g, '""')}"`).join(','));
  }
  const blob = new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'bangkok_cctv_spatial_profile.csv';
  a.click();
}

function pulseColor(val) {
  if (val === null || val === undefined) return 'rgba(244,241,232,0.12)';
  if (val >= 28) return '#b91c1c';
  if (val >= 22) return '#dc2626';
  if (val >= 16) return '#f97316';
  if (val >= 11) return '#f59e0b';
  return '#fde68a';
}

function setPulseBand(band) {
  pulseBand = band;
  document.querySelectorAll('#pulseBandBtns button').forEach(b => {
    b.classList.toggle('primary', b.dataset.band === band);
  });
  renderPulse();
}

function togglePulsePlay() {
  const btn = document.getElementById('pulsePlayBtn');
  if (pulseTimer) {
    clearInterval(pulseTimer);
    pulseTimer = null;
    btn.textContent = '▶ Play Time Animation';
  } else {
    const order = ['morning', 'midday', 'evening', 'night'];
    pulseTimer = setInterval(() => {
      const idx = (order.indexOf(pulseBand) + 1) % order.length;
      setPulseBand(order[idx]);
    }, 1800);
    btn.textContent = '⏸ Pause';
  }
}

function togglePulseExtent() {
  pulseFullExtent = !pulseFullExtent;
  document.getElementById('pulseExtentBtn').textContent = pulseFullExtent ? 'View: Full 50 Districts' : 'View: Inner Core Zoom';
  renderPulse();
}

function selectPulseDistrict(nameTh) {
  selectedDistrictTh = nameTh;
  renderPulse();
}

function renderPulse() {
  if (!PULSE || !PULSE.districts) return;
  const svg = document.getElementById('pulseSvg');
  const dt = document.getElementById('pulseDaytype').value;
  const showDistLbl = document.getElementById('pulseChkDistLbl').checked;
  const showCamLbl = document.getElementById('pulseChkCamLbl').checked;
  const proj = makeProjector(pulseFullExtent);

  const st = (PULSE.story_stops || {})[pulseBand] || {};
  document.getElementById('pulseStoryBox').innerHTML = `
    <div style="font-size:15.5px; font-weight:800; color:var(--accent);">${esc(st.title || pulseBand)}</div>
    <div style="font-size:13px; color:var(--text2); margin-top:4px;">${esc(st.story || '')}</div>
  `;

  let out = '';
  // Polygons of all 50 Bangkok Districts
  for (const d of PULSE.districts) {
    const bstat = d.bands[dt][pulseBand] || {};
    const meanV = d.camera_count > 0 ? bstat.mean : null;
    const fill = pulseColor(meanV);
    const isSel = d.name_th === selectedDistrictTh;
    const stroke = isSel ? '#38bdf8' : (d.camera_count > 0 ? '#7f1d1d' : '#475569');
    const sw = isSel ? '2.6' : (d.camera_count > 0 ? '1.3' : '0.75');
    for (const poly of d.polys) {
      const pts = poly[0].map(p => proj(p[1], p[0]).map(v => v.toFixed(1)).join(',')).join(' ');
      out += `<polygon points="${pts}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" style="cursor:pointer" onclick="selectPulseDistrict('${esc(d.name_th)}')" onmousemove="showTip(event, 'เขต${esc(d.name_th)} (${esc(d.name_en)}): ' + (${meanV ?? 'null'} !== null ? '${meanV} veh/fr' : '0 cameras'))" onmouseout="hideTip()"/>`;
    }
  }

  // District Thai labels
  if (showDistLbl) {
    for (const d of PULSE.districts) {
      if (!pulseFullExtent && (d.centroid_lon < 100.38 || d.centroid_lon > 100.655 || d.centroid_lat < 13.685 || d.centroid_lat > 13.842)) continue;
      const [lx, ly] = proj(d.centroid_lat, d.centroid_lon);
      const bstat = d.bands[dt][pulseBand] || {};
      const mv = bstat.mean;
      const tcol = (mv !== null && mv >= 16) ? '#ffffff' : '#cbd5e1';
      out += `<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" font-size="${d.camera_count > 0 ? 10 : 8.8}" font-weight="${d.camera_count > 0 ? 700 : 400}" fill="${tcol}" text-anchor="middle" style="pointer-events:none">${esc(d.name_th)}</text>`;
    }
  }

  // Camera dots sized by THIS band's live traffic
  for (const c of PULSE.cameras_pulse) {
    const bv = (c.bands[dt][pulseBand] || {}).total;
    if (bv === null || bv === undefined) continue;
    const [px, py] = proj(c.latitude, c.longitude);
    const rad = Math.max(3.2, Math.min(14, 2.5 + 0.22 * bv));
    const col = bv >= 28 ? '#facc15' : (bv >= 18 ? '#38bdf8' : '#0f172a');
    out += `<circle cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="${rad.toFixed(1)}" fill="${col}" fill-opacity="0.9" stroke="#ffffff" stroke-width="0.9" style="cursor:pointer" onclick="inspectCameraOnMap(${c.camera_id})" onmousemove="showTip(event, 'Cam ${c.camera_id} (เขต${esc(c.district_th)}): ${bv} veh/fr')" onmouseout="hideTip()"/>`;
    if (showCamLbl) {
      out += `<text x="${px.toFixed(1)}" y="${(py - rad - 2).toFixed(1)}" font-size="8.5" fill="#f8fafc" text-anchor="middle" style="pointer-events:none">${c.camera_id}</text>`;
    }
  }

  // Center of Mass trail + current stop marker
  const comMap = (PULSE.center_of_mass || {})[dt] || {};
  const trailPts = ['morning', 'midday', 'evening', 'night'].filter(b => comMap[b]).map(b => proj(comMap[b].lat, comMap[b].lon));
  if (trailPts.length >= 2) {
    out += `<polyline points="${trailPts.map(p => p.map(v => v.toFixed(1)).join(',')).join(' ')}" fill="none" stroke="#22d3ee" stroke-width="2.4" stroke-dasharray="4,3"/>`;
  }
  if (comMap[pulseBand]) {
    const [cx, cy] = proj(comMap[pulseBand].lat, comMap[pulseBand].lon);
    out += `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="8" fill="none" stroke="#22d3ee" stroke-width="2.5"/>`;
    out += `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="3" fill="#22d3ee"/>`;
  }

  svg.innerHTML = out;
  renderPulseInspector(dt);
}

function renderPulseInspector(dt) {
  const d = PULSE.districts.find(x => x.name_th === selectedDistrictTh) || PULSE.districts.find(x => x.camera_count > 0);
  const bandLabels = { morning: 'เช้า 06–09', midday: 'กลางวัน 10–16', evening: 'เย็น 17–18', night: 'ดึก 19–21' };
  const barsHtml = ['morning', 'midday', 'evening', 'night'].map(b => {
    const mv = (d.bands[dt][b] || {}).mean;
    const w = mv ? Math.min(100, mv / 42 * 100).toFixed(1) : '0';
    const isCur = b === pulseBand;
    return `
      <div style="display:grid; grid-template-columns:105px 1fr 54px; gap:8px; align-items:center; margin:6px 0; font-size:12px;">
        <div style="font-weight:${isCur ? 800 : 400}; color:${isCur ? 'var(--accent)' : 'var(--text2)'}">${bandLabels[b]}</div>
        <div style="background:var(--bg2); border-radius:4px; height:16px; overflow:hidden;">
          <div style="height:100%; width:${w}%; background:${isCur ? 'var(--coral)' : 'var(--blue)'};"></div>
        </div>
        <div class="num"><b>${mv !== null && mv !== undefined ? mv : '—'}</b></div>
      </div>
    `;
  }).join('');

  const topDists = PULSE.districts
    .filter(x => x.camera_count > 0 && x.bands[dt][pulseBand].mean !== null)
    .sort((a, b) => b.bands[dt][pulseBand].mean - a.bands[dt][pulseBand].mean)
    .slice(0, 6);

  document.getElementById('pulseInspector').innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <span class="pill ok">เขต${esc(d.name_th)} (${esc(d.name_en)})</span>
      <span class="pill">${d.camera_count} cameras</span>
    </div>
    <h3 style="margin:10px 0 4px;">ชีพจรการจราจรของเขต${esc(d.name_th)}</h3>
    <div class="muted" style="margin-bottom:8px;">คลิกเขตบนแผนที่เพื่อดูกราฟเวลา หรือคลิกวงกลมกล้องเพื่อเปิดข้อมูลละเอียด</div>
    ${d.camera_count > 0 ? barsHtml : '<div class="pill warn">0 กล้องในชุดข้อมูลนี้ (พื้นที่บอดรอบนอก)</div>'}

    <h3 style="margin:16px 0 6px; color:var(--accent);">Top 6 เขตที่รถแน่นสุดในช่วง "${bandLabels[pulseBand]}"</h3>
    ${topDists.map((td, idx) => `
      <div class="stat-row" style="cursor:pointer" onclick="selectPulseDistrict('${esc(td.name_th)}')">
        <span>#${idx + 1} เขต${esc(td.name_th)} (${td.camera_count} cams)</span>
        <b>${td.bands[dt][pulseBand].mean} veh/fr</b>
      </div>
    `).join('')}

    <h3 style="margin:16px 0 6px; color:var(--coral);">Early-Bird vs Night-Owl (สะอาด 100%)</h3>
    <div class="muted"><b>เช้าพีค:</b> ${PULSE.early_birds.slice(0, 2).map(x => `Cam ${x.camera_id} เขต${esc(x.district_th)} (${x.morning}→${x.night})`).join(' · ')}</div>
    <div class="muted" style="margin-top:4px;"><b>ดึกพีค:</b> ${PULSE.night_owls.slice(0, 2).map(x => `Cam ${x.camera_id} เขต${esc(x.district_th)} (${x.morning}→${x.night})`).join(' · ')}</div>
  `;
}

initStoryTab();
renderPulse();
renderInspector();
renderMap();
initIntersectionsTab();
initModalTab();
initPolicyTab();
</script>
</body>
</html>
"""


def build_dashboard(in_dir: Path, fig_dir: Path, out_path: Path) -> Path:
    payload = _load_dashboard_payload(in_dir)
    inline_svg = _load_inline_infographic(fig_dir)
    html_out = HTML_TEMPLATE.replace("__JSON_PAYLOAD__", _safe_json_for_html(payload)).replace(
        "__INLINE_INFOGRAPHIC__", inline_svg
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_out, encoding="utf-8")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in-dir", type=Path, default=Path("reports/insights"))
    parser.add_argument("--fig-dir", type=Path, default=Path("reports/figures/spatial_insights"))
    parser.add_argument("--out", type=Path, default=Path("reports/bangkok_spatial_dashboard.html"))
    args = parser.parse_args()
    p = build_dashboard(args.in_dir, args.fig_dir, args.out)
    print(f"wrote {p} ({p.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
