#!/bin/bash

# ── Configuration ────────────────────────────────────────────────
DURATION=900      # 10 minutes (Safe for your 5-day credit plan)
AIS_INTERVAL=15     # Poll AIS every 15 seconds (Crucial to save credits!)

echo "=== Starting 20-minute recording session ==="

# ── 0. Cleanup old processes ─────────────────────────────────────
# Kills any stuck instances of the tracker from previous runs
pkill -f akashi_AIS_tracker.py
sleep 1 

# ── 1. Start AIS data collector (Background) ─────────────────────
echo "Starting AIS collector..."
python3 akashi_AIS_tracker.py --interval $AIS_INTERVAL --duration $DURATION &
AIS_PID=$!
echo "AIS collector started (PID: $AIS_PID)"

# ── 2. Start Camera 1: Maiko Villa Kobe Hotel ────────────────────
# URL: https://www.youtube.com/watch?v=BhtSrV3lnaw
echo "Cam 1 (Maiko Villa Kobe Hotel): Recording for 20 minutes..."
yt-dlp --remote-components ejs:github \
    --js-runtimes node \
    --downloader ffmpeg \
    --downloader-args "ffmpeg_i:-t ${DURATION}" \
    -o "cam1_Maiko_Villa_%(epoch)s.%(ext)s" \
    "https://www.youtube.com/watch?v=BhtSrV3lnaw" &
CAM1_PID=$!

# ── 3. Start Camera 2: TimeRoman ─────────────────────────────────
# URL: https://www.youtube.com/watch?v=ErMMAqYCeSg
echo "Cam 2 (TimeRoman): Recording for 20 minutes..."
yt-dlp --remote-components ejs:github \
    --js-runtimes node \
    --downloader ffmpeg \
    --downloader-args "ffmpeg_i:-t ${DURATION}" \
    -o "cam2_timeroman_%(epoch)s.%(ext)s" \
    "https://www.youtube.com/watch?v=ErMMAqYCeSg" &
CAM2_PID=$!

# ── 4. Safety Trap for early cancellation ────────────────────────
# If you press Ctrl+C, this kills the Python script and both cameras
trap "echo 'Canceling early... Killing background tasks...'; kill $AIS_PID $CAM1_PID $CAM2_PID 2>/dev/null; exit" INT

# ── 5. Wait for all processes to finish ──────────────────────────
wait $CAM1_PID $CAM2_PID
echo "Both cameras finished."

wait $AIS_PID
echo "AIS collector finished."

echo ""
echo "=== All done ==="
echo "Video files : cam1_Maiko_Villa_*.mp4 / cam2_timeroman_*.mp4"
echo "AIS data    : ./ais_data_akashi/ais_*.json"