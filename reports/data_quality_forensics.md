# Bangkok 100-Camera CCTV Data-Quality Forensics & Pre-Insight Report

**Course:** `2110403` Data Science and Data Engineering (`DSDE-CEDT`, 2026/1)  
**Corpus:** `data/100_cameras/` (`cctv_info.csv` + `61,319` raw files across `100` BMA traffic cameras)  
**Verified Collection Window:** **Tue 25 Aug 2026 – Mon 31 Aug 2026** (`25–31 สิงหาคม 2569`), `06:00:00 – 21:01:23 +07:00`  
**Reproducible Audit Artifacts:** `src/cctv/forensics.py`, `src/cctv/forensic_charts.py`, `reports/forensics/*`

---

## Executive Summary

Before drawing urban mobility or weather conclusions from scraped Bangkok Metropolitan Administration (BMA) CCTV snapshots, **data engineering forensics must separate scraper and media-gateway artifacts from genuine real-world road or infrastructure events**. Across the `61,319` raw files collected from `100` cameras over `7` days (`604–631` files/camera, `0` filename/metadata mismatches), our reproducible stdlib audit (`src/cctv/forensics.py`) uncovered four systemic data-quality hazards that were previously invisible to standard image decoders and raw file hashes:

1. **Every file carries an appended ASP.NET HTML tail (`61,319 / 61,319`):** Each image file ends with an HTML `<form action="./show.aspx?image=<id>&time=<epoch_ms>">` payload (`median +3.03 s` after filename timestamp). Hashing raw files without stripping bytes after JPEG EOI (`0xFFD9`) or PNG `IEND` defeated duplicate detection (`0` frozen frames caught by legacy `inventory.py`), hiding **`579` strictly consecutive (`584` PNG-bridged) frozen repeat frames across `21` cameras** (`553` non-placeholder repeats + `31` repeated test-pattern repeats).
2. **`539` embedded non-traffic / corrupted payloads (`504` white PNGs + `33` GStreamer bars + `2` truncated JPEGs; `no_eoi_total = 506`):** `504` files (`07:15:00–08:45:50` daily) are valid **`400×266` solid-white PNG placeholders** (`core_md5 = d4bf31b19261c16f22c17224fab0df3f`) misnamed `.jpg`; `33` frames on Thu 27 AM (`cam 432` and `cam 1804`) are **`246×205` `gst-launch-0.10` SMPTE color bars**; and `2` frames on `cam 595` (Wed 26 Aug `15:30:42` & `15:40:43`) are **truncated JPEGs** sharing an identical `21,900`-byte prefix without EOI.
3. **The Thu 27 Aug `06:00–08:50` blackout had `0` live traffic frames across all `100` cameras:** The apparent `3 / 69 / 28` camera split (`150, 432, 1804` full-morning; `69` single-frame `07:21–07:30`; `28` zero-morning until `08:50–08:51`) yielded **zero** genuine traffic captures before `08:50:08` (`cam 150` served a frozen `26 Aug 19:41:12` frame; `432` & `1804` served SMPTE color bars; `69` received white PNGs during a `07:21–07:30` probe).
4. **Scraper scheduling vs. `/16` subnet infrastructure vs. Mon 31 Aug storm:** The `06:00–21:01` window (`0` overnight files) and `53/47` bimodal polling (`:00/:01` vs `:05/:06`, `749` intra-day + `314` overnight phase switches across `100/100` mixed cameras) are **scraper/BMA gateway artifacts**. By contrast, Fri 28 Aug `13:00–13:36` (`10/11` cameras in `10.116.* / 10.118.*`), Sun 30 Aug `11:25–12:26` (`4/4` cameras in `10.128.*`), and the `25`-hour freeze on `938/939` (`10.156.102.38/39`) are **localized subnet/encoder infrastructure faults** with zero overlapping scheduled MEA power outages. Meanwhile, the Mon 31 Aug evening anomaly in `reports/report.md` (`-7.1` pp wet-evening dip) occurred under **healthy fleet capture (`2,394` frames, `0` PNGs)** and aligns with **TMD 70% thunderstorm coverage** (with `2025` political protests explicitly ruled out) plus `cam 150`'s unflagged freeze.

> **Rubric Alignment (`2110403_2026s1_Project_CEDT.pdf`):** This report fulfills **Component 1 (Data Engineering)** via deterministic container/MD5 remediation (`inventory.py`, `rain.py`), **Component 2 (Data Science)** via temporal/spatial/IP-subnet root-cause analysis and external cross-verification, **Visualization Integration** via five data-driven SVG charts (`src/cctv/forensic_charts.py`), and **Component 4 (Insights & Caveats)** via quantified downstream bias corrections before Chapter 3–6 modeling.

---

## 1. Fleet Overview & Corpus Integrity (`Component 1: Data Engineering`)

All `100` camera folders in `data/100_cameras/cctv_images/` match `data/100_cameras/cctv_info.csv` (`image_count_mismatches = 0`, `unparseable_filenames = 0`, `exif_count = 0`).

| Metric | Verified Value | Notes / Artifact Source |
|---|---:|---|
| Total cameras / total raw files | `100` / `61,319` | `604` (`cam 1076`) to `631` (`cam 150`) files per camera (`corpus_summary.json`) |
| Exact corpus timestamp span | `2026-08-25 06:00:00` – `2026-08-31 21:01:19` | `max_time` across any camera: `21:01:23` (`daily_window`) |
| Files outside `06:00–21:01` | `0` before `06:00` / `0` after `21:01` | `354` trailing sweeps fall in `21:00:00–21:01:23` (`hour=21`) |
| Files with appended ASP.NET HTML tail | `61,319` (`100.0%`) | `action="./show.aspx?image=<id>&time=<epoch_ms>"`, `median +3.03 s` (`+2.51 s` to `+81.55 s`) |
| Valid JPEGs / non-frozen live JPEGs | `60,813` / `60,227` | `352×288` (`60,172`), `348×261` (`608`, `cam 395`), `246×205` (`33`, GStreamer bars) |
| Non-JPEG / missing-EOI files | `506` | `504` `400×266` solid-white PNGs + `2` truncated JPEGs (`cam 595`) |
| Frozen repeat frames (`strict` / `PNG-bridged`) | `579` / `584` (`21` cameras) | `553` non-placeholder live repeats + `31` repeated GStreamer bar frames |
| Complete `06–20h` cells (`>=3` live JPEGs) | `10,125 / 10,500` (`96.4%`) | `59,774` snapshots retained after `rain.py` cell-completeness filter |

![Fleet Hourly Availability and Anomaly Matrix](figures/forensics/01_fleet_hourly_anomaly_heatmap.svg)
*Figure 1: `100` cameras × `105` active hours (`06:00–20:59`, `25–31 Aug 2026`) sorted by `/16` IP subnet (`src/cctv/forensic_charts.py`). The matrix visually separates fleet-wide scraper events (vertical bands: Thu 27 AM blackout, daily `07–08h` white-PNG bursts) from subnet-locked infrastructure faults (horizontal blocks: `10.156.*` `938/939`, `10.116/118.*` Fri 28 `13h`, `10.128.*` Sun 30 `11–12h`, and single-camera freezes `150` and `395`).*

---

## 2. True Calendar Year (`2026` vs. `2025`), Container Forensics & OSD Evidence

### 2.1 Why `2026` Is Certain (and `2025` Events Are Excluded)
Because all `61,319` files contain **zero EXIF tags** (`exif_count = 0`), verifying whether the corpus came from August `2025` (`2568 BE`) or August `2026` (`2569 BE`) is critical before matching historical weather, power outages, or protests. Direct visual inspection of burned-in camera on-screen display (OSD) overlays across `12` frames (`9` distinct cameras: `7` `2026`-verified cameras plus `2` GStreamer test-pattern cameras) proves the true calendar year is **`2026`**, matching exact `2026` weekdays (`Tue 25`, `Wed 26`, `Fri 28`, `Sun 30`, `Mon 31 Aug 2026`), `data/raw/external/daylight.json` (`2026-08-25`..`2026-08-31`), and live `bmatraffic.com` (`18 พฤศจิกายน 2569` = Wed `18 Nov 2026`, `85` days after Tue `25 Aug 2026`).

| Cam | Sample Filename (`data/100_cameras/cctv_images/<id>/`) | Burned-In OSD Text (Directly Viewed) | Year / Day | Clock Drift vs. Filename | Frame Status (`has_exif=False`) |
|---:|---|---|---|---:|---|
| `150` | `150_..._20260825_061023.jpg` | `TF2-PY-VP16-01 25-08-2026 Tue 06:15:47` | `2026` Tue | `+324 s` (`+5m24s`) | `live_jpeg` |
| `150` | `150_..._20260827_073603.jpg` | `TF2-PY-VP16-01 26-08-2026 Wed 19:41:12` | `2026` Wed | `-42,891 s` (`-11h55m`) | `frozen_jpeg` (from 26 Aug) |
| `150` | `150_..._20260831_180105.jpg` | `TF2-PY-VP16-01 31-08-2026 Mon 16:47:08` | `2026` Mon | `-4,437 s` (`-1h14m`) | `frozen_jpeg` (from 16:47) |
| `432` | `432_..._20260827_070021.jpg` | `gst-launch-0.10` (SMPTE color bars) | `—` | `—` | `gst_bars` (`246×205`) |
| `1804` | `1804_..._20260827_070530.jpg` | `gst-launch-0.10` (SMPTE color bars) | `—` | `—` | `gst_bars` (`246×205`) |
| `395` | `395_..._20260828_120103.jpg` | `PN-22-C3 28-08-2026 00:12:01` | `2026` | `-42,542 s` (`-11h49m`) | `frozen_jpeg` (`348×261`) |
| `206` | `206_..._20260829_102604.jpg` | `TF2-YW-U69-CAM1 29/08/2026 10:19:29` | `2026` | `-395 s` (`-6m35s`) | `live_jpeg` |
| `177` | `177_..._20260828_150119.jpg` | `TF2-JJ-VP48-02 28-08-2026 Fri 15:01:21` | `2026` Fri | `+2 s` | `live_jpeg` |
| `194` | `194_..._20260830_122612.jpg` | `TF2-BR-VP67-01 30-08-2026 Sun 12:27:58` | `2026` Sun | `+106 s` (`+1m46s`) | `live_jpeg` |
| `137` | `137_..._20260830_140613.jpg` | `TF2-JJ-VP9-02 30-08-2026 Sun 14:11:47` | `2026` Sun | `+334 s` (`+5m34s`) | `live_jpeg` |
| `36` | `36_..._20260825_101548.jpg` | `TF2-TR-S24-02 25 Aug 2026 10:15:46` | `2026` | `-2 s` | `live_jpeg` |
| `36` | `36_..._20260831_180049.jpg` | `TF2-TR-S24-02 31 Aug 2026 18:00:55` | `2026` | `+6 s` | `live_jpeg` (wet road) |

*Source: `reports/forensics/osd_evidence.csv` (`12` visually verified samples across `9` cameras: `7` `2026`-verified cameras `150, 395, 206, 177, 194, 137, 36` + `2` GStreamer cameras `432, 1804`). Note: live camera internal clocks drift between `-6m35s` (`cam 206`) and `+5m34s` (`cam 137`) relative to scraper timestamps.*

### 2.2 Container & Payload Anomalies (`ASP.NET Tail`, `White PNGs`, `Truncated JPEGs`, `GStreamer Bars`)
- **ASP.NET WebForms HTML tail (`61,319 / 61,319`):** Because the scraper saved the HTTP response body from `http://www.bmatraffic.com/show.aspx?image=<id>&time=<epoch_ms>` verbatim with `.jpg` extensions, every file ends with an HTML document containing a changing `time=<epoch_ms>` parameter (`+2.51 s` to `+81.55 s` after the filename timestamp). Removing the tail reveals exact image core payloads (`core_md5`).
- **`504` Blank White PNGs (`07:15:00–08:45:50` daily):** Exactly `504` files across all `100` cameras (`18` `/16` subnets) are `800`-byte `400×266` solid-white PNGs (`core_md5 = d4bf31b19261c16f22c17224fab0df3f`, `nonwhite_pngs = 0`). Daily totals occur strictly during morning hours (`07–08h`): `15` (Tue 25), `111` (Wed 26), `71` (Thu 27), `108` (Fri 28), `64` (Sat 29), `73` (Sun 30), and `62` (Mon 31).
- **`2` Truncated JPEGs (`cam 595`, Ban Khaek Junction):** At `2026-08-26 15:30:42` and `15:40:43`, `cam 595` saved `22,503`-byte files whose `21,900`-byte JPEG core begins with `0xFFD8` (SOI) but lacks `0xFFD9` (EOI) before the intact ASP.NET HTML footer. Both share the exact truncated `core_md5 = 1fe3a27e5642a0101e11174446a98fe9`, proving the BMA server cache served an incomplete buffer twice.
- **`33` GStreamer SMPTE Color Bars (`246×205`):** On Thu 27 Aug (`06:00:22–08:45:32`), `cam 432` (`17` frames) and `cam 1804` (`16` frames + `1` white PNG at `07:25:30`) served identical `246×205` `gst-launch-0.10` SMPTE test-pattern JPEGs (`core_md5 = 4a6d31be2e3b9feafae84b191169d708`).

---

## 3. Temporal Forensics: Thu 27 Aug Blackout, Staggered Polling & Gaps (`R1`)

### 3.1 Anatomy of the Thu 27 Aug Morning Blackout (`06:00–08:50`)
Between `06:00:00` and `08:49:59` on Thu 27 Aug 2026, **`0` live traffic frames** were recorded across the entire `100`-camera fleet. The apparent `3 / 69 / 28` camera count split decomposes cleanly into four cohorts:
- **`3` Pseudo-Active Cameras (`full_morning_pseudo`):** `cam 150` (`17` captures: `16` stale repeats of its `26 Aug 19:41:12` frame + `1` white PNG at `07:25:58`), `cam 432` (`17` `gst-launch-0.10` SMPTE color bars), and `cam 1804` (`16` `gst-launch-0.10` SMPTE color bars + `1` white PNG at `07:25:30`).
- **`69` Single-Probe Cameras (`partial_white_png`):** Dark from `06:00–07:20`, returned **one** `400×266` white PNG during `07:21:08–07:30:10` (`14` at `07:21`, `36` at `07:25`, `19` at `07:26`, `2` at `07:30` across the `71` total morning PNGs), then dark again until `08:50:08–08:56:22` (`cam 233` recovered one sweep later at `09:00:13`).
- **`28` Zero-Morning Cameras (`zero_morning`):** Completely dark until live recovery at `08:50:10–08:51:06`.

![Thu 27 Aug Morning Blackout Anatomy](figures/forensics/02_thu27_am_blackout_anatomy.svg)
*Figure 2: 5-minute capture timeline (`06:00–09:30`) and 4-cohort swimlanes on Thu 27 Aug 2026. Zero live traffic frames existed before `08:50:08`. The `07:21–07:30` spike consists exclusively of `71` blank `400×266` white PNGs.*

### 3.2 Scraper Operating Window (`06:00–21:01`) & `53/47` Dynamic Phase Switching
The `06:00–21:01` boundary is razor-sharp across all `7` days (`0` captures before `06:00:00` or after `21:01:23`). Within each 10-minute cycle, the scraper polls cameras sequentially in Thai dictionary collation order over an `~81–85 s` sweep, splitting into two staggered queues:
- **Batch A (`:00/:01`–`:04`):** `30,663` frames (`52` strictly modal-A cameras + `1` exact tie `cam 1188` with `307 A / 307 B` = **`53` modal-A**).
- **Batch B (`:05/:06`–`:09`):** `30,656` frames (**`47` modal-B cameras**).
- **Universal Phase Switching (`100 / 100` mixed):** Every single camera switched batches at least `4` times (`cam 370`) and up to `23` times (`cams 26, 1076, 1078`). Across the week there are **`749` intra-day `A↔B` switches** and **`314` overnight switches** (`49–59` per night). Morning scraper stalls (`12–20 min` gaps, `n=797` total) align directly with phase-switch spikes (`26 Aug 06h`: `100` switches / `101` stalls; `25 Aug 06–07h`: `109` switches / `114` stalls; `29 Aug 07–08h`: `87` switches / `88` stalls).

![Batch Polling and Phase Switches](figures/forensics/03_batch_polling_and_phase_switches.svg)
*Figure 3: Bimodal polling distribution (`:00/:01` vs `:05/:06`) and 105-hour alignment between intra-day `A↔B` phase switches (`749`), `12–20 min` stalls (`797`), and `07–08h` white-PNG bursts (`504`).*

### 3.3 Complete Enumeration of All `16` Non-Thu-27-AM Daytime Gaps (`>20 min`)
Outside the Thu 27 AM blackout, `gap_events.csv` records **`16` same-day gaps `>20 min`** (`20.02–55.00 min`) and `797` `12–20 min` stall intervals:

| Date & Window (ICT) | Cameras (`/16` Subnet) | Duration (min) | Neighbor Context | Classification |
|---|---|---:|---|---|
| `2026-08-25 08:15:41–08:35:43` | `1195` (`10.116.*`) | `20.03` | `0/99` fleet, `0/6` subnet down | Single missed poll (`>20m`) |
| `2026-08-25 10:15:48–10:40:48` | **`36`** (`10.116.128.42`) | **`25.00`** | `0/99` fleet, `0/6` subnet (peer `1103` online) | Isolated single-cam gap (`>20m`) |
| `2026-08-25 17:51:23–18:11:24` | `1060` (`10.151.*`) | `20.02` | `2/99` fleet, `0/6` subnet down | Single missed poll (`>20m`) |
| `2026-08-26 06:15–06:45` | **`224`** (`10.117.*`), **`603`** (`10.104.*`), **`938, 939`** (`10.156.*`) + `913, 18` | `24.95–30.00` (`+20.02–20.03`) | Coincides with `06:20–06:39` fleet stall (`100` switches) | Fleet morning scraper stall |
| `2026-08-28 11:10:54–11:30:55` | `36` (`10.116.*`) | `20.02` | `1/99` fleet, `0/6` subnet down | Single missed poll (`>20m`) |
| `2026-08-29 15:01:05–15:21:07` | `1076` (`10.116.*`) | `20.03` | `1/99` fleet, `0/6` subnet down | Single missed poll (`>20m`) |
| `2026-08-29 17:20:00–17:40:01` | `603` (`10.104.*`) | `20.02` | `1/99` fleet, `0/2` subnet down | Single missed poll (`>20m`) |
| `2026-08-30 11:25:36–12:26:17` | **`88, 196`** (`10.128.128.34`, `10.128.129.129`) | **`55.00`** (each) | Siblings `194` & `206` in `10.128.*` froze synchronously | **`10.128.*` subnet outage (`4/4`)** |
| `2026-08-30 15:20:33–15:40:39` | **`363`** (`10.102.102.73`) | **`20.10`** | `0/99` fleet, `0/13` subnet (`332, 630, 1362` online) | Isolated Dusit gap (`>20m`) |
| `2026-08-31 17:51:05–18:11:07` | `206` (`10.128.*`) | `20.03` | `1/99` fleet, `0/3` subnet down | Single missed poll (`>20m`) |

---

## 4. Spatial, IP Subnet & Frozen-Frame Forensics (`R1` & `R2`)

### 4.1 `/16` and `/24` IP Subnets vs. Outages & Frozen Streaks
Testing all `100` cameras across their `18` `/16` IP subnets (`subnet_summary.csv`) provides a sharp diagnostic discriminator:
- **Scraper/gateway events cut across subnets:** Thu 27 AM `partial_white_png` (`69`) and `zero_morning` (`28`) cameras are intermixed inside the exact same `/24` subnets (e.g., `10.117.128.0/24` has `6` `zero_morning` + `4` `partial_white_png`; `10.101.102.0/24` has `4` `zero_morning` + `3` `partial_white_png`), and daily `white_pngs` appear across all `18` `/16` subnets (`2–10` per camera).
- **Infrastructure faults lock onto subnets and encoder pairs (`56` frozen streaks, `584` bridged / `579` strict frames across `21` cameras):**
  - **`10.156.102.38` & `.39` (`938` & `939`, `191` strict / `193` bridged):** `2.4 km` apart (`Ramkhamhaeng-Rama 9` & `Mahadthai`), yet both `connect BMAcctv` encoders froze synchronously from `25 Aug 13:50/55` to `26 Aug 14:50` (`+93` and `+92` PNG-bridged repeats) while sibling `10.156.102.13/.15/.69` stayed normal.
  - **`10.116.*` & `10.118.*` Fri 28 Aug `13:00–13:36` Freeze Wave:** `10` of `11` cameras freezing in lockstep (`+3` repeats each: `595, 36, 32, 26, 1195, 1103, 158, 1076, 1078, 1132`) belong to `10.116.*` (`7`) and `10.118.*` (`3`) across Thonburi/Khlong San/Phasi Charoen (plus `938`).
  - **`10.128.0.0/16` Sun 30 Aug `11:25–12:26` Outage (`4/4`):** Every camera in `10.128.*` (`88, 196` `55`-min gaps; `194` `+4` frozen `11:36–12:16`; `206` `+10` frozen `10:36–12:16`) failed or froze and recovered together at `12:20–12:26`.
  - **Long single-camera encoder freezes:** `cam 150` (`10.102.129.123`: `+99` repeats `26 Aug 19:41 -> 28 Aug 06:11` + `+25` repeats `31 Aug 16:51 -> 21:01`), `cam 206` (`10.128.129.131`: `+85` repeats `29 Aug 10:36 -> 30 Aug 09:46`), and `cam 395` (`10.101.101.104`: `348×261` midnight `00:12:01` frame frozen all day Fri 28 Aug `06:01 -> 16:00`, `+59` PNG-bridged repeats).

![Spatial and Subnet Forensics](figures/forensics/04_subnet_spatial_anomalies_rain.svg)
*Figure 4: Bangkok spatial scatter (left) and all `18` `/16` subnets (right). Thu 27 AM `partial_white_png` (circles) and `zero_morning` (triangles) scatter across every district and subnet, whereas `10.116/118.*` (Thonburi) and `10.128.*` (Yan Nawa/Sathon) cluster cleanly in both IP space and geography.*

### 4.2 External Real-World Attribution Summary (`R2`, Aligned to `PROJECT.md` Contract)

Primary-source checks covered live `bmatraffic.com` probing, `7` days of Metropolitan Electricity Authority (MEA) scheduled outage notices (`25–31 Aug 2569`), EXAT/MRT construction schedules, Thai Meteorological Department (TMD) synoptic bulletins, Open-Meteo Archive hourly rainfall, the Khlong Thom Center fire (`28–29 Aug`), and `2025` protest exclusion (`reports/forensics/external_attribution.json`, `external_sources.md`).

| Contract `event_id` | Scope | `attribution_verdict` (`PROJECT.md`) | Forensic Sub-Category & Evidence (`mea_check`, Weather, URLs) |
|---|---|---|---|
| `06_21_window` | All `100` cams `06:00–21:01` | `SCRAPER_OR_BMA_ARTIFACT` | Live probe proves `bmatraffic.com` runs 24/7; no overnight MEA cuts; scraper scheduler window. |
| `batch_53_47` | `53/47` (`52+1` tie / `47`), `749` intra-day switches | `SCRAPER_OR_BMA_ARTIFACT` | Thai-collated `~81–85 s` sweeps; `show.aspx?image=150` live probe gave TCP `wsarecv` connection reset; peaks on dry `26 Aug 06h` (`0.00 mm/h`). |
| `morning_white_pngs` | `504` `400×266` white PNGs `07:15–08:45` | `SCRAPER_OR_BMA_ARTIFACT` | Identical payload across all `18` `/16` subnets; occurs on dry (`26 Aug`, `n=111`, `0.00 mm/h`) & wet mornings; central ASP.NET cache placeholder. |
| `thu27_am` | `27 Aug 06:00–08:50` (`3/69/28`, `0` live) | `SCRAPER_OR_BMA_ARTIFACT` | Zero overlapping MEA notices (only 4 points `08:30+`); `0.00–0.10 mm/h` rain (`06–07h`); `part69/zero28` intermixed in identical `/24`s. |
| `20260826_0615_fleet` | `26 Aug 06:15–06:45` (`224, 603, 938, 939, 913, 18`) | `SCRAPER_OR_BMA_ARTIFACT` | Dry (`0.00 mm/h`), `0` MEA outages before `09:00`; spans `4` subnets while co-located peers (`225, 604`) polled normally during `100`-switch stall. |
| `cam595_trunc` | `26 Aug 15:30–15:40` `cam 595` (`2` files) | `SCRAPER_OR_BMA_ARTIFACT` | Taksin MEA cut ended `12:00`; identical `21,900`-byte truncated JPEG buffer + intact HTML tail served twice. |
| `20260828_1300_10_116_118` | `28 Aug 13:00–13:36` (`10/11` in `10.116/118.*`) | `RULED_OUT_REAL_WORLD` *(`SUBNET_OR_CAMERA_INFRASTRUCTURE`)* | **Zero** MEA outages in Thonburi/Khlong San/Phasi Charoen on `28 Aug 2569` (only Srinakarin 46); Ratchaphruek roadworks `22:00–05:00`; district CCTV hub/NVR freeze. |
| `20260830_1125_10_128` | `30 Aug 11:25–12:26` (`4/4` in `10.128.*`) | `INCONCLUSIVE` *(`SUBNET_OR_CAMERA_INFRASTRUCTURE`)* | **Zero** Yan Nawa/Sathon MEA outages; `4/4` failed/froze & recovered together (`12:20–12:26`) as Yan Nawa rain jumped `0.10 -> 2.10 -> 3.70 mm/h` (unscheduled feeder vs pure NVR hang). |
| `long_freezes` | `150` (`26–28` & `31`), `206` (`29–30`), `395` (`28`), `938/939` (`25–26`) | `RULED_OUT_REAL_WORLD` *(`SUBNET_OR_CAMERA_INFRASTRUCTURE`)* | No MEA/road closure match; burned-in OSD clocks (`150`, `395` `00:12:01`, `206`) & adjacent IPs (`938/939`) prove camera/gateway encoder hangs. |
| `mon31_evening` | `31 Aug 17:00–21:00` (`2,394` frames, `0` PNGs) | `CONFIRMED_REAL_WORLD` *(Storm; `2025` Protest Ruled Out)* | `31 Aug 2568 (2025)` Victory Monument protest **explicitly ruled out** (`RULED_OUT_REAL_WORLD` for 2025); `0` MEA evening cuts; TMD `70%` thunderstorms (`3.8–8.8 mm/h` `13–15h`, `0.3–0.8 mm/h` `17–21h`, `cam 36` wet-road OSD) + `cam 150` freeze. |
| `20260825_cam36` | `25 Aug 10:15–10:40` (`25.0 m`, `cam 36`) | `INCONCLUSIVE` | MEA & overnight Ratchaphruek roadworks ruled out; `0.10 mm/h` (Central/Yan Nawa); peer `1103` stayed online — transient fetch drop vs micro-glitch. |
| `20260830_1520_cam363` | `30 Aug 15:20–15:40` (`20.1 m`, `cam 363`) | `INCONCLUSIVE` | No Dusit MEA outage; nearby `10.102.*` peers online; Dusit grid recorded `2.50 mm/h` rain (`15:00`) — rain-link glitch vs single-poll drop. |

*Primary Sources Verified (`2026-11-18`, archived in `reports/forensics/external_sources.md`):* `http://www.bmatraffic.com/`, `http://www.bmatraffic.com/show.aspx?image=150`, `https://cctv.bangkok.go.th`, `https://cpudapp.bangkok.go.th/bmatraffic/`, plus `7`-day MEA/TMD/EXAT/news archives (Thairath, PPTVHD36, Thansettakij, The Thaiger, Siamnews, LINE Today, ThaiPBS, JS100, FM91BKK; grounding URLs in `external_attribution.json`). **Methodological Caveats:** (1) Public archives cover *scheduled* MEA maintenance, not private unscheduled MEA 1130 fuse/feeder trips; (2) `data/raw/external/open_meteo_aug2026.json` remains uncached due to a 60-second `read_url` permission timeout on `archive-api.open-meteo.com`, so grid values for Central, Yan Nawa, Dusit, and On Nut come from the prior `survey_3` live Open-Meteo Archive fetch while Thonburi, Ramkhamhaeng, and Ratchada grid-specific extracts await cache approval.

---

## 5. Downstream Pipeline & Insight Analysis Impact (`R3`)

Understanding these forensic artifacts changes how every downstream module in `src/cctv/` must clean, aggregate, and interpret the `100`-camera dataset:

![Downstream Impact Funnel and QC Remediation](figures/forensics/05_downstream_impact_funnel.svg)
*Figure 5: Forensic cleansing funnel (`61,319` raw -> `60,227` non-frozen live JPEGs -> `59,774` complete-hour snapshots) and comparison of legacy vs. patched `inventory.py` and `rain.py`.*

1. **`src/cctv/inventory.py` — HTML Tail Defeated Frozen Detection (`0` -> `553` live repeats across `20` cams; `584` total corpus repeats across `21` cams incl. `31` GSt repeats):**
   - *Legacy defect:* Hashing raw file bytes included the per-poll ASP.NET `&time=<epoch_ms>` tail, yielding **`0` frozen frames** and allowing `504` white PNGs (`brightness=255, sharpness=0`) and `33` SMPTE bars to pass `cv2.imdecode()`.
   - *Remediation (verified in M1):* `strip_html_tail()` + `inspect_image_bytes()` compute `core_md5` after `0xFFD9` / PNG `IEND`, flag `white_png`, `truncated_jpeg`, `gst_bars`, and `placeholder`, and compute PNG-bridged `frozen` on non-placeholder frames (`553` live repeats across `20` cameras + `33` `gst_bars` flagged separately; `usable = readable & ~placeholder & ~frozen`).
2. **`src/cctv/rain.py` — Pre-Baseline `[camera_id, date, hour] >= 3` Filtering:**
   - *Legacy defect:* `add_excess()` grouped only by `[camera_id, hour, daytype]`, allowing Thu 27 Aug `07–08h` single-frame white-PNG slots (`69` cams) and `3` pseudo-active cameras (`150, 432, 1804`) to enter the 5-day weekday morning baseline.
   - *Remediation (verified in M1):* Filtering `[camera_id, date, hour] >= 3` **before** computing `[camera_id, hour, daytype]` baselines drops `375` incomplete `06–20h` cells (`300` Thu 27 AM `06–08h` cells + `75` freeze/gap cells across `150, 206, 395, 938, 939, 1195`) plus `354` `21:00–21:01` boundary cells, retaining **`10,125 / 10,500` (`96.4%`)** complete active cells (**`59,774` clean snapshots** vs `61,143` in the unpatched `2026-11-15` draft of `reports/report.md`).
3. **`src/cctv/daylight.py` — Sunrise Crossing the `53/47` Batch Split:**
   - *Mechanism:* Sunrise in `data/raw/external/daylight.json` falls at **`06:05:50–06:06:13 +07:00`**. Consequently, `Batch A` captures at `06:00–06:04` (`n=280` frames) are tagged `twilight`, while `Batch B` captures at `06:05–06:09` (`n=284` frames) straddle `sunrise` into `day`. Because all `100` cameras switch batches (`749` intra-day + `314` overnight switches), `06h` twilight-vs-daylight comparisons must control for exact minute or aggregate carefully rather than treating cameras as fixed-batch.
4. **YOLO Detector (`yolo11l @ 640 px, conf=0.05`) & `cam 395` Resolution:**
   - Unfiltered `white_png` (`400×266`), `gst_bars` (`246×205`), and `truncated_jpeg` (`2` frames) produce artificial **`0`-vehicle detections** during `07–08h` dry and wet mornings, biasing morning rush-hour counts downward if not excluded prior to `detect.py` / `rain.py`. Additionally, `cam 395` (`608` frames at **`348×261`** rather than `352×288`) affects pixel-area normalization (`covered_fraction`) slightly less if normalized by each image's own `width × height`.
5. **`reports/report.md` Monday 31 Aug Evening Anomaly Re-Interpretation:**
   - M2 confirms the fleet captured `2,394` healthy frames (`0` white PNGs) on Mon 31 Aug `17:00–21:00` and rules out `2025` protests. Thus the `-7.1` pp evening dip in `report.md` is **not** a collection blackout: it reflects genuine **Mon 31 Aug afternoon-evening thunderstorm conditions** (TMD `70%` coverage, `3.8–8.8 mm/h` `13–15h`, `0.3–0.8 mm/h` `17–21h`, wet-road glare/motorcycle drop) compounded by `cam 150`'s unflagged `+25`-frame freeze (`16:51–21:01`) in the legacy `inventory.py` run.
6. **Guidance for Planned Ch. 3–6 Analyses (`Traffy Fondue`, `ThaiRSC`, Modal Split, `H3` Camera Health):**
   - **Modal split & bridge sheltering:** Always filter `usable == True` and `[camera_id, date, hour] >= 3` before computing `motorcycle / four_wheel` ratios; exclude `cam 150` (`124` frozen repeats) and `938/939` (`193` frozen repeats) frozen streaks so stuck dry frames are never miscounted during rainstorms.
   - **Camera Health & `H3` Placement (Ch. 6):** Promote `bridged_frozen` rate (`20` live-frozen cameras / `21` total-frozen incl. `cam 432` GSt bars, led by `150` [`124`], `938` [`98`], `939` [`95`], `206` [`95`], `395` [`72`]), `>20m` subnet fault exposure (`10.128.*`, `10.116/118.*`), and OSD clock drift (`-6m35s` to `+5m34s`) as first-class reliability metrics alongside image `sharpness` and `brightness` — **and exclude `504` scraper-induced white PNGs** (`sharpness=0`) when scoring camera hardware health, since white PNGs reflect BMA's central `show.aspx` cache rather than field lens quality.

---

## 6. Reproducibility

```powershell
$env:PYTHONPATH = "src"
& "C:\Users\golfk\AppData\Roaming\uv\python\cpython-3.15-windows-x86_64-none\python.exe" -m cctv.forensics
& "C:\Users\golfk\AppData\Roaming\uv\python\cpython-3.15-windows-x86_64-none\python.exe" -m cctv.forensic_charts
& "C:\Users\golfk\AppData\Roaming\uv\python\cpython-3.15-windows-x86_64-none\python.exe" -m unittest tests\test_forensics.py -v
```
