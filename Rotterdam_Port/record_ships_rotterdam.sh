#!/bin/bash

# ── 0. Fix Cron Environment "Blindness" ───────────────────────────
USER_NAME=$(whoami)
HOME_DIR="/home/$USER_NAME"
NVM_BIN=$(find "$HOME_DIR/.nvm/versions/node" -maxdepth 2 -type d -name "bin" | head -n 1)
export PATH="$HOME_DIR/.local/bin:$NVM_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# ── 1. Define Paths ──────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
SAVE_DIR="/tmp/rotterdam"
COOKIES_FILE="$SCRIPT_DIR/cookies.txt"

mkdir -p "$SAVE_DIR"
cd "$SAVE_DIR" || exit

# ── Configuration ────────────────────────────────────────────────
DURATION=1800
AIS_INTERVAL=15

echo "=== Starting 30-minute Rotterdam session at $(date) ==="
echo "Saving to: $SAVE_DIR"

# ── 2. Cleanup old processes ─────────────────────────────────────
# Only kill processes related to Rotterdam to avoid stopping Sydney or Kanmon
pkill -INT -f "rotterdam_AIS_tracker.py" || true
pkill -INT -f "gsViKzj7nuQ" || true
pkill -INT -f "nFozEhYTEMo" || true
sleep 5 

# ── 3. Start AIS data collector ──────────────────────────────────
echo "Starting Rotterdam AIS collector..."
timeout -s INT $DURATION python3 "$SCRIPT_DIR/rotterdam_AIS_tracker.py" \
    --interval $AIS_INTERVAL \
    --duration $DURATION &
AIS_PID=$!

# ── 4. Start Camera 1 (KPN) ──────────────────────────────
echo "Cam 1 (KPN): Recording..."
timeout -s INT $DURATION yt-dlp \
    --cookies "$COOKIES_FILE" \
    --remote-components ejs:github \
    --js-runtimes node \
    -o "cam1_KPN_%(epoch)s.%(ext)s" \
    "https://www.youtube.com/watch?v=gsViKzj7nuQ" \
    > "$SAVE_DIR/cam1_error_log.txt" 2>&1 &
CAM1_PID=$!

# ── 5. Start Camera 2 (Kop van) ─────────────────────────────────────
echo "Cam 2 (Kop Van): Recording..."
timeout -s INT $DURATION yt-dlp \
    --cookies "$COOKIES_FILE" \
    --remote-components ejs:github \
    --js-runtimes node \
    -o "cam2_Kop_Van_%(epoch)s.%(ext)s" \
    "https://www.youtube.com/watch?v=nFozEhYTEMo" \
    > "$SAVE_DIR/cam2_error_log.txt" 2>&1 &
CAM2_PID=$!

# ── 6. Wait for processes to finish ──────────────────────────────
wait $CAM1_PID $CAM2_PID
echo "Both cameras finished."

wait $AIS_PID
echo "AIS collector finished."

echo ""
echo "=== Uploading Rotterdam files to Allas ==="
# Moves everything from /tmp/rotterdam to Allas
rclone move "$SAVE_DIR" "allas:Treenut_videos/Rotterdam" -v --delete-empty-src-dirs

echo "=== Rotterdam Session Complete at $(date) ==="