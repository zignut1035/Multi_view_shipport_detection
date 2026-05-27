import os, time, imutils, cv2, argparse, glob
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
# 1. PATH CONFIGURATION (WSL Linux Format)
data_path_1  = "/mnt/d/kanmon_temp/cam1_shimonoseki/" 
data_path_2  = "/mnt/d/kanmon_temp/cam2_moji/"        
ais_dir      = "/mnt/d/kanmon_temp/ais_data_kanmon/first_session/" 
result_path  = "/mnt/d/kanmon_temp/result_dual/"

if not os.path.exists(result_path):
    os.makedirs(result_path)

anti         = 1
anti_rate    = 0

# Read configs for both cameras
vid_path_1, _, res_vid_1, res_met_1, init_time_1, cam_para_1 = read_all(data_path_1, result_path)
vid_path_2, _, res_vid_2, res_met_2, init_time_2, cam_para_2 = read_all(data_path_2, result_path)


# OVERRIDE the ais_path returned by read_all to point to your centralized 'ais' folder
# This assumes your read_all function expects the AIS data to be inside the camera folder
ais_path_shared = ais_dir 

# Initialize AIS data 
ais_file_1, timestamp0, time0 = ais_initial(ais_path_shared, init_time_1)
ais_file_2, _, _              = ais_initial(ais_path_shared, init_time_2) 
Time = init_time_1.copy()

# ---------------------------------------------------------
# 2. INITIALIZE VIDEO CAPTURES & SHAPES
# ---------------------------------------------------------
cap1 = cv2.VideoCapture(vid_path_1)
cap2 = cv2.VideoCapture(vid_path_2)

im_shape_1 = [cap1.get(3), cap1.get(4)]
im_shape_2 = [cap2.get(3), cap2.get(4)]
max_dis_1  = min(im_shape_1) // 2
max_dis_2  = min(im_shape_2) // 2

fps = int(cap1.get(5))
t   = int(1000 / fps)

# ---------------------------------------------------------
# 3. INSTANTIATE PIPELINES FOR EACH CAMERA
# ---------------------------------------------------------
# Camera 1 Modules
AIS1 = AISPRO(ais_path_shared, ais_file_1, im_shape_1, t)
VIS1 = VISPRO(anti, anti_rate, t)
FUS1 = FUSPRO(max_dis_1, im_shape_1, t)
DRA1 = DRAW(im_shape_1, t)

# Camera 2 Modules
AIS2 = AISPRO(ais_path_shared, ais_file_2, im_shape_2, t)
VIS2 = VISPRO(anti, anti_rate, t)
FUS2 = FUSPRO(max_dis_2, im_shape_2, t)
DRA2 = DRAW(im_shape_2, t)

show_size   = 500
videoWriter = None

bin_inf_1 = pd.DataFrame(columns=['ID', 'mmsi', 'timestamp', 'match'])
bin_inf_2 = pd.DataFrame(columns=['ID', 'mmsi', 'timestamp', 'match'])

times = 0; time_i = 0; sum_t = []

print(f'Start Time: {time0} || Stamp: {timestamp0} || fps: {fps}')

# ---------------------------------------------------------
# 4. SYNCHRONIZED PROCESSING LOOP
# ---------------------------------------------------------
while True:
    ret1, im1 = cap1.read()
    ret2, im2 = cap2.read()
    
    if not ret1 or im1 is None or not ret2 or im2 is None:
        break

    start = time.time()
    Time, timestamp, Time_name = update_time(Time, t)

    # --- Process Camera 1 ---
    AIS_vis_1, AIS_cur_1 = AIS1.process(cam_para_1, timestamp, Time_name)
    Vis_tra_1, Vis_cur_1 = VIS1.feedCap(im1, timestamp, AIS_vis_1, bin_inf_1)
    Fus_tra_1, bin_inf_1 = FUS1.fusion(AIS_vis_1, AIS_cur_1, Vis_tra_1, Vis_cur_1, timestamp)
    im1_drawn            = DRA1.draw_traj(im1, AIS_vis_1, AIS_cur_1, Vis_tra_1, Vis_cur_1, Fus_tra_1, timestamp)

    # --- Process Camera 2 ---
    AIS_vis_2, AIS_cur_2 = AIS2.process(cam_para_2, timestamp, Time_name)
    Vis_tra_2, Vis_cur_2 = VIS2.feedCap(im2, timestamp, AIS_vis_2, bin_inf_2)
    Fus_tra_2, bin_inf_2 = FUS2.fusion(AIS_vis_2, AIS_cur_2, Vis_tra_2, Vis_cur_2, timestamp)
    im2_drawn            = DRA2.draw_traj(im2, AIS_vis_2, AIS_cur_2, Vis_tra_2, Vis_cur_2, Fus_tra_2, timestamp)

    end     = time.time() - start
    time_i += end

    if timestamp % 1000 < t:
        gen_result(times, Vis_cur_1, Fus_tra_1, res_met_1, im_shape_1)
        gen_result(times, Vis_cur_2, Fus_tra_2, res_met_2, im_shape_2)
        times += 1
        sum_t.append(time_i)
        print(f'Time: {Time_name} | Stamp: {timestamp} | AIS1: {len(AIS_cur_1)} | AIS2: {len(AIS_cur_2)} | Proc: {time_i:.4f}s')
        time_i = 0

    # ---------------------------------------------------------
    # 5. STITCH AND RENDER
    # ---------------------------------------------------------
    res_1 = imutils.resize(im1_drawn, height=show_size)
    res_2 = imutils.resize(im2_drawn, height=show_size)
    combined_result = np.hstack((res_1, res_2))

    if videoWriter is None:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out_video_path = os.path.join(result_path, 'combined_dual_view.mp4')
        videoWriter = cv2.VideoWriter(out_video_path, fourcc, fps,
                                      (combined_result.shape[1], combined_result.shape[0]))
        
    videoWriter.write(combined_result)
    cv2.imshow('Dual Camera View', combined_result)
    
    # Press 'q' on your keyboard to stop the video early
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap1.release()
cap2.release()
if videoWriter:
    videoWriter.release()

# Add this line to close the video popup window when done!
cv2.destroyAllWindows()

print("Done! Check your result_dual folder.")