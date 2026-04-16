import cv2

# Load your video
video_path = 'trimmed_cam1_shimonoseki_1775987824.mp4'
cap = cv2.VideoCapture(video_path)
ret, frame = cap.read()

def click_event(event, x, y, flags, params):
    if event == cv2.EVENT_LBUTTONDOWN:
        print(f"[{x}, {y}],") # Prints in a format you can copy-paste
        cv2.circle(frame, (x, y), 5, (0, 255, 0), -1)
        cv2.imshow("Click Landmarks at Waterline", frame)

if ret:
    cv2.imshow("Click Landmarks at Waterline", frame)
    print("Click the landmarks at the WATERLINE in this order:")
    print("1. Bridge, 2. Wheel, 3. Shimonoseki Breakwater, 4. Moji Breakwater, 5. Red Roof")
    
    cv2.setMouseCallback("Click Landmarks at Waterline", click_event)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
else:
    print("Could not open video.")