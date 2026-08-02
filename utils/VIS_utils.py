import csv

import numpy as np
import cv2
import torch
from PIL import Image
import pandas as pd
from detection_yolox.yolo import YOLO
from deep_sort.utils.parser import get_config
from deep_sort.deep_sort import DeepSort
from warnings import simplefilter
import cv2
from PIL import Image
import pandas as pd
import os
simplefilter(action='ignore', category=FutureWarning)
# 初始化目标检测
yolo = YOLO()




def box_whether_in_area(bounding_box, Area):
    x_center = (bounding_box[0] + bounding_box[2]) / 2
    y_center = (bounding_box[1] + bounding_box[3]) / 2
    Area = [1] + Area # 添加一个虚拟id，为了使用whether函数
    # 中心点是否落在Area内
    return whether_in_area((x_center, y_center), Area)

def speed_extract(last_traj, now_traj):
    """
    :param last_traj: 若干秒前的轨迹数据
    :param now_traj: 当前时刻轨迹数据
    :return: 【水平速度， 垂直速度】
    """
    last_x = int(last_traj.loc['x'])
    last_y = int(last_traj.loc['y'])
    cur_x = int(now_traj.loc['x'])
    cur_y = int(now_traj.loc['y'])
    x_speed = (cur_x - last_x) / (int(now_traj.loc['timestamp']) - int(last_traj.loc['timestamp']))
    y_speed = (cur_y - last_y) / (int(now_traj.loc['timestamp']) - int(last_traj.loc['timestamp']))
    return [x_speed, y_speed]

def whether_in_area(point, bbox):
    """
    :param point: [x, y]
    :param bbox: [id,x1,y1,x2,y2]
    """
    if point[0] <= bbox[3] and point[0] >= bbox[1] and point[1] <= bbox[4] and point[1] >= bbox[2]:
        return 1
    else:
        return 0

def overlap(box1, box2, val):
    minx1, miny1, maxx1, maxy1 = box1
    minx2, miny2, maxx2, maxy2 = box2
    minx = max(minx1, minx2)
    miny = max(miny1, miny2)
    maxx = min(maxx1, maxx2)
    maxy = min(maxy1, maxy2)
    if minx > maxx or miny > maxy:
        return 0
    else:
        max_x1 = max(minx1, minx2)
        min_x2 = min(maxx1, maxx2)
        max_y1 = max(miny1, miny2)
        min_y2 = min(maxy1, maxy2)
        Cross_area = (min_x2 - max_x1) * (min_y2 - max_y1)
        box1_area = (maxx1 - minx1) * (maxy1 - miny1)
        box2_area = (maxx2 - minx2) * (maxy2 - miny2)
        if Cross_area / box1_area > val or Cross_area / box2_area > val:
            return 1
        else:
            return 0
def whether_occlusion(bbox, cur_bbox_list, val):
    occlusion_bbox_list = []
    occlusion_id_list = []
    for i in range(len(cur_bbox_list)):
        flag = overlap(bbox[1:], cur_bbox_list[i][1:], val)
        if flag:
            if len(occlusion_id_list) == 0:
                occlusion_id_list.append(bbox[0])
                occlusion_bbox_list.append(bbox[1:])
            occlusion_bbox_list.append(cur_bbox_list[i][1:])
            occlusion_id_list.append(cur_bbox_list[i][0])
            break
    return occlusion_bbox_list, occlusion_id_list

def whether_in_OAR(point, OAR_list):
    flag = 0
    for oar in OAR_list:
        oar_id = [0, oar[0], oar[1], oar[2], oar[3]]
        if whether_in_area(point, oar_id):
            flag = whether_in_area(point, oar_id)
            break
    return flag


def OAR_extractor(his_traj_dataframe_list,val):
    OAR_list = []
    OAR_id_list = []
    if len(his_traj_dataframe_list) == 0:
        return OAR_list, OAR_id_list
    his_id_list = his_traj_dataframe_list[-1]['ID'].unique()
    his_bbox_list = []
    for i in range(len(his_id_list)):
        visual_traj = his_traj_dataframe_list[-1].iloc[i]
        his_bbox_list.append([visual_traj['ID'], visual_traj['x1'], visual_traj['y1'], visual_traj['x2'],
                              visual_traj['y2']])
    for i in range(len(his_bbox_list)):
        if i < len(his_bbox_list) - 1:
            occlusion_boxes, occlusion_ids = whether_occlusion(his_bbox_list[i], his_bbox_list[i + 1:], val)
            for index in range(len(occlusion_boxes)):
                if (occlusion_ids[index] not in OAR_id_list) and (occlusion_ids[index] in his_id_list):
                    OAR_list.append(occlusion_boxes[index])
                    OAR_id_list.append(occlusion_ids[index])
    return OAR_list, OAR_id_list

def motion_features_extraction(his_traj_dataframe_list, VIS_tra_cur):
    speed_list = []
    VIS_traj_cur_withfeature = VIS_tra_cur.copy()
    cur_id_list = VIS_tra_cur['ID'].unique()
    for i in range(len(cur_id_list)):
        speed_list.append('[0, 0]')
    VIS_traj_cur_withfeature['speed'] = speed_list
    for k in range(len(cur_id_list)):
        if len(his_traj_dataframe_list) == 0:
            continue
        id = cur_id_list[k]
        for i in his_traj_dataframe_list:
            his_id_list = list(i['ID'].unique())
            if id not in his_id_list:
                continue
            else:
                index = his_id_list.index(id)
                last_traj = i.iloc[index]
                VIS_traj_cur_withfeature.loc[k, 'speed'] = str(speed_extract(last_traj, VIS_traj_cur_withfeature.iloc[k]))
                break
    return VIS_traj_cur_withfeature

def id_whether_stable(id, last_5_trajs):
    for traj in last_5_trajs:
        if id in list(traj['ID'].unique()):
            continue
        else:
            return False
    return True

def _nms_deduplicate(bboxes, iou_threshold=0.6):
    """
    Remove overlapping duplicate detections directly from YOLO's raw
    output, BEFORE anything reaches DeepSORT. Confirmed real-world case:
    raw detection.txt data showed the SAME physical ship producing TWO
    separate overlapping bounding boxes (IOU 0.62-0.89) at multiple
    frames -- this happens at the YOLO detection stage itself, not from
    a tracking/association failure downstream. Tuning DeepSORT's own
    config (NMS_MAX_OVERLAP, MAX_DIST) cannot fix this, since it operates
    on tracks, not on YOLO's raw per-frame box proposals.

    Keeps the HIGHER-confidence box whenever two detections overlap above
    iou_threshold; drops the other entirely so only one box per real
    object ever reaches tracking.
    """
    if len(bboxes) <= 1:
        return bboxes

    def iou(a, b):
        ax1, ay1, ax2, ay2 = a[0], a[1], a[2], a[3]
        bx1, by1, bx2, by2 = b[0], b[1], b[2], b[3]
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0
        inter = (ix2 - ix1) * (iy2 - iy1)
        area_a = (ax2 - ax1) * (ay2 - ay1)
        area_b = (bx2 - bx1) * (by2 - by1)
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0.0

    # Sort by confidence descending, greedily keep boxes that don't
    # overlap too much with anything already kept.
    sorted_boxes = sorted(bboxes, key=lambda b: b[5], reverse=True)
    kept = []
    for box in sorted_boxes:
        if all(iou(box, kept_box) < iou_threshold for kept_box in kept):
            kept.append(box)
    return kept


class VISPRO(object):
    def __init__(self, anti, val, t, detect_roi=None, detect_upscale=1.0, min_confidence=None,
                 deepsort_min_confidence=None, deepsort_n_init=None):
        """
        detect_roi: optional (x1, y1, x2, y2) in ORIGINAL frame coordinates.
            If given, detection() crops to this region before running YOLO,
            instead of using the full frame. Use this for cameras where
            ships only ever appear in a narrow band (e.g. the water
            channel) and are too small in the full frame for reliable
            detection -- cropping increases the object's footprint
            relative to the network's fixed input size, which a plain
            full-frame upscale does NOT achieve (the network just resizes
            it back down). Boxes are transformed back to full-frame
            coordinates before being returned, so tracking/fusion/drawing
            downstream are unaffected and don't need to know this happened.
        detect_upscale: additional scale factor applied to the crop before
            detection (e.g. 2.0 to double the crop's resolution). 1.0 = no
            extra upscaling, just the crop itself.
        min_confidence: optional per-camera confidence floor, applied AFTER
            YOLO's own (shared, global) confidence threshold. The global
            `yolo = YOLO()` instance in this file is shared across every
            VISPRO instance (every camera) -- there's no way to give one
            camera a looser network-level threshold without loosening it
            for all cameras. So instead: set the global threshold low
            enough to keep borderline-but-real detections for whichever
            camera needs them, then use min_confidence here to filter
            each camera back up to its own desired strictness
            independently. E.g. global threshold 0.25, cam1
            min_confidence=0.30 (keep its real 0.41-0.46 detections),
            cam2 min_confidence=0.40 (unchanged from before this existed).
            None = no extra filtering, trust the global threshold as-is.
        deepsort_min_confidence / deepsort_n_init: PER-CAMERA overrides for
            DeepSORT's OWN internal thresholds (deep_sort.yaml's
            MIN_CONFIDENCE and N_INIT). Confirmed real-world case: cam2
            needed a much looser MIN_CONFIDENCE/N_INIT than cam1 to detect
            a real, hard-to-see ship consistently -- but deep_sort.yaml is
            loaded fresh per VISPRO instance, and previously always used
            its file values verbatim for both cameras, meaning any change
            there affected both cameras' tracking simultaneously (loosening
            it for cam2's benefit caused new false-positive tracks to start
            appearing on cam1, which had never needed loosening). These
            two parameters let one camera (e.g. cam2) override just its own
            DeepSort instance's thresholds, leaving deep_sort.yaml's file
            values (and thus any OTHER camera not passing an override) at
            their original, safe defaults. None = use the yaml file's value
            unchanged, same as before this existed.

        NOTE: detect_roi is a guess and needs visual tuning against this
        camera's actual footage -- it is NOT verified against real frames
        here. Ships partially outside the ROI will be missed or clipped;
        leave generous margin above/below the actual channel.
        """
        self.anti = anti
        self.last5_vis_tra_list = []
        self.Vis_tra_cur_3      = pd.DataFrame(columns=['ID','x1','y1','x2','y2','x','y','timestamp'])
        self.Vis_tra_cur        = pd.DataFrame(columns=['ID','x1','y1','x2','y2','x','y','timestamp'])
        self.Vis_tra            = pd.DataFrame(columns=['ID','x1','y1','x2','y2','x','y','timestamp'])
        self.VIS_tra_last = pd.DataFrame(columns=['ID','x1','y1','x2','y2','x','y', 'speed','timestamp'])
        self.OAR_list = []
        self.OAR_ids_list = []
        self.OAR_mmsi_list = []
        self.val = val
        self.t = t
        self.detect_roi = detect_roi
        self.detect_upscale = detect_upscale
        self.min_confidence = min_confidence
        cfg = get_config()
        cfg.merge_from_file("deep_sort/configs/deep_sort.yaml")

        # Apply per-camera overrides AFTER loading the shared yaml, so only
        # THIS instance's DeepSort tracker is affected -- the yaml file
        # itself (and any other camera's VISPRO that doesn't pass an
        # override) stays at its original, safe values.
        effective_min_confidence = (deepsort_min_confidence if deepsort_min_confidence is not None
                                     else cfg.DEEPSORT.MIN_CONFIDENCE)
        effective_n_init = (deepsort_n_init if deepsort_n_init is not None
                             else cfg.DEEPSORT.N_INIT)
        if deepsort_min_confidence is not None or deepsort_n_init is not None:
            print(f"[VISPRO] DeepSort per-camera override -- "
                  f"MIN_CONFIDENCE: {cfg.DEEPSORT.MIN_CONFIDENCE} -> {effective_min_confidence}, "
                  f"N_INIT: {cfg.DEEPSORT.N_INIT} -> {effective_n_init}")

        self.deepsort = DeepSort(cfg.DEEPSORT.REID_CKPT, max_dist=cfg.DEEPSORT.MAX_DIST, min_confidence=effective_min_confidence, nms_max_overlap=cfg.DEEPSORT.NMS_MAX_OVERLAP, max_iou_distance=cfg.DEEPSORT.MAX_IOU_DISTANCE, max_age=cfg.DEEPSORT.MAX_AGE, n_init=effective_n_init, nn_budget=cfg.DEEPSORT.NN_BUDGET, use_cuda=False)
        self.Anti_occlusion_traj = pd.DataFrame(columns=['ID','x1','y1','x2','y2','x','y','speed','timestamp'])

    def _filter_by_confidence(self, bboxes):
        # DEBUG: print every detection's raw confidence BEFORE filtering,
        # so min_confidence can be set from real observed values (e.g. "the
        # false building detection scores ~0.22, real ships score >=0.35 --
        # set min_confidence to 0.28") instead of bisecting blindly between
        # values that are too strict (miss real ships) and too loose (catch
        # noise). Remove this print once you've picked a value with real
        # data backing it, if you don't want it cluttering the log
        # permanently.
        for b in bboxes:
            print(f"[VISPRO debug] raw detection confidence={float(b[5]):.3f} "
                  f"box=({b[0]:.0f},{b[1]:.0f},{b[2]:.0f},{b[3]:.0f}) "
                  f"(current min_confidence={self.min_confidence})")
        if self.min_confidence is None:
            return bboxes
        return [b for b in bboxes if float(b[5]) >= self.min_confidence]

    def detection(self, image):
        # 用于目标检测
        if self.detect_roi is not None:
            x1, y1, x2, y2 = self.detect_roi
            crop = image[y1:y2, x1:x2]
            if self.detect_upscale != 1.0:
                crop = cv2.resize(crop, None, fx=self.detect_upscale, fy=self.detect_upscale,
                                   interpolation=cv2.INTER_LINEAR)
            im0 = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            im0 = Image.fromarray(im0)
            bboxes = yolo.detect_image(im0)
            bboxes = _nms_deduplicate(bboxes)
            bboxes = self._filter_by_confidence(bboxes)

            # Map boxes from crop+upscale space back to original frame
            # coordinates so everything downstream (tracking, fusion,
            # drawing) works exactly as if detection had run on the full
            # frame directly.
            remapped = []
            for bx1, by1, bx2, by2, label, conf in bboxes:
                remapped.append((
                    bx1 / self.detect_upscale + x1,
                    by1 / self.detect_upscale + y1,
                    bx2 / self.detect_upscale + x1,
                    by2 / self.detect_upscale + y1,
                    label, conf,
                ))
            bboxes = remapped
        else:
            im0 = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            im0 = Image.fromarray(im0)
            bboxes = yolo.detect_image(im0)
            bboxes = _nms_deduplicate(bboxes)
            bboxes = self._filter_by_confidence(bboxes)
        return bboxes

    def track(self, image, bboxes, bboxes_anti_occ, id_list, timestamp):
        bbox_xywh, confs = [], []
        bbox_xywh_anti_occ, confs_anti_occ = [], []
        if len(bboxes) or len(bboxes_anti_occ):
            for x1, y1, x2, y2, _, conf in bboxes:
                obj = [int((x1+x2)/2), int((y1+y2)/2),x2-x1, y2-y1]
                bbox_xywh.append(obj)
                confs.append(conf)
            for x1, y1, x2, y2, _, conf in bboxes_anti_occ:
                obj = [int((x1+x2)/2), int((y1+y2)/2),x2-x1, y2-y1]
                bbox_xywh_anti_occ.append(obj)
                confs_anti_occ.append(conf)

            xywhs = torch.Tensor(bbox_xywh)
            confss = torch.Tensor(confs)
            xywhs_anti_occ = torch.Tensor(bbox_xywh_anti_occ)
            confss_anti_occ = torch.Tensor(confs_anti_occ)
            outputs = self.deepsort.update(xywhs, confss, image, xywhs_anti_occ, confss_anti_occ, id_list, timestamp)
            for value in list(outputs):
                x1, y1, x2, y2, _, track_id = value
                if track_id in id_list:
                    x1, y1, x2, y2, _, _ = bboxes_anti_occ[id_list.index(track_id)]
                row = {
                    'ID': track_id,
                    'x1': int(x1), 'y1': int(y1), 'x2': int(x2), 'y2': int(y2),
                    'x': int((x1 + x2) / 2), 'y': int((y1 + y2) / 2),
                    'timestamp': timestamp // 1000
                }
                self.Vis_tra_cur_3 = pd.concat([self.Vis_tra_cur_3, pd.DataFrame([row])], ignore_index=True)

    def update_tra(self, Vis_tra, timestamp):
        self.Vis_tra_cur = pd.DataFrame(columns=['ID','x1','y1','x2','y2','x','y','timestamp'])
        id_list = self.Vis_tra_cur_3['ID'].unique()
        for k in range(len(id_list)):
            id_current = self.Vis_tra_cur_3[self.Vis_tra_cur_3['ID'] == id_list[k]].reset_index(drop=True)
            df = id_current.mean().astype(int)
            df['timestamp'] = timestamp // 1000
            self.Vis_tra_cur = pd.concat([self.Vis_tra_cur, df.to_frame().T], ignore_index=True)

        self.Vis_tra_cur_3 = pd.DataFrame(columns=['ID','x1','y1','x2','y2','x','y','timestamp'])

        Vis_tra_cur_withfeature = motion_features_extraction(self.last5_vis_tra_list, VIS_tra_cur= self.Vis_tra_cur)
        self.Vis_tra = pd.concat([self.Vis_tra, Vis_tra_cur_withfeature], ignore_index=True)
        if len(self.last5_vis_tra_list) > 4:
            self.last5_vis_tra_list.pop(0)
        self.last5_vis_tra_list.append(Vis_tra_cur_withfeature)
        time_limited = 2
        self.Vis_tra = self.Vis_tra.drop(self.Vis_tra[self.Vis_tra['timestamp'] <\
                                                      (timestamp // 1000 - time_limited * 60)].index)
        return Vis_tra_cur_withfeature

    def traj_prediction_via_visual(self, last_traj, timestamp, speed):
        Vis_tra_prediction = last_traj.copy()
        x_move = int(timestamp - last_traj.loc['timestamp']) * float(speed[0])
        y_move = int(timestamp - last_traj.loc['timestamp']) * float(speed[1])
        Vis_tra_prediction.loc['x'] = Vis_tra_prediction.loc['x'] + x_move
        Vis_tra_prediction.loc['x1'] = Vis_tra_prediction.loc['x1'] + x_move
        Vis_tra_prediction.loc['x2'] = Vis_tra_prediction.loc['x2'] + x_move
        Vis_tra_prediction.loc['y'] = Vis_tra_prediction.loc['y'] + y_move
        Vis_tra_prediction.loc['y1'] = Vis_tra_prediction.loc['y1'] + y_move
        Vis_tra_prediction.loc['y2'] = Vis_tra_prediction.loc['y2'] + y_move
        Vis_tra_prediction.loc['timestamp'] = timestamp
        return Vis_tra_prediction

    def anti_occ(self, last5_vis_tra_list, bboxes, AIS_vis, bind_inf,timestamp):
        bboxes_anti_occ = []
        if len(self.OAR_list):
            pop_index_list = []
            for index in range(len(bboxes)):
                for OAR in self.OAR_list:
                    if box_whether_in_area(bboxes[index][:4], OAR):
                        pop_index_list.append(index)
                        break
            for pop_index in range(len(pop_index_list)):
                bboxes.pop(pop_index_list[pop_index] - pop_index)

            bind_id_list = list(bind_inf['ID'].unique())
            self.OAR_mmsi_list = []
            OAR_ids_list_copy = self.OAR_ids_list.copy()
            for k in range(len(OAR_ids_list_copy)):
                if OAR_ids_list_copy[k] in bind_id_list:
                    mmsi = bind_inf.iloc[bind_id_list.index(OAR_ids_list_copy[k])].loc['mmsi']
                    self.OAR_mmsi_list.append([OAR_ids_list_copy[k], int(mmsi)])
                else:
                    self.OAR_mmsi_list.append([OAR_ids_list_copy[k], 0])

            ais_vis_mmsi_list = list(AIS_vis['mmsi'])
            pop_index_list = []
            for k in range(len(self.OAR_mmsi_list)):
                final_find_flg = 0
                second_final_find_flg = 0
                final_pos = []
                second_final_pos = []
                if not self.OAR_mmsi_list[k][1] == 0 and self.OAR_mmsi_list[k][1] in ais_vis_mmsi_list:
                    for i in range(len(ais_vis_mmsi_list)):
                        if int(AIS_vis.iloc[len(ais_vis_mmsi_list) - i - 1].loc['mmsi']) == self.OAR_mmsi_list[k][1] and \
                                int(AIS_vis.iloc[len(ais_vis_mmsi_list) - i - 1].loc['timestamp']) == timestamp - 1:
                            final_find_flg = 1
                            final_pos = [AIS_vis.iloc[len(ais_vis_mmsi_list) - i - 1].loc['x'],
                                         AIS_vis.iloc[len(ais_vis_mmsi_list) - i - 1].loc['y']]
                            continue
                        elif int(AIS_vis.iloc[len(ais_vis_mmsi_list) - i - 1].loc['mmsi']) == self.OAR_mmsi_list[k][
                            1] and int(AIS_vis.iloc[len(ais_vis_mmsi_list) - i - 1].loc['timestamp']) == timestamp - 2:
                            second_final_find_flg = 1
                            second_final_pos = [AIS_vis.iloc[len(ais_vis_mmsi_list) - i - 1].loc['x'],
                                                AIS_vis.iloc[len(ais_vis_mmsi_list) - i - 1].loc['y']]
                            continue
                        if final_find_flg and second_final_find_flg:
                            x_motion = final_pos[0] - second_final_pos[0]
                            y_motion = final_pos[1] - second_final_pos[1]
                            bboxes_anti_occ.append(
                                (self.Anti_occlusion_traj.iloc[k].loc['x1'] + x_motion,
                                 self.Anti_occlusion_traj.iloc[k].loc['y1'] + y_motion,
                                 self.Anti_occlusion_traj.iloc[k].loc['x2'] + x_motion,
                                 self.Anti_occlusion_traj.iloc[k].loc['y2'] + y_motion,
                                 'vessel', 1))
                            break
                else:
                    if not id_whether_stable(self.OAR_mmsi_list[k][0], last5_vis_tra_list):
                        pop_index_list.append(k)
                        continue
                    index = list(last5_vis_tra_list[0]['ID'].unique()).index(self.OAR_mmsi_list[k][0])
                    speed_str = last5_vis_tra_list[0].iloc[index].loc['speed']
                    speed = [float(speed_str[1:-1].split(',')[0]), float(speed_str[1:-1].split(',')[1])]
                    trajs = last5_vis_tra_list[0]
                    id_list = list(trajs['ID'].unique())
                    last_traj = trajs.iloc[id_list.index(self.OAR_mmsi_list[k][0])]
                    Vis_traj_now = self.traj_prediction_via_visual(last_traj, timestamp, speed)
                    bboxes_anti_occ.append(
                        (Vis_traj_now.loc['x1'],
                         Vis_traj_now.loc['y1'],
                         Vis_traj_now.loc['x2'],
                         Vis_traj_now.loc['y2'],
                         'vessel', 1))

            for i in range(len(pop_index_list)):
                self.OAR_mmsi_list.pop(pop_index_list[i] - i)
                self.OAR_ids_list.pop(pop_index_list[i] - i)
                self.OAR_list.pop(pop_index_list[i] - i)
            if not len(self.OAR_ids_list) == len(bboxes_anti_occ):
                print(f"[VISPRO] anti_occ: OAR_ids_list/bboxes_anti_occ length "
                      f"mismatch ({len(self.OAR_ids_list)} vs {len(bboxes_anti_occ)}) "
                      f"at timestamp={timestamp}. Skipping anti-occlusion boxes "
                      f"this tick instead of dropping into an interactive shell.")
                bboxes_anti_occ = []
        return bboxes_anti_occ


    def feedCap(self, image, timestamp, AIS_vis, bind_inf):
        if timestamp % 1000 < self.t:
            bboxes = self.detection(image)
            bboxes_anti_occ = self.anti_occ(self.last5_vis_tra_list, bboxes, AIS_vis, bind_inf, timestamp // 1000)
            self.track(image, bboxes, bboxes_anti_occ=bboxes_anti_occ,\
                    id_list=self.OAR_ids_list, timestamp=timestamp // 1000)

            Vis_tra_cur = self.Vis_tra_cur
            if timestamp % 1000 < self.t:
                Vis_tra_cur = self.update_tra(self.Vis_tra, timestamp)
                if self.anti:
                    self.OAR_list, self.OAR_ids_list = OAR_extractor(self.last5_vis_tra_list, self.val)
                self.VIS_tra_last = Vis_tra_cur
                self.Anti_occlusion_traj = pd.DataFrame(columns=['ID', 'x1', 'y1', 'x2', 'y2', 'x', 'y', 'speed', 'timestamp'])
                id_list = list(self.VIS_tra_last['ID'].unique())
                for i in self.OAR_ids_list:
                   self.Anti_occlusion_traj = pd.concat(
                       [self.Anti_occlusion_traj, self.VIS_tra_last.iloc[[id_list.index(i)]]],
                       ignore_index=True
                   )
        return self.Vis_tra, self.Vis_tra_cur