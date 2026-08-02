import cv2

# Change this to whatever video you want to measure
video_path = "cam2_Helsinki_West.mp4" 
cap = cv2.VideoCapture(video_path)
ret, frame = cap.read()

def click_event(event, x, y, flags, params):
    if event == cv2.EVENT_LBUTTONDOWN:
        print(f"You clicked Pixel Coordinates: [{x}, {y}]")
        # Draw a red dot where you clicked so you don't lose track
        cv2.circle(frame, (x, y), 5, (0, 0, 255), -1)
        cv2.imshow('Image', frame)

cv2.imshow('Image', frame)
cv2.setMouseCallback('Image', click_event)
print("Click on 4 distinct landmarks. Press any key to close.")
cv2.waitKey(0)
cv2.destroyAllWindows()