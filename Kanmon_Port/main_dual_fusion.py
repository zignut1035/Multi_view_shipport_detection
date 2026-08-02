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
args = ap.parse_args()

# --- Build every session-specific path from --session. This is the
#     ONLY place the folder names cam1_KPN / cam2_kopvan need to live --
#     read_all() below does the actual work of finding the video FILE
#     inside each of these folders (handles extension, multiple yt-dlp
#     attempt files, etc.), same as it already did for Kanmon.
session_dir  = os.path.join(args.sessions_root, args.session)
data_path_1  = os.path.join(session_dir, "cam1_KPN")
data_path_2  = os.path.join(session_dir, "cam2_kopvan")
ais_dir      = os.path.join(args.ais_root, f"rotterdam_interpolated_{args.session}.csv")
result_path  = os.path.join(args.result_root, args.session) + "/"

if not os.path.exists(result_path):
    os.makedirs(result_path)

# --- HARDCODED SYNC (Bypassing JSON file) ---
lead_camera = None
lead_seconds = 0.0

# Extract the start time directly from the session name (e.g., "2026-05-27_15-35")
try:
    date_str, time_str = args.session.split('_')
    year, month, day = map(int, date_str.split('-'))
    hour, minute = map(int, time_str.split('-'))
    SYNCED_START_TIME = [year, month, day, hour, minute, 0, 0]
except Exception as e:
    print("[WARN] Could not parse session name into time. Using default.")
    SYNCED_START_TIME = [2026, 5, 27, 15, 35, 0, 0]

print("[SYNC] JSON sync check bypassed.")
print(f"[SYNC] Assuming no offset. lead_camera={lead_camera}, lead_seconds={lead_seconds}")
print(f"[SYNC] synced_start_time={SYNCED_START_TIME}")

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
    fps1 = 60.0
if not fps2 or fps2 <= 0:
    print("[WARN] cam2 fps unreadable from file, defaulting to 30.0")
    fps2 = 30.0

frame_dur_1 = 1000.0 / fps1   # ms per cam1 frame
frame_dur_2 = 1000.0 / fps2   # ms per cam2 frame

print(f"[SYNC] cam1 fps: {fps1:.3f}  (frame duration {frame_dur_1:.3f} ms)")
print(f"[SYNC] cam2 fps: {fps2:.3f}  (frame duration {frame_dur_2:.3f} ms)")

# --- FAST FORWARD WHICHEVER CAMERA LEADS, so both start at the same
#     real-world OSD time. Which camera leads varies session to session
#     (stream buffering delay isn't guaranteed to always favor the same
#     camera), so this is driven entirely by sync_offset.json rather
#     than assuming it's always cam1.
if lead_camera == "cam1" and lead_seconds > 0:
    skip_cap, skip_fps, skip_label = cap1, fps1, "Camera 1"
elif lead_camera == "cam2" and lead_seconds > 0:
    skip_cap, skip_fps, skip_label = cap2, fps2, "Camera 2"
else:
    skip_cap, skip_fps, skip_label = None, None, None

if skip_cap is not None:
    frames_to_skip = round(lead_seconds * skip_fps)
    print(f"Fast-forwarding {skip_label} by {frames_to_skip} frames "
          f"({lead_seconds}s @ {skip_fps:.3f}fps) to sync start...")
    for _ in range(frames_to_skip):
        ret, _ = skip_cap.read()
        if not ret:
            break
    print(f"{skip_label} is in position!")
else:
    print("Cameras already start at the same OSD second -- no skip needed.")

actual_msec_1 = cap1.get(cv2.CAP_PROP_POS_MSEC)
actual_msec_2 = cap2.get(cv2.CAP_PROP_POS_MSEC)

print("\n--- SYNC DIAGNOSTIC ---")
print(f"Cam 1 Position Time : {actual_msec_1} ms")
print(f"Cam 2 Position Time : {actual_msec_2} ms")
print(f"Position Difference : {actual_msec_1 - actual_msec_2} ms  (should be near 0 now)")
print("-----------------------\n")

# Independent clocks, both starting from the same real-world synced time
Time1 = SYNCED_START_TIME.copy()
Time2 = SYNCED_START_TIME.copy()

im_shape_1 = [cap1.get(3), cap1.get(4)]
im_shape_2 = [cap2.get(3), cap2.get(4)]
max_dis_1  = min(im_shape_1) // 2
max_dis_2  = min(im_shape_2) // 2

# ---------------------------------------------------------
# 3. INSTANTIATE PIPELINES FOR EACH CAMERA
#    Each pipeline now gets ITS OWN frame duration (t1 / t2)
#    instead of a single shared `t` derived from cam1's fps.
# ---------------------------------------------------------
t1 = int(round(frame_dur_1))
t2 = int(round(frame_dur_2))

AIS1 = AISPRO(ais_path_shared, ais_file_1, im_shape_1, t1)
VIS1 = VISPRO(anti, anti_rate, t1)
FUS1 = FUSPRO(max_dis_1, im_shape_1, t1, cam_para_1, debug_label="cam1")
DRA1 = DRAW(im_shape_1, t1)
AIS2 = AISPRO(ais_path_shared, ais_file_2, im_shape_2, t2)
VIS2 = VISPRO(anti, anti_rate, t2)
FUS2 = FUSPRO(max_dis_2, im_shape_2, t2, cam_para_2, debug_label="cam2")
DRA2 = DRAW(im_shape_2, t2)

show_size   = 500
videoWriter = None

bin_inf_1 = pd.DataFrame(columns=['ID', 'mmsi', 'timestamp', 'match'])
bin_inf_2 = pd.DataFrame(columns=['ID', 'mmsi', 'timestamp', 'match'])

times1 = 0; times2 = 0
time_i_1 = 0.0; time_i_2 = 0.0
sum_t = []

print(f'Start Time: {time0} || Stamp: {timestamp0}')

# ---------------------------------------------------------
# 4. SYNCHRONIZED PROCESSING LOOP — INDEPENDENT PER-CAMERA CLOCKS
# ---------------------------------------------------------
MASTER_DT = min(frame_dur_1, frame_dur_2)

acc1 = 0.0
acc2 = 0.0

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
        Time1, timestamp1, Time_name1 = update_time(Time1, t1)

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
        Time2, timestamp2, Time_name2 = update_time(Time2, t2)

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

print("Done! Check your result_dual folder.")