import os
import random
import shutil

# --- Configuration ---
split_ratio = 0.8  # 80% for training, 20% for validation
base_out_dir = "yolo_dataset_final"

# Your exact current folders
sources = [
    {"imgs": "hirushi_frames", "lbls": "hirushi_labels", "name": "Set 1 (Dark)"},
    {"imgs": "treenut_frames", "lbls": "treenut_labels", "name": "Set 2 (Bright)"}
]

print("Starting Full Dataset Builder...")
print("-" * 50)

# --- 1. Create YOLO Directory Structure ---
dirs_to_make = [
    os.path.join(base_out_dir, "images", "train"),
    os.path.join(base_out_dir, "images", "val"),
    os.path.join(base_out_dir, "labels", "train"),
    os.path.join(base_out_dir, "labels", "val")
]

for d in dirs_to_make:
    os.makedirs(d, exist_ok=True)

print(f"Created base folder structure inside '{base_out_dir}/'")

total_train = 0
total_val = 0

# --- 2. Process Each Set ---
for source in sources:
    img_dir = source["imgs"]
    lbl_dir = source["lbls"]
    
    # Find all valid image/label pairs
    valid_pairs = []
    if os.path.exists(img_dir) and os.path.exists(lbl_dir):
        for img_file in os.listdir(img_dir):
            if img_file.endswith('.jpg'):
                base_name = os.path.splitext(img_file)[0]
                lbl_file = f"{base_name}.txt"
                if os.path.exists(os.path.join(lbl_dir, lbl_file)):
                    valid_pairs.append((img_file, lbl_file))
    
    print(f"\nFound {len(valid_pairs)} valid pairs in {source['name']}")
    
    # Shuffle for a truly random train/val split
    random.shuffle(valid_pairs)
    
    # Calculate split index
    split_index = int(len(valid_pairs) * split_ratio)
    train_pairs = valid_pairs[:split_index]
    val_pairs = valid_pairs[split_index:]
    
    def copy_files(pair_list, split_type):
        count = 0
        for img_file, lbl_file in pair_list:
            src_img = os.path.join(img_dir, img_file)
            src_lbl = os.path.join(lbl_dir, lbl_file)
            
            dst_img = os.path.join(base_out_dir, "images", split_type, img_file)
            dst_lbl = os.path.join(base_out_dir, "labels", split_type, lbl_file)
            
            shutil.copy(src_img, dst_img)
            shutil.copy(src_lbl, dst_lbl)
            count += 1
        return count

    train_count = copy_files(train_pairs, "train")
    val_count = copy_files(val_pairs, "val")
    
    total_train += train_count
    total_val += val_count
    
    print(f" -> Sent {train_count} to training.")
    print(f" -> Sent {val_count} to validation.")

print("-" * 50)
print(f"✅ Dataset structuring complete! Check the '{base_out_dir}' folder.")
print(f"Grand Total Training Images: {total_train}")
print(f"Grand Total Validation Images: {total_val}")