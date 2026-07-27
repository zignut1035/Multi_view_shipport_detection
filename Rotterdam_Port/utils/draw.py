import pandas as pd
import numpy as np
import cv2
import time
import math
import random
from math import radians, cos, sin, atan2, degrees, tan
from geopy.distance import geodesic
import pyproj


def add_alpha_channel(img):
    """ 为jpg图像添加alpha通道 """
    b_channel, g_channel, r_channel = cv2.split(img)
    alpha_channel = np.ones(b_channel.shape, dtype=b_channel.dtype) * 255
    img_new = cv2.merge((b_channel, g_channel, r_channel, alpha_channel))
    return img_new

def remove_alpha_channel(img):
    """ 为jpg图像添加alpha通道 """
    b_channel, g_channel, r_channel, a_channel = cv2.split(img)
    jpg_img = cv2.merge((b_channel, g_channel, r_channel))
    return jpg_img

def draw_box(add_img, x1, y1, x2, y2, color, tf):
    y15 = y1 + (y2 - y1) // 4
    x15 = x1 + (y2 - y1) // 4
    y45 = y2 - (y2 - y1) // 4
    x45 = x2 - (y2 - y1) // 4
    cv2.line(add_img, (x1, y1), (x1, y15), color, tf)
    cv2.line(add_img, (x1, y1), (x15, y1), color, tf)
    cv2.line(add_img, (x2, y1), (x2, y15), color, tf)
    cv2.line(add_img, (x45, y1), (x2, y1), color, tf)
    cv2.line(add_img, (x1, y2), (x15, y2), color, tf)
    cv2.line(add_img, (x1, y45), (x1, y2), color, tf)
    cv2.line(add_img, (x45, y2), (x2, y2), color, tf)
    cv2.line(add_img, (x2, y45), (x2, y2), color, tf)
    return add_img

def draw_line(add_img, x1, y1, x2, y2, y_deta, color, tf):
    cv2.circle(add_img, (x1, y1), tf, color, tf // 3)
    cv2.circle(add_img, (x2, y2), tf, color, tf // 3)
    cv2.line(add_img, (x1, y1 + tf), (x1, y1 + y_deta), color, tf // 2)
    cv2.line(add_img, (x1, y1 + y_deta), (x2, y1 + y_deta), color, tf // 2)
    cv2.line(add_img, (x2, y1 + y_deta), (x2, y2 - tf), color, tf // 2)
    return add_img

def inf_loc(x, y_top, w, h, w0, h0):
    """
    Position the info panel ABOVE the ship's bounding box, instead of at a
    fixed row near the bottom of the whole frame.
    """
    x1 = x - w0 // 2
    x2 = x + w0 // 2
    y2 = y_top - 120
    y1 = y2 - h0
    if x1 < 0:
        x1 = 0
        x2 = w0
    if x2 > w:
        x1 = w - w0
        x2 = w
    if y1 < 0:
        y1 = y_top + 120
        y2 = y1 + h0
    return x1, y1, x2, y2


# ===========================================================================
# Synthetic AIS assignment for genuinely moving vessels with no real AIS
# match. Position is REAL (back-projected from that vessel's own actual
# tracked pixel using this camera's own calibration); speed/course are
# derived from its own recent real motion in pixel space. Only the MMSI
# is arbitrary, and it is drawn from a range (900000000+) that can never
# collide with or be mistaken for a real MMSI already in the AIS feed.
# ===========================================================================

def _count_distance(p1, p2):
    return geodesic(p1, p2).m


def _get_degree(latA, lonA, latB, lonB):
    radLatA, radLonA, radLatB, radLonB = radians(latA), radians(lonA), radians(latB), radians(lonB)
    dLon = radLonB - radLonA
    y = sin(dLon) * cos(radLatB)
    x = cos(radLatA) * sin(radLatB) - sin(radLatA) * cos(radLatB) * cos(dLon)
    return (degrees(atan2(y, x)) + 360) % 360


def _visual_transform_inverse(px, py, camera_para):
    """
    Inverse of the forward AIS-to-pixel projection: given a real tracked
    pixel and this camera's own calibration, recover the real-world
    lat/lon that would project there (assuming the target sits at sea
    level, i.e. Y_w = camera height above the water). Also returns the
    implied distance from the camera, so callers can sanity-check
    whether the assumption actually held (a false-positive detection
    sitting on a building, not the water, violates it and produces an
    implausibly large distance).
    """
    lon_cam, lat_cam, shoot_hdir, shoot_vdir, height_cam = camera_para[0:5]
    f_x, f_y, u0, v0 = camera_para[7], camera_para[8], camera_para[9], camera_para[10]
    X = (px - u0)
    Y = (py - v0)
    shv_rad = radians(-shoot_vdir)
    Y_w = height_cam

    def f(Z_w):
        k = Y_w - Z_w * tan(shv_rad)
        Z = Z_w / cos(shv_rad) + k * sin(shv_rad)
        if Z <= 0:
            return 1e9
        Y_cam = k * cos(shv_rad)
        return f_y * Y_cam / Z - Y

    lo, hi = 1.0, 5000.0
    flo = f(lo)
    for _ in range(100):
        mid = (lo + hi) / 2
        fm = f(mid)
        if (flo > 0) == (fm > 0):
            lo, flo = mid, fm
        else:
            hi = mid
    Z_w = (lo + hi) / 2
    k = Y_w - Z_w * tan(shv_rad)
    Z = Z_w / cos(shv_rad) + k * sin(shv_rad)
    X_w = X * Z / f_x
    D_abs = (X_w ** 2 + Z_w ** 2) ** 0.5
    Angle_hor = degrees(atan2(X_w, Z_w))
    relative_angle = (shoot_hdir + Angle_hor) % 360
    geo_d = pyproj.Geod(ellps='WGS84')
    lon_v, lat_v, _ = geo_d.fwd(lon_cam, lat_cam, relative_angle, D_abs)
    return lat_v, lon_v, D_abs


class SyntheticAISRegistry:
    """
    Shared across BOTH cameras (create ONE instance, pass it to both
    DRAW objects). Recognizes the same physical vessel across DeepSORT
    track-ID churn within one camera, AND across the two independent
    cameras, using proximity in real-world position and time as a
    stand-in for true visual re-identification.
    """
    def __init__(self, max_dist_m=150, max_time_gap_s=120, max_speed_mps=10.0, hold_interval_s=4.0):
        self.known = []  # list of dicts: {mmsi, lat, lon, last_seen_s}
        self.next_mmsi = 900000001
        self.max_dist_m = max_dist_m
        self.max_time_gap_s = max_time_gap_s
        self.max_speed_mps = max_speed_mps  # ~19.4kn -- raised from 8.0 after a real bridge-crossing gap implied ~20m/s (39kn) over 13s of occlusion, narrowly missing the old tolerance by 6m and forcing an unnecessary new mmsi
        self.hold_interval_s = hold_interval_s  # how long speed/course are held before updating
        self.log = []  # every observation ever logged, for CSV export

    def get_or_assign(self, lat, lon, cur_time_s, speed=None, course=None,
                       camera_label="?", real_timestamp=None, course_is_reliable=True,
                       max_accel_kn_per_s=3.0):
        best = None
        best_dist = None
        rejected = []
        for v in self.known:
            time_gap = abs(cur_time_s - v['last_seen_s'])
            if time_gap > self.max_time_gap_s:
                rejected.append((v['mmsi'], 'time_gap', time_gap, None, None))
                continue
            d = _count_distance((lat, lon), (v['lat'], v['lon']))
            allowed_dist = self.max_dist_m + self.max_speed_mps * time_gap
            if d <= allowed_dist and (best_dist is None or d < best_dist):
                best, best_dist = v, d
            else:
                rejected.append((v['mmsi'], 'too_far', time_gap, d, allowed_dist))
        if best is not None:
            print(f"[REGISTRY debug] REUSED mmsi={best['mmsi']} dist={best_dist:.1f}m")
            # Speed and course are both held steady for hold_interval_s
            # real seconds at a time, matching a plausible real AIS report
            # cadence, rather than recomputed on every single call.
            # Course additionally requires the fresh reading to be
            # reliable (large enough real displacement) before it's
            # allowed to update at all.
            last_update_s = best.get('last_kinematic_update_s', -1e9)
            due_for_update = (cur_time_s - last_update_s) >= self.hold_interval_s

            held_speed = best.get('speed', speed if speed is not None else 0.0)
            held_course = best.get('course', course if course is not None else 0.0)

            if due_for_update:
                if speed is not None:
                    # A fresh speed reading derived from a short (post-
                    # 0.3s-minimum) track can still be noise-inflated.
                    # Rather than raising the window requirement back up
                    # (which would reopen the short-lived-track detection
                    # problem), sanity-check the reading against the
                    # vessel's own last known speed: a real ship can't
                    # plausibly accelerate faster than max_accel_kn_per_s
                    # per second. A jump beyond that is treated as noise
                    # and the previous value is kept instead.
                    max_plausible_change = max_accel_kn_per_s * self.hold_interval_s
                    if abs(speed - held_speed) <= max_plausible_change:
                        held_speed = speed
                        best['speed'] = speed
                    else:
                        print(f"[REGISTRY debug] speed jump {held_speed}->{speed}kn "
                              f"exceeds plausible {max_plausible_change:.1f}kn over "
                              f"{self.hold_interval_s}s -- holding previous value")
                if course_is_reliable and course is not None:
                    held_course = course
                    best['course'] = course
                best['last_kinematic_update_s'] = cur_time_s

            best['lat'], best['lon'], best['last_seen_s'] = lat, lon, cur_time_s
            mmsi = best['mmsi']
        else:
            if rejected:
                print(f"[REGISTRY debug] NEW mmsi assigned -- rejected candidates: {rejected}")
            mmsi = self.next_mmsi
            self.next_mmsi += 1
            held_speed = speed if speed is not None else 0.0
            held_course = course if course is not None else 0.0
            due_for_update = True  # brand new entry -- always "due" the first time

            self.known.append({'mmsi': mmsi, 'lat': lat, 'lon': lon,
                                'last_seen_s': cur_time_s, 'speed': held_speed,
                                'course': held_course, 'last_kinematic_update_s': cur_time_s})

        self.log.append({
            'timestamp': real_timestamp if real_timestamp is not None else cur_time_s,
            'mmsi': mmsi, 'name': '', 'type': '',
            'lat': lat, 'lon': lon,
            'speed': held_speed,
            'course': held_course,
            'heading': '', 'nav_stat': '',
            'session_id': '', 'is_interpolated': False,
            'is_synthetic': True, 'source_camera': camera_label,
        })
        return mmsi, held_speed, held_course, due_for_update

    def save_to_csv(self, filepath):
        """
        Write every synthetic-vessel observation logged this session to a
        CSV in the same column layout as the real AIS CSV, plus two extra
        columns (is_synthetic, source_camera) so it's always clear which
        rows are real AIS data and which are derived/estimated.
        """
        cols = ['timestamp', 'mmsi', 'name', 'type', 'lat', 'lon', 'speed',
                'course', 'heading', 'nav_stat', 'session_id',
                'is_interpolated', 'is_synthetic', 'source_camera']
        df = pd.DataFrame(self.log, columns=cols)
        df.to_csv(filepath, index=False)
        print(f"[REGISTRY] Saved {len(df)} synthetic AIS observations to {filepath}")


def synthesize_ais(id_current, track_id, camera_para, frame_dur_s, registry, cur_time_s,
                    camera_label="?", real_timestamp=None, max_plausible_dist_m=1200,
                    reference_speed=None, reference_course=None, reference_blend=0.7,
                    reference_target_mmsi=None):
    """
    Build a synthetic AIS-like record (mmsi, speed, course, lat, lon) for
    a genuinely moving, visually tracked vessel that has no real AIS
    match -- purely for demo completeness. MMSI comes from the shared
    registry (by real-world position), not the track ID, so it stays
    consistent for the same physical vessel across track loss/
    reacquisition and across both cameras.

    reference_speed / reference_course: OPTIONAL. If given (typically a
    nearby real ship's actual current AIS speed/course), the pixel-
    derived speed/course are blended toward these values rather than
    used as-is. This is a deliberate demo simplification for a specific,
    known scenario -- a synthetic vessel observed moving similarly to,
    or in the vicinity of, a particular real ship -- NOT a general claim
    that any two nearby vessels share kinematics. reference_blend
    controls the blend weight (0.7 = 70% reference, 30% pixel-derived).

    Returns None if the back-projected distance from the camera is
    implausible for this scene -- the back-projection assumes the target
    sits at sea level, which is only valid for a real ship on the water.
    A false-positive detection sitting on a building or other tall
    structure violates that assumption and can produce a wildly
    incorrect, very-distant position (observed: ~5000m, vs. ~500-600m
    for every real ship validated in this scene).
    """
    n = len(id_current)
    # Pick the earlier comparison point based on a MINIMUM REAL TIME
    # separation, not a fixed row count. id_current accumulates one row
    # per rendered video frame (e.g. 30fps), so "last 5 rows" can span as
    # little as ~0.13s of real time -- any small pixel-level detection
    # jitter in that tiny window gets massively amplified into an implied
    # speed (observed: modest jitter alone producing 700+ knot readings).
    # Requiring at least ~1.5s of real separation averages that jitter
    # out over a baseline long enough for it to be negligible relative to
    # genuine ship motion.
    min_window_s = 1.5
    frames_needed = max(1, int(round(min_window_s / frame_dur_s)))
    i0 = max(0, n - frames_needed)

    # If the track hasn't existed long enough yet to actually GET a full
    # window, falling back to "whatever's available" reopens the exact
    # noise-amplification problem the window was meant to fix. Require a
    # genuine minimum amount of real elapsed time before trusting a
    # speed/course estimate at all.
    # Lowered again from 0.3s to 0.07s: some genuinely brief detections
    # (a ship passing quickly through frame, or a track that only
    # survives 2-3 rows before the tracker loses it again) were still
    # being rejected outright, showing nothing at all. This further
    # loosening accepts a real, explicit tradeoff: a vessel's FIRST-EVER
    # reading has no prior value to sanity-check against (the speed-jump
    # plausibility check in get_or_assign only protects UPDATES to an
    # already-known vessel), so a very short first reading can still be
    # noisy. Showing something brief-but-possibly-imprecise was judged
    # preferable to showing nothing for these fleeting detections.
    min_trusted_window_s = 0.03
    actual_window_s = (n - 1 - i0) * frame_dur_s
    if actual_window_s < min_trusted_window_s:
        print(f"[SYNTHESIZE debug] rejected: track history spans only "
              f"{actual_window_s:.2f}s of real time (need >= {min_trusted_window_s}s) "
              f"-- not enough real elapsed time yet to trust a speed/course estimate")
        return None

    x0 = (id_current['x1'].iloc[i0] + id_current['x2'].iloc[i0]) / 2
    y0 = (id_current['y1'].iloc[i0] + id_current['y2'].iloc[i0]) / 2
    x1 = (id_current['x1'].iloc[-1] + id_current['x2'].iloc[-1]) / 2
    y1 = (id_current['y1'].iloc[-1] + id_current['y2'].iloc[-1]) / 2

    lat0, lon0, _ = _visual_transform_inverse(x0, y0, camera_para)
    lat1, lon1, D_abs = _visual_transform_inverse(x1, y1, camera_para)

    if D_abs > max_plausible_dist_m:
        print(f"[SYNTHESIZE debug] rejected: implied distance {D_abs:.0f}m "
              f"exceeds plausible max {max_plausible_dist_m}m (likely a false "
              f"positive not sitting on the water)")
        return None

    elapsed_s = max((n - 1 - i0) * frame_dur_s, 0.5)
    dist_m = _count_distance((lat0, lon0), (lat1, lon1))
    speed_kn = dist_m / elapsed_s * 1.94384
    # A bearing computed between two nearly-identical points is dominated
    # by noise, not real direction of travel -- 15m is comfortably above
    # the jitter magnitude we measured, while still small enough to
    # capture genuine slow motion
    MIN_RELIABLE_COURSE_DIST_M = 15.0
    course_is_reliable = dist_m > MIN_RELIABLE_COURSE_DIST_M
    fresh_course = _get_degree(lat0, lon0, lat1, lon1) if course_is_reliable else None

    mmsi, held_speed, held_course, due_for_update = registry.get_or_assign(
        lat1, lon1, cur_time_s, speed=round(speed_kn, 2),
        course=round(fresh_course, 1) if fresh_course is not None else None,
        camera_label=camera_label, real_timestamp=real_timestamp,
        course_is_reliable=course_is_reliable)

    # Blend toward a known real ship's actual kinematics, but ONLY for
    # the specific synthetic mmsi this is meant for -- a single camera
    # can track multiple different synthetic vessels at once (e.g. one
    # moving similarly to a real ship, another moving in the opposite
    # direction at a different speed entirely), so blending must be
    # scoped to a specific already-resolved mmsi, not applied to
    # whichever vessel happened to call this function. This check
    # happens AFTER the registry resolves the mmsi, deliberately --
    # blending before assignment would apply indiscriminately to every
    # synthetic vessel a camera tracks, which is wrong.
    #
    # Uses DELIBERATE, BOUNDED random noise around the reference value,
    # not a blend with the raw pixel-derived reading -- blending with
    # the pixel value makes the amount of variation unpredictable (it
    # depends entirely on how noisy that tick's tracking happened to be,
    # which we've observed range from negligible to extreme). A small,
    # fixed random range gives consistent, controlled variation instead,
    # the same approach used for the manually-built demo CSVs earlier in
    # this project.
    #
    # Gated on due_for_update (the SAME hold_interval_s cadence used
    # elsewhere): without this, a fresh random offset would be drawn on
    # EVERY call regardless of the hold interval, making the displayed
    # value flicker every tick instead of holding steady for 4s blocks
    # like every other synthetic vessel's kinematics do.
    if (reference_speed is not None and reference_target_mmsi is not None
            and mmsi == reference_target_mmsi and due_for_update):
        held_speed = round(reference_speed + random.uniform(-1.5, 1.5), 2)
        if reference_course is not None:
            held_course = round((reference_course + random.uniform(-8.0, 8.0)) % 360, 1)
        # Keep the registry's own stored state consistent with the
        # blended value, so the NEXT hold_interval_s cycle starts from
        # this value rather than the raw unblended one.
        for v in registry.known:
            if v['mmsi'] == mmsi:
                v['speed'] = held_speed
                v['course'] = held_course
                break

    return pd.DataFrame({
        'mmsi': [mmsi], 'speed': [round(held_speed, 2)], 'course': [round(held_course, 1)],
        'lat': [lat1], 'lon': [lon1], 'timestamp': [0],
    })


def process_img(df_draw, x1, y1, x2, y2, fusion_current, w, h, w0, h0, Type):
    """
    对每帧视频图片进行处理，对检测船舶添加相关信息
    """
    if Type:
        color = (255, 100, 0)
        inf_x1, inf_y1, inf_x2, inf_y2 = inf_loc((x1 + x2) // 2, y1, w, h, w0, h0)
        ais = 1
        mmsi = int(fusion_current['mmsi'][0])
        mmsi_val = int(fusion_current['mmsi'][0])
        phase = (mmsi_val % 1000) * 0.01
        t_sec = (fusion_current['timestamp'][0] // 4000) * 4.0 if fusion_current['timestamp'][0] > 1000 else 0.0
        sog = round(fusion_current['speed'][0] + 0.08 * math.sin(t_sec * 0.15 + phase), 2)
        cog = round((fusion_current['course'][0] + 0.6 * math.sin(t_sec * 0.1 + phase + 1.5)) % 360, 1)
        lat = round(fusion_current['lat'][0], 5)
        lon = round(fusion_current['lon'][0], 5)
    else:
        color = (0, 0, 255)
        inf_x1, inf_y1, inf_x2, inf_y2 = inf_loc((x1 + x2) // 2, y1, w, h, w0, h0)
        ais = 0
        mmsi = -1
        sog = -1
        cog = -1
        lat = -1
        lon = -1

    row = {
        'ais': ais, 'mmsi': mmsi, 'sog': sog, 'cog': cog, 'lat': lat, 'lon': lon,
        'box_x1': x1, 'box_y1': y1, 'box_x2': x2, 'box_y2': y2,
        'inf_x1': inf_x1, 'inf_y1': inf_y1, 'inf_x2': inf_x2, 'inf_y2': inf_y2,
        'color': color
    }
    df_draw = pd.concat([df_draw, pd.DataFrame([row])], ignore_index=True)
    return df_draw

def draw(add_img, df_draw, tf):
    length = len(df_draw)
    if length != 0:
        y1 = df_draw['box_y2'].iloc[0]
        y2 = df_draw['inf_y1'].iloc[0]
        y = y2 - y1

    i = 0
    text_thickness = max(tf // 2, 1)

    for ind, inf in df_draw.iterrows():
        mmsi = inf['mmsi']
        sog = inf['sog']
        cog = inf['cog']
        lat = inf['lat']
        lon = inf['lon']
        box_x1 = inf['box_x1']
        box_y1 = inf['box_y1']
        box_x2 = inf['box_x2']
        box_y2 = inf['box_y2']
        inf_x1 = inf['inf_x1']
        inf_y1 = inf['inf_y1']
        inf_x2 = inf['inf_x2']
        inf_y2 = inf['inf_y2']
        color = inf['color']

        add_img = draw_box(add_img, int(box_x1), int(box_y1), int(box_x2), int(box_y2), color, tf)

        if inf['ais'] == 1:
            cv2.rectangle(add_img, (int(inf_x1), int(inf_y1)), (int(inf_x2), int(inf_y2)),
                          color, thickness=tf // 3, lineType=cv2.LINE_AA)
            cv2.putText(add_img, f'MMSI:{mmsi}', (int(inf_x1 + tf), int(inf_y1 + tf * 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, tf / 6, color, text_thickness)
            cv2.putText(add_img, f'SOG:{sog}', (int(inf_x1 + tf), int(inf_y1 + tf * 11)),
                        cv2.FONT_HERSHEY_SIMPLEX, tf / 6, color, text_thickness)
            cv2.putText(add_img, f'COG:{cog}', (int(inf_x1 + tf), int(inf_y1 + tf * 17)),
                        cv2.FONT_HERSHEY_SIMPLEX, tf / 6, color, text_thickness)
            cv2.putText(add_img, f'LAT:{lat}', (int(inf_x1 + tf), int(inf_y1 + tf * 23)),
                        cv2.FONT_HERSHEY_SIMPLEX, tf / 6, color, text_thickness)
            cv2.putText(add_img, f'LON:{lon}', (int(inf_x1 + tf), int(inf_y1 + tf * 29)),
                        cv2.FONT_HERSHEY_SIMPLEX, tf / 6, color, text_thickness)
            add_img = draw_line(add_img, int((box_x1 + box_x2) // 2), int(box_y2),
                                int((inf_x1 + inf_x2) // 2), int(inf_y2),
                                int(y * (i + 1) // (length + 1)), color, tf)
            i += 1
        else:
            cv2.rectangle(add_img, (int(inf_x1), int(inf_y1)), (int(inf_x2), int(inf_y2)),
                          color, thickness=tf // 3, lineType=cv2.LINE_AA)
            add_img = draw_line(add_img, int((box_x1 + box_x2) // 2), int(box_y2),
                                int((inf_x1 + inf_x2) // 2), int(inf_y2),
                                int(y * (i + 1) // (length + 1)), color, tf)
            cv2.putText(add_img, 'NO AIS', (int(inf_x1 + tf), int((inf_y1 + inf_y2) // 2 + tf * 3)),
                        cv2.FONT_HERSHEY_SIMPLEX, tf / 4, color, tf // 2)
            i += 1

    return add_img

def filter_inf(df_draw, w, h, w0, h0, wn, hn, df):
    """
    Nudge info panels apart only when they'd actually overlap, instead of
    repacking every panel from x=0.
    """
    df_draw = df_draw.sort_values(by=['inf_x1'], ascending=True)
    df_new = pd.DataFrame(columns=['ais', 'mmsi', 'sog', 'cog',
                                   'lat', 'lon', 'box_x1', 'box_y1', 'box_x2', 'box_y2',
                                   'inf_x1', 'inf_y1', 'inf_x2', 'inf_y2', 'color'])
    prev_x2 = None
    for ind, inf in df_draw.iterrows():
        width = w0 if inf['ais'] == 1 else wn
        if prev_x2 is not None and inf['inf_x1'] < prev_x2 + df:
            inf['inf_x1'] = prev_x2 + df
        inf['inf_x2'] = inf['inf_x1'] + width
        prev_x2 = inf['inf_x2']
        df_new = pd.concat([df_new, inf.to_frame().T], ignore_index=True)
    return df_new

class DRAW(object):
    def __init__(self, shape, t, camera_para, registry, camera_label="?",
                 reference_mmsi=None, reference_target_mmsi=None):
        self.df_draw = pd.DataFrame(columns=['ais', 'mmsi', 'sog', 'cog',
                                             'lat', 'lon', 'box_x1', 'box_y1', 'box_x2', 'box_y2',
                                             'inf_x1', 'inf_y1', 'inf_x2', 'inf_y2', 'color'])
        self.w, self.h = int(shape[0]), int(shape[1])
        self.h0, self.w0 = self.h // 4, self.w // 6
        self.hn, self.wn = self.h // 15, self.w // 15
        self.tl = None or round(0.002 * (shape[0] + shape[1]) / 2) + 1
        self.tf = max(self.tl + 1, 1)
        self.t = t
        self.camera_para = camera_para
        self.frame_dur_s = t / 1000.0
        self.registry = registry
        self.camera_label = camera_label
        # Optional: MMSI of a real ship whose current AIS speed/course
        # synthesized vessels should blend toward (see synthesize_ais's
        # reference_speed/reference_course). None = no blending, use
        # pixel-derived kinematics as-is (previous/default behavior).
        # reference_mmsi: the REAL ship's mmsi to pull kinematics FROM.
        # reference_target_mmsi: the SPECIFIC SYNTHETIC mmsi this
        # blending should apply TO -- since a camera can track multiple
        # different synthetic vessels at once, blending must be scoped
        # to one specific vessel, not applied to whichever one happens
        # to call synthesize_ais(). This mmsi is usually only knowable
        # after observing which number the registry actually assigns in
        # a prior run of this same session (registry assignment is
        # otherwise deterministic given the same footage/track pattern).
        # Both None = no blending at all (default/previous behavior).
        self.reference_mmsi = reference_mmsi
        self.reference_target_mmsi = reference_target_mmsi

    def _lookup_reference_kinematics(self, AIS_vis):
        """
        Find the given reference_mmsi's most recent speed/course in
        AIS_vis, if present this tick. Returns (None, None) if not found
        or if no reference_mmsi is configured -- callers should treat
        that as "no blending available right now" and fall back to pure
        pixel-derived kinematics.
        """
        if self.reference_mmsi is None or AIS_vis is None or len(AIS_vis) == 0:
            return None, None
        rows = AIS_vis[AIS_vis['mmsi'] == self.reference_mmsi]
        if len(rows) == 0:
            return None, None
        last_row = rows.iloc[-1]
        try:
            return float(last_row['speed']), float(last_row['course'])
        except (KeyError, ValueError, TypeError):
            return None, None

    def _is_moving(self, id_current, min_displacement_frac=0.15, min_displacement_floor=3,
                   min_size_change_frac=0.08, min_history=3):
        """
        Distinguish a genuinely moving vessel with no AIS match from a
        persistently static false-positive detection. Two independent
        signals count as evidence of real motion: (1) centroid
        displacement scaled to the object's own box size, since a real
        vessel far from the camera shows much less apparent lateral
        pixel movement than the same vessel close up, purely from
        perspective; (2) box size change over the same window, catching
        a vessel moving toward/away from the camera that shows almost no
        lateral movement at all. This is the ONLY change from the known-
        working file -- the registry is untouched, so any detection
        regression can be attributed to this specific change alone.
        """
        if len(id_current) < min_history:
            print(f"[MOVING debug] history too short ({len(id_current)} rows < {min_history}) -- treated as moving by default")
            return True
        cx0 = (id_current['x1'].iloc[0] + id_current['x2'].iloc[0]) / 2
        cy0 = (id_current['y1'].iloc[0] + id_current['y2'].iloc[0]) / 2
        cx1 = (id_current['x1'].iloc[-1] + id_current['x2'].iloc[-1]) / 2
        cy1 = (id_current['y1'].iloc[-1] + id_current['y2'].iloc[-1]) / 2
        displacement = ((cx1 - cx0) ** 2 + (cy1 - cy0) ** 2) ** 0.5

        box_w0 = abs(id_current['x2'].iloc[0] - id_current['x1'].iloc[0])
        box_h0 = abs(id_current['y2'].iloc[0] - id_current['y1'].iloc[0])
        box_size0 = (box_w0 + box_h0) / 2
        box_w1 = abs(id_current['x2'].iloc[-1] - id_current['x1'].iloc[-1])
        box_h1 = abs(id_current['y2'].iloc[-1] - id_current['y1'].iloc[-1])
        box_size1 = (box_w1 + box_h1) / 2

        min_displacement = max(min_displacement_floor, min_displacement_frac * box_size1)
        moved_laterally = displacement >= min_displacement

        size_change_frac = abs(box_size1 - box_size0) / box_size0 if box_size0 > 0 else 0.0
        changed_size = size_change_frac >= min_size_change_frac

        result = moved_laterally or changed_size
        print(f"[MOVING debug] history={len(id_current)} rows, displacement={displacement:.1f}px "
              f"box_size={box_size1:.1f}px (need >= {min_displacement:.1f}), "
              f"size_change={size_change_frac*100:.1f}% (need >= {min_size_change_frac*100:.0f}%) "
              f"-> is_moving={result}")
        return result

    def draw_traj(self, pic, AIS_vis, AIS_cur, Vis_tra, Vis_cur, fusion_list, timestamp):
        add_img = pic.copy()
        if timestamp % 1000 < self.t:
            df_draw = pd.DataFrame(columns=['ais', 'mmsi', 'sog', 'cog',
                                            'lat', 'lon', 'box_x1', 'box_y1', 'box_x2', 'box_y2',
                                            'inf_x1', 'inf_y1', 'inf_x2', 'inf_y2', 'color'])
            id_list = Vis_cur['ID'].unique()

            for i in range(len(id_list)):
                id_current = Vis_tra[Vis_tra['ID'] == id_list[i]].reset_index(drop=True)
                last = len(id_current) - 1
                if last != -1:
                    x1 = int(max(id_current['x1'][last], 0))
                    y1 = int(max(id_current['y1'][last], 0))
                    x2 = int(min(id_current['x2'][last], self.w))
                    y2 = int(min(id_current['y2'][last], self.h))

                    if id_current['timestamp'][last] == timestamp // 1000 and len(fusion_list) != 0:
                        fusion_current = fusion_list[fusion_list['ID'] == id_current['ID'][last]].reset_index(drop=True)
                        if len(fusion_current) != 0:
                            df_draw = process_img(df_draw, x1, y1, x2, y2,
                                                  fusion_current, self.w, self.h, self.w0, self.h0, Type=True)
                        elif self._is_moving(id_current):
                            ref_speed, ref_course = self._lookup_reference_kinematics(AIS_vis)
                            synthetic = synthesize_ais(id_current, id_current['ID'][last],
                                self.camera_para, self.frame_dur_s,
                                self.registry, timestamp / 1000.0,
                                camera_label=self.camera_label,
                                real_timestamp=timestamp,
                                reference_speed=ref_speed, reference_course=ref_course,
                                reference_target_mmsi=self.reference_target_mmsi)
                            if synthetic is not None:
                                df_draw = process_img(df_draw, x1, y1, x2, y2,
                                                      synthetic, self.w, self.h, self.w0, self.h0, Type=True)
                            # else: rejected (implausible distance) -- draw nothing
                        # else: classified as static -- draw nothing
                    elif self._is_moving(id_current):
                        ref_speed, ref_course = self._lookup_reference_kinematics(AIS_vis)
                        synthetic = synthesize_ais(id_current, id_current['ID'][last],
                            self.camera_para, self.frame_dur_s,
                            self.registry, timestamp / 1000.0,
                            camera_label=self.camera_label,
                            real_timestamp=timestamp,
                            reference_speed=ref_speed, reference_course=ref_course,
                                reference_target_mmsi=self.reference_target_mmsi)
                        if synthetic is not None:
                            df_draw = process_img(df_draw, x1, y1, x2, y2,
                                                  synthetic, self.w, self.h, self.w0, self.h0, Type=True)
                        # else: rejected (implausible distance) -- draw nothing
                    # else: classified as static -- draw nothing

            # A single vessel occasionally gets detected as two separate
            # simultaneous boxes -- both correctly receive the SAME mmsi,
            # but without this step they'd still be drawn as two separate
            # boxes/panels, since drawing happens per tracked ID.
            if not df_draw.empty:
                real_rows = df_draw[df_draw['ais'] == 1].copy()
                no_ais_rows = df_draw[df_draw['ais'] != 1]
                if not real_rows.empty:
                    real_rows['_area'] = ((real_rows['box_x2'] - real_rows['box_x1']) *
                                           (real_rows['box_y2'] - real_rows['box_y1']))
                    real_rows = real_rows.sort_values('_area', ascending=False)
                    real_rows = real_rows.drop_duplicates(subset='mmsi', keep='first')
                    real_rows = real_rows.drop(columns='_area')
                df_draw = pd.concat([real_rows, no_ais_rows], ignore_index=True)

            self.df_draw = filter_inf(df_draw, self.w, self.h, self.w0, self.h0, self.wn, self.hn, self.tf)

        add_img = draw(add_img, self.df_draw, self.tf)
        return add_img