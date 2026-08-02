import time
from fastdtw import fastdtw
import pandas as pd
from scipy.spatial.distance import euclidean
import os
import math
import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import linear_sum_assignment as linear_assignment
from IPython import embed

def __reduce_by_half(x):
    # 轨迹压缩
    return [(x[i] + x[1+i]) / 2 for i in range(0, len(x) - len(x) % 2, 2)]

def angle(v1, v2):
    # 计算轨迹速度的夹角
    if len(v1) >= 10:
        dx1 = v1[-1][0] - v1[-10][0]
        dy1 = v1[-1][1] - v1[-10][1]
    else:
        dx1 = v1[-1][0] - v1[0][0]
        dy1 = v1[-1][1] - v1[0][1]

    if len(v2) >= 5:
        dx2 = v2[-1][0] - v2[0][0]
        dy2 = v2[-1][1] - v2[0][1]
    else:
        dx2 = v2[-1][0] - v2[0][0]
        dy2 = v2[-1][1] - v2[0][1]

    angle1 = math.atan2(dy1, dx1)
    angle2 = math.atan2(dy2, dx2)

    if angle1 * angle2 >= 0:
        included_angle = abs(angle1 - angle2)
    else:
        included_angle = abs(angle1) + abs(angle2)
        if included_angle > math.pi:
            included_angle = math.pi * 2 - included_angle
    return included_angle

def DTW_fast(traj0, traj1):
    # 1.计算轨迹间夹角
    if len(traj0) > 1 and len(traj1) > 1:
        theta = angle(traj0, traj1)
        traj0 = __reduce_by_half(traj0)
        traj1 = __reduce_by_half(traj1)
    else:
        theta = 0

    # 2.使用fastDTW
    d, path = fastdtw(traj0, traj1, dist=euclidean)

    return d * math.exp(theta)

def traj_group(df_data, df_dataCur, kind):
    """
    对数据轨迹按照MMSI呼号或者ID号进行分组，并获取每条船舶或者每个检测框的轨迹
    """
    trajData_list = []
    trajLabel_list = []
    trajInf_list = []

    if kind == 'AIS':
        grouped = df_data.groupby('mmsi')
        for value, group in grouped:
            if value in df_dataCur['mmsi'].tolist():
                traj = group.values
                trajData_list.append(np.array(traj[:, 7:9]))
                trajLabel_list.append(int(traj[0, 0]))
                trajInf_list.append(traj)

    elif kind == 'VIS':
        grouped = df_data.groupby('ID')
        for value, group in grouped:
            if value in df_dataCur['ID'].tolist():
                traj = group.values
                trajData_list.append(np.array(traj[:, 5:7]))
                trajLabel_list.append(int(traj[0][0]))
                trajInf_list.append(traj)

    return trajData_list, trajLabel_list, trajInf_list


def is_moving_from_traj(vis_inf_rows, min_displacement_frac=0.15, min_displacement_floor=3,
                          min_size_change_frac=0.08, min_size_change_floor=15, min_history=3):
    """
    Distinguish a genuinely moving visual track from a persistently static
    false-positive (e.g. a building's glare/rooftop feature that YOLO fires
    on every tick, at high confidence, in nearly the exact same spot).

    Same logic/thresholds as DRAW._is_moving() in draw.py, reimplemented
    here so FUSPRO can exclude static tracks from AIS candidate matching
    ENTIRELY (before any dis/theta gate is even checked) -- confidence-based
    filtering alone cannot solve this, since a confident, consistent false
    detection can score just as high as a real ship, at any threshold.

    vis_inf_rows: the full historical rows for one VIS track ID, as stored
    in VInf_list (columns: ID, x1, y1, x2, y2, x, y, timestamp, speed).
    """
    if len(vis_inf_rows) < min_history:
        # Not enough history yet to judge -- treat as moving by default,
        # same as draw.py, so a brand-new real ship isn't excluded before
        # it's had a chance to show movement.
        return True

    first_row = vis_inf_rows[0]
    last_row = vis_inf_rows[-1]

    x1_0, y1_0, x2_0, y2_0 = first_row[1], first_row[2], first_row[3], first_row[4]
    x1_1, y1_1, x2_1, y2_1 = last_row[1], last_row[2], last_row[3], last_row[4]

    cx0, cy0 = (x1_0 + x2_0) / 2, (y1_0 + y2_0) / 2
    cx1, cy1 = (x1_1 + x2_1) / 2, (y1_1 + y2_1) / 2
    displacement = ((cx1 - cx0) ** 2 + (cy1 - cy0) ** 2) ** 0.5

    box_size0 = (abs(x2_0 - x1_0) + abs(y2_0 - y1_0)) / 2
    box_size1 = (abs(x2_1 - x1_1) + abs(y2_1 - y1_1)) / 2

    min_displacement = max(min_displacement_floor, min_displacement_frac * box_size1)
    moved_laterally = displacement >= min_displacement

    size_change_frac = abs(box_size1 - box_size0) / box_size0 if box_size0 > 0 else 0.0
    size_change_abs = abs(box_size1 - box_size0)
    # BOTH a minimum percentage AND a minimum absolute pixel change are now
    # required (not percentage alone). Confirmed real-world case: a static
    # object with box_size=90px showed size_change_frac=9.8% (just over the
    # old 8% threshold) from only ~8.8px of actual difference -- well
    # within normal YOLO detection jitter for a small/distant box, not
    # genuine size change from real approach/recession. The absolute floor
    # (15px) filters this out while still catching real, larger changes.
    changed_size = size_change_frac >= min_size_change_frac and size_change_abs >= min_size_change_floor

    return moved_laterally or changed_size


class FUSPRO(object):
    def __init__(self, max_dis, im_shape, t, debug_label="?"):
        self.max_dis = max_dis
        self.im_shape = im_shape
        self.bin_num = 3
        self.fog_num = 3
        self.t = t
        self._debug_label = debug_label
        self.Y_AXIS_WEIGHT = 1.0

        self.mat_cur  = pd.DataFrame(columns=['ID/mmsi', 'timestamp', 'match'])
        self.mat_list = pd.DataFrame(columns=['ID', 'mmsi', 'lon', 'lat', 'speed', 'course', 'heading', 'type', 'timestamp'])
        self.bin_cur  = pd.DataFrame(columns=['ID', 'mmsi', 'timestamp', 'match'])

        # SWITCH RESISTANCE (NEW): an already-confirmed match (VIS_ID ->
        # mmsi) should not be replaced by a DIFFERENT mmsi just because
        # that different mmsi happens to win the assignment for a single
        # tick -- a real occlusion scenario can produce exactly this kind
        # of brief, single-tick anomaly (e.g. one ship's real box
        # becoming the algorithmically "closer fit" to a different real
        # ship's ghost point for one tick while that ship is genuinely
        # hidden nearby, even though the first ship is correctly
        # confirmed to its OWN mmsi). Require the SAME candidate mmsi to
        # win SEVERAL CONSECUTIVE ticks before actually allowing the
        # switch, filtering out single-tick noise.
        # {VIS_ID: (candidate_mmsi, consecutive_tick_count)}
        self.pending_switch = {}

    def initialization(self, AIS_list, VIS_list):
        mat_las = self.mat_cur
        bin_las = mat_las[mat_las['match'] > self.bin_num]
        mat_cur = pd.DataFrame(columns=['ID/mmsi', 'timestamp', 'match'])
        bin_cur = pd.DataFrame(columns=['ID', 'mmsi', 'timestamp', 'match'])

        mat_list = pd.DataFrame(columns=['ID', 'mmsi', 'lon', 'lat', 'speed', 'course', 'heading', 'type',
                                         'x1', 'y1', 'w', 'h', 'timestamp'])
        return mat_cur, bin_cur, mat_las, bin_las, mat_list

    def cal_similarity(self, AIS_list, AIS_MMSIlist, VIS_list, VIS_IDlist, bin_las, moving_flags=None, edge_flags=None, timestamp=None):
        matrix_S = np.zeros((len(VIS_list), len(AIS_list)))
        _cam_label = getattr(self, "_debug_label", "?")

        binIDmmsi, bin_MMSI, bin_ID = [], [], []
        # Map each confirmed ID/mmsi pair back to its row/col index in this
        # tick's lists, so a confirmed pair can be RE-VALIDATED against the
        # same dis/theta gate every tick instead of just getting an
        # ever-more-negative cost forever regardless of whether it still
        # makes geometric sense. Without this, an early wrong lock (e.g.
        # from imperfect camera calibration) can never be corrected once
        # match > bin_num, even if a much better candidate shows up later.
        bin_pair_indices = {}
        if len(bin_las) != 0:
            grouped = bin_las.groupby('ID/mmsi')
            for value, group in grouped:
                ID, MMSI = value.split('/')
                bin_ID.append(int(ID))
                bin_MMSI.append(int(MMSI))
                binIDmmsi.append(value)

        for i in range(len(VIS_list)):
            for j in range(len(AIS_list)):
                cur_ID, cur_mmsi = VIS_IDlist[i], AIS_MMSIlist[j]
                cur_IDmmsi = str(int(cur_ID)) + '/' + str(int(cur_mmsi))

                # FIX: only the EXACT confirmed (ID, mmsi) pair gets special
                # treatment below. Previously, if EITHER this ID or this
                # mmsi appeared in ANY confirmed pair (even a different
                # one), the combination fell into a blanket-blocked branch
                # further down (forced cost 1e9) -- meaning once VIS_ID=3
                # was confirmed to mmsi=244660565 (MEGAN), it could NEVER
                # even be evaluated against mmsi=244750175 (AMICITIA),
                # regardless of fit. Confirmed real-world case: a marginal
                # lock (dis=299.2px, barely under the 300px gate) stayed
                # wrongly confirmed for 7+ ticks purely because the truly
                # correct alternative was never even considered. Now: any
                # combination that ISN'T the exact confirmed pair is
                # evaluated as a normal fresh candidate, so a clearly
                # better-fitting alternative can actually compete and win.
                if cur_IDmmsi in binIDmmsi:
                    s = bin_las.loc[bin_las['ID/mmsi'] == cur_IDmmsi, 'match']
                    m = int(s.iloc[-1]) if len(s) else 0

                    # STALENESS CHECK: DeepSORT recycles numeric track IDs
                    # once a track expires. If a NEW, genuinely different
                    # real ship later gets assigned that same recycled ID
                    # number, this "ID/mmsi" string match would otherwise
                    # treat it as continuing the OLD confirmed pair --
                    # inheriting stale confirmed status it never earned.
                    STALENESS_THRESHOLD_SECONDS = 5
                    ts_series = bin_las.loc[bin_las['ID/mmsi'] == cur_IDmmsi, 'timestamp']
                    last_confirmed_ts = float(ts_series.iloc[-1]) if len(ts_series) else None
                    current_ts_seconds = (timestamp // 1000) if timestamp is not None else None
                    is_stale = (last_confirmed_ts is not None and current_ts_seconds is not None
                                and (current_ts_seconds - last_confirmed_ts) > STALENESS_THRESHOLD_SECONDS)

                    if is_stale:
                        print(f"[FUS debug][{_cam_label}][STALE-confirmed-ignored] VIS_ID={cur_ID} AIS_mmsi={cur_mmsi} "
                              f"-- {current_ts_seconds - last_confirmed_ts:.0f}s since last confirmed "
                              f"(>{STALENESS_THRESHOLD_SECONDS}s) -- likely a recycled track ID for a "
                              f"different real ship, treating as a fresh candidate instead")
                        theta = angle(VIS_list[i], AIS_list[j])
                        x_VIS, y_VIS = VIS_list[i][-1][0], VIS_list[i][-1][1]
                        x_AIS, y_AIS = AIS_list[j][-1][0], AIS_list[j][-1][1]
                        dis = ((x_VIS - x_AIS) ** 2 + (self.Y_AXIS_WEIGHT * (y_VIS - y_AIS)) ** 2) ** 0.5
                        is_moving = moving_flags[i] if moving_flags is not None else True
                        is_edge = edge_flags[i] if edge_flags is not None else False
                        effective_max_dis = self.max_dis * 2.5 if is_edge else self.max_dis
                        if not is_moving:
                            matrix_S[i][j] = 1000000000
                        elif dis < effective_max_dis and (theta < math.pi * (1 / 3) or dis < 100):
                            SHORT_HISTORY_ROWS = 5
                            if len(VIS_list[i]) < SHORT_HISTORY_ROWS:
                                matrix_S[i][j] = dis
                            else:
                                DIS_WEIGHT = 1.5
                                matrix_S[i][j] = DTW_fast(VIS_list[i], AIS_list[j]) + DIS_WEIGHT * dis
                        else:
                            matrix_S[i][j] = 1000000000
                        continue

                    theta = angle(VIS_list[i], AIS_list[j])
                    x_VIS, y_VIS = VIS_list[i][-1][0], VIS_list[i][-1][1]
                    x_AIS, y_AIS = AIS_list[j][-1][0], AIS_list[j][-1][1]
                    dis = ((x_VIS - x_AIS) ** 2 + (self.Y_AXIS_WEIGHT * (y_VIS - y_AIS)) ** 2) ** 0.5
                    import math as _dbg_math
                    print(f"[FUS debug][{_cam_label}][CONFIRMED match={m}] VIS_ID={cur_ID} AIS_mmsi={cur_mmsi} "
                          f"dis={dis:.1f}px (max {self.max_dis}, strict-reconfirm {self.max_dis*2/3:.0f}) "
                          f"theta={_dbg_math.degrees(theta):.1f}deg (max {_dbg_math.degrees(_dbg_math.pi*1/3):.1f}) "
                          f"| REAL_pixel=({x_VIS:.0f},{y_VIS:.0f}) AIS_projected_pixel=({x_AIS:.0f},{y_AIS:.0f})")

                    is_edge = edge_flags[i] if edge_flags is not None else False
                    effective_max_dis = self.max_dis * 2.5 if is_edge else self.max_dis
                    STRICT_RECONFIRM_DIS = effective_max_dis * 2 / 3
                    is_moving = moving_flags[i] if moving_flags is not None else True
                    if not is_moving:
                        matrix_S[i][j] = 1000000000
                    elif dis < STRICT_RECONFIRM_DIS and (theta < math.pi * (1 / 3) or dis < 100):
                        STABILITY_BONUS = 30
                        matrix_S[i][j] = DTW_fast(VIS_list[i], AIS_list[j]) - STABILITY_BONUS
                    elif dis < effective_max_dis and (theta < math.pi * (1 / 3) or dis < 100):
                        SHORT_HISTORY_ROWS = 5
                        if len(VIS_list[i]) < SHORT_HISTORY_ROWS:
                            matrix_S[i][j] = dis
                        else:
                            DIS_WEIGHT = 1.5
                            matrix_S[i][j] = DTW_fast(VIS_list[i], AIS_list[j]) + DIS_WEIGHT * dis
                    else:
                        matrix_S[i][j] = 1000000000

                else:
                    theta = angle(VIS_list[i], AIS_list[j])
                    x_VIS, y_VIS = VIS_list[i][-1][0], VIS_list[i][-1][1]
                    x_AIS, y_AIS = AIS_list[j][-1][0], AIS_list[j][-1][1]
                    dis = ((x_VIS - x_AIS) ** 2 + (self.Y_AXIS_WEIGHT * (y_VIS - y_AIS)) ** 2) ** 0.5
                    import math as _dbg_math
                    print(f"[FUS debug][{_cam_label}][candidate] VIS_ID={cur_ID} AIS_mmsi={cur_mmsi} "
                          f"dis={dis:.1f}px (max {self.max_dis}) "
                          f"theta={_dbg_math.degrees(theta):.1f}deg (max {_dbg_math.degrees(_dbg_math.pi*1/3):.1f}) "
                          f"| REAL_pixel=({x_VIS:.0f},{y_VIS:.0f}) AIS_projected_pixel=({x_AIS:.0f},{y_AIS:.0f})")

                    is_moving = moving_flags[i] if moving_flags is not None else True
                    is_edge = edge_flags[i] if edge_flags is not None else False
                    effective_max_dis = self.max_dis * 2.5 if is_edge else self.max_dis
                    if not is_moving:
                        matrix_S[i][j] = 1000000000
                    elif dis < effective_max_dis and (theta < math.pi * (1 / 3) or dis < 100):
                        SHORT_HISTORY_ROWS = 5
                        if len(VIS_list[i]) < SHORT_HISTORY_ROWS:
                            matrix_S[i][j] = dis
                        else:
                            DIS_WEIGHT = 1.5
                            matrix_S[i][j] = DTW_fast(VIS_list[i], AIS_list[j]) + DIS_WEIGHT * dis
                    else:
                        matrix_S[i][j] = 1000000000

        return matrix_S

    def data_filter(self, row_ind, col_ind, VIS_list, AIS_list, moving_flags=None, edge_flags=None):
        matches = []
        for row, col in zip(row_ind, col_ind):
            theta = angle(VIS_list[row], AIS_list[col])

            x_VIS, y_VIS = VIS_list[row][-1][0], VIS_list[row][-1][1]
            x_AIS, y_AIS = AIS_list[col][-1][0], AIS_list[col][-1][1]
            dis = ((x_VIS - x_AIS) ** 2 + (self.Y_AXIS_WEIGHT * (y_VIS - y_AIS)) ** 2) ** 0.5

            is_moving = moving_flags[row] if moving_flags is not None else True
            is_edge = edge_flags[row] if edge_flags is not None else False
            effective_max_dis = self.max_dis * 2.5 if is_edge else self.max_dis
            if is_moving and dis < effective_max_dis and (theta < math.pi * (1 / 3) or dis < 100):
                matches.append((row, col))
        return matches

    def save_data(self, mat_cur, bin_cur, mat_las, bin_las, mat_list,
                  matches, AIS_MMSIlist, VIS_IDlist, AInf_list, VInf_list, timestamp):

        # 1) 存储当前时刻匹配信息
        for v_loc, a_loc in matches:
            ID = int(VIS_IDlist[v_loc])
            MMSI = int(AIS_MMSIlist[a_loc])
            ID_MMSI = f"{ID}/{MMSI}"

            lon = AInf_list[a_loc][-1][1]
            lat = AInf_list[a_loc][-1][2]
            speed = AInf_list[a_loc][-1][3]
            course = AInf_list[a_loc][-1][4]
            heading = AInf_list[a_loc][-1][5]
            types = AInf_list[a_loc][-1][6]
            time_val = AInf_list[a_loc][-1][9]

            x1 = max(VInf_list[v_loc][-1][1], 0)
            y1 = max(VInf_list[v_loc][-1][2], 0)
            x2 = min(VInf_list[v_loc][-1][3], self.im_shape[0])
            y2 = min(VInf_list[v_loc][-1][4], self.im_shape[1])
            w = abs(x2 - x1)
            h = abs(y2 - y1)

            # mat_list append -> concat
            row_mat_list = {
                'ID': ID, 'mmsi': MMSI, 'lon': lon, 'lat': lat,
                'speed': speed, 'course': course, 'heading': heading, 'type': types,
                'x1': x1, 'y1': y1, 'w': w, 'h': h, 'timestamp': time_val
            }
            mat_list = pd.concat([mat_list, pd.DataFrame([row_mat_list])], ignore_index=True)

            # mat_cur append -> concat
            if ID_MMSI in mat_las['ID/mmsi'].values:
                match = mat_las[mat_las['ID/mmsi'] == ID_MMSI]['match'].values[0] + 1
            else:
                match = 1

            row_mat_cur = {'ID/mmsi': ID_MMSI, 'timestamp': time_val, 'match': match}
            mat_cur = pd.concat([mat_cur, pd.DataFrame([row_mat_cur])], ignore_index=True)

        # 2) 历史存在匹配对当前不存在 (fog window)
        for ind, inf in bin_las.iterrows():
            ID_MMSI = inf['ID/mmsi']
            ID, MMSI = [int(x) for x in ID_MMSI.split('/')]
            time_val = inf['timestamp']
            if (MMSI in AIS_MMSIlist
                and ID_MMSI not in mat_cur['ID/mmsi'].values
                and timestamp // 1000 - time_val < self.fog_num):
                # inf is a Series -> concat
                mat_cur = pd.concat([mat_cur, inf.to_frame().T], ignore_index=True)

        # 3) 存储当前时刻绑定信息
        for ind, inf in mat_cur.iterrows():
            ID, MMSI = [int(x) for x in inf['ID/mmsi'].split('/')]
            if inf['match'] > self.bin_num:
                row_bin = {'ID': ID, 'mmsi': MMSI,
                           'timestamp': int(inf['timestamp']), 'match': int(inf['match'])}
                bin_cur = pd.concat([bin_cur, pd.DataFrame([row_bin])], ignore_index=True)

        return mat_list, mat_cur, bin_cur

    def traj_match(self, AIS_list, AIS_MMSIlist, VIS_list, VIS_IDlist, AInf_list, VInf_list, timestamp):
        mat_cur, bin_cur, mat_las, bin_las, mat_list = self.initialization(AIS_list, VIS_list)

        # Used ONLY to gate the "dis < 100" close-range bypass below (NOT a
        # full exclusion of the track from all matching, unlike the earlier
        # reverted attempt). Confirmed real-world case: a static coastal
        # feature at dis=74px (well under the 100px bypass threshold) got
        # treated as a valid candidate despite theta=178.6deg (moving
        # opposite direction) purely because the close-range bypass ignores
        # direction entirely, regardless of whether the "closeness" reflects
        # genuine proximity of a moving ship or just a fixed AIS ghost point
        # sweeping near a permanently static object.
        moving_flags = [is_moving_from_traj(vinf) for vinf in VInf_list]

        # A box touching the frame's left/right edge only shows the
        # VISIBLE portion of a possibly larger, partially off-screen ship
        # -- its centroid is systematically biased as more of the hull
        # goes off-frame. EDGE_MARGIN_PX allows a small tolerance for
        # detection noise right at the boundary (a box at x1=1 or 2
        # should still count as "touching" the edge).
        EDGE_MARGIN_PX = 3
        frame_width = self.im_shape[0]
        edge_flags = []
        for vinf in VInf_list:
            last_row = vinf[-1]
            x1, x2 = last_row[1], last_row[3]
            at_edge = (x1 <= EDGE_MARGIN_PX) or (x2 >= frame_width - EDGE_MARGIN_PX)
            edge_flags.append(at_edge)

        matrix_S = self.cal_similarity(AIS_list, AIS_MMSIlist, VIS_list, VIS_IDlist, bin_las, moving_flags, edge_flags, timestamp)

        row_ind, col_ind = linear_assignment(matrix_S)
        matches = self.data_filter(row_ind, col_ind, VIS_list, AIS_list, moving_flags, edge_flags)

        # SWITCH RESISTANCE (NEW): don't let an already-confirmed match get
        # replaced by a DIFFERENT mmsi based on a single tick's evidence.
        # Require the SAME candidate mmsi to win SEVERAL CONSECUTIVE ticks
        # before actually allowing the switch. Below that threshold, keep
        # the ship on its existing confirmed mmsi (if still a valid
        # candidate this tick at all) instead of the newly-suggested one.
        SWITCH_THRESHOLD = 3
        _cam_label = getattr(self, "_debug_label", "?")
        new_pending_switch = {}
        final_matches = []
        for (v_loc, a_loc) in matches:
            VIS_ID = int(VIS_IDlist[v_loc])
            new_mmsi = int(AIS_MMSIlist[a_loc])

            existing_mmsi = None
            if len(bin_las) > 0:
                id_prefix = f"{VIS_ID}/"
                matching_rows = bin_las[bin_las['ID/mmsi'].str.startswith(id_prefix)]
                if len(matching_rows) > 0:
                    existing_mmsi = int(matching_rows['ID/mmsi'].iloc[-1].split('/')[1])

            if existing_mmsi is not None and existing_mmsi != new_mmsi:
                prev_candidate, prev_count = self.pending_switch.get(VIS_ID, (None, 0))
                new_count = prev_count + 1 if prev_candidate == new_mmsi else 1

                if new_count < SWITCH_THRESHOLD:
                    print(f"[FUS debug][{_cam_label}][SWITCH-RESISTED] VIS_ID={VIS_ID} tried to "
                          f"switch from confirmed mmsi={existing_mmsi} to mmsi={new_mmsi} "
                          f"(consecutive attempt {new_count}/{SWITCH_THRESHOLD}) -- keeping "
                          f"existing mmsi for now")
                    new_pending_switch[VIS_ID] = (new_mmsi, new_count)
                    if existing_mmsi in AIS_MMSIlist:
                        existing_a_loc = AIS_MMSIlist.index(existing_mmsi)
                        final_matches.append((v_loc, existing_a_loc))
                    # else: existing mmsi isn't even present this tick --
                    # drop entirely rather than force an invalid pairing.
                else:
                    print(f"[FUS debug][{_cam_label}][SWITCH-ALLOWED] VIS_ID={VIS_ID} switching "
                          f"from confirmed mmsi={existing_mmsi} to mmsi={new_mmsi} after "
                          f"{new_count} consecutive ticks")
                    final_matches.append((v_loc, a_loc))
                    # resolved -- don't carry forward
            else:
                final_matches.append((v_loc, a_loc))
        self.pending_switch = new_pending_switch
        matches = final_matches

        matric = pd.DataFrame(matrix_S, columns=AIS_MMSIlist, index=VIS_IDlist)

        mat_list, mat_cur, bin_cur = self.save_data(
            mat_cur, bin_cur, mat_las, bin_las,
            mat_list, matches, AIS_MMSIlist, VIS_IDlist, AInf_list, VInf_list, timestamp
        )
        return mat_list, mat_cur, bin_cur

    def fusion(self, AIS_vis, AIS_cur, Vis_tra, Vis_cur, timestamp):
        if timestamp % 1000 < self.t:
            AIS_list, AIS_MMSIlist, AInf_list = traj_group(AIS_vis, AIS_cur, 'AIS')
            VIS_list, VIS_IDlist, VInf_list = traj_group(Vis_tra, Vis_cur, 'VIS')

            _cam_label = getattr(self, "_debug_label", "?")
            print(f"[FUS debug][{_cam_label}][fusion() inputs] "
                  f"AIS_vis={len(AIS_vis)} AIS_cur={len(AIS_cur)} "
                  f"Vis_tra={len(Vis_tra)} Vis_cur={len(Vis_cur)} "
                  f"-> AIS_list={len(AIS_list)} VIS_list={len(VIS_list)} "
                  f"VIS_IDlist={VIS_IDlist} AIS_MMSIlist={AIS_MMSIlist}")

            self.mat_list, self.mat_cur, self.bin_cur = self.traj_match(
                AIS_list, AIS_MMSIlist, VIS_list, VIS_IDlist, AInf_list, VInf_list, timestamp
            )

        return self.mat_list, self.bin_cur