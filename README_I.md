# 🚢 Rotterdam Port Dual-Camera Ship Tracking with AIS Fusion

> A real-time vessel tracking pipeline that fuses live, high-frequency AIS data with dual-camera video feeds from the Erasmusbrug crossing in the Port of Rotterdam — detecting ships visually and matching them to their real AIS identities.

![Python](https://img.shields.io/badge/Python-3.x-blue?style=flat-square&logo=python)
![OpenCV](https://img.shields.io/badge/OpenCV-Computer%20Vision-green?style=flat-square&logo=opencv)
![YOLOX](https://img.shields.io/badge/YOLOX-Object%20Detection-red?style=flat-square)
![DeepSort](https://img.shields.io/badge/DeepSort-Tracking-orange?style=flat-square)
![AIS](https://img.shields.io/badge/AIS-Vessel%20Data-navy?style=flat-square)
![Status](https://img.shields.io/badge/Status-Research%20Prototype-yellow?style=flat-square)

---

## Overview

The Erasmusbrug crossing is one of the most heavily trafficked stretches of
the Nieuwe Maas in the Port of Rotterdam. This project builds a dual-camera
fusion pipeline that:

1. **Records synchronized dual-camera video** from two independent live
   YouTube streams, with automatic reconnect on drop, real (not naive)
   broadcast-start-time detection, and FPS-mismatch correction
2. **Streams live AIS vessel data** via a websocket feed (aisstream.io),
   polling frequently enough that real ships in this stretch reliably have
   current position, speed, and course on file
3. **Interpolates that AIS stream** onto a uniform time grid, so every
   camera tick has a matching AIS lookup regardless of exact ping timing
4. **Tracks vessels visually** in real time from two independent camera
   angles (KPN building + Kop van Zuid), using YOLOX detection and DeepSort
   tracking, each independently tuned (ROI, upscaling, confidence floors)
   for its own footage
5. **Projects real AIS vessel data** into each camera's own image plane,
   using per-camera geometric calibration
6. **Matches visual tracks to real AIS identities** using a dual-gate
   (distance + heading) criterion, continuously re-validated every tick,
   with additional safeguards for the specific failure modes this stretch
   of river produces (see below)
7. **Outputs a side-by-side annotated dual-view video**, plus a per-frame
   result export for downstream analysis

**Synthetic identity assignment has been removed.** With AIS polling now
frequent enough to keep real ships continuously covered, a moving vessel
with no real AIS match is simply drawn and logged honestly as `NO AIS`,
rather than being given a fabricated position/speed/course estimated from
its own visual motion. This keeps every identity shown either fully real or
explicitly absent — no output is ever a plausible-looking guess.

---

## System Architecture

```
┌───────────────────────────────────────────────────────────────────┐
│                    SESSION DATA COLLECTION                         │
│                                                                     │
│  record_ships_rotterdam_v2.sh                                      │
│    ├─► rotterdam_aisstream.py  (live AIS websocket → CSV)          │
│    ├─► yt-dlp × 2 cameras      (auto-restart on stream drop)       │
│    ├─► get_stream_realtime.py  (true broadcast start via HLS       │
│    │                            manifest, not naive request time)  │
│    ├─► ffprobe/ffmpeg           (FPS mismatch check + re-encode,   │
│    │                            first-frame extraction for sync)   │
│    └─► rclone                   (upload session to object storage) │
└───────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────────────┐
│                        AIS INGESTION PIPELINE                      │
│                                                                     │
│  ais_interpolation.py  ──►  rotterdam_interpolated_<session>.csv   │
│  (resamples to a uniform time                                      │
│   grid; linear position interp,                                    │
│   proper bearing-wrap interp)                                      │
└───────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────────────┐
│                    DUAL-CAMERA FUSION PIPELINE                     │
│                    (main_dual_fusion_v2.py)                        │
│                                                                      │
│  cam1 (KPN)          ──► AISPRO ──► VISPRO ──► FUSPRO ──► DRAW ──┐ │
│  cam2 (Kop van Zuid) ──► AISPRO ──► VISPRO ──► FUSPRO ──► DRAW ──┼─► hstack ──► combined_dual_view.mp4
│                                                                    ┘ │
│  AISPRO: projects real AIS positions onto this camera's frame;     │
│          drops fixes landing in a known land/building exclusion    │
│          zone; caps unbounded dead-reckoning extrapolation          │
│  VISPRO: YOLOX detection + DeepSort tracking (per-camera ROI/       │
│          upscale + confidence tuning; raw-detection NMS dedup)      │
│  FUSPRO: matches visual tracks to real AIS identities (dual-gate +  │
│          continuous re-validation + switch-resistance + optional   │
│          bridge-crossing-zone handling)                            │
│  DRAW:   renders matches; unmatched moving vessels drawn as         │
│          "NO AIS" honestly, no fabricated identity                 │
└───────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (optional, anytime)
┌───────────────────────────────────────────────────────────────────┐
│                  AIS COVERAGE QA (offline, browser)                 │
│                                                                     │
│  ais_explorer_v2/  ──►  data.js  ──►  index.html                  │
│  (per-vessel trajectory map, coverage stats, ping-level inspection) │
└───────────────────────────────────────────────────────────────────┘
```

Each camera runs on its **own independent clock**, driven by its own
measured fps, so AIS lookups stay correctly aligned even when the two
cameras' frame rates differ.

---

## Repository Structure

```
Rotterdam_Port/
├── main_dual_fusion_v2.py         # Orchestrator: runs both camera pipelines in sync
├── record_ships_rotterdam_v2.sh   # Records both cameras + AIS for one session, syncs, uploads
├── rotterdam_aisstream.py         # Live AIS websocket collector (aisstream.io)
├── get_stream_realtime.py         # Detects true broadcast start time from a live stream's HLS manifest
├── ais_interpolation.py           # Resamples raw AIS pings onto a uniform grid
├── ais_explorer_v2/               # AIS coverage QA viewer (generator + data.js + index.html)
├── check_roi.py                   # Pulls one frame + draws a detect_roi box, for visual ROI tuning
├── cam1_para.txt                  # cam1 (KPN) camera calibration
├── cam2_para.txt                  # cam2 (Kop van Zuid) camera calibration
└── utils/
    ├── file_read.py               # Session config + video/AIS file discovery
    ├── AIS_utils.py               # AISPRO: AIS-to-image projection, land exclusion, staleness cap
    ├── VIS_utils.py                # VISPRO: detection + tracking
    ├── FUS_utils.py                # FUSPRO: AIS-visual fusion + matching gates
    ├── draw.py                     # DRAW: rendering
    └── gen_result.py                # Per-timestamp result export
```

### Legacy files (present, not part of the current baseline)

These live in the same workspace from the earlier synthetic-identity /
bootstrap workflow (see previous README revision) and are kept for
reference, not deleted — but are not used by `main_dual_fusion_v2.py`:

| File | Was used for |
|---|---|
| `main_dual_fusion.py` | Pre-v2 orchestrator (no independent per-camera clocks, still had synthetic AIS) |
| `record_ships_rotterdam.sh` | Pre-v2 collector script |
| `synthesize_ais.py` | Synthetic identity generation (removed workflow) |
| `synthetic_ais_log_held.csv` | Output of the synthetic workflow |
| `convert_to_ais.py` | Converted/merged synthetic log back into a real-format AIS CSV for the old two-pass bootstrap |
| `data.js` / `rotterdam_ship_trajectory.html` (top-level) | Earlier, pre-`ais_explorer_v2` version of the coverage viewer |

A few other scripts in the workspace (`shift_ais.py`, `area_plot.py`,
`rotterdam_AIS_tracker.py`) aren't yet documented here — flag if you'd
like them written up too.

Note: the shared workspace (`~/multi_view/ships/`) also contains sibling
per-port projects (`Kanmon_Port/`, `Helsinki_Port/`, `Sydney_Port/`) using
similar tooling — out of scope for this README.

---

## Camera Setup

| Camera | Location | Resolution | Notes |
|---|---|---|---|
| cam1 | KPN building | 854×480 | ROI-cropped + upscaled (4×) for small/distant ships, lower confidence floor |
| cam2 | Kop van Zuid | 1920×1080 | ROI-cropped (water channel band only) + upscaled (2×), per-camera DeepSort threshold overrides |

---

## Camera Calibration

Each camera's real-world geometry (`cam1_para.txt` / `cam2_para.txt`) was
fitted from real correspondence points — back-projecting a tracked pixel to
lat/lon and comparing against the vessel's known real position.

**Known limitation:** back-projection accuracy degrades meaningfully at
long range near the edge of frame/horizon. At this camera's mounting
height (~30m), the sightline to a distant point is nearly parallel to the
water surface, so a small pose error (`shoot_vdir`, `height_cam`) produces
a large error in the recovered real-world distance — a known failure mode
for monocular ground-plane back-projection near grazing angles. Confirmed
in practice: a ship's AIS ghost point can render offset by hundreds of
meters at long range/near frame edges, even though the same calibration is
accurate along the confirmed transit path used to fit it.

---

## Session Data Collection

`record_ships_rotterdam_v2.sh` runs one full recording session end-to-end:

- Starts `rotterdam_aisstream.py` and both cameras' `yt-dlp` recordings at
  the same wall-clock moment, with **automatic restart** if either
  camera's live stream drops mid-session (retries until the session's
  time window is used up)
- Detects each camera's **true broadcast start time** via
  `get_stream_realtime.py`, which reads the live stream's own HLS manifest
  (`#EXT-X-PROGRAM-DATE-TIME`) rather than trusting the moment the download
  was requested — this captures both local buffering delay and YouTube's
  own live-broadcast latency in one measurement, confirmed on the order of
  several seconds to tens of seconds for these streams. Falls back to the
  local file-appearance time (local delay only) if the manifest fetch
  fails.
- Checks both cameras' actual **FPS and duration** after recording, and
  re-encodes to match if they differ
- Extracts a **first frame from each camera** and writes
  `HOW_TO_SYNC.txt` with manual OSD-timestamp-based sync instructions, as
  a fallback/cross-check alongside the automated `.realstart` detection
- Gracefully handles `Ctrl+C` mid-session (stops all subprocesses, still
  uploads whatever was captured)
- Uploads the full session (video + AIS + logs) to object storage via
  `rclone` once complete

---

## AIS Coverage QA (Trajectory Explorer)

Before running fusion on a session, the `ais_explorer_v2/` viewer gives a
quick browser-based way to sanity-check AIS coverage for that session:

- Its generator script scans every session folder, loads all raw
  AIS files for each (both AISStream-style CSVs and any legacy
  Datalastic-style JSON snapshots), and writes a single `data.js`
  containing every vessel's full ping history plus basic coverage stats
- `index.html` is a self-contained Leaflet map viewer (no server needed)
  with two modes:
  - **All vessels** — every vessel's trajectory plotted at once, with a
    sortable/filterable list showing ping counts and full vs. partial
    coverage, for spotting gaps at a glance
  - **Single vessel** — a focused view of one MMSI's track with
    start/end markers and a clickable ping-by-ping table (lat/lon, speed,
    course, source file) for inspecting exactly what the raw feed reported

This is purely an offline inspection tool — it doesn't feed into or read
from the fusion pipeline itself.

---

## AIS Ingestion & Interpolation

`rotterdam_aisstream.py` subscribes to a live AIS websocket feed, restricted
to a bounding box around this stretch of river, and further filtered to a
tighter real river polygon (`TRACK_POLYGON`) so only vessels genuinely in
the tracked area are logged. `ais_interpolation.py` then resamples each
vessel's raw pings onto a uniform time grid — linear interpolation in time
for position/speed, and proper 0°/360°-wrap-aware interpolation for
bearing — producing `rotterdam_interpolated_<session>.csv`, which
`AISPRO` reads directly.

With polling frequent enough to keep real ships continuously covered, the
older two-pass "synthesize an identity, then bootstrap it back in as if it
were real AIS" workflow is no longer needed and has been removed.

---

## Real AIS Matching (`FUS_utils.py`)

| Gate / safeguard | Threshold | Purpose |
|---|---|---|
| Distance | < 300px (× 2.5 for edge-of-frame boxes) | Base positional match |
| Heading agreement | < 60° | Confirms direction of travel matches |
| Close-range bypass | < 100px | Bypasses the heading gate when position alone is a strong match |
| Motion check | ≥ displacement/size-change thresholds | Excludes persistently static false positives from matching entirely |
| Confirmed-match re-validation | every tick | A locked match is continuously re-checked against the same gate, not permanent |
| Switch resistance | N consecutive ticks | A confirmed binding can't be stolen by a different mmsi based on one tick's noise |
| Bridge-crossing zone *(optional, per camera)* | freeze / block / post-exit hardening | Near a known visual-occlusion crossing point, a confirmed lock is frozen (not re-evaluated) while inside the zone, a brand-new unconfirmed track is blocked unless it's the single unambiguous candidate, and switch-resistance is hardened for a window after leaving the zone |
| Land/building exclusion zone *(optional, per camera)* | drop on entry | An AIS fix landing inside a known bad-fix zone (e.g. a real position rendering onto a building due to GPS blackout/interpolation near a bridge) is dropped rather than displayed |
| Dead-reckoning staleness cap | drop after N seconds unconfirmed | A vessel extrapolated forward with no fresh real fix for too long is dropped instead of drifting indefinitely |
| Demo/debug force-match override | *(disabled by default)* | Bypasses the distance gate for a named mmsi — for demoing/testing a known scenario only; **not** a data-correctness fix, and prints a loud warning when active |

---

## Handling Vessels With No AIS Match

A genuinely moving, visually tracked vessel with no real AIS match is drawn
and logged as `NO AIS` — no synthetic position, speed, or course is
generated for it. This is a deliberate trade-off: with the upgraded AIS
feed, most real ships in frame do have current AIS, so an honest `NO AIS`
label is preferred over a plausible-looking estimate that could be wrong.

---

## Tech Stack

| Tool | Role |
|---|---|
| Python | Core pipeline |
| OpenCV | Video capture, frame processing, rendering |
| YOLOX | Ship detection |
| DeepSort | Multi-object tracking |
| geopy / pyproj | Real-world distance + geodesic projection math |
| Pandas / NumPy | Track and AIS data management |
| websockets | Live AIS feed ingestion |
| imutils | Frame resizing for display |
| yt-dlp | Live YouTube stream recording |
| ffmpeg / ffprobe | FPS/duration checks, re-encoding, frame extraction |
| rclone | Session upload to object storage |
| Leaflet | Browser-based AIS coverage/trajectory viewer |

---

## Installation & Usage

```bash
# 0. Record a full session (video, both cameras, + live AIS), then sync/upload
./record_ships_rotterdam_v2.sh

# 1. (Optional) QA-check AIS coverage for the session before running fusion
cd ais_explorer_v2 && python3 <generator_script>.py
# then open ais_explorer_v2/index.html in a browser

# 2. Interpolate the collected AIS onto a uniform grid
python3 ais_interpolation.py --session <session_id> \
    --sessions-root /path/to/sessions \
    --repo-path /path/to/ais/csvs

# 3. Run fusion on the recorded video + interpolated AIS
python3 main_dual_fusion_v2.py --session <session_id>

# Optional overrides
python3 main_dual_fusion_v2.py --session <session_id> \
    --sessions-root /path/to/sessions \
    --ais-root /path/to/ais/csvs \
    --result-root /path/to/output \
    --cam1-offset-seconds <seconds> \
    --cam2-offset-seconds <seconds> \
    --seek-seconds <seconds>
```

### Output location

```
<result-root>/<session_id>/combined_dual_view.mp4   ← annotated dual-camera video
<result-root>/<session_id>/metric/<session_id>_detection.txt
<result-root>/<session_id>/metric/<session_id>_tracking.txt
<result-root>/<session_id>/metric/<session_id>_fusion.txt
```

---

## Known Limitations

- Camera calibration accuracy is unconfirmed away from the specific transit
  path used to fit it, and degrades at long range near frame edges/horizon
  (see Calibration section above).
- Near the bridge crossing, an occlusion event that outlasts DeepSort's own
  track-expiry window produces a new track ID on re-emergence; the
  bridge-crossing-zone safeguards reduce but don't eliminate a brief
  `NO AIS` gap immediately after re-emergence in the least-ambiguous cases.
- Cam1 has shown persistent detection gaps across parts of sessions;
  confidence threshold and ROI tuning improved but did not fully resolve
  this.
- Per-frame processing time varies significantly (single digits to tens of
  seconds observed), driven mainly by detection cost; not yet suitable for
  true real-time operation.

---

## Future Work

- Multi-point calibration refinement (least-squares fit across several
  known reference points instead of a single transit path), to reduce
  long-range/edge-of-frame back-projection error
- Explicit cross-camera geometric consistency check (epipolar/ground-plane)
- Course/heading-consistency as an additional matching signal, independent
  of position, for cases where two ships' AIS ghost points briefly overlap
- Real-time (rather than post-processed) operation
