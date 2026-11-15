# Does rain make Bangkok roads look more congested? A one-week CCTV case study

*2110403 DSDE final project. Draft: 2026-11-15.*

## Summary

We counted vehicles in 61,143 CCTV snapshots from 100 Bangkok cameras over one week
(Tue 25 – Mon 31 Aug 2026, 06:00–21:00) and matched each snapshot to hourly rainfall
from Open-Meteo. Our team counted vehicles by hand in 1,000 frames, and we used those
counts to pick a detector and correct its undercount.

- **Heavy rain (>5 mm/h) comes with about 4% more vehicles than usual** for that camera
  and hour (+3.7 percentage points vs dry hours; 95% CI of the heavy level +1.9% to +8.8%).
  It holds when any single day is left out (+2.5 to +4.9 points).
- **Only rain in the same hour matters.** Rain one or two hours earlier shows no
  increase, so we see traffic building up during the downpour, not after it.
- **Light rain comes with slightly fewer vehicles** (about −2%), within a few points of zero.
- **The drop in wet evenings comes from one day.** Without Monday 31 Aug, wet evenings are
  +1.6 points vs dry evenings instead of −7.1.
- **The detector needed work.** The first run found only 37% of the vehicles people counted.
  The final detector (yolo11l, 640 px, confidence 0.05) finds 86%. Calibrating each
  vehicle class per condition brings the total to about 100%, except in the late-night
  wet cell, which has too few frames.

This is one week of monsoon-season data with 450 heavy-rain snapshots. We read the results
as a well-checked case study, not a general law.

## Data

| | |
|---|---|
| Cameras | 100 Bangkok traffic cameras, 352×288 px frames |
| Period | 7 days, 25–31 Aug 2026, 06:00–21:00 |
| Snapshots analysed | 61,143 (frozen frames removed; camera/hour cells with <3 snapshots dropped) |
| Rain | Open-Meteo hourly precipitation at each camera's location |
| Share of snapshots in wet hours (>0.1 mm/h) | 51% |
| Hand labels | 1,000 frames counted by 5 people; 199 counted twice; 12 marked unusable |

## Method

**Vehicle counts.** We compared YOLO11 s/m/l/x at 640/960/1280 px and several confidence
thresholds against the hand counts (tune/test split, `data/labels/bakeoff.csv`).
yolo11l at 640 px and confidence 0.05 had the lowest test error (MAE 4.9 vehicles per frame).
For comparison, two people counting the same frame differ by 2.7 vehicles on average.
Larger input sizes did not help, because the frames are only 352×288 px.

**Calibration.** The detector misses more vehicles at night and in rain, which would make
wet evenings look emptier than they really are. For each condition (day / evening /
late × wet / dry) and each class (four-wheel, motorcycle, bus, bicycle), we scale the
model count by hand total ÷ model total from the labelled frames in that condition.

**Excess over usual.** Each snapshot is compared with the mean of the same camera at the
same hour on the same day type (weekday or weekend):

    excess = log(1 + count) − mean of log(1 + count) in that (camera, hour, day type) cell

Subtracting this baseline removes rush hour, camera placement and zoom. exp(excess) − 1 is
roughly "% above usual". Confidence intervals come from resampling camera-days, because
snapshots from one camera on one day are not independent.

## Results

### Rain level and timing

![Rain level](figures/rain_levels.png)

Heavy rain in the same hour gives +5.8% vs usual (dry hours are +2.0%, so the difference
is +3.7 points). Light and moderate rain are slightly below usual. Rain one hour earlier
shows nothing. Heavy rain two hours earlier points to *fewer* vehicles (−4.8%, CI −8.8% to −0.7%),
which could mean traffic clears after a storm, but that level has only 454 snapshots.
The result is the same without calibration: raw counts give +6.2% for heavy rain,
and the share of the frame covered by vehicles gives +2.3% (CI crosses zero).

### Time of day

![Wet vs dry by hour](figures/wet_dry_by_hour.png)

Wet and dry hours track each other through the day. They separate in the evening
(19–20 h), where wet hours fall to about −10%. The next check shows where that comes from.

### Leave one day out

![Leave one day out](figures/leave_one_day_out.png)

The heavy-rain difference stays between +2.5 and +4.9 points whichever day is removed.
The evening dip is different: dropping Monday 31 Aug flips it from −7.1 to +1.6 points.
That evening was unusual in some way the rain does not explain, so we do not report a
general "wet evenings are emptier" effect.

### Detector error

![Detector error](figures/detector_error.png)

The first run (yolo11s, confidence 0.25) found 37% of hand-counted vehicles overall and only
15% in late wet hours, mostly because it missed motorcycles. yolo11l at 640 px with a
low threshold finds 75–92% in every condition. Calibration brings each condition to
1.00–1.05. These bars are *cross-fitted*: each person's frames are corrected with
factors learned from everyone else's frames, so the correction is not tested on the
frames it was fitted to.

The exception is late wet hours (20–21 h, 34 frames). There the model found only 16
motorcycles, 14 of them in one person's frames. Leave that person out and the
motorcycle factor jumps to about 35×. The calibration in this cell is therefore unreliable.
It affects few snapshots and none of the headline numbers depend on it, since raw counts
give the same heavy-rain result.

## Limitations

- **One week.** Only 7 days and 450 heavy-rain snapshots. More scraping in Nov–Dec would not
  help, because that is Bangkok's dry season.
- **Rain is area-level and hourly.** Open-Meteo gives modelled rain on a grid, not a gauge at
  each camera, and a 20-minute storm spreads across its hour.
- **Counts are not congestion.** More vehicles in view can mean slower traffic, or just
  more traffic. We cannot measure speed from snapshots minutes apart.
- **Hand labels are imperfect too.** Two people disagree by 2.7 vehicles per frame,
  which limits how good any detector can look.
- **Rain on the lens** blurs frames. Calibration corrects the counts on average,
  but not frame by frame.

## Reproduce

```bash
uv run python -m cctv.rain --counts data/interim/l640/image_counts.parquet --out data/processed/l640
uv run python -m cctv.charts
```
