import cv2
import numpy as np
# from ultralytics import YOLO  <-- Uncomment when you are ready to plug YOLO back in

# Choose which camera you want to process right now
current_camera = "cam1"
video_path = f"{current_camera}_Helsinki_West.mp4"
cap = cv2.VideoCapture(video_path)

# ==========================================
# 1. HOMOGRAPHY SETUP: CAMERA 1
# ==========================================
pts_video_cam1 = np.array([
    [929, 242],   # Left island
    [1235, 233],  # Right island
    [1818, 418],  # Right box
    [875, 284]    # Left box
], dtype=np.float32)

pts_gps_cam1 = np.array([
    [24.909489, 60.137234], # Matches Left island
    [24.896591, 60.128890], # Matches Right island
    [24.913033, 60.150590], # Matches Right box
    [24.915049, 60.149249]  # Matches Left box
], dtype=np.float32)

h_matrix_cam1, _ = cv2.findHomography(pts_video_cam1, pts_gps_cam1)

# ==========================================
# 2. HOMOGRAPHY SETUP: CAMERA 2
# ==========================================
pts_video_cam2 = np.array([
    [1128, 359],
    [1578, 202],
    [1917, 215],
    [1744, 243]
], dtype=np.float32)

pts_gps_cam2 = np.array([
    [24.916962, 60.150395],
    [24.909489, 60.137234],
    [24.913033, 60.150590],
    [24.914119, 60.149332]
], dtype=np.float32)

h_matrix_cam2, _ = cv2.findHomography(pts_video_cam2, pts_gps_cam2)

# Select the correct matrix based on the video we are playing
active_matrix = h_matrix_cam1 if current_camera == "cam1" else h_matrix_cam2

# ==========================================
# 3. MAIN TRACKING LOOP
# ==========================================
# model = YOLO('helsinki_best.pt') <-- Uncomment when ready

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    # We start by assuming we want to track the frame
    should_track = True 
    status_text = "STATUS: TRACKING"
    status_color = (0, 255, 0) # Green

    # --- CAMERA 1 LOGIC (Time Gated) ---
    if current_camera == "cam1":
        current_time_sec = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        cycle_position = current_time_sec % 30
        
        # If it is in the 20-second zoom out phase, turn off tracking
        if cycle_position >= 10:
            should_track = False
            status_text = "STATUS: IGNORING (ZOOM OUT/RESET)"
            status_color = (0, 0, 255) # Red
            
    # --- CAMERA 2 LOGIC (Continuous) ---
    # Because 'should_track' defaults to True, we actually don't need 
    # to write any extra code for Cam 2. It will just bypass the clock check!

    # ======================================
    # EXECUTE TRACKING BASED ON GATEKEEPER
    # ======================================
    if should_track:
        
        # --- DO YOLO DETECTION ---
        # results = model(frame)
        
        # --- DO HOMOGRAPHY GPS MATH ---
        mock_bottom_center_x = 1000
        mock_bottom_center_y = 300 
        
        point_to_transform = np.array([[[mock_bottom_center_x, mock_bottom_center_y]]], dtype=np.float32)
        gps_coords = cv2.perspectiveTransform(point_to_transform, active_matrix)
        
        estimated_lon = gps_coords[0][0][0]
        estimated_lat = gps_coords[0][0][1]

    # Draw the status text on the video
    cv2.putText(frame, status_text, (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, status_color, 2)

    cv2.imshow(f"Sensor Fusion Pipeline - {current_camera}", frame)
    
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()