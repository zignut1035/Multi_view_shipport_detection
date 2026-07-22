#!/usr/bin/env python3
"""
Auto-detect the cam1/cam2 start-time offset for a Rotterdam session, so it
never has to be hand-typed into the fusion script again.

WHAT THIS DOES
  1. Finds cam1 and cam2's video files inside a session folder.
  2. Reads each camera's real fps.
  3. Grabs the first frame of each video.
  4. Crops the on-screen-display (OSD) clock overlay out of each frame
     (you tell it where that is, once -- see FIRST-TIME SETUP below).
  5. OCRs the crop with pytesseract and parses it into a wall-clock time.
  6. Works out which camera's video starts later, and by how much, so
     the main script knows which one to fast-forward and by how many
     frames.
  7. Writes everything into <session>/sync_offset.json so
     run_dual_sync_v4_rotterdam.py can just load it instead of using
     hardcoded constants.

FIRST-TIME SETUP (only once -- not per session, as long as the camera
provider doesn't change their overlay layout):

  Step 1 -- dump the first frames so you can see them:

      python3 detect_sync_offset_rotterdam.py --session <session_id> --show-frames

  This writes cam1_first_frame.jpg / cam2_first_frame.jpg into the
  session folder. Open them and note the pixel box (x, y, width,
  height) around the clock text for each camera.

  Step 2 -- run with those boxes to confirm the crop is right:

      python3 detect_sync_offset_rotterdam.py --session <session_id> \\
          --osd1 x,y,w,h --osd2 x,y,w,h --show-frames

  This also writes cam1_osd_crop.jpg / cam2_osd_crop.jpg -- check they
  actually show the clock digits and nothing else, adjust the box if not.

  Step 3 -- once the boxes look right, hardcode them below as
  DEFAULT_OSD_BOX_1 / DEFAULT_OSD_BOX_2, or just always pass --osd1/--osd2.

  Step 4 -- run for real (no --show-frames):

      python3 detect_sync_offset_rotterdam.py --session <session_id> \\
          --osd1 x,y,w,h --osd2 x,y,w,h

REQUIRES: pip install pytesseract --break-system-packages
          (and the tesseract-ocr binary: apt-get install tesseract-ocr)

NOTE: Rotterdam's cam1_KPN / cam2_kopvan feeds likely have a DIFFERENT
OSD overlay position/font than the Kanmon cameras did, since they're a
different provider -- don't reuse Kanmon's --osd1/--osd2 box values,
run the FIRST-TIME SETUP steps again for this camera pair.
"""
import argparse, glob, json, os, re, sys
from datetime import datetime, timezone

import cv2

# Fill these in once you've found the right crop box for each camera's
# OSD clock overlay (see FIRST-TIME SETUP above). Format: (x, y, w, h).
DEFAULT_OSD_BOX_1 = None  # e.g. (20, 20, 220, 40)
DEFAULT_OSD_BOX_2 = None  # e.g. (20, 20, 220, 40)

ROOT = "/mnt/d/rotterdam_data/sessions"


def find_video(session_dir, cam_folder):
    pattern = os.path.join(session_dir, cam_folder, "*.mp4")
    files = [f for f in glob.glob(pattern) if not f.endswith(".bak")]
    files.sort()
    if not files:
        raise FileNotFoundError(f"No video found in {os.path.join(session_dir, cam_folder)}")
    return files[0]


def get_first_frame_and_fps(video_path):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        raise RuntimeError(f"Could not read first frame of {video_path}")
    return frame, fps


def ocr_time_from_frame(frame, box, cam_label):
    try:
        import pytesseract
    except ImportError:
        raise RuntimeError(
            "pytesseract is required for OCR sync detection. "
            "Install with: pip install pytesseract --break-system-packages "
            "(and `sudo apt-get install tesseract-ocr` if the binary is missing)."
        )

    x, y, w, h = box
    crop = frame[y:y + h, x:x + w]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # Upscaling + thresholding tends to help OCR accuracy on small OSD text
    gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    text = pytesseract.image_to_string(thresh, config="--psm 7")
    match = re.search(r"(\d{1,2}):(\d{2}):(\d{2})", text)
    if not match:
        raise RuntimeError(
            f"[{cam_label}] Could not parse a HH:MM:SS time from OCR text: {text!r}. "
            f"Check that the OSD crop box actually frames the clock digits."
        )
    hh, mm, ss = (int(g) for g in match.groups())
    return hh, mm, ss, text.strip()


def parse_box(s):
    parts = [int(p) for p in s.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("Expected 4 comma-separated ints: x,y,w,h")
    return tuple(parts)


def main():
    ap = argparse.ArgumentParser(description="Auto-detect cam1/cam2 sync offset for a Rotterdam session.")
    ap.add_argument("--session", required=True, help="Session ID, e.g. 2026-05-27_15-35")
    ap.add_argument("--root", default=ROOT, help="Sessions root directory")
    ap.add_argument("--osd1", type=parse_box, default=DEFAULT_OSD_BOX_1,
                    help="cam1 OSD clock crop box as x,y,w,h")
    ap.add_argument("--osd2", type=parse_box, default=DEFAULT_OSD_BOX_2,
                    help="cam2 OSD clock crop box as x,y,w,h")
    ap.add_argument("--date", default=None,
                    help="Recording date as YYYY-MM-DD (defaults to the date in the session ID)")
    ap.add_argument("--show-frames", action="store_true",
                    help="Dump first-frame / OSD-crop JPGs for manual inspection, then exit without OCR")
    args = ap.parse_args()

    session_dir = os.path.join(args.root, args.session)
    if not os.path.isdir(session_dir):
        sys.exit(f"Session folder not found: {session_dir}")

    cam1_video = find_video(session_dir, "cam1_KPN")
    cam2_video = find_video(session_dir, "cam2_kopvan")

    frame1, fps1 = get_first_frame_and_fps(cam1_video)
    frame2, fps2 = get_first_frame_and_fps(cam2_video)

    cv2.imwrite(os.path.join(session_dir, "cam1_first_frame.jpg"), frame1)
    cv2.imwrite(os.path.join(session_dir, "cam2_first_frame.jpg"), frame2)

    if args.show_frames or not (args.osd1 and args.osd2):
        print(f"Wrote cam1_first_frame.jpg / cam2_first_frame.jpg to {session_dir}")
        print("Inspect them, find the pixel box around each OSD clock, then re-run with --osd1/--osd2.")
        if args.osd1 and args.osd2:
            for box, frame, label in ((args.osd1, frame1, "cam1"), (args.osd2, frame2, "cam2")):
                x, y, w, h = box
                crop = frame[y:y + h, x:x + w]
                out = os.path.join(session_dir, f"{label}_osd_crop.jpg")
                cv2.imwrite(out, crop)
                print(f"  wrote {out} -- check this actually shows the clock digits")
        return

    hh1, mm1, ss1, raw1 = ocr_time_from_frame(frame1, args.osd1, "cam1")
    hh2, mm2, ss2, raw2 = ocr_time_from_frame(frame2, args.osd2, "cam2")

    print(f"[OCR] cam1 OSD reads: {hh1:02d}:{mm1:02d}:{ss1:02d}  (raw: {raw1!r})")
    print(f"[OCR] cam2 OSD reads: {hh2:02d}:{mm2:02d}:{ss2:02d}  (raw: {raw2!r})")

    if args.date:
        y, m, d = (int(p) for p in args.date.split("-"))
    else:
        date_part = args.session.split("_")[0]
        y, m, d = (int(p) for p in date_part.split("-"))

    t1_seconds = hh1 * 3600 + mm1 * 60 + ss1
    t2_seconds = hh2 * 3600 + mm2 * 60 + ss2
    diff = t1_seconds - t2_seconds  # positive => cam1 is ahead of cam2

    if diff > 0:
        lead_cam, lead_seconds = "cam1", diff
        synced_hh, synced_mm, synced_ss = hh1, mm1, ss1
    elif diff < 0:
        lead_cam, lead_seconds = "cam2", -diff
        synced_hh, synced_mm, synced_ss = hh2, mm2, ss2
    else:
        lead_cam, lead_seconds = None, 0
        synced_hh, synced_mm, synced_ss = hh1, mm1, ss1

    result = {
        "session": args.session,
        "cam1_video": cam1_video,
        "cam2_video": cam2_video,
        "fps1": fps1,
        "fps2": fps2,
        "cam1_osd_time": f"{hh1:02d}:{mm1:02d}:{ss1:02d}",
        "cam2_osd_time": f"{hh2:02d}:{mm2:02d}:{ss2:02d}",
        "lead_camera": lead_cam,       # which camera's video FILE starts later in real time -> needs skipping
        "lead_seconds": lead_seconds,  # how many seconds of that camera to skip
        "synced_start_time": [y, m, d, synced_hh, synced_mm, synced_ss, 0],
        "detected_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    out_path = os.path.join(session_dir, "sync_offset.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\n[SYNC] {lead_cam or 'neither camera'} is ahead by {lead_seconds}s")
    print(f"[SYNC] synced_start_time = {result['synced_start_time']}")
    print(f"[SYNC] Wrote {out_path}")
    print("\nDouble-check cam1_osd_time / cam2_osd_time against the JPGs before trusting this blindly --")
    print("OCR on a burned-in clock can misread digits, especially at low resolution or with compression artifacts.")


if __name__ == "__main__":
    main()