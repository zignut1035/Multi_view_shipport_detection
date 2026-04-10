#!/bin/bash

# ── 0. Fix Cron Environment "Blindness" ───────────────────────────
export PATH=/home/treenut/.local/bin:/home/treenut/.nvm/versions/node/v20.20.0/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# ── 1. Define Paths ──────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
SAVE_DIR="/mnt/d/Sydney_Videos"

mkdir -p "$SAVE_DIR"
cd "$SAVE_DIR" || exit

# ── Configuration ────────────────────────────────────────────────
# Set DURATION to 1800 seconds (30 minutes) for Smart Sampling
DURATION=1800
AIS_INTERVAL=30

echo "=== Starting 30-minute recording session at $(date) ==="
echo "Saving all files directly to: $SAVE_DIR"

# ── 2. Cleanup old processes ─────────────────────────────────────
pkill -INT -f Sydney_AIS_tracker.py
pkill -INT -f yt-dlp
sleep 5 

# ── 3. Start AIS data collector ──────────────────────────────────
echo "Starting AIS collector..."
timeout -s INT $DURATION python3 "$SCRIPT_DIR/Sydney_AIS_tracker.py" --interval $AIS_INTERVAL --duration $DURATION &
AIS_PID=$!
echo "AIS collector started (PID: $AIS_PID)"

# ── 4. Start Camera 1 (Sydney) ───────────────────────────────────
echo "Cam (Sydney): Recording for 30 minutes..."

# Define your YouTube link here
CAM1_URL="https://www.youtube.com/watch?v=5uZa3-RMFos" 

timeout -s INT $DURATION yt-dlp \
    --remote-components ejs:github \
    --js-runtimes node \
    -o "cam_sydney_%(epoch)s.%(ext)s" \
    "$CAM1_URL" &

CAM1_PID=$!

# ── 5. Wait for processes to finish ──────────────────────────────
wait $CAM1_PID
echo "Camera finished gracefully."

wait $AIS_PID
echo "AIS collector finished gracefully."

echo ""
echo "=== All done ==="
echo "Files saved in Windows at: D:\Sydney_Videos"