import os
import glob

folder = os.path.expanduser("~/multi_view/ships/Helsinki_Port/yolo_training_frames/")

def check_first_file(prefix):
    # Find the first txt file for this camera
    files = glob.glob(os.path.join(folder, f"{prefix}*.txt"))
    if not files:
        print(f"No text files found for {prefix}!")
        return
    
    first_file = sorted(files)[0]
    
    # Read what classes are inside
    class_counts = {0: 0, 1: 0}
    with open(first_file, 'r') as f:
        for line in f:
            class_id = int(line.split()[0])
            if class_id in class_counts:
                class_counts[class_id] += 1
                
    print(f"--- {prefix} File: {os.path.basename(first_file)} ---")
    print(f"Found {class_counts[0]} objects labeled '0'")
    print(f"Found {class_counts[1]} objects labeled '1'")
    print("")

check_first_file("cam1")
check_first_file("cam2")