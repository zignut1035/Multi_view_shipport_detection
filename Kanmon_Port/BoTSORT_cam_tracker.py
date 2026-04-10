"""
Multi-camera ship tracker — Kanmon Port
Runs YOLO on both cameras, assigns a shared global_id to the same ship
across cam1 (Shimonoseki) and cam2 (Moji).

Usage:
    python3 multicam_tracker.py \
        --cam1 Set1_cam1_shimonoseki.mp4 \
        --cam2 Set1_cam2_moji.mp4 \
        --model weights/best.pt \
        --show

Requirements:
    pip3 install ultralytics boxmot opencv-python-headless numpy pyproj
"""

import cv2
import numpy as np
import argparse
import math
from ultralytics import YOLO
from boxmot import BotSort
from pyproj import Transformer
from pathlib import Path

# ---------------------------------------------------------------------------
# 1.  UTM CONVERSION  (GPS → metres, zone 52N covers Kanmon area)
# ---------------------------------------------------------------------------

_t = Transformer.from_crs("epsg:4326", "epsg:32652", always_xy=True)

def to_utm(lon, lat):
    x, y = _t.transform(lon, lat)
    return (x, y)

# ---------------------------------------------------------------------------
# 2.  LANDMARKS — CLEANED
# ---------------------------------------------------------------------------

# --- CAM1: Shimonoseki landmarks (lon, lat) ---
CAM1_GPS = [
    (130.955347, 33.963303),   # 0 — Shimonoseki bridge base
    (130.961858, 33.959900),   # 1 — Moji bridge base
    # (130.961497, 33.948072), # 2 — Mojiko Retro REMOVED (902m error)
    (130.939142, 33.950114),   # 3 — Breakwater right
    (130.941286, 33.952989),   # 4 — Ferris wheel
]

# --- CAM2: Moji landmarks (lon, lat) ---
CAM2_GPS = [
    # (130.962308, 33.954875), # 0 — Breakwater left REMOVED (146m error)
    (130.962164, 33.955994),   # 1 — Breakwater right
    (130.962042, 33.957208),   # 2 — Red roof building
    (130.955425, 33.963311),   # 3 — Shimonoseki bridge base
    (130.929742, 33.949850),   # 4 — Kaikyo Yume Tower
]

# Convert to UTM (Using float64 to prevent OpenCV overflow)
CAM1_WORLD = np.float64([to_utm(lon, lat) for lon, lat in CAM1_GPS])
CAM2_WORLD = np.float64([to_utm(lon, lat) for lon, lat in CAM2_GPS])

# ---------------------------------------------------------------------------
# 3.  PIXEL COORDINATES
# ---------------------------------------------------------------------------

# CAM1 — Shimonoseki frame pixel coords
CAM1_PX = np.float32([
    [510,  466],  # Shimonoseki bridge base
    [926,  468],  # Moji bridge base
    # [51714, 3518], # Mojiko Retro REMOVED
    [1606, 770],  # Breakwater right
    [1001, 626],  # Ferris wheel
])

# CAM2 — Moji frame pixel coords
CAM2_PX = np.float32([
    # [3660, 253],  # Breakwater left REMOVED
    [1133, 701],  # Breakwater right
    [1650, 610],  # Red roof building
    [1782, 561],  # Shimonoseki bridge base
    [178,  533],  # Kaikyo Yume Tower
])

# Compute homography matrices using standard method (since we now have exactly 4 points)
# 0 is often better than cv2.RANSAC when you have the mathematical minimum of 4 points.
H1, _ = cv2.findHomography(CAM1_PX, CAM1_WORLD, 0)
H2, _ = cv2.findHomography(CAM2_PX, CAM2_WORLD, 0)

print("[calibration] H1 and H2 calculated successfully using 4 points each.", flush=True)

# Sanity check — shared point: Shimonoseki bridge base
# Using index 0 for Cam1 and index 3 for Cam2 (based on the cleaned lists)
# Note: Because we commented out earlier items, the indices in the active list have shifted. 
# Bridge base is now index 0 in CAM1, and index 2 in CAM2's active array.
_p1_world = to_utm(*CAM1_GPS[0])
_p2_world = to_utm(*CAM2_GPS[2]) 
_shared_dist = math.sqrt((_p1_world[0]-_p2_world[0])**2 + (_p1_world[1]-_p2_world[1])**2)
print(f"[sanity] Shared bridge point distance: {_shared_dist:.1f} m (should be < 10 m)", flush=True)


def px_to_world(u, v, H):
    """Project pixel (u, v) → UTM (x, y) in metres."""
    pt = np.float32([[[float(u), float(v)]]])
    result = cv2.perspectiveTransform(pt, H)
    return float(result[0][0][0]), float(result[0][0][1])


# ---------------------------------------------------------------------------
# 4.  MATCHING PARAMS  (both cameras only see the strait)
# ---------------------------------------------------------------------------

MATCH_DIST_M  = 100       # only match if cameras agree within 100m
REID_DIST_M   = 80        # tighter re-id radius too
MERGE_VOTES   = 150       # ~2.5s at 60fps, much harder to accidentally merge
EXPIRY_FRAMES = 1800      # fine
MERGE_FRESHNESS_FRAMES = 150   # halved — stale votes clear faster
REID_MAX_ABSENCE_FRAMES = 3600 # fine

def euclidean(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


# ---------------------------------------------------------------------------
# 5.  GLOBAL ID REGISTRY
# ---------------------------------------------------------------------------

_global_id_counter = 1
_local_to_global: dict[tuple, int] = {}

_last_seen:  dict[tuple, int]   = {}
_last_world: dict[tuple, tuple] = {}
_merge_votes: dict[tuple, int]  = {}
_warned_pairs: set = set()
_valid_global_ids: set = set()  

def get_or_create_global(cam: int, local_id: int,
                         wx: float = None, wy: float = None, current_frame: int = 0) -> int:
    global _global_id_counter, _valid_global_ids
    key = (cam, int(local_id))
    if key not in _local_to_global:
        if wx is not None and wy is not None:
            recycled = reidentify_new_track(cam, local_id, wx, wy, current_frame)
            if recycled is not None:
                print(f"[REID] cam{cam} new lid{local_id} → reused G{recycled}", flush=True)
                _local_to_global[key] = recycled
                return recycled
        print(f"[NEW] cam{cam} lid{local_id} → G{_global_id_counter} "
              f"world=({wx:.0f},{wy:.0f})" if wx is not None else
              f"[NEW] cam{cam} lid{local_id} → G{_global_id_counter}", flush=True)
        _local_to_global[key] = _global_id_counter
        _valid_global_ids.add(_global_id_counter)  # <--- NEW
        _global_id_counter += 1
    return _local_to_global[key]


def reidentify_new_track(cam: int, local_id: int, wx: float, wy: float, current_frame: int):
    key = (cam, int(local_id))
    if key in _local_to_global:
        return None

    best_dist = REID_DIST_M
    best_gid  = None

    for old_key, gid in list(_local_to_global.items()):
        if old_key == key:
            continue
        if old_key[0] != cam:
            continue
        if _last_seen.get(old_key, 0) == current_frame:
            continue

        frames_absent = current_frame - _last_seen.get(old_key, 0)

        # Skip tracks that are still actively being seen — they don't need ReID
        if frames_absent < 5:
            continue

        # Skip IDs that have been gone too long
        if frames_absent > REID_MAX_ABSENCE_FRAMES:
            continue

        if old_key in _last_world:
            d = euclidean((wx, wy), _last_world[old_key])
            if d < best_dist:
                best_dist = d
                best_gid  = gid

    return best_gid


def force_same_global(cam1: int, lid1: int, cam2: int, lid2: int, current_frame: int = 0):
    global _global_id_counter, _valid_global_ids
    key1 = (cam1, int(lid1))
    key2 = (cam2, int(lid2))

    has_1 = key1 in _local_to_global
    has_2 = key2 in _local_to_global

    if has_1 and has_2:
        gid1 = _local_to_global[key1]
        gid2 = _local_to_global[key2]
        if gid1 == gid2:
            return

        age1 = current_frame - _last_seen.get(key1, 0)
        age2 = current_frame - _last_seen.get(key2, 0)
        if age1 > MERGE_FRESHNESS_FRAMES or age2 > MERGE_FRESHNESS_FRAMES:
            return

        vote_key = (min(key1, key2), max(key1, key2))
        _merge_votes[vote_key] = _merge_votes.get(vote_key, 0) + 1

        if _merge_votes[vote_key] >= MERGE_VOTES:
            gid = min(gid1, gid2)
            burned_gid = max(gid1, gid2)
            _local_to_global[key1] = gid
            _local_to_global[key2] = gid
            _valid_global_ids.discard(burned_gid)  # <--- NEW: Remove burned ID from true count
            print(f"[MERGE] G{gid1} + G{gid2} → G{gid} "
                  f"after {_merge_votes[vote_key]} votes", flush=True)
            _merge_votes.pop(vote_key, None)

            pair = (min(gid1, gid2), max(gid1, gid2))
            _warned_pairs.discard(pair)

        else:
            pair = (min(gid1, gid2), max(gid1, gid2))
            if pair not in _warned_pairs:
                print(f"[WARN] Suspicious pair G{gid1} (cam{cam1},lid{lid1}) "
                      f"↔ G{gid2} (cam{cam2},lid{lid2}) — "
                      f"vote {_merge_votes[vote_key]}/{MERGE_VOTES}", flush=True)
                _warned_pairs.add(pair)
        return

    elif has_1:
        _local_to_global[key2] = _local_to_global[key1]
    elif has_2:
        _local_to_global[key1] = _local_to_global[key2]
    else:
        gid = _global_id_counter
        _valid_global_ids.add(gid)  # <--- NEW
        _global_id_counter += 1
        _local_to_global[key1] = gid
        _local_to_global[key2] = gid


def refresh_active_mappings(tc1: list, tc2: list, frame_idx: int):
    for t in tc1:
        k = (1, t["local_id"])
        _last_seen[k]  = frame_idx
        _last_world[k] = t["world"]
    for t in tc2:
        k = (2, t["local_id"])
        _last_seen[k]  = frame_idx
        _last_world[k] = t["world"]

    stale = [k for k in list(_local_to_global)
             if frame_idx - _last_seen.get(k, 0) > EXPIRY_FRAMES]
             
    for k in stale:
        expired_gid = _local_to_global[k]  # Grab the global ID before deleting
        
        del _local_to_global[k]
        _last_seen.pop(k, None)
        _last_world.pop(k, None)
        
        for vk in list(_merge_votes):
            if k in vk:
                del _merge_votes[vk]
                
        # --- FIX 2 APPLIED: Scrub any warnings attached to this dead ID ---
        for pair in list(_warned_pairs):
            if expired_gid in pair:
                _warned_pairs.discard(pair)

# ---------------------------------------------------------------------------
# 6.  CROSS-CAMERA MATCHING
# ---------------------------------------------------------------------------

def cross_camera_match(tracks_c1: list, tracks_c2: list, frame_idx: int = 0):
    refresh_active_mappings(tracks_c1, tracks_c2, frame_idx)

    # 1. Build a list of ALL possible pairs across both cameras
    all_pairs = []
    for t1 in tracks_c1:
        for t2 in tracks_c2:
            d = euclidean(t1["world"], t2["world"])
            if d < MATCH_DIST_M:
                all_pairs.append((d, t1, t2))

    # 2. Sort all pairs by absolute closest distance first
    all_pairs.sort(key=lambda x: x[0])

    assigned_t1_locals = set()
    assigned_t2_locals = set()

    # 3. Assign greedily (closest pairs get locked in first)
    for d, t1, t2 in all_pairs:
        if t1["local_id"] in assigned_t1_locals or t2["local_id"] in assigned_t2_locals:
            continue # One of them is already paired to something closer

        assigned_t1_locals.add(t1["local_id"])
        assigned_t2_locals.add(t2["local_id"])
        force_same_global(1, t1["local_id"], 2, t2["local_id"], frame_idx)

    # 4. Wipe votes for any cam1 tracks that weren't matched
    matched_t1_keys = {(1, lid) for lid in assigned_t1_locals}
    for t1 in tracks_c1:
        key1 = (1, t1["local_id"])
        if key1 not in matched_t1_keys:
            for vk in list(_merge_votes):
                if key1 in vk:
                    _merge_votes.pop(vk, None) # <--- CRASH-PROOF DELETION

    # 5. Wipe votes for any cam2 tracks that weren't matched
    matched_t2_keys = {(2, lid) for lid in assigned_t2_locals}
    for t2 in tracks_c2:
        key2 = (2, t2["local_id"])
        if key2 not in matched_t2_keys:
            for vk in list(_merge_votes):
                if key2 in vk:
                    _merge_votes.pop(vk, None) # <--- CRASH-PROOF DELETION

    # 6. Assign globals to completely new tracks
    for t1 in tracks_c1:
        if (1, t1["local_id"]) not in _local_to_global:
            get_or_create_global(1, t1["local_id"], *t1["world"], frame_idx)
    for t2 in tracks_c2:
        if (2, t2["local_id"]) not in _local_to_global:
            get_or_create_global(2, t2["local_id"], *t2["world"], frame_idx)


# ---------------------------------------------------------------------------
# 7.  PARSE TRACKER OUTPUT
# ---------------------------------------------------------------------------

def parse_tracks(raw_tracks, cam_id: int, H) -> list:
    result = []
    if raw_tracks is None or len(raw_tracks) == 0:
        return result
    for row in raw_tracks:
        x1, y1, x2, y2, local_id, conf, cls = row[:7]
        
        # Calculate WATERLINE (bottom-center of bounding box) for accurate GPS
        cx = (x1 + x2) / 2.0
        cy = float(y2)  
        
        wx, wy = px_to_world(cx, cy, H)
        result.append({
            "local_id": int(local_id),
            "bbox":     (float(x1), float(y1), float(x2), float(y2)),
            "world":    (wx, wy),
            "conf":     float(conf),
            "cls":      int(cls),
        })
    return result

# ---------------------------------------------------------------------------
# 8.  DRAWING
# ---------------------------------------------------------------------------

_COLORS: dict[int, tuple] = {}

def track_color(gid: int) -> tuple:
    if gid not in _COLORS:
        rng = np.random.RandomState(gid * 37 + 13)
        _COLORS[gid] = tuple(int(c) for c in rng.randint(80, 230, 3))
    return _COLORS[gid]

def draw_tracks(frame, tracks_info: list, cam_label: str, frame_idx: int):
    for t in tracks_info:
        x1, y1, x2, y2 = (int(v) for v in t["bbox"])
        gid   = t.get("global_id", -1)
        color = track_color(gid)

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        label = f"G{gid}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(frame, (x1, y1 - th - 10), (x1 + tw + 4, y1), color, -1)
        cv2.putText(frame, label, (x1 + 2, y1 - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        wx, wy = t["world"]
        cv2.putText(frame, f"({wx:.0f},{wy:.0f})",
                    (x1, y2 + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)

    cv2.putText(frame,
                f"{cam_label}  |  frame {frame_idx}  |  ships: {len(tracks_info)}",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return frame


# ---------------------------------------------------------------------------
# 9.  MAIN LOOP
# ---------------------------------------------------------------------------
 
def run(args):
    model = YOLO(args.model)

    cap1 = cv2.VideoCapture(args.cam1)
    cap2 = cv2.VideoCapture(args.cam2)

    assert cap1.isOpened(), f"Cannot open {args.cam1}"
    assert cap2.isOpened(), f"Cannot open {args.cam2}"

    fps1 = cap1.get(cv2.CAP_PROP_FPS) or 60.0
    fps2 = cap2.get(cv2.CAP_PROP_FPS) or 30.0

    dur1 = cap1.get(cv2.CAP_PROP_FRAME_COUNT) / fps1
    dur2 = cap2.get(cv2.CAP_PROP_FRAME_COUNT) / fps2
    print(f"cam1: {fps1}fps  {dur1:.1f}s  ({int(dur1//60)}m{int(dur1%60):02d}s)", flush=True)
    print(f"cam2: {fps2}fps  {dur2:.1f}s  ({int(dur2//60)}m{int(dur2%60):02d}s)", flush=True)

    # ------------------------------------------------------------------
    # TRACKER INITIALIZATION
    # ------------------------------------------------------------------
    track_buffer_seconds = 15.0

    frames_buffer1 = int(fps1 * track_buffer_seconds)
    frames_buffer2 = int(fps2 * track_buffer_seconds)

    tracker1 = BotSort(
        Path("osnet_x0_25_msmt17.pt"),  # reid_weights — positional
        "cuda:0",                        # device — positional
        False,                           # half — positional
        track_high_thresh=0.3,
        track_low_thresh=0.1,
        track_buffer=frames_buffer1,
        frame_rate=int(fps1),
        max_age=frames_buffer1,
)

    tracker2 = BotSort(
        Path("osnet_x0_25_msmt17.pt"),
        "cuda:0",
        False,
        track_high_thresh=0.3,
        track_low_thresh=0.1,
        track_buffer=frames_buffer2,
        frame_rate=int(fps2),
        max_age=frames_buffer2,
)

    # ------------------------------------------------------------------
    # SYNC LOGIC: Fast-forward CAM2 to align to the same real-world time
    # ------------------------------------------------------------------
    sync_offset_seconds = args.sync_offset
    offset_frames_cam2 = int(sync_offset_seconds * fps2)

    print(f"[sync] Fast-forwarding {offset_frames_cam2} frames "
          f"({sync_offset_seconds}s) on cam2...", flush=True)
    for _ in range(offset_frames_cam2):
        success, _ = cap2.read()
        if not success:
            break
    print("[sync] Fast-forward complete. Starting tracking.", flush=True)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    w1 = int(cap1.get(cv2.CAP_PROP_FRAME_WIDTH))
    h1 = int(cap1.get(cv2.CAP_PROP_FRAME_HEIGHT))
    w2 = int(cap2.get(cv2.CAP_PROP_FRAME_WIDTH))
    h2 = int(cap2.get(cv2.CAP_PROP_FRAME_HEIGHT))

    out1 = cv2.VideoWriter("out_cam1.mp4", fourcc, fps1, (w1, h1))
    out2 = cv2.VideoWriter("out_cam2.mp4", fourcc, fps2, (w2, h2))

    frame_idx1 = 0
    frame_idx2 = offset_frames_cam2
    tc1 = []
    tc2 = []
    cam2_active = True

    # ------------------------------------------------------------------
    # Read and write CAM2's first frame before the main loop
    # ------------------------------------------------------------------
    ret2, f2 = cap2.read()
    if ret2:
        frame_idx2 += 1
        det2 = model(f2, verbose=False, conf=0.25, iou=0.45)[0].boxes.data.cpu().numpy()
        raw2 = tracker2.update(det2, f2)
        tc2 = parse_tracks(raw2, 2, H2)
        cross_camera_match(tc1, tc2, 0)
        for t in tc2:
            t["global_id"] = _local_to_global.get((2, t["local_id"]), -1)
        f2_draw = draw_tracks(f2.copy(), tc2, "CAM2 Moji", frame_idx2)
        out2.write(f2_draw)
    else:
        cam2_active = False

    # ------------------------------------------------------------------
    # MAIN LOOP WITH CTRL+C HANDLING
    # ------------------------------------------------------------------
    cam2_time_accumulator = 0.0
    seconds_per_f1 = 1.0 / fps1
    seconds_per_f2 = 1.0 / fps2

    try:
        while True:
            ret1, f1 = cap1.read()
            if not ret1:
                break
            frame_idx1 += 1

            # 1. Update CAM1 every loop iteration
            results1 = model(f1, verbose=False, conf=0.45, iou=0.45)[0].boxes.data.cpu().numpy()
            det1 = results1 if (results1 is not None and len(results1) > 0) else np.empty((0, 6))
            raw1 = tracker1.update(det1, f1)
            tc1  = parse_tracks(raw1, 1, H1)

            # 2. Update CAM2 at its own rate (Leaky Bucket to prevent FPS drift)
            cam2_time_accumulator += seconds_per_f1
            is_cam2_frame = False

            if cam2_active and cam2_time_accumulator >= seconds_per_f2:
                is_cam2_frame = True
                cam2_time_accumulator -= seconds_per_f2

            if is_cam2_frame:
                ret2, f2 = cap2.read()
                if ret2:
                    frame_idx2 += 1
                    results2 = model(f2, verbose=False, conf=0.30, iou=0.45, imgsz=1280)[0].boxes.data.cpu().numpy()
                    det2 = results2 if (results2 is not None and len(results2) > 0) else np.empty((0, 6))
                    raw2 = tracker2.update(det2, f2)
                    tc2  = parse_tracks(raw2, 2, H2)
                else:
                    print(f"[INFO] CAM2 exhausted. Continuing CAM1 only.", flush=True)
                    cam2_active = False
                    tc2 = []

                # 3. Cross-camera matching (only when both cameras are fresh)
                cross_camera_match(tc1, tc2, frame_idx1)

            else:
                # Intermediate frames: ensure brand new CAM1 ships get IDs
                for t1 in tc1:
                    if (1, t1["local_id"]) not in _local_to_global:
                        get_or_create_global(1, t1["local_id"], *t1["world"], frame_idx1)

            # 4. Attach global IDs for drawing
            for t in tc1:
                t["global_id"] = _local_to_global.get((1, t["local_id"]), -1)
            for t in tc2:
                t["global_id"] = _local_to_global.get((2, t["local_id"]), -1)

            # 5. Draw and write outputs
            f1_draw = draw_tracks(f1.copy(), tc1, "CAM1 Shimonoseki", frame_idx1)
            out1.write(f1_draw)

            if is_cam2_frame:
                if cam2_active and ret2:
                    f2_draw = draw_tracks(f2.copy(), tc2, "CAM2 Moji", frame_idx2)
                    out2.write(f2_draw)
                elif 'f2_draw' in locals():
                    out2.write(f2_draw)

            if frame_idx1 % 100 == 0:
                print(f"frame {frame_idx1:5d}  |  "
                      f"cam1 tracks: {len(tc1)}  cam2 tracks: {len(tc2)}  |  "
                      f"global IDs so far: {_global_id_counter - 1}", flush=True)

    except KeyboardInterrupt:
        print("\n[INFO] Stopping early...", flush=True)

    finally:
        cap1.release()
        cap2.release()
        out1.release()
        out2.release()

        print(f"\nDone. Processed {frame_idx1} CAM1 frames "
              f"and {frame_idx2} CAM2 frames.", flush=True)
        print(f"Raw Global ID Counter (Inflated): {_global_id_counter - 1}", flush=True)
        print(f"TRUE Unique Ships (After Merges): {len(_valid_global_ids)}", flush=True)
        print("Saved: out_cam1.mp4  out_cam2.mp4", flush=True)

# ---------------------------------------------------------------------------
# 10.  ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kanmon multi-camera ship tracker")
    parser.add_argument("--cam1",  default="cam1_synced.mp4")
    parser.add_argument("--cam2",  default="cam2_synced.mp4")
    parser.add_argument("--model", default="weights/best.pt")
    parser.add_argument("--show",  action="store_true")
    
    # --- NEW ARGUMENT ADDED HERE ---
    parser.add_argument("--sync-offset", type=float, default=9.0, 
                        help="Seconds to fast-forward CAM2 to sync with CAM1")
    # -------------------------------
    
    run(parser.parse_args())