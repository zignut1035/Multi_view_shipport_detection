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

class FUSPRO(object):
    def __init__(self, max_dis, im_shape, t):
        self.max_dis = max_dis
        self.im_shape = im_shape
        self.bin_num = 3
        self.fog_num = 3
        self.t = t

        self.mat_cur  = pd.DataFrame(columns=['ID/mmsi', 'timestamp', 'match'])
        self.mat_list = pd.DataFrame(columns=['ID', 'mmsi', 'lon', 'lat', 'speed', 'course', 'heading', 'type', 'timestamp'])
        self.bin_cur  = pd.DataFrame(columns=['ID', 'mmsi', 'timestamp', 'match'])

    def initialization(self, AIS_list, VIS_list):
        mat_las = self.mat_cur
        bin_las = mat_las[mat_las['match'] > self.bin_num]
        mat_cur = pd.DataFrame(columns=['ID/mmsi', 'timestamp', 'match'])
        bin_cur = pd.DataFrame(columns=['ID', 'mmsi', 'timestamp', 'match'])

        mat_list = pd.DataFrame(columns=['ID', 'mmsi', 'lon', 'lat', 'speed', 'course', 'heading', 'type',
                                         'x1', 'y1', 'w', 'h', 'timestamp'])
        return mat_cur, bin_cur, mat_las, bin_las, mat_list

    def cal_similarity(self, AIS_list, AIS_MMSIlist, VIS_list, VIS_IDlist, bin_las):
        matrix_S = np.zeros((len(VIS_list), len(AIS_list)))

        binIDmmsi, bin_MMSI, bin_ID = [], [], []
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

                if int(cur_mmsi) not in bin_MMSI and int(cur_ID) not in bin_ID:
                    theta = angle(VIS_list[i], AIS_list[j])
                    x_VIS, y_VIS = VIS_list[i][-1][0], VIS_list[i][-1][1]
                    x_AIS, y_AIS = AIS_list[j][-1][0], AIS_list[j][-1][1]
                    dis = ((x_VIS - x_AIS) ** 2 + (y_VIS - y_AIS) ** 2) ** 0.5

                    if dis < self.max_dis and theta < math.pi * (5 / 6):
                        matrix_S[i][j] = DTW_fast(VIS_list[i], AIS_list[j])
                    else:
                        matrix_S[i][j] = 1000000000

                elif cur_IDmmsi in binIDmmsi:
                    s = bin_las.loc[bin_las['ID/mmsi'] == cur_IDmmsi, 'match']
                    m = int(s.iloc[-1]) if len(s) else 0
                    matrix_S[i][j] = -m * 100

                else:
                    matrix_S[i][j] = 1000000000

        return matrix_S

    def data_filter(self, row_ind, col_ind, VIS_list, AIS_list):
        matches = []
        for row, col in zip(row_ind, col_ind):
            theta = angle(VIS_list[row], AIS_list[col])

            x_VIS, y_VIS = VIS_list[row][-1][0], VIS_list[row][-1][1]
            x_AIS, y_AIS = AIS_list[col][-1][0], AIS_list[col][-1][1]
            dis = ((x_VIS - x_AIS) ** 2 + (y_VIS - y_AIS) ** 2) ** 0.5

            if dis < self.max_dis and theta < math.pi * (5 / 6):
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
        matrix_S = self.cal_similarity(AIS_list, AIS_MMSIlist, VIS_list, VIS_IDlist, bin_las)

        row_ind, col_ind = linear_assignment(matrix_S)
        matches = self.data_filter(row_ind, col_ind, VIS_list, AIS_list)

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

            self.mat_list, self.mat_cur, self.bin_cur = self.traj_match(
                AIS_list, AIS_MMSIlist, VIS_list, VIS_IDlist, AInf_list, VInf_list, timestamp
            )

        return self.mat_list, self.bin_cur
