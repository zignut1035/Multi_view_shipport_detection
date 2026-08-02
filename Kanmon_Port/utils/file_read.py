import os, time, glob, re, calendar
from datetime import datetime, timezone

def time2stamp(Time):
    name = "%d_%02d_%02d_%02d_%02d_%02d_%03d" % (
        Time[0], Time[1], Time[2], Time[3], Time[4], Time[5], Time[6])
    datetime_obj = datetime.strptime(name, "%Y_%m_%d_%H_%M_%S_%f")
    # calendar.timegm treats the tuple as UTC (unlike time.mktime which uses local tz)
    timeStamp = int(calendar.timegm(datetime_obj.timetuple()) * 1000.0
                    + datetime_obj.microsecond / 1000.0)
    return timeStamp, name

def update_time(Time, t):
    Time[6] = Time[6] + t
    if Time[6] >= 1000:
        Time[5] = Time[5] + 1
        Time[6] = Time[6] - 1000
        if Time[5] >= 60:
            Time[4] = Time[4] + 1
            Time[5] = Time[5] - 60
            if Time[4] >= 60:
                Time[3] = Time[3] + 1
                Time[4] = Time[4] - 60
    timeStamp, name = time2stamp(Time)
    return Time, timeStamp, name

def read_all(path, result_path):
    # 1. Clean the path just in case of hidden spaces or trailing slashes
    path = path.strip().rstrip('/')

    # 2. BULLETPROOF VIDEO SEARCH
    search_mp4 = os.path.join(path, '*.mp4')
    search_avi = os.path.join(path, '*.avi')
    video_list = glob.glob(search_mp4) + glob.glob(search_avi)
    
    if not video_list:
        raise FileNotFoundError(f"[ERROR] No .mp4 or .avi files found inside: {path}")
    
    video_path = video_list[0]
    v_p = re.split(r'[\.\-\_\\\\/]', video_path)

    ais_path = os.path.join(path, 'ais')
    os.makedirs(result_path, exist_ok=True)

    # Cleaned up result paths using os.path.join
    folder_name = os.path.basename(path)
    result_video  = os.path.join(result_path, 'video', f"{folder_name}.{v_p[-1]}")
    result_metric = os.path.join(result_path, 'metric', f"{folder_name}.txt")
    
    os.makedirs(os.path.join(result_path, 'video'), exist_ok=True)
    os.makedirs(os.path.join(result_path, 'metric'), exist_ok=True)

    for suffix in ('_detection', '_tracking', '_fusion'):
        p = result_metric[:-4] + suffix + result_metric[-4:]
        if os.path.exists(p):
            os.remove(p)

    # Extract start time from the epoch in the video filename
    epoch_match = re.search(r'_(\d{10})\.', video_path)
    if epoch_match:
        epoch = int(epoch_match.group(1))
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
        initial_time = [dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, 0]
    else:
        # fallback: hardcoded
        initial_time = [2026, 5, 22, 0, 28, 48, 0]

    # 3. BULLETPROOF TEXT FILE SEARCH
    search_txt = os.path.join(path, '*.txt')
    txt_list = glob.glob(search_txt)
    
    if not txt_list:
        raise FileNotFoundError(f"[ERROR] No camera calibration .txt file found inside: {path}")

    with open(txt_list[0], "r") as f:
        camera_para = f.readlines()[0][1:-2]
        camera_para = camera_para.split(',')
        camera_para = list(map(float, camera_para))

    return video_path, ais_path, result_video, result_metric, initial_time, camera_para

def ais_initial(ais_path, initial_time):
    # ais_path may not exist when using centralised JSON folder — safe fallback
    try:
        ais_file = os.listdir(ais_path)
    except FileNotFoundError:
        ais_file = []
    timestamp0, time0 = time2stamp(initial_time)
    return ais_file, timestamp0, time0