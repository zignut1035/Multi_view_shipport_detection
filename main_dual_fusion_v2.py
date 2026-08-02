"""
Dual-camera + AIS fusion, v3 — independent per-camera sync clocks,
AND no more hardcoded session/offset constants.

WHY THIS CHANGED FROM v2:
  v2 fixed the fps-ratio-assumption bug (see below) but still had
  CAM1_LEAD_SECONDS / SYNCED_START_TIME hardcoded for one specific
  session -- meaning every new recording required manually reading
  two OSD clocks by eye and editing this file.

  Now: run `detect_sync_offset.py --session <id> ...` once per
  session (it OCRs the OSD clocks automatically) to produce a
  <session>/sync_offset.json file. This script just loads that file
  and works for ANY session, via `--session <id>` on the command line.
  Paths (video folders, AIS csv, output folder) are also derived from
  --session instead of being hardcoded.

WHY v1 -> v2 CHANGED (kept for context):
  v1 assumed cam1 = 60fps and cam2 = 30fps exactly, and used
  `frame_count % 2 == 0` to only advance cam2 every other loop.
  That only stays correct if the ratio between the two cameras'
  fps is *exactly* 2:1. Real captured video (esp. from yt-dlp /
  live streams) is almost never a clean ratio -- you get things
  like 59.94/29.97, dropped frames, or genuinely mismatched fps.
  Any drift there silently desyncs both the two camera views from
  each other AND the AIS timestamps fed to each pipeline. v2 fixed
  this with independent per-camera clocks driven by each camera's
  own real fps.

FIX APPLIED HERE (vs the broken "hardcoded sync bypass" version):
  The broken version derived SYNCED_START_TIME by parsing the
  session folder name (e.g. "2026-05-27_15-35") and used that as
  both Time1 and Time2. That folder name is just when the session
  was created/named -- not the real-world timestamp of the actual
  first video frame. Since AIS matching (AIS1.process / AIS2.process)
  depends entirely on Time1/Time2 lining up with real AIS timestamps,
  any gap between the folder-name time and the true recording start
  time causes AIS lookups to never match -> zero AIS detections.

  read_all() already returns the real first-frame time for each
  camera as init_time_1 / init_time_2. This version uses those
  directly as the starting clocks instead of guessing from the
  folder name.

  NOTE: this build assumes both cameras are already started at the
  same real-world time (no separate lead/lag between them), so the
  sync_offset.json / frame-skip logic from earlier versions has been
  removed entirely. If that assumption ever stops holding for some
  future session, that's a case worth re-adding explicit handling for.

DISPLAY NOTE: matches are shown the instant they pass FUSPRO's own
dis/theta gate for a single tick -- there is no additional N-tick
confirmation delay before something is drawn (an earlier version of
this file added such a delay via a filter_confirmed() step; it was
removed because it hid real matches for multiple seconds during
otherwise-normal detection gaps, which was worse than the occasional
brief mismatch it was meant to prevent).

SYNTHETIC AIS REMOVED (NEW): this build no longer assigns a synthetic
MMSI to visually-tracked vessels with no real AIS match. Every ship
in this session's AIS CSV is assumed to be genuinely real, so an
AIS-unmatched moving vessel is simply drawn/logged as unmatched
("NO AIS") -- there is no two-pass synthetic-then-merge workflow
anymore, and no synthetic_ais_log.csv is produced.

MANUAL TIME-SYNC OVERRIDE (NEW): --cam1-offset-seconds / --cam2-offset-seconds
let you directly shift each camera's clock by a manually-measured number of
seconds (positive = video's real start was LATER than init_time currently
says, negative = EARLIER), instead of relying on a .realstart sidecar file
or the backfill script. Use this when you've empirically determined the
correct offset yourself (e.g. by cross-referencing a real ship's known AIS
position against when it visually enters/exits a camera's tracked polygon).
"""
import os, time, imutils, cv2, argparse, glob, json
import pandas as pd
import numpy as np
from PIL import Image

from utils.file_read import read_all, ais_initial, update_time, time2stamp
from utils.AIS_utils import AISPRO
from utils.VIS_utils import VISPRO
from utils.FUS_utils import FUSPRO
from utils.draw import DRAW
from utils.gen_result import gen_result

# ---------------------------------------------------------
# 1. COMMAND-LINE ARGS -- everything session-specific comes from here
#    instead of being hardcoded, so this script runs on any session.
# ---------------------------------------------------------
ap = argparse.ArgumentParser(description="Dual-camera + AIS fusion for a Rotterdam session.")
ap.add_argument("--session", required=True,
                help="Session ID, e.g. 2026-05-27_15-35 (matches the sessions/ subfolder name)")
ap.add_argument("--sessions-root", default="/mnt/d/rotterdam_data/sessions",
                help="Root folder containing per-session subfolders")
ap.add_argument("--ais-root", default="/home/treenut/multi_view/ships",
                help="Folder containing rotterdam_interpolated_<session>.csv files")
ap.add_argument("--result-root", default="/mnt/d/rotterdam_data/result_dual",
                help="Root folder to write per-session results into")
ap.add_argument("--ais-csv", default=None,
                help="Optional: explicit path to an AIS CSV to use instead of "
                     "the default <ais-root>/rotterdam_interpolated_<session>.csv.")
ap.add_argument("--cam1-offset-seconds", type=float, default=-3.0,
                help="Manually shift cam1's clock by this many seconds. "
                     "POSITIVE = the video's real start was LATER than "
                     "init_time currently reports (init_time moves later "
                     "to match). NEGATIVE = real start was EARLIER "
                     "(init_time moves earlier). Default -3.0 is the "
                     "empirically confirmed value for session "
                     "2026-07-27_17-38 (visually verified against real "
                     "ship AIS matches) -- override with a different "
                     "value for other sessions.")
ap.add_argument("--cam2-offset-seconds", type=float, default=-17.0,
                help="Same as --cam1-offset-seconds, but for cam2. Default "
                     "-17.0 is derived for session 2026-07-27_17-38 from "
                     "cam1's confirmed -3.0s anchor plus four independent "
                     "same-ship, same-location cross-camera measurements "
                     "(relative gaps of 12s, 14s, 13s, 15s, averaging to "
                     "16.5s total offset) -- override with a different "
                     "value for other sessions.")
ap.add_argument("--seek-seconds", type=float, default=110.0,
                help="How many seconds of REAL TIME to skip past, measured from "
                     "whichever camera starts LATER (after offset correction), "
                     "before processing begins. Default 110s skips the opening "
                     "stretch with no ships present. Lower this to test a "
                     "specific moment faster -- e.g. 161 lands around "
                     "14:41:05 for session 2026-07-27_17-38, just before "
                     "AMICITIA becomes visible. Set to 0 to disable.")
args = ap.parse_args()

# --- Build every session-specific path from --session. This is the
#     ONLY place the folder names cam1_KPN / cam2_kopvan need to live --
#     read_all() below does the actual work of finding the video FILE
#     inside each of these folders (handles extension, multiple yt-dlp
#     attempt files, etc.), same as it already did for Kanmon.
session_dir  = os.path.join(args.sessions_root, args.session)
data_path_1  = os.path.join(session_dir, "cam1_KPN")
data_path_2  = os.path.join(session_dir, "cam2_kopvan")
ais_dir      = args.ais_csv if args.ais_csv else os.path.join(args.ais_root, f"rotterdam_interpolated_{args.session}.csv")
result_path  = os.path.join(args.result_root, args.session) + "/"

if not os.path.exists(result_path):
    os.makedirs(result_path)

anti      = 1
anti_rate = 0

# --- Read configs for both cameras. This is what actually locates the
#     video file inside data_path_1 / data_path_2 -- you don't need to
#     write separate "find the video" code, this already does it. ---
vid_path_1, _, res_vid_1, res_met_1, init_time_1, cam_para_1 = read_all(data_path_1, result_path)
vid_path_2, _, res_vid_2, res_met_2, init_time_2, cam_para_2 = read_all(data_path_2, result_path)

print(f"[VIDEO] cam1 file: {vid_path_1}")
print(f"[VIDEO] cam2 file: {vid_path_2}")

# ---------------------------------------------------------
# MANUAL TIME-SYNC OVERRIDE -- applied right after read_all(), before
# anything else uses init_time_1/init_time_2. This directly corrects for
# the known gap between when the pipeline THINKS the video started and
# when it ACTUALLY started (e.g. yt-dlp connection/buffering delay),
# using a manually-measured offset in seconds rather than a .realstart
# sidecar file or the backfill script.
# ---------------------------------------------------------
from datetime import datetime as _dt2, timedelta as _td2, timezone as _tz2

def _apply_offset(init_time, offset_seconds, cam_label):
    if offset_seconds == 0.0:
        return init_time
    dt0 = _dt2(init_time[0], init_time[1], init_time[2],
               init_time[3], init_time[4], init_time[5],
               int(init_time[6] * 1000) if len(init_time) > 6 else 0,
               tzinfo=_tz2.utc)
    # POSITIVE offset = real start was LATER than init_time currently
    # says -> init_time is too EARLY -> move it LATER by adding the
    # offset. NEGATIVE offset moves it earlier, symmetrically.
    dt1 = dt0 + _td2(seconds=offset_seconds)
    corrected = [dt1.year, dt1.month, dt1.day, dt1.hour, dt1.minute, dt1.second,
                 int(round(dt1.microsecond / 1000))]
    print(f"[TIME-OVERRIDE] {cam_label}: {dt0} -> {dt1}  (offset {offset_seconds:+.1f}s)")
    return corrected

init_time_1 = _apply_offset(init_time_1, args.cam1_offset_seconds, "cam1")
init_time_2 = _apply_offset(init_time_2, args.cam2_offset_seconds, "cam2")

# ---------------------------------------------------------
# SYNC: use each camera's REAL start time (from read_all, possibly
# manually corrected above), not a time guessed by parsing the session
# folder name. AIS matching is driven entirely by Time1/Time2 below, so these must reflect the
# actual real-world time of the first video frame or AIS lookups
# will silently fail to match anything.
#
# Both cameras are already started at the same real-world time for
# this setup, so there's no separate lead/lag frame-skip step here.
# ---------------------------------------------------------
print(f"[SYNC] cam1 init_time={init_time_1}")
print(f"[SYNC] cam2 init_time={init_time_2}")

# ---------------------------------------------------------
# SETUP AIS PATHS SAFELY (SPLITTING FOLDER AND FILE)
# ---------------------------------------------------------
ais_csv_path = ais_dir.strip()
ais_path_shared = os.path.dirname(ais_csv_path)
ais_file_shared = [os.path.basename(ais_csv_path)]

if not os.path.exists(ais_csv_path):
    raise FileNotFoundError(
        f"No interpolated AIS csv found at {ais_csv_path}.\n"
        f"This must be generated from the raw AIS JSON polls in "
        f"{session_dir}/ais/ before fusion can run."
    )

print(f"[AIS] Using: {ais_csv_path}")

_, timestamp0, time0 = ais_initial(ais_path_shared, init_time_1)
_, _, _              = ais_initial(ais_path_shared, init_time_2)

ais_file_1 = ais_file_shared
ais_file_2 = ais_file_shared

# ---------------------------------------------------------
# 2. INITIALIZE VIDEO CAPTURES, READ REAL FPS PER CAMERA
# ---------------------------------------------------------
cap1 = cv2.VideoCapture(vid_path_1)
cap2 = cv2.VideoCapture(vid_path_2)

fps1 = cap1.get(cv2.CAP_PROP_FPS)
fps2 = cap2.get(cv2.CAP_PROP_FPS)

if not fps1 or fps1 <= 0:
    print("[WARN] cam1 fps unreadable from file, defaulting to 60.0")
    fps1 = 30.0
if not fps2 or fps2 <= 0:
    print("[WARN] cam2 fps unreadable from file, defaulting to 30.0")
    fps2 = 30.0

frame_dur_1 = 1000.0 / fps1   # ms per cam1 frame
frame_dur_2 = 1000.0 / fps2   # ms per cam2 frame

print(f"[SYNC] cam1 fps: {fps1:.3f}  (frame duration {frame_dur_1:.3f} ms)")
print(f"[SYNC] cam2 fps: {fps2:.3f}  (frame duration {frame_dur_2:.3f} ms)")

actual_msec_1 = cap1.get(cv2.CAP_PROP_POS_MSEC)
actual_msec_2 = cap2.get(cv2.CAP_PROP_POS_MSEC)

print("\n--- SYNC DIAGNOSTIC ---")
print(f"Cam 1 Position Time : {actual_msec_1} ms")
print(f"Cam 2 Position Time : {actual_msec_2} ms")
print(f"Position Difference : {actual_msec_1 - actual_msec_2} ms  (should be near 0 now)")
print("-----------------------\n")

# Independent clocks -- each seeded from that camera's OWN real
# init time (fixes the AIS-matching bug), not a shared guessed time.
Time1 = list(init_time_1)
Time2 = list(init_time_2)

# ---> FAST FORWARD (skip ahead in both videos before processing) <---
# cv2's CAP_PROP_POS_MSEC seek is a request, not a guarantee -- for most
# compressed video, OpenCV can typically only seek to the nearest keyframe,
# so the actual resulting position can differ from what was requested by
# anywhere from nothing to hundreds of ms or more, and can differ between
# cam1 and cam2 even when both are told the same target. Trusting the
# requested value instead of reading back what actually happened silently
# desyncs Time1/Time2 from the real video position -- exactly the class of
# bug this whole AIS-matching pipeline is sensitive to. So: seek, then
# measure, then derive Time1/Time2 from the measured position, not the
# requested one.
from datetime import datetime as _dt, timedelta as _td, timezone as _tz

SEEK_TARGET_MS = int(args.seek_seconds * 1000)  # of REAL TIME to skip past, measured from whichever camera starts LATER (see below). Set --seek-seconds 0 to disable fast-forward.

def _advance_time(init_time, actual_ms):
    dt0 = _dt(init_time[0], init_time[1], init_time[2],
              init_time[3], init_time[4], init_time[5], tzinfo=_tz.utc)
    dt1 = dt0 + _td(milliseconds=actual_ms)
    return [dt1.year, dt1.month, dt1.day, dt1.hour, dt1.minute, dt1.second,
            int(round(dt1.microsecond / 1000))]

# --- REAL-WORLD-MOMENT SEEK (fixes cam1/cam2 showing different real moments) ---
# BUG THIS FIXES: seeking both cameras to the SAME SEEK_TARGET_MS mark only
# lands them on the same real-world instant if both videos' frame-0 happen
# to correspond to the exact same real-world time. Since init_time_1 and
# init_time_2 (after the --cam1/2-offset-seconds correction above) can
# legitimately differ -- confirmed empirically for this session, cam1
# starts ~14-17s later than cam2 -- seeking both to "110s into MY OWN
# file" instead lands them 14-17s apart in real time, exactly matching
# the "cameras don't show the same real-world moment" symptom.
#
# Fix: pick ONE shared real-world target time (the later of the two
# corrected init_times, plus SEEK_TARGET_MS of real buffer), then compute
# EACH camera's own seek position as "how far into MY file is that same
# real moment" -- which will differ between cameras by construction,
# correctly compensating for their different real start times.
def _to_epoch_ms(init_time):
    dt = _dt(init_time[0], init_time[1], init_time[2],
             init_time[3], init_time[4], init_time[5], tzinfo=_tz.utc)
    return dt.timestamp() * 1000 + init_time[6]

init_epoch_ms_1 = _to_epoch_ms(init_time_1)
init_epoch_ms_2 = _to_epoch_ms(init_time_2)
later_start_epoch_ms = max(init_epoch_ms_1, init_epoch_ms_2)

shared_real_target_epoch_ms = later_start_epoch_ms + SEEK_TARGET_MS

seek_ms_1 = shared_real_target_epoch_ms - init_epoch_ms_1
seek_ms_2 = shared_real_target_epoch_ms - init_epoch_ms_2

print(f"[SEEK] cam1/cam2 real start times differ by "
      f"{abs(init_epoch_ms_1 - init_epoch_ms_2)/1000:.1f}s -- "
      f"computing per-camera seek targets so both land on the SAME "
      f"real-world moment (not the same file-relative timestamp).")
print(f"[SEEK] cam1 seek target: {seek_ms_1:.0f}ms into its own file")
print(f"[SEEK] cam2 seek target: {seek_ms_2:.0f}ms into its own file")

if seek_ms_1 < 0 or seek_ms_2 < 0:
    print(f"[WARN] Computed a negative seek target -- one camera's video "
          f"doesn't have enough runway before the shared real-world target "
          f"moment. Clamping to 0 for that camera; real-time alignment "
          f"will be off until that camera's video catches up naturally.")
    seek_ms_1 = max(seek_ms_1, 0)
    seek_ms_2 = max(seek_ms_2, 0)

if seek_ms_1 > 0 or seek_ms_2 > 0:
    cap1.set(cv2.CAP_PROP_POS_MSEC, seek_ms_1)
    cap2.set(cv2.CAP_PROP_POS_MSEC, seek_ms_2)

    actual_seek_ms_1 = cap1.get(cv2.CAP_PROP_POS_MSEC)
    actual_seek_ms_2 = cap2.get(cv2.CAP_PROP_POS_MSEC)

    print(f"[SEEK] cam1 requested {seek_ms_1:.0f}ms -> actually landed at "
          f"{actual_seek_ms_1}ms (off by {actual_seek_ms_1 - seek_ms_1:+.0f}ms)")
    print(f"[SEEK] cam2 requested {seek_ms_2:.0f}ms -> actually landed at "
          f"{actual_seek_ms_2}ms (off by {actual_seek_ms_2 - seek_ms_2:+.0f}ms)")

    # Recompute the ACTUAL real-world moment each camera landed on, using
    # the position OpenCV actually gave us (keyframe-snapped), not the
    # requested one -- same "seek then measure" principle as before, now
    # correctly applied per-camera against each camera's OWN init_time.
    Time1 = _advance_time(init_time_1, actual_seek_ms_1)
    Time2 = _advance_time(init_time_2, actual_seek_ms_2)

    landed_epoch_ms_1 = init_epoch_ms_1 + actual_seek_ms_1
    landed_epoch_ms_2 = init_epoch_ms_2 + actual_seek_ms_2
    real_moment_gap_s = abs(landed_epoch_ms_1 - landed_epoch_ms_2) / 1000
    print(f"[SEEK] Real-world moment gap after seeking: {real_moment_gap_s:.2f}s "
          f"(should be near 0 -- this is what actually matters for the two "
          f"video panes showing the same moment, NOT the raw ms seek "
          f"targets being equal)")
    if real_moment_gap_s > 1.0:
        print(f"[WARN] Still {real_moment_gap_s:.2f}s apart in real-world "
              f"terms after seeking -- likely keyframe-snapping rounding "
              f"on one or both cameras. Usually small enough to ignore, "
              f"but re-check --cam1/2-offset-seconds if this stays large.")
# ---------------------------------------------

im_shape_1 = [cap1.get(3), cap1.get(4)]
im_shape_2 = [cap2.get(3), cap2.get(4)]
max_dis_1  = 300
max_dis_2  = 300

# ---------------------------------------------------------
# 3. INSTANTIATE PIPELINES FOR EACH CAMERA
#    Each pipeline now gets ITS OWN frame duration (t1 / t2)
#    instead of a single shared `t` derived from cam1's fps.
# ---------------------------------------------------------
t1 = int(round(frame_dur_1))
t2 = int(round(frame_dur_2))
VIS1 = VISPRO(anti, anti_rate, t1, detect_roi=(256, 210, 854, 460), detect_upscale=4.0, min_confidence=0.03)
FUS1 = FUSPRO(max_dis_1, im_shape_1, t1, debug_label="cam1")
AIS1 = AISPRO(ais_path_shared, ais_file_1, im_shape_1, t1)

# Synthetic AIS assignment is removed entirely -- registry is no longer
# needed since DRAW is always run with no_synthetic=True below. Every
# AIS-unmatched moving vessel is drawn/logged honestly as "NO AIS"
# instead of being given a fabricated MMSI/speed/course.
DRA1 = DRAW(im_shape_1, t1, cam_para_1, None, camera_label="cam1",
            no_synthetic=True)

AIS2 = AISPRO(ais_path_shared, ais_file_2, im_shape_2, t2)
# ROUGH STARTING BOX, NOT MEASURED FROM A REAL FRAME -- estimated from
# screenshot proportions only. cam2 is 1920x1080 (confirmed by cx=960,
# cy=540 in cam_para_2). This roughly excludes the upper sky/building
# band and the lower foreground road/dock, leaving the water channel --
# but per VISPRO's own docstring, detect_roi needs visual tuning against
# actual footage. Pull a real frame (e.g. cam2_first_frame.jpg from a
# past session) and adjust these four numbers until the box tightly
# hugs just the water, the same way cam1's box was tuned.
# UPDATED ROI (was 0,350,1920,750) -- the previous y1=350 still included too
# much of the building band, confirmed by false "NO AIS" detections landing on
# the tall towers in a real screenshot. Pushed y1 down to 480 to clear the
# building facades, and y2 tightened slightly to 720 to stay clear of the
# foreground road/dock at the bottom. STILL AN ESTIMATE, not measured against
# a real frame -- verify against cam2_first_frame.jpg or a fresh screenshot
# and adjust further if false positives persist on buildings, or if real
# ships near the top of the water channel get clipped.
# CONFIRMED via check_roi.py against real frames at multiple timestamps
# (previous 0,480,1920,720 was too tight/misplaced; this was visually
# verified to correctly bound the water channel without clipping ships).
# detect_upscale=2.0 added as a test: a real ship on the right side showed
# intermittent, borderline confidence (0.674, then 0.213 a few seconds
# later, then nothing) rather than total absence -- consistent with a
# genuinely hard-to-recognize-consistently object (small/distant), which
# upscaling may help stabilize. Started at 2.0 (not cam1's 4.0) since
# cam2's native resolution is already much higher and Proc: times were
# already spiking to 20-45s at points -- raise further only if 2.0 proves
# insufficient.
VIS2 = VISPRO(anti, anti_rate, t2, detect_roi=(80, 552, 1920, 888), detect_upscale=2.0, min_confidence=0.2,
              deepsort_min_confidence=0.15, deepsort_n_init=2)
FUS2 = FUSPRO(max_dis_2, im_shape_2, t2, debug_label="cam2")
DRA2 = DRAW(im_shape_2, t2, cam_para_2, None, camera_label="cam2",
            no_synthetic=True)
show_size   = 500
videoWriter = None

bin_inf_1 = pd.DataFrame(columns=['ID', 'mmsi', 'timestamp', 'match'])
bin_inf_2 = pd.DataFrame(columns=['ID', 'mmsi', 'timestamp', 'match'])

times1 = 0; times2 = 0
time_i_1 = 0.0; time_i_2 = 0.0
sum_t = []

print(f'Start Time: {time2stamp(Time1)[1]} || Stamp: {time2stamp(Time1)[0]} '
      f'(actual post-seek start, cam1 clock)')

# ---------------------------------------------------------
# 4. SYNCHRONIZED PROCESSING LOOP — INDEPENDENT PER-CAMERA CLOCKS
# ---------------------------------------------------------
MASTER_DT = min(frame_dur_1, frame_dur_2)

acc1 = 0.0
acc2 = 0.0

# t1/t2 are frame_dur_1/frame_dur_2 rounded to whole ms for update_time()'s
# integer millisecond field. That rounding (e.g. 33.333ms -> 33ms at 30fps)
# makes Time1/Time2 fall behind the video's true elapsed time by a small
# amount every single frame -- ~0.33ms/frame here, which adds up to whole
# seconds of AIS-lookup-clock drift over a multi-minute session even
# though video playback itself stays correct (cap.read() always consumes
# exactly one real frame regardless of this). These carry the fractional
# remainder and add a compensating +-1ms every so often (Bresenham-style
# error diffusion) so the long-run average exactly matches the true frame
# duration instead of silently drifting.
frac_carry_1 = 0.0
frac_carry_2 = 0.0

ret1, im1_raw = cap1.read()
ret2, im2_raw = cap2.read()

if not ret1 or not ret2:
    raise RuntimeError("Could not read initial frame from one of the cameras.")

im1_drawn = im1_raw.copy()
im2_drawn = im2_raw.copy()

while True:
    if not ret1 or im1_raw is None or not ret2 or im2_raw is None:
        break

    acc1 += MASTER_DT
    acc2 += MASTER_DT

    # --- Camera 1: only step its own pipeline when its own frame is due ---
    if acc1 >= frame_dur_1:
        acc1 -= frame_dur_1
        im1 = im1_raw.copy()

        start = time.time()
        frac_carry_1 += (frame_dur_1 - t1)
        drift_correction_1 = 0
        if frac_carry_1 >= 1.0:
            drift_correction_1 = 1
            frac_carry_1 -= 1.0
        elif frac_carry_1 <= -1.0:
            drift_correction_1 = -1
            frac_carry_1 += 1.0
        Time1, timestamp1, Time_name1 = update_time(Time1, t1 + drift_correction_1)

        AIS_vis_1, AIS_cur_1 = AIS1.process(cam_para_1, timestamp1, Time_name1)
        Vis_tra_1, Vis_cur_1 = VIS1.feedCap(im1, timestamp1, AIS_vis_1, bin_inf_1)
        Fus_tra_1, bin_inf_1 = FUS1.fusion(AIS_vis_1, AIS_cur_1, Vis_tra_1, Vis_cur_1, timestamp1)
        im1_drawn            = DRA1.draw_traj(im1, AIS_vis_1, AIS_cur_1, Vis_tra_1, Vis_cur_1, Fus_tra_1, timestamp1)

        time_i_1 += time.time() - start

        if timestamp1 % 1000 < t1:
            gen_result(times1, Vis_cur_1, Fus_tra_1, res_met_1, im_shape_1)
            times1 += 1
            print(f'[cam1] Time: {Time_name1} | Stamp: {timestamp1} | AIS: {len(AIS_cur_1)} | Proc: {time_i_1:.4f}s')
            time_i_1 = 0.0

        ret1, im1_raw = cap1.read()

    # --- Camera 2: only step its own pipeline when its own frame is due ---
    if acc2 >= frame_dur_2:
        acc2 -= frame_dur_2
        im2 = im2_raw.copy()

        start = time.time()
        frac_carry_2 += (frame_dur_2 - t2)
        drift_correction_2 = 0
        if frac_carry_2 >= 1.0:
            drift_correction_2 = 1
            frac_carry_2 -= 1.0
        elif frac_carry_2 <= -1.0:
            drift_correction_2 = -1
            frac_carry_2 += 1.0
        Time2, timestamp2, Time_name2 = update_time(Time2, t2 + drift_correction_2)

        AIS_vis_2, AIS_cur_2 = AIS2.process(cam_para_2, timestamp2, Time_name2)
        Vis_tra_2, Vis_cur_2 = VIS2.feedCap(im2, timestamp2, AIS_vis_2, bin_inf_2)
        Fus_tra_2, bin_inf_2 = FUS2.fusion(AIS_vis_2, AIS_cur_2, Vis_tra_2, Vis_cur_2, timestamp2)
        im2_drawn            = DRA2.draw_traj(im2, AIS_vis_2, AIS_cur_2, Vis_tra_2, Vis_cur_2, Fus_tra_2, timestamp2)

        time_i_2 += time.time() - start

        if timestamp2 % 1000 < t2:
            gen_result(times2, Vis_cur_2, Fus_tra_2, res_met_2, im_shape_2)
            times2 += 1
            print(f'[cam2] Time: {Time_name2} | Stamp: {timestamp2} | AIS: {len(AIS_cur_2)} | Proc: {time_i_2:.4f}s')
            time_i_2 = 0.0

        ret2, im2_raw = cap2.read()

    # ---------------------------------------------------------
    # 5. STITCH AND RENDER (every master tick, using latest drawn
    #    frame from each camera -- holds the previous frame for
    #    whichever camera didn't update this tick)
    # ---------------------------------------------------------
    res_1 = imutils.resize(im1_drawn, height=show_size)
    res_2 = imutils.resize(im2_drawn, height=show_size)
    combined_result = np.hstack((res_1, res_2))

    if videoWriter is None:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out_video_path = os.path.join(result_path, 'combined_dual_view.mp4')
        output_fps = 1000.0 / MASTER_DT
        videoWriter = cv2.VideoWriter(out_video_path, fourcc, output_fps,
                                       (combined_result.shape[1], combined_result.shape[0]))

    videoWriter.write(combined_result)
    cv2.imshow('Dual Camera View', combined_result)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap1.release()
cap2.release()
if videoWriter:
    videoWriter.release()
cv2.destroyAllWindows()

print(f"Done! Check your result_dual folder: {result_path}")