import pandas as pd
from IPython import embed
import numpy as np
import cv2
import time

def add_alpha_channel(img):
    """ 为jpg图像添加alpha通道 """
    b_channel, g_channel, r_channel = cv2.split(img)  # 剥离jpg图像通道
    alpha_channel = np.ones(b_channel.shape, dtype=b_channel.dtype) * 255  # 创建Alpha通道
    img_new = cv2.merge((b_channel, g_channel, r_channel, alpha_channel))  # 融合通道
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

    # 左上角
    cv2.line(add_img, (x1, y1), (x1, y15), color, tf)
    cv2.line(add_img, (x1, y1), (x15, y1), color, tf)

    # 右上角
    cv2.line(add_img, (x2, y1), (x2, y15), color, tf)
    cv2.line(add_img, (x45, y1), (x2, y1), color, tf)

    # 左下角
    cv2.line(add_img, (x1, y2), (x15, y2), color, tf)
    cv2.line(add_img, (x1, y45), (x1, y2), color, tf)

    # 右下角
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

def inf_loc(x, y, w, h, w0, h0):
    """ 将png透明图像与jpg图像叠加 """
    x1 = x - w0 // 2
    y1 = 25 * h // 30
    x2 = x + w0 // 2
    y2 = y1 + h0

    if x1 < 0:
        x1 = 0
        x2 = w0
    if x2 > w:
        x1 = w - w0
        x2 = w
    return x1, y1, x2, y2

def process_img(df_draw, x1, y1, x2, y2, fusion_current, w, h, w0, h0, Type):
    """
    对每帧视频图片进行处理，对检测船舶添加相关信息
    """
    if Type:
        color = (204, 204, 51)
        inf_x1, inf_y1, inf_x2, inf_y2 = inf_loc((x1 + x2) // 2, y2, w, h, w0, h0)

        ais = 1
        mmsi = int(fusion_current['mmsi'][0])
        sog = round(fusion_current['speed'][0], 5)
        cog = round(fusion_current['course'][0], 5)
        lat = round(fusion_current['lat'][0], 5)
        lon = round(fusion_current['lon'][0], 5)
    else:
        color = (0, 0, 255)
        inf_x1, inf_y1, inf_x2, inf_y2 = inf_loc((x1 + x2) // 2, y2, w, h, w0, h0)
        ais = 0
        mmsi = -1
        sog = -1
        cog = -1
        lat = -1
        lon = -1

    # pandas 2.x: append -> concat
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
                        cv2.FONT_HERSHEY_SIMPLEX, tf / 8, color, tf // 2)
            cv2.putText(add_img, f'SOG:{sog}', (int(inf_x1 + tf), int(inf_y1 + tf * 11)),
                        cv2.FONT_HERSHEY_SIMPLEX, tf / 8, color, tf // 2)
            cv2.putText(add_img, f'COG:{cog}', (int(inf_x1 + tf), int(inf_y1 + tf * 17)),
                        cv2.FONT_HERSHEY_SIMPLEX, tf / 8, color, tf // 2)
            cv2.putText(add_img, f'LAT:{lat}', (int(inf_x1 + tf), int(inf_y1 + tf * 23)),
                        cv2.FONT_HERSHEY_SIMPLEX, tf / 8, color, tf // 2)
            cv2.putText(add_img, f'LON:{lon}', (int(inf_x1 + tf), int(inf_y1 + tf * 29)),
                        cv2.FONT_HERSHEY_SIMPLEX, tf / 8, color, tf // 2)
            add_img = draw_line(add_img, int((box_x1 + box_x2) // 2), int(box_y2),
                                int((inf_x1 + inf_x2) // 2), int(inf_y1),
                                int(y * (i + 1) // (length + 1)), color, tf)
            i += 1
        else:
            cv2.rectangle(add_img, (int(inf_x1), int(inf_y1)), (int(inf_x2), int(inf_y2)),
                          color, thickness=tf // 3, lineType=cv2.LINE_AA)
            add_img = draw_line(add_img, int((box_x1 + box_x2) // 2), int(box_y2),
                                int((inf_x1 + inf_x2) // 2), int(inf_y1),
                                int(y * (i + 1) // (length + 1)), color, tf)
            cv2.putText(add_img, 'NO AIS', (int(inf_x1 + tf), int((inf_y1 + inf_y2) // 2 + tf * 3)),
                        cv2.FONT_HERSHEY_SIMPLEX, tf / 4, color, tf // 2)
            i += 1

    return add_img

def filter_inf(df_draw, w, h, w0, h0, wn, hn, df):
    df_draw = df_draw.sort_values(by=['inf_x1'], ascending=True)
    df_new = pd.DataFrame(columns=['ais', 'mmsi', 'sog', 'cog',
                                   'lat', 'lon', 'box_x1', 'box_y1', 'box_x2', 'box_y2',
                                   'inf_x1', 'inf_y1', 'inf_x2', 'inf_y2', 'color'])
    index = 0
    for ind, inf in df_draw.iterrows():
        if inf['ais'] == 1:
            inf['inf_x1'] = index + df
            inf['inf_x2'] = inf['inf_x1'] + w0
            index = index + df + w0
        else:
            inf['inf_x1'] = index + df
            inf['inf_x2'] = inf['inf_x1'] + wn
            index = index + df + wn

        # pandas 2.x: append -> concat (inf is a Series)
        df_new = pd.concat([df_new, inf.to_frame().T], ignore_index=True)

    return df_new

class DRAW(object):
    def __init__(self, shape, t):
        self.df_draw = pd.DataFrame(columns=['ais', 'mmsi', 'sog', 'cog',
                                             'lat', 'lon', 'box_x1', 'box_y1', 'box_x2', 'box_y2',
                                             'inf_x1', 'inf_y1', 'inf_x2', 'inf_y2', 'color'])
        self.w, self.h = int(shape[0]), int(shape[1])
        self.h0, self.w0 = self.h // 8, self.w // 12
        self.hn, self.wn = self.h // 15, self.w // 15
        self.tl = None or round(0.002 * (shape[0] + shape[1]) / 2) + 1
        self.tf = max(self.tl + 1, 1)  # font thickness
        self.t = t

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
                        else:
                            df_draw = process_img(df_draw, x1, y1, x2, y2,
                                                  [], self.w, self.h, self.wn, self.hn, Type=False)
                    else:
                        df_draw = process_img(df_draw, x1, y1, x2, y2,
                                              [], self.w, self.h, self.wn, self.hn, Type=False)

            self.df_draw = filter_inf(df_draw, self.w, self.h, self.w0, self.h0, self.wn, self.hn, self.tf)

        add_img = draw(add_img, self.df_draw, self.tf)
        return add_img
