# 🚢 Kanmon Strait Dual-Camera Ship Tracking with AIS Synchronization

> A multi-modal vessel tracking pipeline that synchronizes live AIS data with dual-camera video feeds from the Kanmon Strait, fusing visual object detection with real-time ship position data.

![Python](https://img.shields.io/badge/Python-3.x-blue?style=flat-square&logo=python)
![OpenCV](https://img.shields.io/badge/OpenCV-Computer%20Vision-green?style=flat-square&logo=opencv)
![AIS](https://img.shields.io/badge/AIS-Datalastic%20API-navy?style=flat-square)
![Platform](https://img.shields.io/badge/Platform-WSL%20%2F%20Linux-orange?style=flat-square)
![Storage](https://img.shields.io/badge/Cloud-CSC%20Allas-blueviolet?style=flat-square)
![Status](https://img.shields.io/badge/Status-Research%20Prototype-yellow?style=flat-square)

---

## Overview

The Kanmon Strait (関門海峡) is one of the busiest waterways in Japan, connecting the Shimonoseki and Moji sides between Honshu and Kyushu. This project builds an automated pipeline that:

1. **Simultaneously records** two live YouTube camera streams of the strait (Shimonoseki side + Moji side)
2. **Polls real-time AIS vessel position data** from the Datalastic API at regular intervals, synchronized to the recording epoch
3. **Fuses visual ship detections with AIS identities** — matching tracked objects in video to named vessels with MMSI, speed, heading, and navigational status
4. **Outputs a side-by-side annotated dual-view video** with vessel trajectories and AIS overlays drawn on both cameras
<img width="1600" height="500" alt="image" src="https://github.com/user-attachments/assets/6dfe12cd-2b06-41ff-89f5-1356e479cddc" />

The result is a temporally synchronized, identity-aware ship tracking dataset for maritime research and vessel behavior analysis.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA COLLECTION                          │
│                                                                 │
│  YouTube Live Stream          Datalastic AIS API               │
│  cam1 (Shimonoseki) ──┐       (every 30s polling)              │
│  cam2 (Moji)         ──┼──► Bash Orchestrator ◄── AIS Tracker  │
│                        │    (collect.sh)      (kanmon_AIS_      │
│                        │                       tracker.py)      │
│                   SAVE_DIR/                                     │
│                   ├── cam1_shimonoseki/  (video + logs)        │
│                   ├── cam2_moji/         (video + logs)        │
│                   └── ais/               (JSON snapshots)      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (post-collection)
┌─────────────────────────────────────────────────────────────────┐
│                      FUSION PIPELINE                            │
│                       (main.py)                                 │
│                                                                 │
│  cam1 video ──► AISPRO ──► VISPRO ──► FUSPRO ──► DRAW ──┐      │
│                                                           ├──► hstack ──► combined_dual_view.mp4
│  cam2 video ──► AISPRO ──► VISPRO ──► FUSPRO ──► DRAW ──┘      │
│                                                                 │
│  AISPRO: projects AIS positions onto camera frame               │
│  VISPRO: visual object detection & tracking                     │
│  FUSPRO: fuses AIS identity with visual track                   │
│  DRAW:   renders trajectories & labels on frame                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    CSC Allas Cloud Storage
                    (rclone upload per session)
```

---

## Repository Structure

```
kanmon/
├── collect.sh                  # Main orchestrator: records video + AIS in sync
├── kanmon_AIS_tracker.py       # AIS poller: fetches vessel snapshots from Datalastic
├── main.py                     # Fusion pipeline: processes dual video + AIS
├── cookies.txt                 # YouTube auth cookies (yt-dlp)
└── utils/
    ├── file_read.py            # Session config + AIS file initialization
    ├── AIS_utils.py            # AISPRO: AIS-to-image projection
    ├── VIS_utils.py            # VISPRO: visual tracking
    ├── FUS_utils.py            # FUSPRO: AIS-visual fusion
    ├── draw.py                 # DRAW: trajectory & label rendering
    └── gen_result.py           # Result export per timestamp
```

---

## Data Collection (`collect.sh`)

The bash script orchestrates all three parallel processes with a shared **record epoch** so video and AIS data are temporally aligned.

| Parameter | Value |
|---|---|
| Session duration | 900s (30 minutes) |
| AIS polling interval | Every 30 seconds |
| Camera 1 | Shimonoseki side live stream |
| Camera 2 | Moji side live stream |
| Video tool | `yt-dlp` with Node.js JS runtime |
| Auto-restart | Yes — streams are re-joined on unexpected disconnect |
| Cloud upload | `rclone` → CSC Allas after session completes |

### Session Output Structure

```
sessions/
└── 2025-06-01_14-30/
    ├── cam1_shimonoseki/
    │   ├── cam1_shimonoseki_<epoch>.mp4
    │   └── cam1_error_log.log
    ├── cam2_moji/
    │   ├── cam2_moji_<epoch>.mp4
    │   └── cam2_error_log.log
    ├── ais/
    │   └── ais_20250601T143000Z_epoch<N>.json
    ├── cam1_first_frame.jpg        ← for manual sync check
    ├── cam2_first_frame.jpg
    └── HOW_TO_SYNC.txt             ← OSD-based sync instructions
```

### Post-Collection Processing

After recording, the script automatically:
- Extracts the **first frame** of each camera for OSD timestamp comparison
- Detects and fixes **FPS mismatches** between cameras (re-encodes the faster stream via `ffmpeg`)
- Checks for **duration mismatches** (>5s gap triggers a trim warning)
- Writes `HOW_TO_SYNC.txt` with step-by-step manual sync instructions

---

## AIS Tracker (`kanmon_AIS_tracker.py`)
<img width="530" height="297" alt="{B7AC337D-3F30-4994-BAB6-E7C42B3FF1DF}" src="https://github.com/user-attachments/assets/38f985c5-e23a-454d-82ed-71236636f073" />

Polls the **Datalastic `vessel_inradius` API** around the center of the Kanmon Strait.

| Parameter | Value |
|---|---|
| Center coordinates | 33.954331°N, 130.954801°E |
| Radius | 1.8 nautical miles |
| API | Datalastic v0 |

Each JSON snapshot includes:

```json
{
  "timestamp_utc": "2025-06-01T14:30:00+00:00",
  "epoch": 1748780000,
  "record_epoch": 1748779800,
  "offset_seconds": 200,
  "poll_index": 7,
  "vessel_count": 12,
  "vessels": [
    {
      "mmsi": "431000000",
      "name": "VESSEL NAME",
      "lat": 33.952,
      "lon": 130.957,
      "speed": 8.4,
      "course": 270,
      "heading": 268,
      "nav_stat": "Under way using engine"
    }
  ]
}
```

The `offset_seconds` field links each AIS poll to the exact second within the video recording, enabling frame-accurate synchronization.

---

## Fusion Pipeline (`main_dual_fusion.py`)

Processes the recorded dual-camera video alongside the AIS JSON snapshots.

### Per-Frame Processing

For each synchronized frame from both cameras:

```
Frame (cam1 or cam2)
    │
    ├─► AISPRO.process()   — projects AIS vessel coordinates onto image plane
    │                         using camera calibration parameters
    │
    ├─► VISPRO.feedCap()   — runs visual object detection & multi-object tracking
    │                         with anti-jitter filtering
    │
    ├─► FUSPRO.fusion()    — matches visual tracks to AIS vessel identities
    │                         by minimizing projected position distance
    │
    └─► DRAW.draw_traj()   — renders trajectories, MMSI labels, speed/heading
                              annotations on the frame
```

### Output

- `combined_dual_view.mp4` — side-by-side annotated video of both cameras
- Per-second CSVs with fused track results for each camera

---

## Camera Setup

| Camera | Location | View |
|---|---|---|
| cam1 | Shimonoseki (Honshu side) | Eastbound shipping lane |
| cam2 | Moji (Kyushu side) | Westbound shipping lane |

Both cameras stream publicly via YouTube Live with OSD timestamps visible on-screen, used for manual sync verification.

---

## Tech Stack

| Tool | Role |
|---|---|
| Python | Core pipeline |
| OpenCV | Video capture, frame processing, rendering |
| `yt-dlp` | Live stream recording |
| `ffmpeg` | FPS normalization, frame extraction |
| `ffprobe` | Duration and FPS detection |
| Datalastic API | Real-time AIS vessel data |
| `requests` | AIS API calls with retry logic |
| `rclone` | Upload sessions to CSC Allas cloud |
| `imutils` | Frame resizing for display |
| Pandas / NumPy | Track data management |

---

## Installation & Usage

```bash
# Clone the repository
git clone https://github.com/zignut1035/Kanmon_Port.git

# Add your Datalastic API key to kanmon_AIS_tracker.py
# API_KEY = "your_key_here"

# Add YouTube cookies for yt-dlp (required for live streams)
# See: https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp

# Run a 30-minute collection session
bash collect.sh

# After collection, run the fusion pipeline
python main_dual_fusion.py
```

### Output location

```
/mnt/d/kanmon_data/sessions/<SESSION_ID>/   ← raw session files
/mnt/d/kanmon_temp/result_dual/             ← fusion output video & metrics
```

---

## Sync Methodology

Temporal alignment between video and AIS uses a two-step approach:

1. **Epoch sync** — `collect.sh` passes a shared `RECORD_EPOCH` (Unix timestamp) to both the AIS tracker and video recorder at launch. Every AIS snapshot stores `offset_seconds = epoch − record_epoch`.

2. **OSD sync** — Each camera displays an on-screen clock. First frames are extracted and compared manually; any offset between camera OSD times is corrected by trimming the earlier stream with `ffmpeg -ss`.

This gives frame-level alignment between the two video feeds and second-level alignment with the AIS polling timestamps.

---

## Future Work

- **Automated OSD reading** — Use OCR to extract on-screen timestamps automatically, replacing the manual sync step
- **YOLO-based ship detection** — Replace the current visual tracker with a fine-tuned YOLO model for more robust detection in varying weather and lighting
- **Vessel behavior analysis** — Use the fused AIS + visual tracks to study traffic patterns, speed distributions, and lane adherence in the strait
- **Real-time mode** — Adapt the pipeline to process and fuse streams live rather than in post-processing

---

## Acknowledgements

Live camera streams sourced from publicly available YouTube feeds of the Kanmon Strait. AIS data provided by [Datalastic](https://datalastic.com). Cloud storage provided by **CSC Finland** (Allas object storage).
