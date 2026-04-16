import cv2
import numpy as np

# ==========================================
# 1. YOUR CURRENT MATRICES (Cam 1)
# ==========================================
pts_cam1 = np.array([[512, 471], [1010, 655], [1609, 773], [1293, 487], [1093, 473]], dtype='float32')
gps_targets = np.array([[130.955369, 33.963322], [130.941378, 33.953036], [130.939064, 33.950069], [130.962311, 33.954869], [130.962061, 33.957167]], dtype='float32')

# Calculate Homography and Inverse
H_cam1, status = cv2.findHomography(pts_cam1, gps_targets)
H_inv = np.linalg.inv(H_cam1)

# ==========================================
# 2. THE MATH TEST (Reprojection Error)
# ==========================================
print("=== CALIBRATION ERROR REPORT ===")
pts_cam1_reshaped = pts_cam1.reshape(-1, 1, 2)
calculated_gps = cv2.perspectiveTransform(pts_cam1_reshaped, H_cam1).reshape(-1, 2)

for i in range(len(gps_targets)):
    actual = gps_targets[i]
    calculated = calculated_gps[i]
    print(f"Point {i+1} Error: {abs(actual[0] - calculated[0]):.6f} lon, {abs(actual[1] - calculated[1]):.6f} lat")

# ==========================================
# 3. THE VISUAL TEST (Eye Test)
# ==========================================
# Load your video (Make sure this file is on your laptop!)
cap = cv2.VideoCapture('trimmed_cam1_shimonoseki_1775987824.mp4')
ret, frame = cap.read()

if ret:
    for gps in gps_targets:
        # Convert GPS back to pixels
        gps_pt = np.array([gps[0], gps[1], 1.0])
        pixel_pt = np.dot(H_inv, gps_pt)
        x, y = int(pixel_pt[0] / pixel_pt[2]), int(pixel_pt[1] / pixel_pt[2])
        
        # Draw a red dot where the math thinks the landmark is
        cv2.circle(frame, (x, y), 8, (0, 0, 255), -1)

    print("\nOpening image window... Press any key to close it.")
    cv2.imshow("Validation Check", frame)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
else:
    print("Could not read the video file. Check the file name and path!")