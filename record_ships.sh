#!/bin/bash

# Configuration
DURATION=600        # 10 minutes in seconds
AIS_INTERVAL=30     # Poll AIS every 30 seconds (Adjusted to be useful)

echo "=== Starting 10-minute recording session ==="

# ── 1. Start AIS data collector (Background) ────────────────────
# Runs geolocation.py to fetch ship data while video records
echo "Starting AIS collector..."
python3 geolocation.py --interval $AIS_INTERVAL --duration $DURATION &
AIS_PID=$!
echo "AIS collector started (PID: $AIS_PID)"

# ── 2. Start Camera 1 (West Harbour L2 - South) ─────────────────
echo "Cam 1: Recording for 10 minutes..."
~/.local/bin/yt-dlp --remote-components ejs:github \
    --js-runtimes node \
    --downloader ffmpeg \
    --downloader-args "ffmpeg_i:-t ${DURATION}" \
    -o "cam1_%(epoch)s.%(ext)s" \
    "https://www.youtube.com/watch?v=6hPWq2IG08M" &
CAM1_PID=$!

# ── 3. Start Camera 2 (West Harbour L1 - North) ─────────────────
echo "Cam 2: Recording for 10 minutes..."
~/.local/bin/yt-dlp --remote-components ejs:github \
    --js-runtimes node \
    --downloader ffmpeg \
    --downloader-args "ffmpeg_i:-t ${DURATION}" \
    -o "cam2_%(epoch)s.%(ext)s" \
    "https://www.youtube.com/watch?v=JnJhFYhIjFs" &
CAM2_PID=$!

# ── 4. Wait for all processes to finish ─────────────────────────
wait $CAM1_PID $CAM2_PID
echo "Both cameras finished."

wait $AIS_PID
echo "AIS collector finished."

echo ""
echo "=== All done ==="
echo "Video files : cam1_*.mp4 / cam2_*.mp4"
echo "AIS data    : ./ais_data/ais_*.json"