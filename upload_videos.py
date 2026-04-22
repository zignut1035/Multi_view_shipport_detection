import os
import subprocess
from datetime import datetime

# --- CONFIGURATION ---
# The name of your rclone remote and bucket (from your rclone lsd command)
RCLONE_REMOTE = "allas:Treenut_videos"

# Your 3 target ports
PORTS = ['Kanmon', 'Rotterdam', 'Sydney']

def upload_video_to_allas(local_file_path, port_name):
    """Uploads a video to Allas by telling rclone to do the heavy lifting."""
    
    # 1. Validate the port
    if port_name not in PORTS:
        print(f"Error: '{port_name}' is not a recognized port.")
        return

    # 2. Check if file exists
    if not os.path.exists(local_file_path):
        print(f"Error: File {local_file_path} not found.")
        return

    file_name = os.path.basename(local_file_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 3. Create the exact target path for rclone
    # Example: allas:Treenut_videos/Sydney/20260422_164800_video.mp4
    target_path = f"{RCLONE_REMOTE}/{port_name}/{timestamp}_{file_name}"

    try:
        print(f"Uploading {file_name} via Rclone -> {target_path}...")
        
        # 4. Build the rclone command
        # 'copyto' allows us to copy the file AND rename it with the timestamp in one step
        command = [
            "rclone", 
            "copyto", 
            local_file_path, 
            target_path
        ]
        
        # 5. Execute the command
        # check=True forces Python to throw an error if rclone fails
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        
        print("✅ Upload complete!")
        
        # ---------------------------------------------------------
        # CLEANUP BLOCK (Executes ONLY if upload succeeds)
        # ---------------------------------------------------------
        try:
            os.remove(local_file_path)
            file_size = os.path.getsize(local_file_path) if os.path.exists(local_file_path) else 0
            print(f"🗑️ Deleted local file: {local_file_path}")
        except Exception as delete_error:
            pass # File is already deleted or couldn't be deleted
            
    except subprocess.CalledProcessError as e:
        # This catches any errors rclone throws (e.g. network drops)
        print(f"❌ Failed to upload. Rclone Error: {e.stderr}")

# --- TEST IT ---
if __name__ == "__main__":
    test_file = "test_sydney_video.mp4"
    
    # Create a dummy file
    with open(test_file, "wb") as f:
        f.write(os.urandom(1024 * 1024 * 5)) # 5MB dummy file
        
    upload_video_to_allas(test_file, 'Sydney')