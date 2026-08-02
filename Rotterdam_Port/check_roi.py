"""
Pull a single frame from a video at a chosen timestamp and draw a
detect_roi rectangle on it, so you can visually confirm the ROI actually
covers where ships appear before committing to it in VISPRO(detect_roi=...).

Usage:
    python3 check_roi.py cam1_KPN_....mp4 --seek-ms 240000 \\
        --roi 0 210 854 460 --out roi_check.png

Try several --seek-ms values across the session (e.g. every 30-60s) if you
don't know exactly when a ship is visible -- cheaper than scrubbing the
whole video by hand, and each check only pulls one frame.
"""
import argparse
import cv2

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video_path")
    ap.add_argument("--seek-ms", type=float, required=True,
                     help="position to seek to, in milliseconds")
    ap.add_argument("--roi", type=int, nargs=4, metavar=("X1", "Y1", "X2", "Y2"),
                     required=True, help="detect_roi to draw: x1 y1 x2 y2")
    ap.add_argument("--out", default="roi_check.png")
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open {args.video_path}")

    cap.set(cv2.CAP_PROP_POS_MSEC, args.seek_ms)
    actual_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        raise RuntimeError(f"Could not read a frame at {args.seek_ms}ms "
                            f"(landed at {actual_ms}ms)")

    print(f"Requested {args.seek_ms}ms -> actually landed at {actual_ms}ms")
    print(f"Frame size: {frame.shape[1]}x{frame.shape[0]}")

    x1, y1, x2, y2 = args.roi
    annotated = frame.copy()
    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), 2)
    cv2.putText(annotated, f"detect_roi ({x1},{y1})-({x2},{y2})",
                (x1 + 5, max(y1 - 8, 15)), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (0, 0, 255), 2, cv2.LINE_AA)

    cv2.imwrite(args.out, annotated)
    print(f"Saved {args.out} -- open it and check whether any ships in "
          f"frame actually fall inside the red box.")