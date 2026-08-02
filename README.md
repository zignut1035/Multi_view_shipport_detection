# 🚢 Rotterdam Port Dual-Camera Ship Tracking with AIS Fusion

> A real-time vessel tracking pipeline that fuses live AIS data with dual-camera video feeds from the Erasmusbrug crossing in the Port of Rotterdam — detecting ships visually, matching them to real AIS identities, and synthesizing plausible identities for vessels with no AIS coverage at all.

![Python](https://img.shields.io/badge/Python-3.x-blue?style=flat-square&logo=python)
![OpenCV](https://img.shields.io/badge/OpenCV-Computer%20Vision-green?style=flat-square&logo=opencv)
![YOLOX](https://img.shields.io/badge/YOLOX-Object%20Detection-red?style=flat-square)
![DeepSort](https://img.shields.io/badge/DeepSort-Tracking-orange?style=flat-square)
![AIS](https://img.shields.io/badge/AIS-Vessel%20Data-navy?style=flat-square)
![Status](https://img.shields.io/badge/Status-Research%20Prototype-yellow?style=flat-square)

---
<img width="2048" height="946" alt="image" src="https://github.com/user-attachments/assets/c1a11520-bf5e-4eb4-8ef1-8f69a7e4227f" />
<img width="2048" height="946" alt="image" src="https://github.com/user-attachments/assets/98c204bb-4a53-46e2-b4b2-46e60d23abbe" />

## Overview

The Erasmusbrug crossing is one of the most heavily trafficked stretches of
the Nieuwe Maas in the Port of Rotterdam. This project builds a dual-camera
fusion pipeline that:

1. **Tracks vessels visually** in real time from two independent camera
   angles (KPN building + Kop van Zuid), using YOLOX detection and DeepSort
   tracking
2. **Projects real AIS vessel data** into each camera's own image plane,
   using per-camera geometric calibration
3. **Matches visual tracks to real AIS identities** using a dual-gate
   (distance + heading) criterion with multi-tick confirmation
4. **Synthesizes plausible identities** — position, speed, and course
   genuinely back-projected from a vessel's own tracked pixels — for
   moving vessels that have no real AIS match, so every real ship in frame
   gets an identity panel, not just the ones broadcasting AIS
5. **Outputs a side-by-side annotated dual-view video**, plus a synthetic
   AIS log that can optionally be merged back in for a stricter second pass

The result is an identity-aware vessel tracking system that stays honest
about which identities are real AIS data and which are estimated.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    DUAL-CAMERA FUSION PIPELINE                  │
│                    (main_dual_fusion.py)                        │
│                                                                   │
│  cam1 (KPN)      ──► AISPRO ──► VISPRO ──► FUSPRO ──► DRAW ──┐  │
│  854x480                                                       ├─► hstack ──► combined_dual_view.mp4
│  cam2 (Kop van Zuid) ─► AISPRO ──► VISPRO ──► FUSPRO ──► DRAW ─┘  │
│  1980x1080                                                       │
│                                                                   │
│  AISPRO: projects real AIS positions onto this camera's frame   │
│  VISPRO: YOLOX detection + DeepSort tracking (per-camera ROI/    │
│          upscale + confidence tuning)                            │
│  FUSPRO: matches visual tracks to real AIS identities             │
│          (dual-gate + confirmation + plausibility checks)        │
│  DRAW:   renders matches; synthesizes identity for moving,       │
│          unmatched vessels via a shared cross-camera registry    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (optional second pass)
┌─────────────────────────────────────────────────────────────────┐
│                    BOOTSTRAP REFINEMENT                          │
│                                                                   │
│  synthetic_ais_log.csv ──► convert_synthetic_to_ais.py ──►      │
│      merged AIS csv ──► main_dual_fusion.py --ais-csv <merged>  │
│                                                                   │
│  Previously-synthetic vessels now evaluated by FUSPRO's own      │
│  real matching gates, instead of the lighter synthesis path.     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Repository Structure

```
Rotterdam_Port/
├── main_dual_fusion.py         # Orchestrator: runs both camera pipelines in sync
├── convert_synthetic_to_ais.py # Converts + merges synthetic log for the second pass
├── cam1_para.txt                # cam1 (KPN) camera calibration
├── cam2_para.txt                # cam2 (Kop van Zuid) camera calibration
└── utils/
    ├── file_read.py             # Session config + video/AIS file discovery
    ├── AIS_utils.py             # AISPRO: AIS-to-image projection
    ├── VIS_utils.py             # VISPRO: detection + tracking
    ├── FUS_utils.py             # FUSPRO: AIS-visual fusion + matching gates
    ├── draw.py                  # DRAW: rendering + synthetic AIS assignment
    └── gen_result.py            # Per-timestamp result export
```

---

## Camera Setup

| Camera | Location | Resolution | Notes |
|---|---|---|---|
| cam1 | KPN building | 854×480 | ROI-cropped + upscaled for small/distant ships, lower confidence floor |
| cam2 | Kop van Zuid | 1980×1080 | Full-frame detection |

Each camera runs on its **own independent clock**, driven by its own
measured fps — not a shared or guessed timestamp — so AIS lookups stay
correctly aligned even when the two cameras' frame rates differ.

---

## Camera Calibration

Each camera's real-world geometry (`cam1_para.txt` / `cam2_para.txt`) was
fitted from real correspondence points — back-projecting a tracked pixel to
lat/lon and comparing against the vessel's known real position.

| Issue found | Fix applied |
|---|---|
| Unconstrained least-squares fit converged to a numerically accurate but physically impossible calibration (absurd mounting height/tilt) | Bounded the parameter search to physically plausible ranges |
| A fitted heading ~150° off true bearing still passed the pixel-reprojection objective | Added an independent, application-level visibility check as a second, separate validation |

**Known limitation:** cam1's calibration is validated only along the real
target ship's own transit path; accuracy elsewhere in frame (particularly
near the edges) is unconfirmed.

---

## Real AIS Matching (`FUS_utils.py`)

| Gate | Threshold | Purpose |
|---|---|---|
| Distance | < 300px | Base positional match |
| Heading agreement | < 60° | Confirms direction of travel matches |
| Distance override | < 100px (any track), < 220px (new tracks only) | Bypasses the heading gate when position alone is a strong match — track-age-gated so it can't reopen previously-fixed wrong-ship mismatches |
| Motion check | ≥ displacement/size-change threshold | Excludes persistently static false positives from matching entirely |
| Back-projection plausibility | ≤ 1200m implied distance from camera | Excludes detections that don't correspond to a real position on the water |
| Confirmed-match re-validation | every tick | A locked match is continuously re-checked, not permanent |

---

## Synthetic AIS Assignment (`draw.py`)

For a genuinely moving, visually tracked vessel with **no real AIS match**:

```
tracked pixel position
      │
      ▼
back-projected to real-world lat/lon (camera's own calibration)
      │
      ▼
speed/course derived from own recent real motion
(minimum real-time sampling window — not fixed frame count —
 to avoid amplifying pixel jitter into implausible speed readings)
      │
      ▼
identity assigned via SHARED REGISTRY
(keyed on real-world position + time, not track ID —
 survives tracker reacquisition AND camera handoff)
```

| Safeguard | What it prevents |
|---|---|
| Minimum trusted history window | Noise-amplified speed from very short-lived tracks |
| Absolute speed ceiling | An implausible reading getting displayed at all |
| Max-change-per-update check | A sudden implausible jump between consecutive readings |
| Forced-unfreeze after N rejections | Display getting stuck frozen indefinitely under persistent noise |
| Course-holding | A noise-dominated bearing overwriting a reliable prior course |
| Cross-camera reconnection tolerance | Tighter than same-camera reconnection — two different real vessels are a real risk across cameras |
| Optional reference blending | A specific synthetic vessel can blend toward a known real ship's actual kinematics, scoped to one MMSI only |

---

## Bootstrap Two-Pass Workflow

```bash
# Pass 1 -- normal run, produces synthetic_ais_log.csv
python3 main_dual_fusion.py --session <session_id>

# Convert + merge with real AIS data
python3 convert_synthetic_to_ais.py \
    --synthetic-csv /path/to/result_dual/<session>/synthetic_ais_log.csv \
    --out rotterdam_merged_<session>.csv \
    --merge-with rotterdam_interpolated_<session>.csv

# Pass 2 -- previously-synthetic vessels now matched by FUSPRO's real gates
python3 main_dual_fusion.py --session <session_id> --ais-csv rotterdam_merged_<session>.csv
```

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
| imutils | Frame resizing for display |

---

## Installation & Usage

```bash
# Run a session
python3 main_dual_fusion.py --session 2026-05-27_15-35

# Optional overrides
python3 main_dual_fusion.py --session <id> \
    --sessions-root /path/to/sessions \
    --ais-root /path/to/ais/csvs \
    --result-root /path/to/output \
    --ais-csv /path/to/merged_ais.csv   # second pass only
```

### Output location

```
<result-root>/<session_id>/combined_dual_view.mp4   ← annotated dual-camera video
<result-root>/<session_id>/synthetic_ais_log.csv    ← every synthetic assignment made this run
```

---

## Known Limitations

- The synthetic registry's cross-camera identity is **position-based, not
  appearance-based** — it cannot in principle distinguish two different
  real vessels that happen to pass close together within its tolerance
  window.
- Cam1 has shown persistent detection gaps across parts of sessions;
  confidence threshold and ROI tuning improved but did not fully resolve
  this.
- Displayed synthetic speed/course are demo-quality approximations with
  layered noise safeguards, **not validated measurements**.

---

## Future Work

- Explicit cross-camera geometric consistency check (epipolar/ground-plane),
  rather than relying on independent per-camera matching alone
- Lightweight appearance features as a secondary signal in the synthetic
  registry, alongside position and time
- Multi-point calibration with uncertainty estimation, so downstream
  matching tolerances could adapt per-camera to calibration confidence
- Real-time (rather than post-processed) operation
