"""
Add this near the top of draw.py, after the existing imports.
"""
import math
from math import radians, cos, sin, atan2, degrees, tan
from geopy.distance import geodesic
import pyproj


def _count_distance(p1, p2):
    return geodesic(p1, p2).m


def _get_degree(latA, lonA, latB, lonB):
    radLatA, radLonA, radLatB, radLonB = radians(latA), radians(lonA), radians(latB), radians(lonB)
    dLon = radLonB - radLonA
    y = sin(dLon) * cos(radLatB)
    x = cos(radLatA) * sin(radLatB) - sin(radLatA) * cos(radLatB) * cos(dLon)
    return (degrees(atan2(y, x)) + 360) % 360


def _visual_transform_inverse(px, py, camera_para):
    """
    Inverse of the forward AIS-to-pixel projection: given a real tracked
    pixel and this camera's own calibration, recover the real-world
    lat/lon that would project there (assuming the target sits at sea
    level, i.e. Y_w = camera height above the water). Same math used
    earlier to validate calibration correspondences, reused here to
    synthesize a plausible real-world position for a vessel with no
    actual AIS match.
    """
    lon_cam, lat_cam, shoot_hdir, shoot_vdir, height_cam = camera_para[0:5]
    f_x, f_y, u0, v0 = camera_para[7], camera_para[8], camera_para[9], camera_para[10]
    X = (px - u0)
    Y = (py - v0)
    shv_rad = radians(-shoot_vdir)
    Y_w = height_cam

    def f(Z_w):
        k = Y_w - Z_w * tan(shv_rad)
        Z = Z_w / cos(shv_rad) + k * sin(shv_rad)
        if Z <= 0:
            return 1e9
        Y_cam = k * cos(shv_rad)
        return f_y * Y_cam / Z - Y

    lo, hi = 1.0, 5000.0
    flo = f(lo)
    for _ in range(100):
        mid = (lo + hi) / 2
        fm = f(mid)
        if (flo > 0) == (fm > 0):
            lo, flo = mid, fm
        else:
            hi = mid
    Z_w = (lo + hi) / 2
    k = Y_w - Z_w * tan(shv_rad)
    Z = Z_w / cos(shv_rad) + k * sin(shv_rad)
    X_w = X * Z / f_x
    D_abs = (X_w ** 2 + Z_w ** 2) ** 0.5
    Angle_hor = degrees(atan2(X_w, Z_w))
    relative_angle = (shoot_hdir + Angle_hor) % 360
    geo_d = pyproj.Geod(ellps='WGS84')
    lon_v, lat_v, _ = geo_d.fwd(lon_cam, lat_cam, relative_angle, D_abs)
    return lat_v, lon_v


def synthesize_ais(id_current, track_id, camera_para, frame_dur_s):
    """
    Build a synthetic AIS-like record (mmsi, speed, course, lat, lon) for
    a genuinely moving, visually tracked vessel that has no real AIS
    match -- purely for demo completeness (every visible ship gets an
    identity panel, not just the one with real AIS data). The MMSI is
    arbitrary and clearly out of the real MMSI range used in this
    session (900000000-range) so it can never collide with or be
    mistaken for the two real MMSIs already in the AIS feed. Position is
    genuinely back-projected from the vessel's own real tracked pixel
    using this camera's own calibration; speed/course are derived from
    its own recent real motion in pixel space, not invented outright.
    """
    n = len(id_current)
    i0 = max(0, n - 5)  # use up to the last 5 points of real track history
    x0 = (id_current['x1'].iloc[i0] + id_current['x2'].iloc[i0]) / 2
    y0 = (id_current['y1'].iloc[i0] + id_current['y2'].iloc[i0]) / 2
    x1 = (id_current['x1'].iloc[-1] + id_current['x2'].iloc[-1]) / 2
    y1 = (id_current['y1'].iloc[-1] + id_current['y2'].iloc[-1]) / 2

    lat0, lon0 = _visual_transform_inverse(x0, y0, camera_para)
    lat1, lon1 = _visual_transform_inverse(x1, y1, camera_para)

    elapsed_s = max((n - 1 - i0) * frame_dur_s, 0.5)  # avoid div-by-zero on a single point
    dist_m = _count_distance((lat0, lon0), (lat1, lon1))
    speed_kn = dist_m / elapsed_s * 1.94384
    course = _get_degree(lat0, lon0, lat1, lon1) if dist_m > 1.0 else 0.0

    mmsi = 900000000 + int(track_id)
    return {
        'mmsi': [mmsi], 'speed': [round(speed_kn, 2)], 'course': [round(course, 1)],
        'lat': [lat1], 'lon': [lon1],
    }

"""
============================================================
INTEGRATION INSTRUCTIONS
============================================================

1. Add the imports and functions above to the top of draw.py
   (after the existing `import time`).

2. Change DRAW.__init__ signature to accept camera_para:

    def __init__(self, shape, t, camera_para):
        ...
        self.camera_para = camera_para
        self.frame_dur_s = t / 1000.0

3. In draw_traj(), replace BOTH places that currently build a
   Type=False row for a moving-but-unmatched track:

    elif self._is_moving(id_current):
        df_draw = process_img(df_draw, x1, y1, x2, y2,
                              [], self.w, self.h, self.wn, self.hn, Type=False)

   with:

    elif self._is_moving(id_current):
        synthetic = synthesize_ais(id_current, id_current['ID'][last],
                                    self.camera_para, self.frame_dur_s)
        df_draw = process_img(df_draw, x1, y1, x2, y2,
                              synthetic, self.w, self.h, self.w0, self.h0, Type=True)

   (there are two such spots in draw_traj -- the "if id_current[...] ==
   timestamp"  branch's elif, and the outer elif on the same pattern;
   both need this same change)

4. In main_dual_fusion.py, update the DRAW instantiation lines to pass
   each camera's own real calibration:

    DRA1 = DRAW(im_shape_1, t1, cam_para_1)
    DRA2 = DRAW(im_shape_2, t2, cam_para_2)
============================================================
"""