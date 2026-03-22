#!/bin/bash

# ── 1. Define Paths ──────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
SAVE_DIR="/mnt/d/Kanmon_Videos"

mkdir -p "$SAVE_DIR"
cd "$SAVE_DIR" || exit

# ── Configuration ────────────────────────────────────────────────
DURATION=600        # 10 minutes

echo "=== Starting 10-minute recording session at $(date) ==="
echo "Saving all files directly to: $SAVE_DIR"

# ── 0. Cleanup old processes ─────────────────────────────────────
pkill -f kanmon_AIS_tracker.py
pkill -f yt-dlp
sleep 1 

# ── 1. Start AIS data collector ──────────────────────────────────
# CURRENTLY DISABLED: Waiting for API Key. Remove the '#' when ready!
# echo "Starting AIS collector..."
# timeout -s INT $DURATION python3 "$SCRIPT_DIR/kanmon_AIS_tracker.py" --interval 5 --duration $DURATION &
# AIS_PID=$!
# echo "AIS collector started (PID: $AIS_PID)"

# ── 2. Start Camera 1 (Shimonoseki) ──────────────────────────────
echo "Cam 1 (Shimonoseki): Recording for 10 minutes..."
timeout -s INT $DURATION /home/treenut/.local/bin/yt-dlp --remote-components ejs:github --js-runtimes node -o "cam1_shimonoseki_%(epoch)s.%(ext)s" "https://www.youtube.com/watch?v=ihPEMsh1mFw" &
CAM1_PID=$!

# ── 3. Start Camera 2 (Moji) ─────────────────────────────────────
echo "Cam 2 (Moji): Recording for 10 minutes..."
timeout -s INT $DURATION /home/treenut/.local/bin/yt-dlp --remote-components ejs:github --js-runtimes node -o "cam2_moji_%(epoch)s.%(ext)s" "https://www.youtube.com/watch?v=_r-g8wU-0o8" &
CAM2_PID=$!

# ── 4. Wait for processes to finish ──────────────────────────────
wait $CAM1_PID $CAM2_PID
echo "Both cameras finished."

# wait $AIS_PID
# echo "AIS collector finished."

echo ""
echo "=== All done ==="
echo "Files saved in Windows at: D:\Kanmon_Videos"