"""
Diagnostic: why did AIS-to-vision fusion never produce a match?

Computes where visual_transform() places a vessel's real AIS lat/lon in a
camera's pixel space at a given moment, and compares that against every
tracked box in _tracking.txt at the corresponding frame -- reporting the
pixel distance to each. If the nearest tracked box is still far beyond
FUSPRO's max_dis threshold, that's strong evidence of a camera_para
calibration problem (wrong lat/lon, heading, tilt, height, or focal
length/principal point) rather than a timing or matching-logic issue.

This also serves as a standalone way to find which track ID corresponds
to a given vessel WITHOUT relying on a confirmed _fusion.txt bind --
useful when fusion never actually locked in.

Usage:
    python3 diagnose_fusion_mismatch.py \\
        cam2_kopvan_tracking.txt camera2.txt \\
        --width 1980 --height 1080 \\
        --init-time 2026-05-27T06:39:00 --frame-interval-s 1.0 \\
        --ais-lat 51.911785 --ais-lon 4.487980 --ais-time 2026-05-27T06:40:00
"""
import sys
import argparse
from math import radians, cos, sin, atan2, degrees
from geopy.distance import geodesic
import pandas as pd


def count_distance(point1, point2):
    return geodesic(point1, point2).m


def getDegree(latA, lonA, latB, lonB):
    radLatA, radLonA, radLatB, radLonB = radians(latA), radians(lonA), radians(latB), radians(lonB)
    dLon = radLonB - radLonA
    y = sin(dLon) * cos(radLatB)
    x = cos(radLatA) * sin(radLatB) - sin(radLatA) * cos(radLatB) * cos(dLon)
    return (degrees(atan2(y, x)) + 360) % 360


def visual_transform(lon_v, lat_v, camera_para):
    lon_cam, lat_cam, shoot_hdir, shoot_vdir, height_cam = camera_para[0:5]
    f_x, f_y, u0, v0 = camera_para[7], camera_para[8], camera_para[9], camera_para[10]
    from math import tan
    D_abs = count_distance((lat_cam, lon_cam), (lat_v, lon_v))
    relative_angle = getDegree(lat_cam, lon_cam, lat_v, lon_v)
    Angle_hor = relative_angle - shoot_hdir
    if Angle_hor < -180: Angle_hor += 360
    elif Angle_hor > 180: Angle_hor -= 360
    hor_rad = radians(Angle_hor)
    shv_rad = radians(-shoot_vdir)
    Z_w = D_abs * cos(hor_rad); X_w = D_abs * sin(hor_rad); Y_w = height_cam
    Z = Z_w / cos(shv_rad) + (Y_w - Z_w * tan(shv_rad)) * sin(shv_rad)
    X = X_w
    Y = (Y_w - Z_w * tan(shv_rad)) * cos(shv_rad)
    return int(f_x * X / Z + u0), int(f_y * Y / Z + v0), D_abs, relative_angle


def load_camera_para(txt_path):
    with open(txt_path, "r") as f:
        line = f.readlines()[0][1:-2]
    return list(map(float, line.split(",")))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tracking_csv")
    ap.add_argument("camera_para_txt")
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--height", type=int, required=True)
    ap.add_argument("--init-time", required=True)
    ap.add_argument("--frame-interval-s", type=float, required=True)
    ap.add_argument("--ais-lat", type=float, required=True)
    ap.add_argument("--ais-lon", type=float, required=True)
    ap.add_argument("--ais-time", required=True)
    ap.add_argument("--max-dis", type=float, default=300,
                     help="FUSPRO's max_dis for this camera, for reference (default 300)")
    args = ap.parse_args()

    camera_para = load_camera_para(args.camera_para_txt)
    init_ts = pd.Timestamp(args.init_time, tz="UTC")
    ais_ts = pd.Timestamp(args.ais_time, tz="UTC")

    target_frame = round((ais_ts - init_ts).total_seconds() / args.frame_interval_s)

    px, py, dist_m, bearing = visual_transform(args.ais_lon, args.ais_lat, camera_para)
    print(f"AIS position projects to pixel ({px}, {py}) in this camera's frame")
    print(f"  (real distance from camera: {dist_m:.0f}m, bearing: {bearing:.1f} deg,"
          f" camera heading: {camera_para[2]:.1f} deg)")
    if not (0 <= px <= args.width and 0 <= py <= args.height):
        print(f"  *** This pixel is OUTSIDE the {args.width}x{args.height} frame bounds. ***")
        print(f"      camera_para's lat/lon/heading/tilt/height/FOV/focal length for this")
        print(f"      camera is likely wrong, or the vessel genuinely isn't visible here.")
    print()

    tracking = pd.read_csv(args.tracking_csv, header=None,
                            names=["frame", "ID", "x", "y", "w", "h", "_a", "_b", "_c", "_d"])
    frame_rows = tracking[tracking["frame"] == target_frame].copy()

    if frame_rows.empty:
        nearby = tracking[(tracking["frame"] >= target_frame - 2) & (tracking["frame"] <= target_frame + 2)]
        print(f"No tracked boxes at frame {target_frame} (target time {args.ais_time}).")
        if not nearby.empty:
            print(f"Nearby frames that DO have boxes: {sorted(nearby['frame'].unique())}")
        sys.exit()

    frame_rows["cx"] = frame_rows["x"] + frame_rows["w"] / 2
    frame_rows["cy"] = frame_rows["y"] + frame_rows["h"] / 2
    frame_rows["dis_to_ais"] = ((frame_rows["cx"] - px) ** 2 + (frame_rows["cy"] - py) ** 2) ** 0.5

    print(f"Tracked boxes at frame {target_frame}, distance to AIS-projected pixel:")
    print(frame_rows[["ID", "cx", "cy", "dis_to_ais"]].sort_values("dis_to_ais").to_string(index=False))

    nearest = frame_rows.sort_values("dis_to_ais").iloc[0]
    print()
    if nearest["dis_to_ais"] <= args.max_dis:
        print(f"Nearest box (ID {int(nearest['ID'])}) IS within max_dis={args.max_dis}px "
              f"-- fusion should have matched this. If it didn't, check the heading/theta "
              f"gate in FUS_utils.py's cal_similarity(), not the distance gate.")
    else:
        print(f"Nearest box (ID {int(nearest['ID'])}) is {nearest['dis_to_ais']:.0f}px away, "
              f"beyond max_dis={args.max_dis}px -- this is why fusion never matched. "
              f"Check this camera's calibration .txt values (lat/lon/heading/tilt/height/"
              f"FOV/focal length/principal point).")