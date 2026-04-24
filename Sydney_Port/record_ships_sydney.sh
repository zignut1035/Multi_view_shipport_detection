#!/bin/bash

# ── 0. Fix Cron Environment "Blindness" ───────────────────────────
USER_NAME=$(whoami)
HOME_DIR="/home/$USER_NAME"
NVM_BIN=$(find "$HOME_DIR/.nvm/versions/node" -maxdepth 2 -type d -name "bin" | head -n 1)
export PATH="$HOME_DIR/.local/bin:$NVM_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# ── 1. Define Paths ──────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
SAVE_DIR="/tmp/sydney"
COOKIES_FILE="$SCRIPT_DIR/cookies.txt"

mkdir -p "$SAVE_DIR"
cd "$SAVE_DIR" || exit

# ── Configuration ────────────────────────────────────────────────
DURATION=1800
AIS_INTERVAL=30

echo "=== Starting 30-minute recording session at $(date) ==="
echo "Saving all files directly to: $SAVE_DIR"
echo "Using cookies from: $COOKIES_FILE"

# ── 2. Cleanup old processes ─────────────────────────────────────
pkill -INT -f "Sydney_AIS_tracker.py" || true
pkill -INT -f "5uZa3-RMFos" || true
sleep 5

# ── 3. Start AIS data collector ──────────────────────────────────
echo "Starting AIS collector..."
timeout -s INT $DURATION python3 "$SCRIPT_DIR/Sydney_AIS_tracker.py" \
    --interval $AIS_INTERVAL \
    --duration $DURATION &
AIS_PID=$!
echo "AIS collector started (PID: $AIS_PID)"

# ── 4. Start Camera 1 (Sydney) ───────────────────────────────────
echo "Cam (Sydney): Recording for 30 minutes..."
timeout -s INT $DURATION yt-dlp \
    --cookies "$COOKIES_FILE" \
    --remote-components ejs:github \
    --js-runtimes node \
    -o "cam_sydney_%(epoch)s.%(ext)s" \
    "https://www.youtube.com/watch?v=5uZa3-RMFos" \
    > "$SAVE_DIR/sydney_error_log.txt" 2>&1 &
CAM1_PID=$!

# ── 5. Wait for processes to finish ──────────────────────────────
wait $CAM1_PID
echo "Camera finished gracefully."

wait $AIS_PID
echo "AIS collector finished gracefully."

echo ""
echo "=== Uploading files to Allas ==="
# Using -v instead of --progress for clean cron logs
# Using --delete-empty-src-dirs to keep your /tmp folder clean
rclone move "$SAVE_DIR" "allas:Treenut_videos/Sydney" -v --delete-empty-src-dirs

echo "=== Session Complete at $(date) ==="