#!/bin/bash

# ── 0. Fix Cron Environment "Blindness" ───────────────────────────
USER_NAME=$(whoami)
HOME_DIR="/home/$USER_NAME"

# Dynamically find the NVM Node path
NVM_BIN=$(find "$HOME_DIR/.nvm/versions/node" -maxdepth 2 -type d -name "bin" | head -n 1)

# Set the PATH specifically for Cron
export PATH="$HOME_DIR/.local/bin:$NVM_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# ── 1. Define Paths ──────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
SAVE_DIR="/mnt/d/Rotterdam_Videos"
COOKIES_FILE="$SCRIPT_DIR/cookies.txt" # Define path to your cookies file

mkdir -p "$SAVE_DIR"
cd "$SAVE_DIR" || exit

# ── Configuration ────────────────────────────────────────────────
# Set to 60 for short local testing. 
# CHANGE TO: DURATION=5400 for your 1h 30m production runs.
DURATION=60 
AIS_INTERVAL=30

echo "=== Starting recording session at $(date) ==="
echo "Saving to: $SAVE_DIR"
echo "Using cookies from: $COOKIES_FILE"

# ── 2. Cleanup old processes ─────────────────────────────────────
# FIX: Instead of killing ALL yt-dlp processes, only kill specific stream URLs
pkill -INT -f "rotterdam_tracker.py" || true
pkill -INT -f "VUXXORrhIFs" || true
pkill -INT -f "_r-g8wU-0o8" || true
sleep 2 

# ── 3. Start AIS data collector ──────────────────────────────────
echo "Starting AIS collector..."
timeout -s INT $DURATION python3 "$SCRIPT_DIR/rotterdam_AIS_tracker.py" --interval $AIS_INTERVAL --duration $DURATION &
AIS_PID=$!

# ── 4. Start Camera 1 (KPN) ──────────────────────────────
echo "Cam 1 (KPN): Recording..."
# Added --cookies and error logging to a specific file
timeout -s INT $DURATION yt-dlp --cookies "$COOKIES_FILE" --remote-components ejs:github --js-runtimes node -o "cam1_KPN_%(epoch)s.%(ext)s" "https://www.youtube.com/watch?v=gsViKzj7nuQ" > "$SAVE_DIR/cam1_error_log.txt" 2>&1 &
CAM1_PID=$!

# ── 5. Start Camera 2 (Kop van) ─────────────────────────────────────
echo "Cam 2 (Kop Van): Recording..."
# Added --cookies and error logging to a specific file
timeout -s INT $DURATION yt-dlp --cookies "$COOKIES_FILE" --remote-components ejs:github --js-runtimes node -o "cam2_Kop_Van_%(epoch)s.%(ext)s" "https://www.youtube.com/watch?v=nFozEhYTEMo&list=PLE5EGpZfeBtySMc4w9-O78Oe-1fnm01Am" > "$SAVE_DIR/cam2_error_log.txt" 2>&1 &
CAM2_PID=$!

# ── 6. Wait for processes to finish ──────────────────────────────
wait $CAM1_PID $CAM2_PID
echo "Both cameras finished."

wait $AIS_PID
echo "AIS collector finished."

echo "=== Session Complete ==="
