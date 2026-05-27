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
AIS_INTERVAL=30

echo "╔══════════════════════════════════════════════════════════╗"
echo "  Kanmon Port Data Collector  [VIDEO + AIS MODE]"
echo "  Session  : $SESSION_ID"
echo "  Duration : ${DURATION}s (30 min)"
echo "  Save dir : $SAVE_DIR"
echo "  Started  : $(date)"
echo "╚══════════════════════════════════════════════════════════╝"

# ── 2. Cleanup old processes ─────────────────────────────────────
echo ""
echo "--- Cleaning up stale processes ---"
pkill -INT -f "kanmon_AIS_tracker.py" || true
pkill -INT -f "VUXXORrhIFs" || true
pkill -INT -f "_r-g8wU-0o8" || true
sleep 5

# ── TRAP SETUP ────────────────────────────────────────────────────
cleanup() {
    trap - INT
    echo ""
    echo "⚠️  Ctrl+C detected — stopping all background processes..."
    kill -INT $CAM1_PID $CAM2_PID 2>/dev/null
    kill -INT $AIS_PID 2>/dev/null
    echo "Waiting for yt-dlp to flush files (up to 15s)..."
    sleep 15
    kill -KILL $CAM1_PID $CAM2_PID 2>/dev/null
    pkill -KILL -f "VUXXORrhIFs" 2>/dev/null
    pkill -KILL -f "_r-g8wU-0o8" 2>/dev/null
    pkill -KILL -f "kanmon_AIS_tracker.py" 2>/dev/null
    sleep 2
    wait $CAM1_PID $CAM2_PID 2>/dev/null
    wait $AIS_PID 2>/dev/null
    echo ""
    echo "=== Uploading partial Kanmon files to Allas ==="
    rclone copy "$SAVE_DIR" "allas:Treenut_videos/Kanmon/sessions/$SESSION_ID" -v
    echo "=== Kanmon Session Manually Aborted at $(date) ==="
    exit 1
}
trap cleanup INT

# ── 3. Auto-restart wrapper for live streams ─────────────────────
record_stream() {
    local CAM_NAME="$1"
    local URL="$2"
    local OUTPUT="$3"
    local LOGFILE="$4"
    local END_TIME=$(( $(date +%s) + DURATION ))
    local ATTEMPT=0

    while true; do
        REMAINING=$(( END_TIME - $(date +%s) ))

        if [ "$REMAINING" -le 0 ]; then
            echo "[$(date '+%H:%M:%S')] [$CAM_NAME] Recording window finished." | tee -a "$LOGFILE"
            break
        fi

        ATTEMPT=$(( ATTEMPT + 1 ))
        echo "[$(date '+%H:%M:%S')] [$CAM_NAME] Attempt #$ATTEMPT — ${REMAINING}s remaining in window." | tee -a "$LOGFILE"

        LOCAL_OUTPUT="${OUTPUT/%.%(ext)s/_attempt${ATTEMPT}.%(ext)s}"

        timeout -s INT "$REMAINING" yt-dlp \
            --cookies "$COOKIES_FILE" \
            --remote-components ejs:github \
            --js-runtimes node \
            --no-part \
            -o "$LOCAL_OUTPUT" \
            "$URL" >> "$LOGFILE" 2>&1

        EXIT_CODE=$?

        echo "[$(date '+%H:%M:%S')] [$CAM_NAME] yt-dlp exited (code: $EXIT_CODE)." | tee -a "$LOGFILE"

        if [ "$EXIT_CODE" -eq 124 ]; then
            echo "[$(date '+%H:%M:%S')] [$CAM_NAME] Timeout reached — done." | tee -a "$LOGFILE"
            break
        fi

        if [ "$EXIT_CODE" -eq 130 ]; then
            echo "[$(date '+%H:%M:%S')] [$CAM_NAME] Interrupted by user — stopping." | tee -a "$LOGFILE"
            break
        fi

        echo "[$(date '+%H:%M:%S')] [$CAM_NAME] ⚠️  Unexpected stop (code $EXIT_CODE). Restarting in 5s..." | tee -a "$LOGFILE"
        sleep 5
    done

    echo "[$(date '+%H:%M:%S')] [$CAM_NAME] record_stream finished after $ATTEMPT attempt(s)." | tee -a "$LOGFILE"
}

# ── 4. Start AIS + cameras at exactly the same time ──────────────
RECORD_EPOCH=$(date +%s)
echo ""
echo "--- Starting AIS + cameras ---"
echo "Record epoch : $RECORD_EPOCH  ($(date -u -d @$RECORD_EPOCH '+%Y-%m-%d %H:%M:%S UTC'))"

# AIS starts first line, cameras immediately after — all three
# launched in the same block so timing is as close as possible
timeout -s INT $DURATION python3 "$SCRIPT_DIR/kanmon_AIS_tracker.py" \
    --interval $AIS_INTERVAL \
    --duration  $DURATION \
    --epoch     $RECORD_EPOCH \
    --output    "$SAVE_DIR/ais" &
AIS_PID=$!
echo "AIS PID: $AIS_PID"

record_stream \
    "cam1_shimonoseki" \
    "https://www.youtube.com/watch?v=VUXXORrhIFs" \
    "$SAVE_DIR/cam1_shimonoseki/cam1_shimonoseki_${RECORD_EPOCH}.%(ext)s" \
    "$SAVE_DIR/cam1_shimonoseki/cam1_error_log.log" &
CAM1_PID=$!
echo "cam1 PID: $CAM1_PID"

record_stream \
    "cam2_moji" \
    "https://www.youtube.com/watch?v=_r-g8wU-0o8" \
    "$SAVE_DIR/cam2_moji/cam2_moji_${RECORD_EPOCH}.%(ext)s" \
    "$SAVE_DIR/cam2_moji/cam2_error_log.log" &
CAM2_PID=$!
echo "cam2 PID: $CAM2_PID"

# ── 5. Wait for cameras and AIS to finish ────────────────────────
wait $CAM1_PID $CAM2_PID
echo ""
echo "✓ Both cameras finished."
wait $AIS_PID
echo "✓ AIS collector finished."

# ── 6. POST-PROCESSING ────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "  Post-processing session: $SESSION_ID"
echo "╚══════════════════════════════════════════════════════════╝"

CAM1_FILE=$(ls "$SAVE_DIR/cam1_shimonoseki/"*.{mp4,ts,mkv} 2>/dev/null | grep -v ".bak" | head -1)
CAM2_FILE=$(ls "$SAVE_DIR/cam2_moji/"*.{mp4,ts,mkv} 2>/dev/null | grep -v ".bak" | head -1)

if [ -z "$CAM1_FILE" ] || [ -z "$CAM2_FILE" ]; then
    echo "❌ Could not find video files. Skipping post-processing."
    echo "   Check logs:"
    echo "     $SAVE_DIR/cam1_shimonoseki/cam1_error_log.log"
    echo "     $SAVE_DIR/cam2_moji/cam2_error_log.log"
else
    echo "✓ cam1: $CAM1_FILE"
    echo "✓ cam2: $CAM2_FILE"

    # ── 6a. Extract first frame from each camera for sync check ──
    echo ""
    echo "--- Extracting first frames for sync check ---"
    ffmpeg -i "$CAM1_FILE" -vframes 1 "$SAVE_DIR/cam1_first_frame.jpg" -y -loglevel error
    ffmpeg -i "$CAM2_FILE" -vframes 1 "$SAVE_DIR/cam2_first_frame.jpg" -y -loglevel error
    echo "✓ cam1_first_frame.jpg"
    echo "✓ cam2_first_frame.jpg"

    # ── 6b. Check and fix fps mismatch ───────────────────────────
    CAM1_FPS=$(ffprobe -v error -select_streams v:0 \
        -show_entries stream=avg_frame_rate \
        -of default=noprint_wrappers=1:nokey=1 \
        "$CAM1_FILE" | awk -F'/' '{if($2) printf "%.0f\n", $1/$2; else print $1}')

    CAM2_FPS=$(ffprobe -v error -select_streams v:0 \
        -show_entries stream=avg_frame_rate \
        -of default=noprint_wrappers=1:nokey=1 \
        "$CAM2_FILE" | awk -F'/' '{if($2) printf "%.0f\n", $1/$2; else print $1}')

    echo ""
    echo "cam1 fps : $CAM1_FPS"
    echo "cam2 fps : $CAM2_FPS"

    if [ "$CAM1_FPS" -gt "$CAM2_FPS" ]; then
        TARGET_FPS=$CAM2_FPS
        echo "⚠️  cam1 is faster — re-encoding cam1 to ${TARGET_FPS}fps..."
        EXT="${CAM1_FILE##*.}"
        CAM1_FIXED="${CAM1_FILE%.$EXT}_${TARGET_FPS}fps.$EXT"
        ffmpeg -i "$CAM1_FILE" \
               -vf fps=$TARGET_FPS \
               -r $TARGET_FPS \
               -fps_mode cfr \
               -c:v libx264 -preset fast -crf 18 \
               -c:a copy \
               "$CAM1_FIXED"
        mv "$CAM1_FILE" "${CAM1_FILE%.$EXT}.bak"
        mv "$CAM1_FIXED" "$CAM1_FILE"
        echo "✓ cam1 re-encoded to ${TARGET_FPS}fps"

    elif [ "$CAM2_FPS" -gt "$CAM1_FPS" ]; then
        TARGET_FPS=$CAM1_FPS
        echo "⚠️  cam2 is faster — re-encoding cam2 to ${TARGET_FPS}fps..."
        EXT="${CAM2_FILE##*.}"
        CAM2_FIXED="${CAM2_FILE%.$EXT}_${TARGET_FPS}fps.$EXT"
        ffmpeg -i "$CAM2_FILE" \
               -vf fps=$TARGET_FPS \
               -r $TARGET_FPS \
               -fps_mode cfr \
               -c:v libx264 -preset fast -crf 18 \
               -c:a copy \
               "$CAM2_FIXED"
        mv "$CAM2_FILE" "${CAM2_FILE%.$EXT}.bak"
        mv "$CAM2_FIXED" "$CAM2_FILE"
        echo "✓ cam2 re-encoded to ${TARGET_FPS}fps"

    else
        echo "✓ fps match — no re-encode needed"
    fi

    # ── 6c. Print durations ───────────────────────────────────────
    CAM1_DUR=$(ffprobe -v error -show_entries format=duration \
        -of default=noprint_wrappers=1:nokey=1 "$CAM1_FILE" | cut -d. -f1)
    CAM2_DUR=$(ffprobe -v error -show_entries format=duration \
        -of default=noprint_wrappers=1:nokey=1 "$CAM2_FILE" | cut -d. -f1)

    echo ""
    echo "cam1 duration : $(printf '%02d:%02d' $((CAM1_DUR/60)) $((CAM1_DUR%60)))  (${CAM1_DUR}s)"
    echo "cam2 duration : $(printf '%02d:%02d' $((CAM2_DUR/60)) $((CAM2_DUR%60)))  (${CAM2_DUR}s)"

    DUR_DIFF=$(( CAM1_DUR - CAM2_DUR ))
    DUR_DIFF=${DUR_DIFF#-}
    if [ "$DUR_DIFF" -gt 5 ]; then
        echo "⚠️  Duration mismatch: ${DUR_DIFF}s — trim needed after checking first frames"
    else
        echo "✓ Durations match (within 5s)"
    fi

    # ── 6d. Write sync instructions ──────────────────────────────
    cat > "$SAVE_DIR/HOW_TO_SYNC.txt" << SYNCEOF
Session      : $SESSION_ID
Record epoch : $RECORD_EPOCH
cam1         : $(basename "$CAM1_FILE")   fps: $CAM1_FPS   duration: ${CAM1_DUR}s
cam2         : $(basename "$CAM2_FILE")   fps: $CAM2_FPS   duration: ${CAM2_DUR}s
AIS files    : $SAVE_DIR/ais/

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

AIS SYNC:
- Each JSON file in ais/ has a timestamp_utc and epoch field
- Match epoch to RECORD_EPOCH to find the first AIS poll
- Match timestamp_utc to OSD clock on screen for frame-level sync
SYNCEOF
    echo "✓ Sync instructions written to HOW_TO_SYNC.txt"
fi

# ── 7. Upload to Allas ────────────────────────────────────────────
echo ""
echo "=== Uploading session $SESSION_ID to Allas ==="
rclone copy "$SAVE_DIR" "allas:Treenut_videos/Kanmon/sessions/$SESSION_ID" -v

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "  Kanmon Session Complete  [VIDEO + AIS MODE]"
echo "  Finished : $(date)"
echo "╚══════════════════════════════════════════════════════════╝"