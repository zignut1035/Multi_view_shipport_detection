import cv2
import os

# ── Configuration ────────────────────────────────────────────────
VIDEO_PATHS = ["Set2_cam1_shimonoseki.mp4", "Set2_cam2_moji.mp4"] 
OUTPUT_DIR = "yolo_training_frames" 
SECONDS_BETWEEN_FRAMES = 10  

def extract_frames(video_path, output_folder):
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        print(f"Error: Could not open video {video_path}")
        return

    original_fps = round(cap.get(cv2.CAP_PROP_FPS))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_interval = int(original_fps * SECONDS_BETWEEN_FRAMES)
    expected_images = total_frames // frame_interval if frame_interval > 0 else 0

    print(f"\n--- Processing '{video_name}' ---")
    print(f"Original FPS          : {original_fps}")
    print(f"Extraction Interval   : 1 frame every {SECONDS_BETWEEN_FRAMES} seconds (every {frame_interval} frames)")
    print(f"Expected Output       : ~{expected_images} images")
    
    frame_count = 0
    saved_count = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        if frame_count % frame_interval == 0:
            # Calculate the exact second in the video
            current_second = int(frame_count / original_fps)
            
            # Format: video1_sec_0000.jpg, video1_sec_0010.jpg
            filename = f"{video_name}_sec_{current_second:04d}.jpg"
            out_path = os.path.join(output_folder, filename)
            
            cv2.imwrite(out_path, frame)
            saved_count += 1
            
        frame_count += 1

    cap.release()
    print(f"  -> Extracted {saved_count} frames from {video_name}")

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for video in VIDEO_PATHS:
        if os.path.exists(video):
            extract_frames(video, OUTPUT_DIR)
        else:
            print(f"File not found: {video}")
            
    print(f"\nDone! All frames saved to the '{OUTPUT_DIR}' folder.")

if __name__ == "__main__":
    main()