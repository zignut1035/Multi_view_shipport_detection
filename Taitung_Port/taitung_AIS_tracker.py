import requests
import json
import time
import os
import argparse
from datetime import datetime, timezone

# ── CLI arguments ────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--interval", type=int, default=15, 
                    help="Seconds between AIS polls (default: 15)")
parser.add_argument("--duration", type=int, default=900,
                    help="Total recording duration in seconds (default: 900 = 15 mins)")
args = parser.parse_args()

# ── Configuration ────────────────────────────────────────────────
# Akashi Strait Bounding Box (Kobe / Awaji Island Area)
MIN_LAT = 34.5500
MAX_LAT = 34.6800
MIN_LON = 134.9500
MAX_LON = 135.1500

API_KEY = "y9@99Q87W33BZwR9lcdRAsv0a1WIFnu904"
OUTPUT_DIR = "ais_data_akashi"
API_URL = "https://api.myshiptracking.com/api/v2/vessel/zone"

os.makedirs(OUTPUT_DIR, exist_ok=True)

def fetch_ais_snapshot():
    headers = {"x-api-key": API_KEY}
    
    params = {
        "minlat": MIN_LAT, 
        "maxlat": MAX_LAT,  
        "minlon": MIN_LON,  
        "maxlon": MAX_LON,  
        "response": "simple" 
    }

    # Retry Logic
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.get(API_URL, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") == "success":
                vessels_list = data.get("data", [])
                
                results = []
                for v in vessels_list:
                    length = (v.get("size_a") or 0) + (v.get("size_b") or 0)
                    width  = (v.get("size_c") or 0) + (v.get("size_d") or 0)
                    v_type = v.get("vessel_type") or v.get("vtype")

                    results.append({
                        "mmsi":        v.get("mmsi"),
                        "name":        v.get("vessel_name", "Unknown"),
                        "type":        v_type,
                        "lat":         v.get("lat"),
                        "lon":         v.get("lng"),
                        "speed":       v.get("speed"),
                        "course":      v.get("course"),
                        "heading":     v.get("heading"),
                        "nav_stat":    v.get("nav_status"),
                        "received_ts": v.get("received"),
                        "length":      length,
                        "width":       width,
                        "destination": v.get("destination"),
                        "eta":         v.get("eta"),
                        "draught":     v.get("draught")
                    })
                return results
            else:
                print(f"[AIS] API Error: {data.get('message')}")
                return []

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.RequestException) as e:
            print(f"[AIS] Network/Server Error: {e}. Retrying {attempt + 1}/{max_retries}...")
            time.sleep(2)

    print("[AIS] Failed to fetch data after multiple attempts.")
    return []

def main():
    start_time = time.time()
    poll_count = 0

    print(f"[AIS] Starting — polling MyShipTracking every {args.interval}s")
    print(f"[AIS] Union Area: {MIN_LAT}-{MAX_LAT} N, {MIN_LON}-{MAX_LON} E")

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

        print(f"[AIS] Poll #{poll_count} | {len(vessels_found)} vessel(s) saved.")

        elapsed = time.time() - start_time
        remaining = args.duration - elapsed
        sleep_for = min(args.interval, remaining)
        if sleep_for > 0:
            time.sleep(sleep_for)

    print(f"[AIS] Finished. Saved to '{OUTPUT_DIR}' directory.")

if __name__ == "__main__":
    main()