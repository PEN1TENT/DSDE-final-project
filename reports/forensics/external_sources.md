# External Real-World Attribution & Primary Source Dossier (`25–31 Aug 2026 / 2569 BE`)

**Milestone:** M2 (External Real-World Attribution & Primary Source Verification)  
**Verified Baseline Window:** **Tue 25 Aug 2026 – Mon 31 Aug 2026** (`25–31 สิงหาคม 2569`), `06:00:00 – 21:01:23 +07:00`  
**Retrieved Date:** `2026-11-18` (2569 BE)

---

## 1. Calendar Year Verification & Explicit Exclusion of 2025 (`2568 BE`) Events

1. **Verified `2026` Evidence (`data/100_cameras/`, `data/raw/external/daylight.json`, live `bmatraffic.com`):**
   - Burned-in camera OSD overlays across multiple independent cameras explicitly display **`2026`** and exact 2026 weekdays:
     - `cam 150`: `25-08-2026 Tue`, `26-08-2026 Wed`, `31-08-2026 Mon`
     - `cam 177`: `28-08-2026 Fri`
     - `cam 194` & `cam 137`: `30-08-2026 Sun`
     - `cam 36`: `25 Aug 2026`, `31 Aug 2026`
   - `data/raw/external/daylight.json` covers `2026-08-25` through `2026-08-31` (sunrise `06:05:50–06:06:13 +07:00`, sunset `18:34:15–18:30:19 +07:00`).
   - Current system/BMA portal date is **Wednesday, 18 Nov 2026 (`18 พฤศจิกายน 2569`)**, matching `Tue 25 Aug 2026` (`85 days`, `85 mod 7 = 1`).
2. **Explicit Exclusion of `2025` (`2568 BE`) Events:**
   - **31 Aug 2568 (2025) Victory Monument Political Rally (`คณะรวมพลังแผ่นดินปกป้องอธิปไตย`):** Confirmed via Thai PBS, Thairath, Workpoint, and Naewna as occurring on **Sunday, 31 Aug 2025 (2568 BE)** following the removal of PM Paetongtarn Shinawatra. **Ruled out** for `2026-08-31` (`Mon 31 Aug 2569`).
   - Any 2025 MEA outage notices, 2025 weather events, or 2025 traffic closures are excluded from this attribution.

---

## 2. BMA Traffic Portal Technical Verification (`bmatraffic.com`)

| Probe Target | Method | Observed Result | Forensic Implication |
|---|---|---|---|
| `http://www.bmatraffic.com/` | `read_url_content` (`2026-11-18`) | HTTP 200 ASP.NET WebForms portal (`ระบบกล้องโทรทัศน์วงจรปิด (cctv) ตรวจวัดและรายงานสภาพการจราจร`, สำนักการจราจรและขนส่ง สจส. กรุงเทพมหานคร, header date `18 พฤศจิกายน 2569`) | Portal runs 24/7; does not shut down `21:00–06:00` (`06_21_window` is purely scraper scheduling). |
| `http://www.bmatraffic.com/show.aspx?image=150` | `read_url_content` (`2026-11-18`) | Failed with `wsarecv: An existing connection was forcibly closed by the remote host` (`110.170.214.36:80`) | Direct unauthenticated/unsessioned requests to `show.aspx` are actively reset, consistent with rate-limiting / session gating and explaining `20.02 min` single-poll drops and fleet stalls. |
| `https://cctv.bangkok.go.th` & `https://cpudapp.bangkok.go.th/bmatraffic/` | `search_web` (`2026-11-18`) | Official BMA CCTV request portal & BMA Traffic web/iOS/Android app operate 24/7; heavy-rain traffic spikes are known to cause portal/app image loading stalls or cached freezes. | Explains why raw files end with `./show.aspx?image=<id>&time=<epoch_ms>` ASP.NET HTML tails and why morning server resets emit identical `400x266` pure-white PNG placeholders (`504` files). |

---

## 3. Metropolitan Electricity Authority (MEA) Scheduled Power Outages (`25–31 Aug 2569 / 2026`)

Verified via `search_web` against Thai news archives (Thairath, PPTVHD36, Thansettakij, The Thaiger, Siamnews, LINE Today, Mumkhao) and MEA official portal (`mea.or.th`, Call Center 1130):

| Date (BE / CE) | Published MEA Scheduled Outage Areas (Bangkok) | Time Window (ICT) | Overlap with CCTV Anomalies? |
|---|---|---|---|
| **Tue 25 Aug 2569** (`2026-08-25`) | Seri Thai 44/46 (`09:00–10:00`), Lat Phrao 79/81 (`09:00–15:00`), Kanchanaphisek–Sakaengam Soi 8 (`09:00–12:00`), Sena Nikhom 1 (`09:00–13:00`), Nawamin (`09:30–11:00`), Phatthana Chonnabot 3 (`09:30–14:30`), Lat Phrao 126 (`10:00–12:00`) | `09:00–15:00` | **NO.** No outage near `cam 36` (Ratchada–Ratchaphruek, `10:15–10:40`), `cam 1195` (Bukkhalo, `08:15–08:35`), `cam 1060` (Krung Kasem, `17:51–18:11`), or `938/939` (Ramkhamhaeng/Mahadthai, `13:50+`). |
| **Wed 26 Aug 2569** (`2026-08-26`) | Srinakarin / Lasalle 14 (`09:00–14:00`), Suphapong 4 (`09:00–13:00`), Taksin 27–29 (`09:00–12:00`), Phatthanakan 7 (`09:00–15:30`), Seri Thai / Nawathani 4, 6 (`09:00–14:00`), Kanchanaphisek (`11:00–13:00`) | `09:00–15:30` | **NO.** Nothing during `06:15–06:45` (`224/603/938/939/913/18`) and nothing near `cam 595` (Ban Khaek, `15:30–15:40`). |
| **Thu 27 Aug 2569** (`2026-08-27`) | Pridi Banomyong 37 (`08:30–14:00`), Suan Phak / Phanu Garden (`08:30–15:30`), Ramkhamhaeng 89/2 (`08:30–12:00`), Pracha Uthit 59 (`09:00–15:00`) | `08:30–15:30` | **NO.** Does NOT explain city-wide `06:00–08:50` blackout of `97/100` cameras (`0` live frames across all `100` cameras). |
| **Fri 28 Aug 2569** (`2026-08-28`) | Srinakarin 46 (Soi Baan Suan Nakarin 1, `08:30–13:00`). **Targeted check for Thonburi, Bangkok Yai, Khlong San, Phasi Charoen, Rat Burana, Chom Thong (`10.116/118.*` freeze wave): ZERO scheduled outages.** | `08:30–13:00` | **NO.** Rules out scheduled MEA power cut as cause of `2026-08-28 13:00–13:36` coordinated freeze across `10` Thonburi/Khlong San cameras (`10.116.*/10.118.*`) + `938`, `cam 36` (`11:10`), and `cam 395` (`00:12` midnight freeze). |
| **Sat 29 Aug 2569** (`2026-08-29`) | Nuanchan 5 (`08:00–15:30`), Banthat Thong / Rama 1 / Rama 6 Soi 13 / Rong Mueang 5 (`08:00–13:30`), Thoet Rachan 9 (`08:30–12:00`), Liap Khlong Song 19 (`08:30–15:30`), Wat Sukchai (`08:30–15:30`), Nawamin 69 (`08:30+`), Ramkhamhaeng 2 (`08:30–15:30`), Kanchanaphisek–Bang Waek (`08:30–15:00`), Pracha Uthit / Ratchadaniwet 9 (`09:00–14:30`), Nakniwat 47 (`09:00–15:00`) | `08:00–15:30` | **NO.** None near `cam 206` (Naradhiwas 20, freeze started `10:36`), `cam 1076` (Ratchaphruek/Thoet Thai 21, `15:01`), or `cam 603` (Silom–Naradhiwas, `17:20`). |
| **Sun 30 Aug 2569** (`2026-08-30`) | Nuanchan 9 (`08:00–15:30`), Seri Thai 73 (`08:30–15:30`), Rama 2 Soi 85–87 (`08:30–16:30`) & Soi 50 (`13:00–15:30`), Senanikom 101–109 (`08:30–15:00`), Din Daeng Soi Bunchusi (`08:30–15:30`), Phutthamonthon Sai 1 / Bang Chueak Nang 9 (`08:30–15:30`), Ramkhamhaeng 177–183 (`09:00–13:00`). **Zero outages in Yan Nawa, Sathon, Naradhiwas, Chan (`10.128.*`) or Dusit (`cam 363`).** | `08:00–16:30` | **NO.** Rules out scheduled MEA maintenance for `10.128.*` (`88, 194, 196, 206`) at `11:25–12:26` and `cam 363` (Dusit) at `15:20–15:40`. |
| **Mon 31 Aug 2569** (`2026-08-31`) | Phetkasem 16 (`08:30–11:30`), Srinakarin 55 (`09:00–14:00`), Sukhumvit 23 (`09:00–13:00`), Lat Phrao 81 (`09:00–15:00`), Romklao 21 (`09:30–13:00`), Pradit Manutham (`10:00–12:00`) | `08:30–15:00` | **NO.** Zero MEA scheduled outages during `17:00–21:00` (`mon31_evening`, `cam 150` freeze `16:51–21:01`, `cam 206` gap `17:51–18:11`). |

*(Caveat: Public media archives record MEA scheduled maintenance, not unscheduled micro-faults such as blown pole fuses or storm-triggered trips; MEA Call Center 1130 / internal logs are not publicly archived.)*

---

## 4. Weather & Open-Meteo Archive Status (`25–31 Aug 2026`)

### 4.1 Live Cache Status (`data/raw/external/open_meteo_aug2026.json`)
- **Status:** **PENDING USER PERMISSION APPROVAL** (`read_url` on `archive-api.open-meteo.com` timed out after 60s waiting for permission approval; per tool safety rules, not circumvented via Python/curl).
- **Verified TMD (`กรมอุตุนิยมวิทยา`) Synoptic Context (`25–31 Aug 2569`):**
  - `25–26 Aug 2569`: Southwest monsoon + monsoon trough across upper Myanmar/Laos toward Tropical Storm "Narra" (Gulf of Tonkin, moved into southern China); Bangkok afternoon-evening thunderstorm coverage ~30%.
  - `27–31 Aug 2569`: Monsoon trough shifted southward; Bangkok thunderstorm coverage rose to **60–70%** on **Sun 30 – Mon 31 Aug 2569** with warnings of short-duration urban flash flooding (`น้ำท่วมขังรอการระบาย`).
- **Previously Verified Open-Meteo Archive Hourly Precipitation (`survey_3/handoff.md §1.4`, 4 grids):**
  - **Tue 25 Aug `10:00` (`cam 36`):** `0.10 mm/h` (Central & Yan Nawa grids — trace/dry).
  - **Wed 26 Aug `06:00–07:00` (`224/603/938/939`):** `0.00 mm/h` across all 4 grids (dry).
  - **Thu 27 Aug `06:00–08:00` (`97-cam blackout`):** `0.00–0.10 mm/h` (`06–07h`), `0.30–1.10 mm/h` (`08h`); heavier rain `2.0–5.9 mm/h` (`12–13h`) had 100% camera uptime.
  - **Sun 30 Aug `11:00–13:00` (`10.128.*` Yan Nawa `88, 194, 196, 206`):** Central/Dusit `0.00–0.10 mm/h`, **Yan Nawa grid `0.10 mm/h` (`11:00`) -> `2.10 mm/h` (`12:00`) -> `3.70 mm/h` (`13:00`)**.
  - **Sun 30 Aug `14:00–15:00` (`cam 363` Dusit):** Dusit grid `0.80 mm/h` (`14:00`), **`2.50 mm/h` (`15:00`)** (Central `1.50 mm/h`).
  - **Mon 31 Aug `13:00–21:00` (`mon31_evening_anomaly`):** **`3.8–8.8 mm/h` (`13–15h`)**, followed by **`0.3–0.8 mm/h` (`17–21h`)**.

*(Pending live 7-zone cache `open_meteo_aug2026.json` for Thonburi `13.715, 100.478`, Ramkhamhaeng `13.754, 100.615`, Ratchada `13.815, 100.576`, plus `rain`, `weather_code`, `cloud_cover`.)*

---

## 5. Construction, EXAT/MRT Closures, Fires & News (`25–31 Aug 2569`)

1. **MRT & Road Construction (`รฟม.` / `กทพ.` / Highways):**
   - **Ratchaphruek Rd:** Main-lane pavement/structure maintenance strictly **overnight `22:00–05:00`** (Aug–Oct 2569); does not explain `cam 36` (`25 Aug 10:15`, `28 Aug 11:10`), `cam 1076` (`29 Aug 15:01`), or `28 Aug 13:00–13:36` Thonburi freeze.
   - **EXAT Chaloem Maha Nakhon Expy:** Fiber-optic cable pulling strictly **overnight `21:00–05:00`** (1 Aug – 30 Sep 2569); Dao Khanong weigh-station lane shift (26 Aug–30 Sep) and Km 17+300A sign work (25–26 Aug, Tha Ruea–Bang Na) did not coincide with any affected camera outage.
   - **MRT Orange & Purple Line South:** Ongoing lane shifts on Lan Luang Rd, Phetchaburi Rd (Urupong), Din Daeng Rd (ONCB), and Samsen Rd (Soi 30) — none correlate with the 20–60 min camera blackouts.
2. **Notable Bangkok Incidents (`28–31 Aug 2569`):**
   - **Khlong Thom Center Fire (`ไฟไหม้คลองถมเซ็นเตอร์`, Worachak Rd):** Started **Fri 28 Aug 2569 ~20:42**, burned >8 hours until **Sat 29 Aug AM**, closing Worachak Rd (`แยกวรจักร–แยก SCB`) with forensic building inspection continuing **Mon 31 Aug 2569**. Notably, nearby BMA cameras (`cam 68` Bangkok Bank Worachak, `cam 228` Klang Hospital, `cam 1589` Maen Si, `cam 913` SAB) recorded **zero** `>20m` gaps or freezes during 28–31 Aug.
   - **Mon 31 Aug 2569 Events:** Daytime iLaw symbolic activity at ECT Chaeng Watthana (north of the 100-camera corridor) and a minor residential AC fire on Phetchaburi Rd (Ratchathewi). No major downtown political rally occurred on 31 Aug 2026 (that rally was 31 Aug **2025**).

---

## 6. Primary Source Index (`search_web` & `read_url_content` Verified `2026-11-18`)

- **BMA Traffic Portal:** `http://www.bmatraffic.com/`, `http://www.bmatraffic.com/show.aspx?image=150`, `https://cctv.bangkok.go.th`, `https://cpudapp.bangkok.go.th/bmatraffic/`
- **MEA Outage Notices (`25–31 Aug 2569`):**
  - 25 Aug 2569: Thairath (`https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQEB2CR3Huylgw2ihFCi6gCWtrGKtMRzKF2WPMPgcOlPyUm6iKzjqCFaaepDV4FyZXMx5HNykZSwR1yTZO6VxTqra_z-UmcOZPBb8GOA66cSi4FwkYwgoadfVy53VVp0SVH8s8Cm`), The Thaiger (`https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQGB89LRpSwt4UPV0ydIk-aPY8P77sCsv8oEczzVRp5AWaZxFqHGmwSLtnecF5du3VqL7TZT0km4AYhtKLQajDKXQw7DP58dOwe06JLjKhQgEmSCq5xziOQIbGLxgQ==`)
  - 26 Aug 2569: PPTVHD36 (`https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQEi8jxPlWjVyEx9ORhhACR1dTscZjaccaIoH1DXIq4u5slsVr9Vvt1QcDXxbJ3QgRGYeaTbqI6F-hkjwER8EK1RNve3-mbkP9MSKT1iM4y8ZB3Y9hFPni4OKFQg-chfsmHAXAmklJ8v_f8pclRddqn4Jt4p_sNGDDFaMSNcVA-3vKgxew6J664=`)
  - 27 Aug 2569: Thairath (`https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQGvtIRqCjyfgC3iN3YDNtc6LK1sLasT1ON3ktES4HoHik2410wGV2d88iQ3U9hIiEMMzpFAK6rwRB7r38DG6NanFXb_1R-UcQ6yGtGmc42HXXGfVI8laZlSc_NRJyYzVtdxvTehfw==`), Siamnews (`https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQEZBRxxc1wWaZvm8SMM7ScXSgQlZLtOtqZKxgJcRn2a4g3P7sw82ETwkhkUP2MlzZpfA4n6VCp-IdIZU5PDOk-XN5KGY3YruwbQj6nSByhuP9Htaf_cAwrvNRG1rQPBibpyVQ==`)
  - 28 Aug 2569: Thairath (`https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQH3iBQhhqNdAreqMssRhSGh917rGlRXTvyD0adcZFWt_ffD-G6ibwhPKRWMJ3UCGA9pmxYVyYypdndS-SLZWC0Dr1dqC15yYUZkob_1A325_5M6-g98z_s3hVc27dzXz9lnKy7Xbw==`), Thansettakij (`https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQGv2R87Wn89BgZY_mKkOXYtmutET4TqfqOdbyCpYdCm3qoQnW6rGUlyeFX0DmUJZYMkeDqwWeliA5J_btWss_tkx1Du4QMYooRVfEkR0Vx2Dd5yAl8J4IrsOBzQ75cxFib2L8gj1aw=`)
  - 29–30 Aug 2569: Thansettakij (`https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQEY8YfTtnHvgC2r1cy0NwmihdhdkCgG1JKFGNVIPrYzagg_kb9VpzwQYjFLj3c4bYUU4iD9YJToJgwOY2H9qTuUTv4T2xW7TMd15FW3WYe0UKOH7uzsyRPPgmF8-oTWeo6Xd5v93wU=`), LINE Today (`https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQFB_vpS9eJLnQv58Z3J2X8XCbfKQxohe1f1daGR3Z1xySh0YUyX3vVqMaj1dgCu_gz48KyzqsCEWgjtTQKfNA1LvmmJGOBnY9GXZFRm1yH03JfXXj4_ndYmryRqAvEGW4m-`)
  - 31 Aug 2569: Thairath (`https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQG4o6oNPgC9rUEeWMoyGLHyEfrdsQREI4B7ev-vwFAggtT0VXzongsS91LzNwez1ymewyiY10s82J0sGkUlVQeN1294YEMfF-otlnMAhfgT5nNxKDOeyGAHv_gHDicmSBdyR98x`), PPTVHD36 (`https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQHb6o-s32t9UVCnPjf1mwkNpqan4eZyZPWz5JIEoZWXSSSK87S9yYU5DQUArMqwtyI-ieRHIlwvZMSEaR_3x6MkxGqaWpomjUai9SmSzfN7VVlrA-rgOZzBP2WSwRIYPVsjz95F1RlOnZ9zsUE9A93tAB6vLHZQrUCUsX7GHYPT6JYZl3rk6Pg=`)
- **TMD Weather, EXAT/MRT, Khlong Thom Fire, 31 Aug 2025 Exclusion:** Bangkokbiznews, FM91BKK, JS100, ThaiGov, NationTV, ThaiPBS, AEC10News (`search_web` grounding URLs archived in `external_attribution.json`).

---

## 7. `M2 → M3` Contract Event ID Index (`external_attribution.json`)

| Contract `event_id` | `attribution_verdict` | Additional Mechanism |
|---|---|---|
| `thu27_am` | `SCRAPER_OR_BMA_ARTIFACT` | — |
| `06_21_window` | `SCRAPER_OR_BMA_ARTIFACT` | — |
| `batch_53_47` | `SCRAPER_OR_BMA_ARTIFACT` | — |
| `morning_white_pngs` | `SCRAPER_OR_BMA_ARTIFACT` | — |
| `20260825_cam36` | `INCONCLUSIVE` | — |
| `20260826_0615_fleet` | `SCRAPER_OR_BMA_ARTIFACT` | — |
| `20260828_1300_10_116_118` | `RULED_OUT_REAL_WORLD` | `SUBNET_OR_CAMERA_INFRASTRUCTURE` |
| `20260830_1125_10_128` | `INCONCLUSIVE` | `SUBNET_OR_CAMERA_INFRASTRUCTURE` |
| `20260830_1520_cam363` | `INCONCLUSIVE` | — |
| `cam595_trunc` | `SCRAPER_OR_BMA_ARTIFACT` | — |
| `long_freezes` | `RULED_OUT_REAL_WORLD` | `SUBNET_OR_CAMERA_INFRASTRUCTURE` |
| `mon31_evening` | `CONFIRMED_REAL_WORLD` | — |
| `20260825_26_938_939_freeze` *(extra)* | `RULED_OUT_REAL_WORLD` | `SUBNET_OR_CAMERA_INFRASTRUCTURE` |
| `other_20min_drops` *(extra)* | `SCRAPER_OR_BMA_ARTIFACT` | — |

