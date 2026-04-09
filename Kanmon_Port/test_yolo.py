"""
Standalone YOLO Detection Tester
Runs inference on a single video and outputs an MP4 with bounding boxes.
"""

import cv2
import argparse
from ultralytics import YOLO

def test_detection(video_path, model_path, output_path, conf_thresh, img_size):
    print(f"Loading model: {model_path}...")
    model = YOLO(model_path)
    
    print(f"Opening video: {video_path}...")
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open {video_path}")
        return

    # Set up the MP4 video writer
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, fps, (w, h))

    print(f"Starting inference (Conf: {conf_thresh}, Imgsz: {img_size})...")
    frame_count = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
                
            frame_count += 1
            
            # Run raw YOLO inference
            results = model.predict(frame, conf=conf_thresh, imgsz=img_size, verbose=False)
            
            # YOLO's built-in plotting (draws boxes, labels, and scores)
            annotated_frame = results[0].plot()
            
            # Add a diagnostic overlay at the top left
            cv2.putText(annotated_frame, f"Frame: {frame_count} | Conf: {conf_thresh} | Imgsz: {img_size}", 
                        (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
            
            out.write(annotated_frame)
            
            if frame_count % 100 == 0:
                print(f"Processed {frame_count} frames...", flush=True)

    except KeyboardInterrupt:
        print("\n[INFO] Stopped early by user.")

    finally:
        cap.release()
        out.release()
        print(f"\nDone! Processed {frame_count} frames.")
        print(f"Saved to: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # Defaulting to cam2 since that was the tricky side-view
    parser.add_argument("--video", default="FrontView.mp4", help="Path to video file")
    parser.add_argument("--model", default="/home/treenut/multi_view/ships/Kanmon_Port/kanmon_results/weights/best.pt", help="Path to YOLO weights")
    parser.add_argument("--out", default="test_detections.mp4", help="Output video name")
    parser.add_argument("--conf", type=float, default=0.15, help="Confidence threshold")
    parser.add_argument("--imgsz", type=int, default=1280, help="Image size for inference")
    
    args = parser.parse_args()
    
    test_detection(args.video, args.model, args.out, args.conf, args.imgsz)