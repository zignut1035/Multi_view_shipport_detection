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
    video_path = glob.glob(path + '*.mp4') + glob.glob(path + '*.avi')
    video_path = video_path[0]
    v_p = re.split(r'[\.\-\_\\\\/]', video_path)

    ais_path = path + '/ais'
    os.makedirs(result_path, exist_ok=True)

    result_video  = result_path + 'video/'  + path.split('/')[-2] + '.' + v_p[-1]
    result_metric = result_path + 'metric/' + path.split('/')[-2] + '.txt'
    os.makedirs(result_path + 'video/',  exist_ok=True)
    os.makedirs(result_path + 'metric/', exist_ok=True)

    for suffix in ('_detection', '_tracking', '_fusion'):
        p = result_metric[:-4] + suffix + result_metric[-4:]
        if os.path.exists(p):
            os.remove(p)

    # Extract start time from the epoch in the video filename
    # e.g. cam1_shimonoseki_1779409728.mp4 → epoch 1779409728
    epoch_match = re.search(r'_(\d{10})\.', video_path)
    if epoch_match:
        epoch = int(epoch_match.group(1))
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
        initial_time = [dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, 0]
    else:
        # fallback: hardcoded (edit if your session time changes)
        initial_time = [2026, 5, 22, 0, 28, 48, 0]   # epoch 1779409728 → 00:28:48 UTC

    with open(glob.glob(path + '/*.txt')[0], "r") as f:
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