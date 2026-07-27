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

TWO-PASS WORKFLOW NOTE (NEW):
  --ais-csv lets you override the default session-derived AIS CSV
  path. This enables a two-pass workflow: pass 1 runs normally and
  produces synthetic_ais_log.csv (vessels with no real AIS match);
  convert_synthetic_to_ais.py then merges that with the real AIS CSV;
  pass 2 re-runs THIS SAME script with --ais-csv pointing at the
  merged file, so previously-synthetic vessels are now matched by
  FUSPRO's own real gates (distance/heading/confirmation) instead of
  the heuristic synthesis in draw.py.
"""
import os, time, imutils, cv2, argparse, glob, json
import pandas as pd
import numpy as np
from PIL import Image

from utils.file_read import read_all, ais_initial, update_time, time2stamp
from utils.AIS_utils import AISPRO
from utils.VIS_utils import VISPRO
from utils.FUS_utils import FUSPRO
from utils.draw import DRAW, SyntheticAISRegistry
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
                     "the default <ais-root>/rotterdam_interpolated_<session>.csv. "
                     "Use this for a second pass with a merged real+synthetic CSV "
                     "produced by convert_synthetic_to_ais.py -- previously-synthetic "
                     "vessels are then matched as real AIS vessels by FUSPRO's own "
                     "gates, instead of relying on the heuristic synthesis in draw.py.")
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
# SYNC: use each camera's REAL start time (from read_all), not a
# time guessed by parsing the session folder name. AIS matching is
# driven entirely by Time1/Time2 below, so these must reflect the
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

SEEK_TARGET_MS = 224000  # 3 min 44 sec -- set to 0 to disable fast-forward

def _advance_time(init_time, actual_ms):
    dt0 = _dt(init_time[0], init_time[1], init_time[2],
              init_time[3], init_time[4], init_time[5], tzinfo=_tz.utc)
    dt1 = dt0 + _td(milliseconds=actual_ms)
    return [dt1.year, dt1.month, dt1.day, dt1.hour, dt1.minute, dt1.second,
            int(round(dt1.microsecond / 1000))]

if SEEK_TARGET_MS > 0:
    cap1.set(cv2.CAP_PROP_POS_MSEC, SEEK_TARGET_MS)
    cap2.set(cv2.CAP_PROP_POS_MSEC, SEEK_TARGET_MS)

    actual_seek_ms_1 = cap1.get(cv2.CAP_PROP_POS_MSEC)
    actual_seek_ms_2 = cap2.get(cv2.CAP_PROP_POS_MSEC)

    print(f"[SEEK] cam1 requested {SEEK_TARGET_MS}ms -> actually landed at "
          f"{actual_seek_ms_1}ms (off by {actual_seek_ms_1 - SEEK_TARGET_MS:+.0f}ms)")
    print(f"[SEEK] cam2 requested {SEEK_TARGET_MS}ms -> actually landed at "
          f"{actual_seek_ms_2}ms (off by {actual_seek_ms_2 - SEEK_TARGET_MS:+.0f}ms)")
    if abs(actual_seek_ms_1 - actual_seek_ms_2) > 200:
        print(f"[WARN] cam1/cam2 seeked to positions "
              f"{abs(actual_seek_ms_1 - actual_seek_ms_2):.0f}ms apart -- "
              f"the two cameras are no longer time-aligned with each other.")

    Time1 = _advance_time(init_time_1, actual_seek_ms_1)
    Time2 = _advance_time(init_time_2, actual_seek_ms_2)
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

# ONE shared registry so the same physical vessel (recognized by real-world
# position, not track ID) gets the same synthetic MMSI whether cam1 or cam2
# is currently tracking it, and keeps that same MMSI across DeepSORT track
# loss/reacquisition within either camera.
synthetic_registry = SyntheticAISRegistry()

# DRAW now needs each camera's own real calibration, so it can
# back-project positions for vessels with no real AIS match (synthetic
# AIS assignment for demo completeness).
DRA1 = DRAW(im_shape_1, t1, cam_para_1, synthetic_registry, camera_label="cam1")

AIS2 = AISPRO(ais_path_shared, ais_file_2, im_shape_2, t2)
VIS2 = VISPRO(anti, anti_rate, t2, min_confidence=0.40)
FUS2 = FUSPRO(max_dis_2, im_shape_2, t2, debug_label="cam2")
DRA2 = DRAW(im_shape_2, t2, cam_para_2, synthetic_registry, camera_label="cam2")
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

synthetic_registry.save_to_csv(os.path.join(result_path, "synthetic_ais_log.csv"))

print("Done! Check your result_dual folder.")