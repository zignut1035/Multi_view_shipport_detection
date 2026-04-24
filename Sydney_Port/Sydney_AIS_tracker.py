import requests
import json
import time
import os
import argparse
from datetime import datetime, timezone

# ── CLI arguments ────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--interval", type=int, default=30, 
                    help="Seconds between AIS polls (default: 30)")
parser.add_argument("--duration", type=int, default=1800,
                    help="Total recording duration in seconds (default: 1800 = 30 mins)")
args = parser.parse_args()

# ── Configuration ────────────────────────────────────────────────
# >>> YOU MUST PASTE YOUR DATALASTIC API KEY HERE <<<
API_KEY = "YOUR_DATALASTIC_API_KEY_HERE"

# Bounding Box for Sydney Harbour Webcam View (Southern Hemisphere = Negative Latitudes)
MINLAT = -33.8650  # Bottom edge (South: Circular Quay)
MAXLAT = -33.8450  # Top edge (North: Near Kirribilli camera)
MINLON = 151.1950  # Left edge (West: Past the Harbour Bridge)
MAXLON = 151.2250  # Right edge (East: Past the Opera House)

# Convert Bounding Box into a closed Polygon string for Datalastic
COORDS = f"{MINLAT},{MINLON};{MAXLAT},{MINLON};{MAXLAT},{MAXLON};{MINLAT},{MAXLON};{MINLAT},{MINLON}"

OUTPUT_DIR = "ais_data_sydney"

# Datalastic Vessel in Polygon API endpoint
API_URL = "https://api.datalastic.com/api/v0/vessel_in_polygon"

os.makedirs(OUTPUT_DIR, exist_ok=True)

def fetch_ais_snapshot():
    # Retry Logic in case the server hiccups
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Datalastic passes parameters via the 'params' dictionary
            params = {
                "api-key": API_KEY,
                "coords": COORDS
            }
            
            response = requests.get(API_URL, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            # Datalastic places the list of vessels inside a "data" array
            vessels_list = data.get("data", [])
            
            if isinstance(vessels_list, list):
                results = []
                for v in vessels_list:
                    results.append({
                        "mmsi":        v.get("mmsi") or v.get("uuid"),
                        "name":        v.get("name", "Unknown"),
                        "type":        v.get("type"),
                        "lat":         v.get("lat"),
                        "lon":         v.get("lon"),
                        # Datalastic speed (sog) is already in knots, so we removed the /10.0 division that MarineTraffic needed
                        "speed":       v.get("sog"), 
                        "course":      v.get("cog"), 
                        "heading":     v.get("heading"),
                        "nav_stat":    v.get("navigational_status"),
                        "received_ts": v.get("last_position_epoch") 
                    })
                return results
            else:
                print(f"[AIS Sydney] Unexpected API format. Response: {str(data)[:100]}")
                return []

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            print(f"[AIS Sydney] Server slow. Retrying {attempt + 1}/{max_retries}...")
            time.sleep(2)
        except json.JSONDecodeError:
            print(f"[AIS Sydney] API did not return JSON. Check your API key and limits.")
            break
        except requests.exceptions.RequestException as e:
            # Show detailed Datalastic error if available (e.g., rate limits, bad API key)
            if e.response is not None:
                print(f"[AIS Sydney] Network Error: HTTP {e.response.status_code} - {e.response.text}")
            else:
                print(f"[AIS Sydney] Network Error: {e}")
            break 

    print("[AIS Sydney] Failed to fetch data after multiple attempts.")
    return []

def main():
    if API_KEY == "YOUR_DATALASTIC_API_KEY_HERE":
        print("[ERROR] Execution stopped: You forgot to paste your API Key in the script!")
        return

    start_time = time.time()
    poll_count = 0

    print(f"[AIS Sydney] Starting — polling Datalastic every {args.interval}s")
    print(f"[AIS Sydney] Area: Sydney Harbour Polygon")

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

        print(f"[AIS Sydney] Poll #{poll_count} | {len(vessels_found)} vessel(s) saved.")

        elapsed = time.time() - start_time
        remaining = args.duration - elapsed
        sleep_for = min(args.interval, remaining)
        if sleep_for > 0:
            time.sleep(sleep_for)

    print(f"[AIS Sydney] Finished. Saved to '{OUTPUT_DIR}' directory.")

if __name__ == "__main__":
    main()