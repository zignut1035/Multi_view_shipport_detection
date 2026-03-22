import cv2
from ultralytics import YOLO

# Load your model
model = YOLO('helsinki_best.pt')

# Open both camera streams
cap1 = cv2.VideoCapture('cam1_Helsinki_West.mp4')
cap2 = cv2.VideoCapture('cam2_Helsinki_West.mp4')

# Settings for the output video
frame_width, frame_height = 640, 360
skip_rate = 20 
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
out = cv2.VideoWriter('stable_tracking_output.mp4', fourcc, 30, (frame_width * 2, frame_height))

print("Processing with BoT-SORT Tracking (IoU enabled)...")

frame_count = 0
while cap1.isOpened() and cap2.isOpened():
    success1, frame1 = cap1.read()
    success2, frame2 = cap2.read()

    if not success1 or not success2:
        break

    if frame_count % skip_rate == 0:
        # Resize for faster processing on your laptop
        f1_s = cv2.resize(frame1, (frame_width, frame_height))
        f2_s = cv2.resize(frame2, (frame_width, frame_height))

        # --- THE TRACKING STEP ---
        # persist=True: Keeps the ID across frames
        res1 = model.track(f1_s, persist=True, imgsz=640, verbose=False, tracker="bytetrack.yaml")
        res2 = model.track(f2_s, persist=True, imgsz=640, verbose=False, tracker="bytetrack.yaml")

        # Draw the tracking boxes (includes IDs)
        ann1 = res1[0].plot()
        ann2 = res2[0].plot()

        # Combine frames side-by-side
        combined = cv2.hconcat([ann1, ann2])
        out.write(combined)
        
        print(f"Frame {frame_count} processed...", end="\r")

    frame_count += 1

cap1.release()
cap2.release()
out.release()
print("\nDone! Open 'stable_tracking_output.mp4' to see the stable boxes.")