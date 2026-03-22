import cv2
import os

# ── Configuration ────────────────────────────────────────────────
# Put the paths to your two videos here
VIDEO_PATHS = ["cam1_Helsinki_West.mp4", "cam2_Helsinki_West.mp4"] 

# Where the extracted images will be saved
OUTPUT_DIR = "yolo_training_frames" 

# How many frames to save per second of video. 
# 1 is usually a good starting point for YOLO to avoid redundant data.
FRAMES_PER_SECOND_TO_SAVE = 1  

def extract_frames(video_path, output_folder):
    # Extract the base name of the video (e.g., "video1" from "video1.mp4")
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    
    # Open the video file
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        print(f"Error: Could not open video {video_path}")
        return

    # Get the original video's frames per second (FPS)
    original_fps = round(cap.get(cv2.CAP_PROP_FPS))
    print(f"Processing '{video_name}' (Original FPS: {original_fps})")
    
    # Calculate how many frames to skip to achieve the desired output rate
    frame_interval = max(1, original_fps // FRAMES_PER_SECOND_TO_SAVE)
    
    frame_count = 0
    saved_count = 0
    
    while True:
        ret, frame = cap.read()
        
        # If no frame is returned, we've reached the end of the video
        if not ret:
            break
            
        # Only save the frame if it matches our interval
        if frame_count % frame_interval == 0:
            # Format: video1_frame_0000.jpg
            filename = f"{video_name}_frame_{saved_count:04d}.jpg"
            out_path = os.path.join(output_folder, filename)
            
            cv2.imwrite(out_path, frame)
            saved_count += 1
            
        frame_count += 1

    cap.release()
    print(f"  -> Extracted {saved_count} frames from {video_name}")

def main():
    # Create the output directory if it doesn't exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    for video in VIDEO_PATHS:
        if os.path.exists(video):
            extract_frames(video, OUTPUT_DIR)
        else:
            print(f"File not found: {video}")
            
    print(f"\nDone! All frames saved to the '{OUTPUT_DIR}' folder.")

if __name__ == "__main__":
    main()