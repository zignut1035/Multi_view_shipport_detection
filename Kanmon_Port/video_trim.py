#!/usr/bin/env python3

import sys
import os
import subprocess

def main():
    # 1. Check if the user provided the exact two arguments needed
    if len(sys.argv) != 3:
        print("❌ Error: Missing arguments.")
        print("💡 Usage: python trimmer.py <video_file.mp4> <start_time>")
        print("📝 Example: python trimmer.py camera3.mp4 00:01:15")
        sys.exit(1)

    input_file = sys.argv[1]
    start_time = sys.argv[2]
    output_file = f"trimmed_{input_file}"

    # 2. Check if the video file actually exists
    if not os.path.isfile(input_file):
        print(f"❌ Error: File '{input_file}' not found in this folder!")
        sys.exit(1)

    print(f"⏳ Fast-forwarding '{input_file}' to start at {start_time}...")

    # 3. Set up the exact FFmpeg command as a list
    command = [
        "ffmpeg",
        "-ss", start_time,
        "-i", input_file,
        "-c", "copy",
        output_file,
        "-y",                 # Overwrite existing files automatically
        "-loglevel", "warning" # Hide the massive block of FFmpeg text
    ]

    # 4. Run the command using subprocess
    try:
        subprocess.run(command, check=True)
        print(f"✅ Success! New video saved as: {output_file}")
    except subprocess.CalledProcessError:
        print("❌ Error: FFmpeg failed to process the video.")

if __name__ == "__main__":
    main()