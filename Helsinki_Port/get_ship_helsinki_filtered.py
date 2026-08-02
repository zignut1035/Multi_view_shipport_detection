import os
import json
import glob

# ── Configuration ────────────────────────────────────────────────
INPUT_DIR = "ais_data_helsinki" 
OUTPUT_FILE = "filtered_mystar_finlandia.json"

# Target Ships (Checking both MMSI and Name just to be completely safe)
TARGET_MMSIS = [230628000, 276859000]
TARGET_NAMES = ["FINLANDIA", "MYSTAR"]

def main():
    if not os.path.exists(INPUT_DIR):
        print(f"Error: Directory '{INPUT_DIR}' not found. Are you in the right folder?")
        return

    # Find all JSON files in the input directory
    file_pattern = os.path.join(INPUT_DIR, "*.json")
    json_files = glob.glob(file_pattern)
    
    if not json_files:
        print(f"No JSON files found in {INPUT_DIR}.")
        return

    print(f"Found {len(json_files)} files. Filtering specifically for MyStar and Finlandia...")
    
    filtered_records = []
    files_processed = 0

    for filepath in json_files:
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            files_processed += 1
            
            # Extract ONLY the two specific ferries
            for vessel in data.get("vessels", []):
                mmsi = vessel.get("mmsi")
                # Clean up the name string just in case there are trailing spaces
                name = vessel.get("name", "").strip().upper() 
                
                if (mmsi in TARGET_MMSIS) or (name in TARGET_NAMES):
                    # Flatten the data for easy plotting later
                    vessel_record = vessel.copy()
                    vessel_record["timestamp"] = data.get("timestamp_utc", "")
                    filtered_records.append(vessel_record)
                        
        except Exception as e:
            print(f"Error processing {filepath}: {e}")

    # Save the filtered results to a new file
    with open(OUTPUT_FILE, 'w') as out_f:
        json.dump(filtered_records, out_f, indent=2)

    print("\n--- Filtering Complete ---")
    print(f"Files processed: {files_processed}")
    print(f"Total track points found for MyStar/Finlandia: {len(filtered_records)}")
    print(f"Saved compiled data to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()