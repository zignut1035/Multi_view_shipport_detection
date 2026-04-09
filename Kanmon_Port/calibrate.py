# save as: check_calibration.py

import cv2
import numpy as np
import math
from pyproj import Transformer

_t = Transformer.from_crs("epsg:4326", "epsg:32652", always_xy=True)

def to_utm(lon, lat):
    x, y = _t.transform(lon, lat)
    return (x, y)

def px_to_world(u, v, H):
    pt = np.float32([[[float(u), float(v)]]])
    result = cv2.perspectiveTransform(pt, H)
    return float(result[0][0][0]), float(result[0][0][1])

CAM1_GPS = [
    (130.955347, 33.963303),
    (130.961858, 33.959900),
    (130.961497, 33.948072),
    (130.939142, 33.950114),
    (130.941286, 33.952989),
]
CAM2_GPS = [
    (130.962308, 33.954875),
    (130.962164, 33.955994),
    (130.962042, 33.957208),
    (130.955425, 33.963311),
    (130.929742, 33.949850),
]

CAM1_WORLD = np.float64([to_utm(lon, lat) for lon, lat in CAM1_GPS])
CAM2_WORLD = np.float64([to_utm(lon, lat) for lon, lat in CAM2_GPS])

CAM1_PX = np.float32([
    [510, 466],
    [926, 468],
    [51714, 3518],
    [1606, 770],
    [1001, 626],
])
CAM2_PX = np.float32([
    [3660, 253],
    [1133, 701],
    [1650, 610],
    [1782, 561],
    [178, 533],
])

H1, mask1 = cv2.findHomography(CAM1_PX, CAM1_WORLD, cv2.RANSAC, 5.0)
H2, mask2 = cv2.findHomography(CAM2_PX, CAM2_WORLD, cv2.RANSAC, 5.0)

CAM1_NAMES = [
    "Shimonoseki bridge base",
    "Moji bridge base",
    "Mojiko Retro",
    "Breakwater right",
    "Ferris wheel",
]
CAM2_NAMES = [
    "Breakwater left",
    "Breakwater right",
    "Red roof building",
    "Shimonoseki bridge base",
    "Kaikyo Yume Tower",
]

print("\n[CAL] CAM1 landmark projection errors:")
for i, (px, gps, name) in enumerate(zip(CAM1_PX, CAM1_GPS, CAM1_NAMES)):
    wx, wy = px_to_world(px[0], px[1], H1)
    expected = to_utm(*gps)
    err = math.sqrt((wx - expected[0])**2 + (wy - expected[1])**2)
    status = "✓" if err < 50 else "✗ BAD"
    print(f"  pt{i} {name:<30} {err:6.1f} m  {status}")

print("\n[CAL] CAM2 landmark projection errors:")
for i, (px, gps, name) in enumerate(zip(CAM2_PX, CAM2_GPS, CAM2_NAMES)):
    wx, wy = px_to_world(px[0], px[1], H2)
    expected = to_utm(*gps)
    err = math.sqrt((wx - expected[0])**2 + (wy - expected[1])**2)
    status = "✓" if err < 50 else "✗ BAD"
    print(f"  pt{i} {name:<30} {err:6.1f} m  {status}")