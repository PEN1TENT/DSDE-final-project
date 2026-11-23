"""Stdlib-only forensic verifier for the 100-camera Bangkok CCTV raw corpus.

Scans `data/100_cameras/cctv_info.csv` and `data/100_cameras/cctv_images/`,
dynamically strips appended ASP.NET HTML tails after JPEG EOI / PNG IEND,
classifies container anomalies (blank white PNGs, truncated JPEGs, GStreamer
SMPTE color bars), detects strict and PNG-bridged frozen streaks, tracks batch
phase switching and same-day gaps, and writes structured CSV/JSON artifacts to
`reports/forensics/`.

Runnable under Python 3.12–3.15 using only the Python standard library:
    python -m cctv.forensics
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import os
import re
import statistics
import struct
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

BANGKOK_TZ = timezone(timedelta(hours=7))
JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"
PNG_SIG = b"\x89PNG\r\n\x1a\n"
PNG_IEND = b"\x49\x45\x4e\x44\xae\x42\x60\x82"
GST_BARS_MD5 = "4a6d31be2e3b9feafae84b191169d708"

_FILENAME_RE = re.compile(r"^(\d+)_(.+)_(\d{8})_(\d{6})\.jpg$")
_HTML_START_RE = re.compile(rb"(?:\r\n|\n)*<!DOCTYPE\s+html", re.IGNORECASE)
_TAIL_ACTION_RE = re.compile(rb'action="\./show\.aspx\?image=(\d+)&(?:amp;)?time=(\d+)"')

_SOF_MARKERS = {
    0xC0, 0xC1, 0xC2, 0xC3,
    0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB,
    0xCD, 0xCE, 0xCF,
}

# Visually inspected burned-in OSD frames (verified directly via view_file;
# programmatic EXIF/MD5/size fields are computed dynamically from the files).
VERIFIED_OSD_SAMPLES: list[dict[str, Any]] = [
    {
        "camera_id": "150",
        "filename": "150_สะพานลอยใกล้-โรงเรียนสามเสน_รถมาจากแยกอารีย์สัมพันธ์-มุ_20260825_061023.jpg",
        "osd_text": "TF2-PY-VP16-01 25-08-2026 Tue 06:15:47",
        "verified_year": 2026,
        "verified_weekday": "Tue",
        "clock_offset_sec": 324,
        "notes": "Live frame; +5m24s camera clock offset vs filename",
    },
    {
        "camera_id": "150",
        "filename": "150_สะพานลอยใกล้-โรงเรียนสามเสน_รถมาจากแยกอารีย์สัมพันธ์-มุ_20260827_073603.jpg",
        "osd_text": "TF2-PY-VP16-01 26-08-2026 Wed 19:41:12",
        "verified_year": 2026,
        "verified_weekday": "Wed",
        "clock_offset_sec": -42891,
        "notes": "Frozen nighttime frame from 26 Aug 19:41:12 served during Thu 27 Aug morning outage",
    },
    {
        "camera_id": "150",
        "filename": "150_สะพานลอยใกล้-โรงเรียนสามเสน_รถมาจากแยกอารีย์สัมพันธ์-มุ_20260831_180105.jpg",
        "osd_text": "TF2-PY-VP16-01 31-08-2026 Mon 16:47:08",
        "verified_year": 2026,
        "verified_weekday": "Mon",
        "clock_offset_sec": -4437,
        "notes": "Frozen feed from 16:47:08 during Mon 31 Aug evening",
    },
    {
        "camera_id": "432",
        "filename": "432_ทางแยกสามย่าน_ทางแยกสามย่าน_20260827_070021.jpg",
        "osd_text": "gst-launch-0.10 (SMPTE color bars)",
        "verified_year": "",
        "verified_weekday": "",
        "clock_offset_sec": "",
        "notes": "246x205 GStreamer test-pattern frame during Thu 27 Aug morning outage",
    },
    {
        "camera_id": "1804",
        "filename": "1804_ปากซอยอ่อนนุข-33_ท้ายรถมุ่งหน้าแยกสวนหลวง_20260827_070530.jpg",
        "osd_text": "gst-launch-0.10 (SMPTE color bars)",
        "verified_year": "",
        "verified_weekday": "",
        "clock_offset_sec": "",
        "notes": "Identical 246x205 GStreamer test-pattern MD5 during Thu 27 Aug morning outage",
    },
    {
        "camera_id": "395",
        "filename": "395_แยกเสาชิงช้า_แยกเสาชิงช้า_20260828_120103.jpg",
        "osd_text": "PN-22-C3 28-08-2026 00:12:01",
        "verified_year": 2026,
        "verified_weekday": "",
        "clock_offset_sec": -42542,
        "notes": "Midnight frame frozen continuously from 06:01:01 through 16:00:57",
    },
    {
        "camera_id": "206",
        "filename": "206_สะพานลอยใกล้ซอยนราธิวาสราช_รถมาจากแยกรัชดา-นราธิวาส-มุ่_20260829_102604.jpg",
        "osd_text": "TF2-YW-U69-CAM1 29/08/2026 10:19:29",
        "verified_year": 2026,
        "verified_weekday": "",
        "clock_offset_sec": -395,
        "notes": "Live frame prior to 29-30 Aug freeze; -6m35s clock drift",
    },
    {
        "camera_id": "177",
        "filename": "177_สะพานลอยหน้าสวนจตุจักร-ถนนพ_รถมาจากกำแพงเพชร-มุ่งหน้าไป_20260828_150119.jpg",
        "osd_text": "TF2-JJ-VP48-02 28-08-2026 Fri 15:01:21",
        "verified_year": 2026,
        "verified_weekday": "Fri",
        "clock_offset_sec": 2,
        "notes": "Live frame; +2s clock alignment",
    },
    {
        "camera_id": "194",
        "filename": "194_สะพานลอยใกล้ปากซอยคอนแวนต์_รถมาจากแยกสาทร-นราธิวาส-มุ่ง_20260830_122612.jpg",
        "osd_text": "TF2-BR-VP67-01 30-08-2026 Sun 12:27:58",
        "verified_year": 2026,
        "verified_weekday": "Sun",
        "clock_offset_sec": 106,
        "notes": "Live recovery frame after 10.128.0.0/16 event; +1m46s clock offset",
    },
    {
        "camera_id": "137",
        "filename": "137_สะพานลอยใกล้บิ๊กซีเอ็กซ์ตร_รถมาจากแยกรัชดา-ลาดพร้าว-มุ่_20260830_140613.jpg",
        "osd_text": "TF2-JJ-VP9-02 30-08-2026 Sun 14:11:47",
        "verified_year": 2026,
        "verified_weekday": "Sun",
        "clock_offset_sec": 334,
        "notes": "Live frame; +5m34s clock offset",
    },
    {
        "camera_id": "36",
        "filename": "36_แยกรัชดา-ราชพฤกษ์-ด้านถนนราช_รถมาจากแยกตากสิน_20260825_101548.jpg",
        "osd_text": "TF2-TR-S24-02 25 Aug 2026 10:15:46",
        "verified_year": 2026,
        "verified_weekday": "",
        "clock_offset_sec": -2,
        "notes": "Last live frame before 25-min gap (10:15-10:40)",
    },
    {
        "camera_id": "36",
        "filename": "36_แยกรัชดา-ราชพฤกษ์-ด้านถนนราช_รถมาจากแยกตากสิน_20260831_180049.jpg",
        "osd_text": "TF2-TR-S24-02 31 Aug 2026 18:00:55",
        "verified_year": 2026,
        "verified_weekday": "",
        "clock_offset_sec": 6,
        "notes": "Live wet-road frame during Mon 31 Aug evening rain",
    },
]


@dataclass(frozen=True)
class ContainerInspection:
    container: str  # "jpeg", "png", "truncated_jpeg", "truncated_png", "unknown"
    core_bytes: bytes
    core_md5: str
    full_md5: str
    file_bytes: int
    has_html_tail: bool
    tail_camera_id: str | None
    tail_epoch_ms: int | None
    width: int | None
    height: int | None
    has_exif: bool
    white_png: bool
    truncated_jpeg: bool
    gst_bars: bool


@dataclass
class FrameRecord:
    camera_id: str
    filename: str
    filepath: Path
    timestamp: datetime
    container: str
    frame_kind: str  # "live_jpeg", "white_png", "truncated_jpeg", "gst_bars", "unknown"
    core_md5: str
    full_md5: str
    file_bytes: int
    core_len: int
    width: int | None
    height: int | None
    has_exif: bool
    has_html_tail: bool
    tail_epoch_ms: int | None
    phase: str  # "A" or "B"
    strict_frozen: bool = False
    bridged_frozen: bool = False


def parse_filename(name: str) -> tuple[str, datetime] | None:
    """Parse `<camera_id>_..._<YYYYMMDD>_<HHMMSS>.jpg` into `(camera_id, naive_dt)`."""
    match = _FILENAME_RE.match(name)
    if not match:
        return None
    cam_id, _, ymd, hms = match.groups()
    try:
        dt = datetime.strptime(ymd + hms, "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return cam_id, dt


def ip_subnets(ip_address: str) -> tuple[str, str]:
    """Return `(/16 CIDR, /24 CIDR)` strings for an IPv4 address."""
    parts = ip_address.strip().split(".")
    if len(parts) != 4:
        return ("", "")
    return (f"{parts[0]}.{parts[1]}.0.0/16", f"{parts[0]}.{parts[1]}.{parts[2]}.0/24")


def strip_html_tail(data: bytes) -> tuple[bytes, bytes, str]:
    """Separate core image bytes from any appended HTML payload.

    Returns `(core_bytes, tail_bytes, container_kind)`.
    """
    html_match = _HTML_START_RE.search(data)
    html_pos = html_match.start() if html_match else -1

    if data.startswith(PNG_SIG):
        search_limit = html_pos if html_pos != -1 else len(data)
        iend_pos = data.find(PNG_IEND, 0, search_limit)
        if iend_pos != -1:
            end = iend_pos + len(PNG_IEND)
            return data[:end], data[end:], "png"
        if html_pos != -1:
            return data[:html_pos], data[html_pos:], "truncated_png"
        return data, b"", "truncated_png"

    if data.startswith(JPEG_SOI):
        search_limit = html_pos if html_pos != -1 else len(data)
        eoi_pos = data.rfind(JPEG_EOI, 0, search_limit)
        if eoi_pos != -1:
            end = eoi_pos + len(JPEG_EOI)
            return data[:end], data[end:], "jpeg"
        if html_pos != -1:
            return data[:html_pos], data[html_pos:], "truncated_jpeg"
        return data, b"", "truncated_jpeg"

    if html_pos != -1:
        return data[:html_pos], data[html_pos:], "unknown"
    return data, b"", "unknown"


def parse_jpeg_metadata(core: bytes) -> tuple[int | None, int | None, bool]:
    """Parse `(width, height, has_exif)` from JPEG bytes using stdlib only."""
    n = len(core)
    if n < 4 or not core.startswith(JPEG_SOI):
        return None, None, False
    pos = 2
    width = height = None
    has_exif = False
    while pos < n - 1:
        if core[pos] != 0xFF:
            pos += 1
            continue
        while pos < n and core[pos] == 0xFF:
            pos += 1
        if pos >= n:
            break
        marker = core[pos]
        pos += 1
        if marker in (0xD8, 0xD9, 0x00) or (0xD0 <= marker <= 0xD7):
            if marker == 0xD9:
                break
            continue
        if marker == 0xDA:  # Start of Scan; metadata headers are complete.
            break
        if pos + 2 > n:
            break
        seg_len = struct.unpack(">H", core[pos:pos + 2])[0]
        if seg_len < 2 or pos + seg_len > n:
            break
        seg_data = core[pos + 2:pos + seg_len]
        if marker == 0xE1 and seg_data.startswith(b"Exif\x00\x00"):
            has_exif = True
        elif marker in _SOF_MARKERS and len(seg_data) >= 5:
            height, width = struct.unpack(">HH", seg_data[1:5])
        pos += seg_len
    return width, height, has_exif


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def parse_png_metadata(core: bytes) -> tuple[int | None, int | None, bool]:
    """Parse `(width, height, is_solid_white)` from PNG chunks via stdlib `zlib`."""
    if not core.startswith(PNG_SIG):
        return None, None, False
    pos = len(PNG_SIG)
    n = len(core)
    width = height = bit_depth = color_type = None
    idat_parts: list[bytes] = []
    while pos + 8 <= n:
        chunk_len = struct.unpack(">I", core[pos:pos + 4])[0]
        chunk_type = core[pos + 4:pos + 8]
        data_start = pos + 8
        data_end = data_start + chunk_len
        if data_end + 4 > n:
            break
        chunk_data = core[data_start:data_end]
        if chunk_type == b"IHDR" and len(chunk_data) >= 13:
            width, height, bit_depth, color_type = struct.unpack(">IIBB", chunk_data[:10])
        elif chunk_type == b"IDAT":
            idat_parts.append(chunk_data)
        elif chunk_type == b"IEND":
            break
        pos = data_end + 4

    is_white = False
    if width and height and bit_depth == 8 and color_type in (0, 2, 6) and idat_parts:
        bpp = {0: 1, 2: 3, 6: 4}[color_type]
        stride = width * bpp
        try:
            raw = zlib.decompress(b"".join(idat_parts))
        except zlib.error:
            return width, height, False
        if len(raw) == height * (1 + stride):
            prev = bytearray(stride)
            all_white = True
            for row_idx in range(height):
                row_start = row_idx * (1 + stride)
                flt = raw[row_start]
                scan = raw[row_start + 1:row_start + 1 + stride]
                cur = bytearray(stride)
                if flt == 0:
                    cur[:] = scan
                elif flt == 1:
                    for i in range(stride):
                        cur[i] = (scan[i] + (cur[i - bpp] if i >= bpp else 0)) & 0xFF
                elif flt == 2:
                    for i in range(stride):
                        cur[i] = (scan[i] + prev[i]) & 0xFF
                elif flt == 3:
                    for i in range(stride):
                        left = cur[i - bpp] if i >= bpp else 0
                        cur[i] = (scan[i] + ((left + prev[i]) >> 1)) & 0xFF
                elif flt == 4:
                    for i in range(stride):
                        left = cur[i - bpp] if i >= bpp else 0
                        up = prev[i]
                        up_left = prev[i - bpp] if i >= bpp else 0
                        cur[i] = (scan[i] + _paeth(left, up, up_left)) & 0xFF
                else:
                    all_white = False
                    break
                if any(b != 255 for b in cur):
                    all_white = False
                    break
                prev = cur
            is_white = all_white
    return width, height, is_white


def inspect_bytes(
    data: bytes,
    png_white_cache: dict[str, bool] | None = None,
) -> ContainerInspection:
    """Inspect one image file's bytes for tail, container, dimensions, EXIF, and flags."""
    core, tail, container = strip_html_tail(data)
    core_md5 = hashlib.md5(core).hexdigest()
    full_md5 = hashlib.md5(data).hexdigest()

    has_html_tail = bool(_HTML_START_RE.match(tail))
    tail_cam: str | None = None
    tail_epoch_ms: int | None = None
    if tail:
        m = _TAIL_ACTION_RE.search(tail)
        if m:
            tail_cam = m.group(1).decode("ascii", errors="ignore")
            tail_epoch_ms = int(m.group(2))
            has_html_tail = True

    width: int | None = None
    height: int | None = None
    has_exif = False
    white_png = False

    if container == "jpeg":
        width, height, has_exif = parse_jpeg_metadata(core)
    elif container == "png":
        if png_white_cache is not None and core_md5 in png_white_cache:
            # Parse only IHDR quickly if white status for this MD5 is already cached.
            if len(core) >= 24 and core[12:16] == b"IHDR":
                width, height = struct.unpack(">II", core[16:24])
            white_png = png_white_cache[core_md5]
        else:
            width, height, white_png = parse_png_metadata(core)
            if png_white_cache is not None:
                png_white_cache[core_md5] = white_png

    truncated_jpeg = container == "truncated_jpeg"
    gst_bars = container == "jpeg" and core_md5 == GST_BARS_MD5
    return ContainerInspection(
        container=container,
        core_bytes=core,
        core_md5=core_md5,
        full_md5=full_md5,
        file_bytes=len(data),
        has_html_tail=has_html_tail,
        tail_camera_id=tail_cam,
        tail_epoch_ms=tail_epoch_ms,
        width=width,
        height=height,
        has_exif=has_exif,
        white_png=white_png,
        truncated_jpeg=truncated_jpeg,
        gst_bars=gst_bars,
    )


def _classify_kind(ins: ContainerInspection) -> str:
    if ins.white_png:
        return "white_png"
    if ins.container == "png":
        return "nonwhite_png"
    if ins.truncated_jpeg:
        return "truncated_jpeg"
    if ins.gst_bars:
        return "gst_bars"
    if ins.container == "jpeg":
        return "live_jpeg"
    return "unknown"


def _is_valid_core_for_freeze(rec: FrameRecord) -> bool:
    return rec.container == "jpeg"


def compute_frozen_and_streaks(
    records: list[FrameRecord],
    cam_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Annotate `strict_frozen` and `bridged_frozen` in place and return bridged streak rows."""
    if not records:
        return []

    # 1) Strict consecutive identical valid JPEG core MD5
    for i in range(1, len(records)):
        prev_r, cur_r = records[i - 1], records[i]
        if _is_valid_core_for_freeze(prev_r) and _is_valid_core_for_freeze(cur_r):
            if cur_r.core_md5 == prev_r.core_md5:
                cur_r.strict_frozen = True

    # 2) PNG-bridged streaks (ignore intervening white_png / truncated_jpeg placeholders)
    valid_indices = [idx for idx, r in enumerate(records) if _is_valid_core_for_freeze(r)]
    last_valid_md5: str | None = None
    for idx in valid_indices:
        cur_r = records[idx]
        if last_valid_md5 is not None and cur_r.core_md5 == last_valid_md5:
            cur_r.bridged_frozen = True
        last_valid_md5 = cur_r.core_md5

    streaks: list[dict[str, Any]] = []
    pos = 0
    while pos < len(valid_indices):
        start_idx = valid_indices[pos]
        anchor_md5 = records[start_idx].core_md5
        end_pos = pos + 1
        while end_pos < len(valid_indices) and records[valid_indices[end_pos]].core_md5 == anchor_md5:
            end_pos += 1
        streak_len = end_pos - pos
        if streak_len >= 2:
            end_idx = valid_indices[end_pos - 1]
            bridged = any(not _is_valid_core_for_freeze(records[k]) for k in range(start_idx, end_idx + 1))
            s16, _ = ip_subnets(cam_meta.get("ip_address", ""))
            streaks.append(
                {
                    "camera_id": records[start_idx].camera_id,
                    "ip_address": cam_meta.get("ip_address", ""),
                    "subnet_16": s16,
                    "location_en": cam_meta.get("location_en", ""),
                    "md5_core": anchor_md5,
                    "start_ts": records[start_idx].timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    "end_ts": records[end_idx].timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    "repeat_count": streak_len - 1,
                    "streak_frames": streak_len,
                    "bridged_by_png": bridged,
                    "is_gst_bars": records[start_idx].frame_kind == "gst_bars",
                }
            )
        pos = end_pos
    return streaks


def _format_ts(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt is not None else ""


def _build_neighbor_context(
    target_cam: str,
    target_subnet: str,
    start_dt: datetime,
    end_dt: datetime,
    live_ts_by_cam: dict[str, list[datetime]],
    cam_subnets: dict[str, str],
) -> str:
    """Count peer cameras missing live JPEGs strictly inside `(start_dt, end_dt)`."""
    fleet_missing = 0
    subnet_missing = 0
    subnet_peers = 0
    for cid, ts_list in live_ts_by_cam.items():
        if cid == target_cam:
            continue
        is_same_subnet = bool(target_subnet and cam_subnets.get(cid) == target_subnet)
        if is_same_subnet:
            subnet_peers += 1
        idx = bisect.bisect_right(ts_list, start_dt)
        has_live_inside = idx < len(ts_list) and ts_list[idx] < end_dt
        if not has_live_inside:
            fleet_missing += 1
            if is_same_subnet:
                subnet_missing += 1
    return f"fleet_no_live_midgap={fleet_missing}/{max(0, len(live_ts_by_cam) - 1)}; subnet_no_live_midgap={subnet_missing}/{subnet_peers}"


def run_forensics(
    info_csv: Path,
    images_dir: Path,
    out_dir: Path,
) -> dict[str, Any]:
    """Scan the raw CCTV corpus and write all 8 forensic deliverables to `out_dir`."""
    with info_csv.open("r", encoding="utf-8-sig", newline="") as f:
        info_rows = list(csv.DictReader(f))
    cam_meta_map: dict[str, dict[str, str]] = {r["camera_id"].strip(): r for r in info_rows}
    cam_ids = sorted(cam_meta_map.keys(), key=lambda c: (0, int(c)) if c.isdigit() else (1, c))
    cam_subnets = {cid: ip_subnets(cam_meta_map[cid].get("ip_address", ""))[0] for cid in cam_ids}

    png_white_cache: dict[str, bool] = {}
    all_records: dict[str, list[FrameRecord]] = {}
    all_streaks: list[dict[str, Any]] = []
    no_eoi_rows: list[dict[str, Any]] = []

    image_count_mismatches = 0
    unparseable_filenames = 0
    jpeg_dims: Counter[str] = Counter()
    png_dims: Counter[str] = Counter()
    exif_count = 0
    html_tail_count = 0
    epoch_diffs_sec: list[float] = []
    min_ts: datetime | None = None
    max_ts: datetime | None = None
    min_tod: time | None = None
    max_tod: time | None = None
    before_0600 = 0
    after_2101 = 0
    between_2100_2101 = 0
    dates_seen: set[date] = set()

    for cid in cam_ids:
        cam_dir = images_dir / cid
        recs: list[FrameRecord] = []
        if cam_dir.is_dir():
            for entry in sorted(os.scandir(cam_dir), key=lambda e: e.name):
                if not entry.is_file():
                    continue
                parsed = parse_filename(entry.name)
                if parsed is None:
                    unparseable_filenames += 1
                    continue
                parsed_cid, dt = parsed
                if parsed_cid != cid:
                    unparseable_filenames += 1
                    continue

                filepath = Path(entry.path)
                data = filepath.read_bytes()
                ins = inspect_bytes(data, png_white_cache=png_white_cache)
                kind = _classify_kind(ins)
                phase = "A" if dt.minute % 10 < 5 else "B"

                if ins.has_html_tail:
                    html_tail_count += 1
                if ins.tail_epoch_ms is not None:
                    epoch_dt = datetime.fromtimestamp(ins.tail_epoch_ms / 1000.0, tz=BANGKOK_TZ).replace(tzinfo=None)
                    epoch_diffs_sec.append((epoch_dt - dt).total_seconds())
                if ins.container == "jpeg":
                    if ins.has_exif:
                        exif_count += 1
                    if ins.width and ins.height:
                        jpeg_dims[f"{ins.width}x{ins.height}"] += 1
                elif ins.container == "png":
                    if ins.width and ins.height:
                        png_dims[f"{ins.width}x{ins.height}"] += 1

                if ins.container != "jpeg":
                    no_eoi_rows.append(
                        {
                            "camera_id": cid,
                            "filename": entry.name,
                            "filepath": str(filepath.as_posix()),
                            "date": dt.date().isoformat(),
                            "timestamp": _format_ts(dt),
                            "file_type": kind,
                            "file_bytes": ins.file_bytes,
                            "core_bytes": len(ins.core_bytes),
                            "core_md5": ins.core_md5,
                            "width": ins.width if ins.width is not None else "",
                            "height": ins.height if ins.height is not None else "",
                            "has_html_tail": ins.has_html_tail,
                            "tail_epoch_ms": ins.tail_epoch_ms if ins.tail_epoch_ms is not None else "",
                        }
                    )

                rec = FrameRecord(
                    camera_id=cid,
                    filename=entry.name,
                    filepath=filepath,
                    timestamp=dt,
                    container=ins.container,
                    frame_kind=kind,
                    core_md5=ins.core_md5,
                    full_md5=ins.full_md5,
                    file_bytes=ins.file_bytes,
                    core_len=len(ins.core_bytes),
                    width=ins.width,
                    height=ins.height,
                    has_exif=ins.has_exif,
                    has_html_tail=ins.has_html_tail,
                    tail_epoch_ms=ins.tail_epoch_ms,
                    phase=phase,
                )
                recs.append(rec)

                dates_seen.add(dt.date())
                if min_ts is None or dt < min_ts:
                    min_ts = dt
                if max_ts is None or dt > max_ts:
                    max_ts = dt
                tod = dt.time()
                if min_tod is None or tod < min_tod:
                    min_tod = tod
                if max_tod is None or tod > max_tod:
                    max_tod = tod
                if tod < time(6, 0, 0):
                    before_0600 += 1
                elif tod >= time(21, 2, 0):
                    after_2101 += 1
                elif tod >= time(21, 0, 0):
                    between_2100_2101 += 1

        recs.sort(key=lambda r: (r.timestamp, r.filename))
        expected_str = cam_meta_map[cid].get("image_count", "").strip()
        if expected_str.isdigit() and int(expected_str) != len(recs):
            image_count_mismatches += 1
        streaks = compute_frozen_and_streaks(recs, cam_meta_map[cid])
        all_streaks.extend(streaks)
        all_records[cid] = recs

    live_ts_by_cam: dict[str, list[datetime]] = {
        cid: [r.timestamp for r in recs if r.frame_kind == "live_jpeg" and not r.bridged_frozen]
        for cid, recs in all_records.items()
    }

    sorted_dates = sorted(dates_seen)
    thu27 = date(2026, 8, 27)
    has_thu27 = thu27 in dates_seen

    camera_rows: list[dict[str, Any]] = []
    gap_rows: list[dict[str, Any]] = []
    hourly_rows: list[dict[str, Any]] = []
    subnet_agg: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    total_files = 0
    total_valid_jpegs = 0
    total_white_pngs = 0
    total_nonwhite_pngs = 0
    total_trunc = 0
    total_gst = 0
    total_strict_frozen = 0
    total_bridged_frozen = 0
    strict_frozen_cams = 0
    bridged_frozen_cams = 0
    phase_a_frames = 0
    phase_b_frames = 0
    modal_a_strict = 0
    modal_tie = 0
    modal_b_strict = 0
    same_day_switches_total = 0
    overnight_switches_total = 0
    mixed_cameras = 0
    always_a_cameras = 0
    always_b_cameras = 0
    thu_full_pseudo_cams: list[str] = []
    thu_partial_cams: list[str] = []
    thu_zero_cams: list[str] = []
    thu_live_frames = 0

    for cid in cam_ids:
        meta = cam_meta_map[cid]
        recs = all_records[cid]
        ip = meta.get("ip_address", "").strip()
        s16, s24 = ip_subnets(ip)

        n_files = len(recs)
        n_valid_jpegs = sum(1 for r in recs if r.container == "jpeg")
        n_white_pngs = sum(1 for r in recs if r.frame_kind == "white_png")
        n_nonwhite_pngs = sum(1 for r in recs if r.frame_kind == "nonwhite_png")
        n_trunc = sum(1 for r in recs if r.frame_kind == "truncated_jpeg")
        n_gst = sum(1 for r in recs if r.frame_kind == "gst_bars")
        n_strict = sum(1 for r in recs if r.strict_frozen)
        n_bridged = sum(1 for r in recs if r.bridged_frozen)

        total_files += n_files
        total_valid_jpegs += n_valid_jpegs
        total_white_pngs += n_white_pngs
        total_nonwhite_pngs += n_nonwhite_pngs
        total_trunc += n_trunc
        total_gst += n_gst
        total_strict_frozen += n_strict
        total_bridged_frozen += n_bridged
        if n_strict > 0:
            strict_frozen_cams += 1
        if n_bridged > 0:
            bridged_frozen_cams += 1

        n_a = sum(1 for r in recs if r.phase == "A")
        n_b = sum(1 for r in recs if r.phase == "B")
        phase_a_frames += n_a
        phase_b_frames += n_b
        if n_a > n_b:
            modal_a_strict += 1
        elif n_a == n_b:
            modal_tie += 1
        else:
            modal_b_strict += 1
        modal_phase = "A" if n_a >= n_b else "B"

        sd_sw = ov_sw = 0
        for i in range(1, len(recs)):
            if recs[i].phase != recs[i - 1].phase:
                if recs[i].timestamp.date() == recs[i - 1].timestamp.date():
                    sd_sw += 1
                else:
                    ov_sw += 1
        same_day_switches_total += sd_sw
        overnight_switches_total += ov_sw
        if n_a > 0 and n_b > 0:
            mixed_cameras += 1
        elif n_a > 0:
            always_a_cameras += 1
        elif n_b > 0:
            always_b_cameras += 1

        # Thu 27 Aug morning forensics
        thu_am_recs = [
            r for r in recs
            if r.timestamp.date() == thu27 and r.timestamp.time() < time(8, 50, 0)
        ] if has_thu27 else []
        thu_am_count = len(thu_am_recs)
        thu_am_live = sum(
            1 for r in thu_am_recs if r.frame_kind == "live_jpeg" and not r.bridged_frozen
        )
        thu_live_frames += thu_am_live
        if not has_thu27:
            thu_status = "not_in_corpus"
            thu_recovery = None
        else:
            if thu_am_count >= 2:
                thu_status = "full_morning_live" if thu_am_live > 0 else "full_morning_pseudo"
                if thu_status == "full_morning_pseudo":
                    thu_full_pseudo_cams.append(cid)
            elif thu_am_count == 1:
                thu_status = "partial_white_png" if thu_am_recs[0].frame_kind == "white_png" else "partial_other"
                if thu_status == "partial_white_png":
                    thu_partial_cams.append(cid)
            else:
                thu_status = "zero_morning"
                thu_zero_cams.append(cid)

            rec_candidates = [
                r.timestamp for r in recs
                if r.timestamp >= datetime(2026, 8, 27, 8, 50, 0)
                and r.frame_kind == "live_jpeg"
                and not r.bridged_frozen
            ]
            thu_recovery = rec_candidates[0] if rec_candidates else None

            if thu_am_live == 0:
                start_outage = datetime(2026, 8, 27, 6, 0, 0)
                end_outage = thu_recovery if thu_recovery is not None else datetime(2026, 8, 27, 21, 0, 0)
                outage_min = round((end_outage - start_outage).total_seconds() / 60.0, 2)
                if thu_status == "full_morning_pseudo":
                    detail = f"0 live frames; {thu_am_count} pseudo frames ({','.join(sorted({r.frame_kind if not r.bridged_frozen else 'frozen_jpeg' for r in thu_am_recs}))})"
                elif thu_status == "partial_white_png":
                    detail = f"0 live frames; 1 white_png probe at {thu_am_recs[0].timestamp.strftime('%H:%M:%S')}"
                else:
                    detail = "0 captures before 08:50"
                gap_rows.append(
                    {
                        "camera_id": cid,
                        "ip_address": ip,
                        "subnet_16": s16,
                        "location_en": meta.get("location_en", ""),
                        "date": thu27.isoformat(),
                        "start_ts": _format_ts(start_outage),
                        "end_ts": _format_ts(end_outage),
                        "gap_min": outage_min,
                        "gap_class": "thu27_am",
                        "neighbor_context": f"{thu_status}: {detail}",
                    }
                )

        # Same-day gap analysis
        max_same_day_gap = 0.0
        cam_gt20_non_thu_am = 0
        for i in range(1, len(recs)):
            prev_dt, cur_dt = recs[i - 1].timestamp, recs[i].timestamp
            if cur_dt.date() != prev_dt.date():
                continue
            gap_min = (cur_dt - prev_dt).total_seconds() / 60.0
            if gap_min > max_same_day_gap:
                max_same_day_gap = gap_min
            is_thu27_probe_gap = (
                prev_dt.date() == thu27 and prev_dt.time() < time(8, 50, 0) and gap_min > 20.0
            )
            if gap_min > 20.0:
                if not is_thu27_probe_gap:
                    cam_gt20_non_thu_am += 1
                    ctx = _build_neighbor_context(cid, s16, prev_dt, cur_dt, live_ts_by_cam, cam_subnets)
                    gap_rows.append(
                        {
                            "camera_id": cid,
                            "ip_address": ip,
                            "subnet_16": s16,
                            "location_en": meta.get("location_en", ""),
                            "date": cur_dt.date().isoformat(),
                            "start_ts": _format_ts(prev_dt),
                            "end_ts": _format_ts(cur_dt),
                            "gap_min": round(gap_min, 2),
                            "gap_class": ">20m",
                            "neighbor_context": ctx,
                        }
                    )
            elif gap_min > 12.0:
                ctx = _build_neighbor_context(cid, s16, prev_dt, cur_dt, live_ts_by_cam, cam_subnets)
                gap_rows.append(
                    {
                        "camera_id": cid,
                        "ip_address": ip,
                        "subnet_16": s16,
                        "location_en": meta.get("location_en", ""),
                        "date": cur_dt.date().isoformat(),
                        "start_ts": _format_ts(prev_dt),
                        "end_ts": _format_ts(cur_dt),
                        "gap_min": round(gap_min, 2),
                        "gap_class": "12-20m",
                        "neighbor_context": ctx,
                    }
                )

        # Hourly coverage breakdown
        by_dh: dict[tuple[date, int], list[FrameRecord]] = defaultdict(list)
        for r in recs:
            by_dh[(r.timestamp.date(), r.timestamp.hour)].append(r)
        for d_cur in sorted_dates:
            hours_for_day = list(range(6, 21))
            extra_hours = sorted({h for (dd, h) in by_dh if dd == d_cur and h not in hours_for_day})
            for h in hours_for_day + extra_hours:
                cell_recs = by_dh.get((d_cur, h), [])
                if h == 21 and not cell_recs:
                    continue
                hourly_rows.append(
                    {
                        "camera_id": cid,
                        "date": d_cur.isoformat(),
                        "hour": h,
                        "total_files": len(cell_recs),
                        "valid_live_jpegs": sum(
                            1 for r in cell_recs if r.frame_kind == "live_jpeg" and not r.bridged_frozen
                        ),
                        "white_pngs": sum(1 for r in cell_recs if r.frame_kind == "white_png"),
                        "truncated_jpegs": sum(1 for r in cell_recs if r.frame_kind == "truncated_jpeg"),
                        "gst_bars": sum(1 for r in cell_recs if r.frame_kind == "gst_bars"),
                        "frozen_frames": sum(1 for r in cell_recs if r.bridged_frozen),
                    }
                )

        camera_rows.append(
            {
                "camera_id": cid,
                "location": meta.get("location", ""),
                "location_en": meta.get("location_en", ""),
                "latitude": meta.get("latitude", ""),
                "longitude": meta.get("longitude", ""),
                "ip_address": ip,
                "subnet_16": s16,
                "subnet_24": s24,
                "total_files": n_files,
                "valid_jpegs": n_valid_jpegs,
                "white_pngs": n_white_pngs,
                "truncated_jpegs": n_trunc,
                "gst_bars": n_gst,
                "strict_frozen": n_strict,
                "bridged_frozen": n_bridged,
                "modal_phase": modal_phase,
                "phase_a_count": n_a,
                "phase_b_count": n_b,
                "phase_switches": sd_sw + ov_sw,
                "thu27_am_status": thu_status,
                "thu27_am_count": thu_am_count,
                "thu27_recovery_ts": _format_ts(thu_recovery),
                "max_same_day_gap_min": round(max_same_day_gap, 2),
            }
        )

        # Subnet aggregation
        sa = subnet_agg[s16]
        sa["camera_count"] += 1
        sa["total_files"] += n_files
        sa["white_pngs"] += n_white_pngs
        sa["strict_frozen"] += n_strict
        sa["bridged_frozen"] += n_bridged
        if thu_status == "full_morning_pseudo":
            sa["thu27_full"] += 1
        elif thu_status == "partial_white_png":
            sa["thu27_part69"] += 1
        elif thu_status == "zero_morning":
            sa["thu27_zero28"] += 1
        sa["gaps_gt20m"] += cam_gt20_non_thu_am

    subnet_rows = [
        {
            "subnet_16": s16,
            "camera_count": agg["camera_count"],
            "total_files": agg["total_files"],
            "white_pngs": agg["white_pngs"],
            "strict_frozen": agg["strict_frozen"],
            "bridged_frozen": agg["bridged_frozen"],
            "thu27_full": agg["thu27_full"],
            "thu27_part69": agg["thu27_part69"],
            "thu27_zero28": agg["thu27_zero28"],
            "gaps_gt20m": agg["gaps_gt20m"],
        }
        for s16, agg in sorted(
            subnet_agg.items(),
            key=lambda kv: (-kv[1]["camera_count"], kv[0]),
        )
    ]

    # Build verified OSD evidence table dynamically checking each sampled file on disk
    osd_rows: list[dict[str, Any]] = []
    rec_lookup: dict[tuple[str, str], FrameRecord] = {
        (r.camera_id, r.filename): r
        for recs in all_records.values()
        for r in recs
    }
    for sample in VERIFIED_OSD_SAMPLES:
        key = (sample["camera_id"], sample["filename"])
        rec = rec_lookup.get(key)
        if rec is None:
            if len(rec_lookup) >= 60000:
                raise FileNotFoundError(
                    f"Verified OSD sample missing from corpus: camera_id={sample['camera_id']} filename={sample['filename']}"
                )
            continue
        if rec.frame_kind == "gst_bars":
            status = "gst_bars"
        elif rec.bridged_frozen:
            status = "frozen_jpeg"
        else:
            status = rec.frame_kind
        osd_rows.append(
            {
                "camera_id": rec.camera_id,
                "filename": rec.filename,
                "file_ts": _format_ts(rec.timestamp),
                "osd_text": sample["osd_text"],
                "verified_year": sample["verified_year"],
                "verified_weekday": sample["verified_weekday"],
                "clock_offset_sec": sample["clock_offset_sec"],
                "frame_status": status,
                "has_exif": rec.has_exif,
                "core_md5": rec.core_md5,
                "verification_source": "visual_view_file+programmatic_exif",
            }
        )

    gap_rows.sort(key=lambda r: (r["gap_class"], r["date"], r["start_ts"], int(r["camera_id"]) if r["camera_id"].isdigit() else r["camera_id"]))
    all_streaks.sort(key=lambda r: (r["start_ts"], int(r["camera_id"]) if r["camera_id"].isdigit() else r["camera_id"]))
    no_eoi_rows.sort(key=lambda r: (r["timestamp"], int(r["camera_id"]) if r["camera_id"].isdigit() else r["camera_id"]))

    gt20_count = sum(1 for g in gap_rows if g["gap_class"] == ">20m")
    g12_20_count = sum(1 for g in gap_rows if g["gap_class"] == "12-20m")
    thu27_am_events = sum(1 for g in gap_rows if g["gap_class"] == "thu27_am")

    summary: dict[str, Any] = {
        "cameras": len(cam_ids),
        "total_files": total_files,
        "valid_jpegs": total_valid_jpegs,
        "valid_live_jpegs": total_valid_jpegs - total_gst,
        "non_frozen_live_jpegs": total_valid_jpegs - total_gst - sum(
            1 for recs in all_records.values() for r in recs if r.frame_kind == "live_jpeg" and r.bridged_frozen
        ),
        "white_pngs": total_white_pngs,
        "nonwhite_pngs": total_nonwhite_pngs,
        "truncated_jpegs": total_trunc,
        "no_eoi_total": len(no_eoi_rows),
        "gst_color_bars": total_gst,
        "strict_frozen": total_strict_frozen,
        "bridged_frozen": total_bridged_frozen,
        "strict_frozen_cameras": strict_frozen_cams,
        "bridged_frozen_cameras": bridged_frozen_cams,
        "exif_count": exif_count,
        "jpeg_dimensions": dict(sorted(jpeg_dims.items(), key=lambda kv: -kv[1])),
        "png_dimensions": dict(sorted(png_dims.items(), key=lambda kv: -kv[1])),
        "image_count_mismatches": image_count_mismatches,
        "unparseable_filenames": unparseable_filenames,
        "phase_a_frames": phase_a_frames,
        "phase_b_frames": phase_b_frames,
        "batch_split": {
            "phase_a_frames": phase_a_frames,
            "phase_b_frames": phase_b_frames,
            "modal_a_strict": modal_a_strict,
            "modal_tie": modal_tie,
            "modal_b_strict": modal_b_strict,
            "modal_a_with_tie": modal_a_strict + modal_tie,
            "modal_b": modal_b_strict,
            "same_day_switches": same_day_switches_total,
            "overnight_switches": overnight_switches_total,
            "mixed_cameras": mixed_cameras,
            "always_a_cameras": always_a_cameras,
            "always_b_cameras": always_b_cameras,
        },
        "thu_27_am_split": {
            "full_morning_pseudo": len(thu_full_pseudo_cams),
            "partial_white_png": len(thu_partial_cams),
            "zero_morning": len(thu_zero_cams),
            "live_traffic_frames": thu_live_frames,
            "full_morning_cameras": thu_full_pseudo_cams,
            "zero_morning_cameras": thu_zero_cams,
        },
        "date_range": {
            "min_ts": _format_ts(min_ts),
            "max_ts": _format_ts(max_ts),
            "days": [d.isoformat() for d in sorted_dates],
        },
        "daily_window": {
            "min_time": min_tod.strftime("%H:%M:%S") if min_tod else "",
            "max_time": max_tod.strftime("%H:%M:%S") if max_tod else "",
            "before_0600": before_0600,
            "between_2100_2101": between_2100_2101,
            "after_2101": after_2101,
        },
        "html_tail": {
            "files_with_tail": html_tail_count,
            "files_with_epoch_ms": len(epoch_diffs_sec),
            "epoch_minus_filename_sec_min": round(min(epoch_diffs_sec), 3) if epoch_diffs_sec else None,
            "epoch_minus_filename_sec_median": round(statistics.median(epoch_diffs_sec), 3) if epoch_diffs_sec else None,
            "epoch_minus_filename_sec_max": round(max(epoch_diffs_sec), 3) if epoch_diffs_sec else None,
        },
        "gaps_summary": {
            "same_day_gt20m_non_thu27_am": gt20_count,
            "same_day_12_20m": g12_20_count,
            "thu27_am_events": thu27_am_events,
        },
        "subnets_count": len(subnet_rows),
        "osd_verified_samples": len(osd_rows),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "corpus_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    _write_csv(
        out_dir / "camera_forensics.csv",
        camera_rows,
        [
            "camera_id", "location", "location_en", "latitude", "longitude",
            "ip_address", "subnet_16", "subnet_24", "total_files", "valid_jpegs",
            "white_pngs", "truncated_jpegs", "gst_bars", "strict_frozen",
            "bridged_frozen", "modal_phase", "phase_a_count", "phase_b_count",
            "phase_switches", "thu27_am_status", "thu27_am_count",
            "thu27_recovery_ts", "max_same_day_gap_min",
        ],
    )
    _write_csv(
        out_dir / "gap_events.csv",
        gap_rows,
        [
            "camera_id", "ip_address", "subnet_16", "location_en", "date",
            "start_ts", "end_ts", "gap_min", "gap_class", "neighbor_context",
        ],
    )
    _write_csv(
        out_dir / "frozen_streaks.csv",
        all_streaks,
        [
            "camera_id", "ip_address", "subnet_16", "location_en", "md5_core",
            "start_ts", "end_ts", "repeat_count", "streak_frames",
            "bridged_by_png", "is_gst_bars",
        ],
    )
    _write_csv(
        out_dir / "subnet_summary.csv",
        subnet_rows,
        [
            "subnet_16", "camera_count", "total_files", "white_pngs",
            "strict_frozen", "bridged_frozen", "thu27_full",
            "thu27_part69", "thu27_zero28", "gaps_gt20m",
        ],
    )
    _write_csv(
        out_dir / "hourly_coverage.csv",
        hourly_rows,
        [
            "camera_id", "date", "hour", "total_files", "valid_live_jpegs",
            "white_pngs", "truncated_jpegs", "gst_bars", "frozen_frames",
        ],
    )
    _write_csv(
        out_dir / "no_eoi_events.csv",
        no_eoi_rows,
        [
            "camera_id", "filename", "filepath", "date", "timestamp",
            "file_type", "file_bytes", "core_bytes", "core_md5",
            "width", "height", "has_html_tail", "tail_epoch_ms",
        ],
    )
    _write_csv(
        out_dir / "osd_evidence.csv",
        osd_rows,
        [
            "camera_id", "filename", "file_ts", "osd_text", "verified_year",
            "verified_weekday", "clock_offset_sec", "frame_status",
            "has_exif", "core_md5", "verification_source",
        ],
    )
    return summary


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--info", type=Path, default=Path("data/100_cameras/cctv_info.csv"))
    parser.add_argument("--images", type=Path, default=Path("data/100_cameras/cctv_images"))
    parser.add_argument("--out", type=Path, default=Path("reports/forensics"))
    args = parser.parse_args()

    summary = run_forensics(args.info, args.images, args.out)
    print(
        f"Forensics complete: {summary['cameras']} cameras, {summary['total_files']} files, "
        f"valid_jpegs={summary['valid_jpegs']}, white_pngs={summary['white_pngs']}, "
        f"truncated={summary['truncated_jpegs']}, gst_bars={summary['gst_color_bars']}, "
        f"strict_frozen={summary['strict_frozen']}, bridged_frozen={summary['bridged_frozen']}"
    )
    print(f"Outputs written to {args.out}")


if __name__ == "__main__":
    main()
