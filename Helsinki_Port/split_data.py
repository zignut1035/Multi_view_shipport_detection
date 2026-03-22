import os
import random
import shutil

# Your current folder with everything mixed
source_folder = os.path.expanduser("~/multi_view/ships/Helsinki_Port/yolo_training_frames")
# The new folder YOLO will use for training
base_out = os.path.expanduser("~/multi_view/ships/Helsinki_Port/yolo_dataset")

# Create YOLO directories
dirs = ['images/train', 'images/val', 'labels/train', 'labels/val']
for d in dirs:
    os.makedirs(os.path.join(base_out, d), exist_ok=True)

# Get all images
images = [f for f in os.listdir(source_folder) if f.endswith('.jpg')]

# Shuffle and split (80% train, 20% val)
random.shuffle(images)
split_index = int(len(images) * 0.8)
train_images = images[:split_index]
val_images = images[split_index:]

def move_files(image_list, split_name):
    for img_name in image_list:
        # Copy image
        src_img = os.path.join(source_folder, img_name)
        dst_img = os.path.join(base_out, 'images', split_name, img_name)
        shutil.copy(src_img, dst_img)
        
        # Copy matching label
        txt_name = img_name.replace('.jpg', '.txt')
        src_txt = os.path.join(source_folder, txt_name)
        if os.path.exists(src_txt):
            dst_txt = os.path.join(base_out, 'labels', split_name, txt_name)
            shutil.copy(src_txt, dst_txt)

print(f"Copying {len(train_images)} files to train...")
move_files(train_images, 'train')

print(f"Copying {len(val_images)} files to val...")
move_files(val_images, 'val')

print("Done! Your YOLO dataset is ready.")