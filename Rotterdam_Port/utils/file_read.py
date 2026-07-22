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

    # Previous runs' _detection/_tracking/_fusion files get renamed with a
    # timestamp suffix instead of deleted outright. These files are needed
    # by tools like find_track_id.py / camera_backproject.py after the
    # fact, and simply overwriting them on every re-run (even for a small
    # parameter tweak) silently destroys that history with no warning.
    for suffix in ('_detection', '_tracking', '_fusion'):
        p = result_metric[:-4] + suffix + result_metric[-4:]
        if os.path.exists(p):
            backup_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_p = f"{p[:-4]}_backup_{backup_tag}{p[-4:]}"
            os.rename(p, backup_p)
            print(f"[BACKUP] Previous {os.path.basename(p)} -> {os.path.basename(backup_p)}")

    # Extract start time from the epoch in the video filename.
    # This is REQUIRED to be correct -- it becomes this camera's Time1/Time2
    # seed, which every AIS lookup for this camera is anchored against for
    # the entire session. A silently wrong value here desyncs AIS matching
    # from frame 0 with no visible symptom other than "AIS: 0" or frozen
    # data -- so we fail loudly instead of guessing.
    epoch_match = re.search(r'_(\d{10})', video_path)
    if not epoch_match:
        raise ValueError(
            f"[ERROR] Could not find a 10-digit Unix epoch in the video "
            f"filename: {video_path}\n"
            f"This filename's real start time can't be determined, so it "
            f"can't be safely used to anchor AIS matching. Rename the file "
            f"to include its real recording epoch (e.g. "
            f"'..._1779896100.mp4') or fix the naming convention -- do not "
            f"guess a fallback date here, it will silently desync AIS."
        )
    epoch = int(epoch_match.group(1))
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    initial_time = [dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, 0]
    print(f"[TIME] {os.path.basename(video_path)} -> real start time (UTC): {dt}")

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
    # ais_path may not exist when using centralised JSON folder -- safe fallback
    try:
        ais_file = os.listdir(ais_path)
    except FileNotFoundError:
        ais_file = []
    timestamp0, time0 = time2stamp(initial_time)
    return ais_file, timestamp0, time0