import json
import glob
import os

def filter_west_terminal_by_date(folder_path, target_date):
    filtered_results = []
    
    # --- GEOFENCE COORDINATES (Helsinki West Terminal 1 & 2) ---
    # These coordinates cover the Jätkäsaari pier area
    LAT_MIN = 60.10
    LAT_MAX = 60.30  # Upper limit covers the quayside
    LON_MIN = 24.70
    LON_MAX = 25.30  # Covers both terminals
    
    # 1. Find all JSON files
    search_path = os.path.join(folder_path, '*.json')
    files = glob.glob(search_path)
    
    print(f"Scanning {len(files)} files for ships at West Terminal on {target_date}...")

    for file_path in files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 2. CHECK DATE FIRST
            # We assume timestamp_utc looks like "2026-02-19T..."
            timestamp = data.get('timestamp_utc', '')
            if not timestamp.startswith(target_date):
                continue # Skip this file if the date is wrong

            # 3. CHECK LOCATION FOR EACH SHIP
            vessels = data.get('vessels', [])
            
            for ship in vessels:
                try:
                    lat = float(ship.get('lat', 0))
                    lon = float(ship.get('lon', 0))
                    
                    # IS IT INSIDE THE BOX?
                    if (LAT_MIN <= lat <= LAT_MAX) and (LON_MIN <= lon <= LON_MAX):
                        
                        # Yes, it is at the West Terminal on the right day.
                        record = {
                            "timestamp_utc": timestamp,
                            "epoch": data.get('epoch'),
                            "ship_data": ship
                        }
                        filtered_results.append(record)
                        
                except (ValueError, TypeError):
                    continue # Skip if lat/lon are invalid or missing

        except (json.JSONDecodeError, OSError):
            print(f"Skipping unreadable file: {file_path}")
            continue

    return filtered_results

# --- CONFIGURATION ---
folder_name = 'ais_data'
target_date = '2026-02-17'  # <--- CHANGE DATE HERE IF NEEDED

# --- RUN FILTER ---
results = filter_west_terminal_by_date(folder_name, target_date)

# --- OUTPUT ---
print(f"Found {len(results)} records at Helsinki West Terminal.")

if results:
    output_filename = f'west_terminal_{target_date}.json'
    with open(output_filename, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)
    print(f"Saved results to '{output_filename}'")