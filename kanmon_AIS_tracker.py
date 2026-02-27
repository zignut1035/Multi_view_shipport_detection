import requests
import json
import time
import os
import argparse
from datetime import datetime, timezone

# ── CLI arguments ────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--interval", type=int, default=10, # Changed default to 10s
                    help="Seconds between AIS polls (default: 10)")
parser.add_argument("--duration", type=int, default=600,
                    help="Total recording duration in seconds (default: 600 = 10 mins)")
args = parser.parse_args()

# ── Configuration ────────────────────────────────────────────────
# Kanmon Straits Bounding Box (Small box for efficiency)
MIN_LAT = 33.90
MAX_LAT = 34.00
MIN_LON = 130.85
MAX_LON = 131.05

API_KEY = "PASTE_YOUR_MYSHIPTRACKING_KEY_HERE"
OUTPUT_DIR = "ais_data_kanmon"

# MyShipTracking Vessels In Zone Endpoint
API_URL = "https://api.myshiptracking.com/v2/vessels-in-zone"

os.makedirs(OUTPUT_DIR, exist_ok=True)

def fetch_ais_snapshot():
    # MyShipTracking requires the key in the header
    headers = {
        "x-api-key": API_KEY
    }
    
    # Parameters for the area
    params = {
        "min_lat": MIN_LAT,
        "max_lat": MAX_LAT,
        "min_lng": MIN_LON,
        "max_lng": MAX_LON,
        "response": "simple" # Returns basic info like name, sog, cog, etc.
    }

    try:
        response = requests.get(API_URL, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        # Check if the API returned success and has data
        if data.get("status") == "success":
            vessels_list = data.get("data", [])
            
            results = []
            for v in vessels_list:
                results.append({
                    "mmsi":     v.get("mmsi"),
                    "name":     v.get("vessel_name", "Unknown"),
                    "lat":      v.get("lat"),
                    "lon":      v.get("lng"), # API uses 'lng'
                    "sog":      v.get("speed"),
                    "cog":      v.get("course"),
                    "heading":  v.get("heading"), # Note: some simple responses might omit this
                    "nav_stat": v.get("nav_status")
                })
            return results
        else:
            print(f"[AIS] API Error: {data.get('message')}")
            return []

    except requests.exceptions.RequestException as e:
        print(f"[AIS] Network Error: {e}")
        return []

def main():
    start_time = time.time()
    poll_count = 0

    print(f"[AIS] Starting — polling MyShipTracking every {args.interval}s for {args.duration}s")

    while (time.time() - start_time) < args.duration:
        poll_count += 1
        timestamp = datetime.now(timezone.utc)
        epoch = int(timestamp.timestamp())
        iso_ts = timestamp.strftime("%Y%m%dT%H%M%SZ")

        vessels_found = fetch_ais_snapshot()

        snapshot = {
            "timestamp_utc": timestamp.isoformat(),
            "epoch":         epoch,
            "poll_index":    poll_count,
            "vessel_count":  len(vessels_found),
            "vessels":       vessels_found,
        }

        out_path = os.path.join(OUTPUT_DIR, f"ais_{iso_ts}_epoch{epoch}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)

        print(f"[AIS] Poll #{poll_count} | {len(vessels_found)} vessel(s) found.")

        # Timing logic
        elapsed = time.time() - start_time
        remaining = args.duration - elapsed
        sleep_for = min(args.interval, remaining)
        if sleep_for > 0:
            time.sleep(sleep_for)

    print(f"[AIS] Finished. {poll_count} snapshots saved.")

if __name__ == "__main__":
    main()