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
    (4.489953, 51.908383), #first bridgewater
    (4.489269, 51.908706), #second bridgewater
    (4.487450, 51.909081), #bottom nylon poll
    (4.487636, 51.908778), #top nylon poll
    (4.480656, 51.911306), #right grey building
    (4.481078, 51.907614), #left white boat
    (4.474322, 51.905897), #left white grey building
    (4.489322, 51.907231), #left close building
])

CAM2_GPS = np.array([
    (4.489269, 51.908706), #second bridgewater
    (4.487450, 51.909081), #bottom nylon poll
    (4.487636, 51.908778), #top nylon poll
    (4.488147, 51.909942), #left land
    (4.483858, 51.910925), #left corner at bridge
    (4.483653, 51.909875), #parking ship right of bridge
    (4.482533, 51.909569), #corner of right close building
    (4.488186, 51.906664), #opposite 3 building in the middle
    (4.484689, 51.904872), #tall building on the far right
])

# Measured pixel positions for each landmark
CAM1_PX = np.float32([
    [688,  442],
    [755, 400],
    [751, 329],
    [700, 112],
    [823, 245],
    [521,255],
    [448,227],
    [370,352],
])

CAM2_PX = np.float32([
    [290, 610],
    [415,  650],
    [490,   155],
    [20,  662],
    [320, 1020],
    [1130, 826],
    [1736, 726],
    [896, 504],
    [1643, 537],
])

# ── FIXED CAMERA PARAMETERS ───────────────────────────────────────────────────
CAM1_FIXED = {
    'lon_cam': 4.493216,   # Longitude for KPN Tower (Wilhelminaplein)
    'lat_cam': 51.909200,  # Latitude for KPN Tower (Wilhelminaplein)
    'height_cam': 96.5,    # Roof height in meters (adjust if camera is mounted lower)
    'u0': 427.0,           # Optical center X (half of 854px)
    'v0': 240.0            # Optical center Y (half of 480px)
}

CAM2_FIXED = {
    'lon_cam':    4.483,
    'lat_cam':    51.911,
    'height_cam': 30.0,
    'u0': 960.0, 
    'v0': 540.0,
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
    "CAM1 (KPN)",
    CAM1_GPS, CAM1_PX, CAM1_FIXED,
    init_hdir=82, init_vdir=8,
)

cam2_params = calibrate(
    "CAM2 (KOPVAN)",
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

write_para("/mnt/d/rotterdam_data/cam1_kpn/cam1_para.txt", CAM1_FIXED, cam1_params)
write_para("/mnt/d/rotterdam_data/cam2_kopvan/cam2_para.txt",        CAM2_FIXED, cam2_params)

print("\nDone — re-run main_dual_fusion.py to see the updated projection.")