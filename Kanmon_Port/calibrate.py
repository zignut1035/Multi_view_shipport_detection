# calibrate_gcp.py
# Optimizes camera parameters so that GPS landmarks project onto
# their measured pixel positions.
#
# Run:  python3 calibrate_gcp.py
# Output: updated cam1_para.txt and cam2_para.txt

import numpy as np
from scipy.optimize import minimize
from math import radians, cos, sin, tan, atan2, degrees, atan
from geopy.distance import geodesic

# ── GROUND CONTROL POINTS ────────────────────────────────────────────────────
# (lon, lat) of each landmark
CAM1_GPS = np.array([
    (130.955369, 33.963322),
    (130.941378, 33.953036),
    (130.939064, 33.950069),
    (130.962311, 33.954869),
    (130.962061, 33.957167),
])

CAM2_GPS = np.array([
    (130.955369, 33.963322),
    (130.941378, 33.953036),
    (130.939064, 33.950069),
    (130.962311, 33.954869),
    (130.962061, 33.957167),
])

# Measured pixel positions for each landmark
CAM1_PX = np.float32([
    [512,  471],
    [1010, 655],
    [1609, 773],
    [1293, 487],
    [1093, 473],
])

CAM2_PX = np.float32([
    [1778, 564],
    [302,  576],
    [50,   583],
    [370,  745],
    [1660, 610],
])

# ── FIXED CAMERA PARAMETERS ───────────────────────────────────────────────────
CAM1_FIXED = {
    'lon_cam':    130.92971658421953,
    'lat_cam':    33.94999487880194,
    'height_cam': 143.0,
    'u0': 960.0, 'v0': 540.0,
}

CAM2_FIXED = {
    'lon_cam':    130.965136,
    'lat_cam':    33.954914,
    'height_cam': 30.0,
    'u0': 960.0, 'v0': 540.0,
}

# ── PROJECTION FUNCTION (matches AIS_utils.visual_transform) ─────────────────

def project(lon_v, lat_v, params, fixed):
    lon_cam    = fixed['lon_cam']
    lat_cam    = fixed['lat_cam']
    height_cam = fixed['height_cam']
    u0         = fixed['u0']
    v0         = fixed['v0']
    shoot_hdir, shoot_vdir, f_x, f_y = params

    D_abs = geodesic((lat_cam, lon_cam), (lat_v, lon_v)).m

    # bearing camera→target
    rLatA = radians(lat_cam); rLonA = radians(lon_cam)
    rLatB = radians(lat_v);   rLonB = radians(lon_v)
    dLon  = rLonB - rLonA
    y     = sin(dLon) * cos(rLatB)
    x     = cos(rLatA) * sin(rLatB) - sin(rLatA) * cos(rLatB) * cos(dLon)
    bearing = (degrees(atan2(y, x)) + 360) % 360

    Angle_hor = bearing - shoot_hdir
    if Angle_hor < -180: Angle_hor += 360
    if Angle_hor >  180: Angle_hor -= 360

    hor_rad = radians(Angle_hor)
    shv_rad = radians(-shoot_vdir)

    Z_w = D_abs * cos(hor_rad)
    X_w = D_abs * sin(hor_rad)
    Y_w = height_cam

    Z = Z_w / cos(shv_rad) + (Y_w - Z_w * tan(shv_rad)) * sin(shv_rad)
    X = X_w
    Y = (Y_w - Z_w * tan(shv_rad)) * cos(shv_rad)

    if Z <= 0:
        return None   # behind camera

    px = f_x * X / Z + u0
    py = f_y * Y / Z + v0
    return px, py


def reprojection_error(params, gps_pts, px_pts, fixed):
    total = 0.0
    for (lon_v, lat_v), (px, py) in zip(gps_pts, px_pts):
        proj = project(lon_v, lat_v, params, fixed)
        if proj is None:
            total += 1e6
            continue
        total += (proj[0] - px) ** 2 + (proj[1] - py) ** 2
    return total


# ── OPTIMIZE ──────────────────────────────────────────────────────────────────

def calibrate(name, gps_pts, px_pts, fixed, init_hdir, init_vdir,
              init_fx=1371.0, init_fy=1371.0):
    print(f"\n{'='*60}")
    print(f"Calibrating {name}")
    print(f"{'='*60}")

    x0 = [init_hdir, init_vdir, init_fx, init_fy]

    # Print initial error
    err0 = reprojection_error(x0, gps_pts, px_pts, fixed)
    print(f"Initial reprojection error : {err0:.1f} px²  "
          f"(RMS {(err0/len(gps_pts))**0.5:.1f} px per point)")

    result = minimize(
        reprojection_error,
        x0,
        args=(gps_pts, px_pts, fixed),
        method='Nelder-Mead',
        options={'maxiter': 50000, 'xatol': 0.01, 'fatol': 0.1}
    )

    params = result.x
    err1   = result.fun
    print(f"Final   reprojection error : {err1:.1f} px²  "
          f"(RMS {(err1/len(gps_pts))**0.5:.1f} px per point)")

    shoot_hdir, shoot_vdir, f_x, f_y = params
    print(f"\n  shoot_hdir : {shoot_hdir:.2f}°  (was {init_hdir}°)")
    print(f"  shoot_vdir : {shoot_vdir:.2f}°  (was {init_vdir}°)")
    print(f"  f_x        : {f_x:.1f} px  (was {init_fx:.1f})")
    print(f"  f_y        : {f_y:.1f} px  (was {init_fy:.1f})")

    # Per-point breakdown
    print(f"\n  Point-by-point reprojection:")
    for i, ((lon_v, lat_v), (px, py)) in enumerate(zip(gps_pts, px_pts)):
        proj = project(lon_v, lat_v, params, fixed)
        if proj:
            err = ((proj[0]-px)**2 + (proj[1]-py)**2) ** 0.5
            print(f"    [{i}] target ({px:.0f},{py:.0f})  "
                  f"projected ({proj[0]:.0f},{proj[1]:.0f})  "
                  f"error {err:.1f} px")
        else:
            print(f"    [{i}] BEHIND CAMERA")

    return params


cam1_params = calibrate(
    "CAM1 (Kaikyo Yume Tower)",
    CAM1_GPS, CAM1_PX, CAM1_FIXED,
    init_hdir=82, init_vdir=8,
)

cam2_params = calibrate(
    "CAM2 (Moji apartment)",
    CAM2_GPS, CAM2_PX, CAM2_FIXED,
    init_hdir=262, init_vdir=2,
)

# ── WRITE UPDATED .TXT FILES ──────────────────────────────────────────────────

def write_para(path, fixed, params):
    hdir, vdir, fx, fy = params
    line = (f"[{fixed['lon_cam']},{fixed['lat_cam']},"
            f"{hdir:.4f},{vdir:.4f},{fixed['height_cam']},"
            f"70,43,{fx:.2f},{fy:.2f},"
            f"{fixed['u0']:.1f},{fixed['v0']:.1f}]")
    with open(path, 'w') as f:
        f.write(line)
    print(f"\nWritten: {path}")
    print(f"  {line}")

write_para("/mnt/d/kanmon_temp/cam1_shimonoseki/cam1_para.txt", CAM1_FIXED, cam1_params)
write_para("/mnt/d/kanmon_temp/cam2_moji/cam2_para.txt",        CAM2_FIXED, cam2_params)

print("\nDone — re-run main_dual_fusion.py to see the updated projection.")