#!/bin/bash

# ── 0. Fix Cron Environment "Blindness" ───────────────────────────
USER_NAME=$(whoami)
HOME_DIR="/home/$USER_NAME"
NVM_BIN=$(find "$HOME_DIR/.nvm/versions/node" -maxdepth 2 -type d -name "bin" | head -n 1)
export PATH="$HOME_DIR/.local/bin:$NVM_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# ── 1. Define Paths ──────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
SESSION_ID=$(date +"%Y-%m-%d_%H-%M")
SAVE_DIR="/mnt/d/kanmon_data/sessions/$SESSION_ID"
COOKIES_FILE="$SCRIPT_DIR/cookies.txt"

mkdir -p "$SAVE_DIR/cam1_shimonoseki"
mkdir -p "$SAVE_DIR/cam2_moji"
mkdir -p "$SAVE_DIR/ais"

cd "$SAVE_DIR" || exit

# ── Configuration ────────────────────────────────────────────────
DURATION=1800
AIS_INTERVAL=60

echo "=== Starting 30-minute Kanmon session at $(date) ==="
echo "Session ID: $SESSION_ID"
echo "Saving to: $SAVE_DIR"

# ── 2. Cleanup old processes ─────────────────────────────────────
pkill -INT -f "kanmon_AIS_tracker.py" || true
pkill -INT -f "VUXXORrhIFs" || true
pkill -INT -f "_r-g8wU-0o8" || true
sleep 5

# ── TRAP SETUP ────────────────────────────────────────────────────
cleanup() {
    echo ""
    echo "⚠️  Ctrl+C detected! Stopping background processes gracefully..."
    kill -INT $AIS_PID $CAM1_PID $CAM2_PID 2>/dev/null
    wait $AIS_PID $CAM1_PID $CAM2_PID 2>/dev/null
    echo "=== Uploading partial Kanmon files to Allas ==="
    rclone copy "$SAVE_DIR" "allas:Treenut_videos/Kanmon/sessions/$SESSION_ID" -v
    echo "=== Kanmon Session Manually Aborted at $(date) ==="
    exit 1
}
trap cleanup INT

# ── 3. Start AIS data collector ──────────────────────────────────
echo "Starting Kanmon AIS collector..."
timeout -s INT $DURATION python3 "$SCRIPT_DIR/kanmon_AIS_tracker.py" \
    --interval $AIS_INTERVAL \
    --duration $DURATION \
    --output "$SAVE_DIR/ais/ais_$SESSION_ID.csv" &
AIS_PID=$!

# ── 4. Start BOTH cameras at exactly the same time ───────────────
RECORD_EPOCH=$(date +%s)
echo "Record epoch: $RECORD_EPOCH  ($(date -u -d @$RECORD_EPOCH '+%Y-%m-%d %H:%M:%S UTC'))"

timeout -s INT $DURATION yt-dlp \
    --cookies "$COOKIES_FILE" \
    --remote-components ejs:github \
    --js-runtimes node \
    -o "$SAVE_DIR/cam1_shimonoseki/cam1_shimonoseki_${RECORD_EPOCH}.%(ext)s" \
    "https://www.youtube.com/watch?v=VUXXORrhIFs" \
    > "$SAVE_DIR/cam1_shimonoseki/cam1_error_log.log" 2>&1 &
CAM1_PID=$!

timeout -s INT $DURATION yt-dlp \
    --cookies "$COOKIES_FILE" \
    --remote-components ejs:github \
    --js-runtimes node \
    -o "$SAVE_DIR/cam2_moji/cam2_moji_${RECORD_EPOCH}.%(ext)s" \
    "https://www.youtube.com/watch?v=_r-g8wU-0o8" \
    > "$SAVE_DIR/cam2_moji/cam2_error_log.log" 2>&1 &
CAM2_PID=$!

# ── 5. Wait for cameras and AIS to finish ────────────────────────
wait $CAM1_PID $CAM2_PID
echo "Both cameras finished."
wait $AIS_PID
echo "AIS collector finished."

# ── 6. POST-PROCESSING ────────────────────────────────────────────
echo ""
echo "=== Post-processing session $SESSION_ID ==="

CAM1_FILE=$(ls "$SAVE_DIR/cam1_shimonoseki/"*.{mp4,ts,mkv} 2>/dev/null | grep -v ".bak" | head -1)
CAM2_FILE=$(ls "$SAVE_DIR/cam2_moji/"*.{mp4,ts,mkv} 2>/dev/null | grep -v ".bak" | head -1)

if [ -z "$CAM1_FILE" ] || [ -z "$CAM2_FILE" ]; then
    echo "❌ Could not find video files. Skipping post-processing."
else
    # ── 6a. Extract first frame from each camera for sync check ──
    echo "Extracting first frames for sync check..."
    ffmpeg -i "$CAM1_FILE" -vframes 1 "$SAVE_DIR/cam1_first_frame.jpg" -y -loglevel error
    ffmpeg -i "$CAM2_FILE" -vframes 1 "$SAVE_DIR/cam2_first_frame.jpg" -y -loglevel error
    echo "✓ First frames saved:"
    echo "    $SAVE_DIR/cam1_first_frame.jpg"
    echo "    $SAVE_DIR/cam2_first_frame.jpg"

    # ── 6b. Check and fix fps mismatch ───────────────────────────
    CAM1_FPS=$(ffprobe -v error -select_streams v:0 \
        -show_entries stream=r_frame_rate \
        -of default=noprint_wrappers=1:nokey=1 \
        "$CAM1_FILE" | bc)
    CAM2_FPS=$(ffprobe -v error -select_streams v:0 \
        -show_entries stream=r_frame_rate \
        -of default=noprint_wrappers=1:nokey=1 \
        "$CAM2_FILE" | bc)

    echo ""
    echo "cam1 fps: $CAM1_FPS  |  cam2 fps: $CAM2_FPS"

    if [ "$CAM1_FPS" != "$CAM2_FPS" ]; then
        echo "⚠️  fps mismatch — re-encoding cam2 to ${CAM1_FPS}fps..."
        CAM2_FIXED="${CAM2_FILE%.mp4}_${CAM1_FPS}fps.mp4"
        ffmpeg -i "$CAM2_FILE" \
               -vf fps=$CAM1_FPS \
               -c:v libx264 -preset fast -crf 18 \
               "$CAM2_FIXED"
        mv "$CAM2_FILE" "${CAM2_FILE%.mp4}.bak"
        mv "$CAM2_FIXED" "$CAM2_FILE"
        echo "✓ cam2 re-encoded to ${CAM1_FPS}fps"
    else
        echo "✓ fps match — no re-encode needed"
    fi

    # ── 6c. Print durations ───────────────────────────────────────
    CAM1_DUR=$(ffprobe -v error -show_entries format=duration \
        -of default=noprint_wrappers=1:nokey=1 "$CAM1_FILE" | cut -d. -f1)
    CAM2_DUR=$(ffprobe -v error -show_entries format=duration \
        -of default=noprint_wrappers=1:nokey=1 "$CAM2_FILE" | cut -d. -f1)

    echo ""
    echo "cam1 duration: $(printf '%02d:%02d' $((CAM1_DUR/60)) $((CAM1_DUR%60)))"
    echo "cam2 duration: $(printf '%02d:%02d' $((CAM2_DUR/60)) $((CAM2_DUR%60)))"

    DUR_DIFF=$(( CAM1_DUR - CAM2_DUR ))
    DUR_DIFF=${DUR_DIFF#-}
    if [ "$DUR_DIFF" -gt 5 ]; then
        echo "⚠️  Duration mismatch: ${DUR_DIFF}s — trim needed after checking first frames"
    fi

    # ── 6d. Write sync instructions ──────────────────────────────
    cat > "$SAVE_DIR/HOW_TO_SYNC.txt" << EOF
Session: $SESSION_ID
cam1: $(basename $CAM1_FILE)  fps: $CAM1_FPS  duration: ${CAM1_DUR}s
cam2: $(basename $CAM2_FILE)  fps: $CAM2_FPS  duration: ${CAM2_DUR}s

SYNC STEPS:
1. Open cam1_first_frame.jpg and cam2_first_frame.jpg
2. Read the OSD timestamp from each (JST time shown on screen)
3. Fill in and run:

   EARLIER_FILE=<file that shows earlier OSD time>
   LATER_FILE=<file that shows later OSD time>
   OFFSET=HH:MM:SS   # later_OSD - earlier_OSD
   MIN_DUR=<shorter duration in seconds>

   ffmpeg -ss \$OFFSET -i \$EARLIER_FILE -t \$MIN_DUR -c copy <earlier_synced.mp4>
   ffmpeg          -i \$LATER_FILE  -t \$MIN_DUR -c copy <later_synced.mp4>
EOF
    echo "✓ Sync instructions written to HOW_TO_SYNC.txt"
fi

# ── 7. Upload to Allas ────────────────────────────────────────────
echo ""
echo "=== Uploading session $SESSION_ID to Allas ==="
rclone copy "$SAVE_DIR" "allas:Treenut_videos/Kanmon/sessions/$SESSION_ID" -v

echo "=== Kanmon Session Complete at $(date) ==="