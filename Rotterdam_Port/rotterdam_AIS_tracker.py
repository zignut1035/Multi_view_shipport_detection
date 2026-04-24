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
parser.add_argument("--duration", type=int, default=1800,
                    help="Total recording duration in seconds (default: 1800 = 30 mins)")
args = parser.parse_args()

# ── Configuration ────────────────────────────────────────────────
# >>> YOU MUST PASTE YOUR DATALASTIC API KEY HERE <<<
API_KEY = "YOUR_DATALASTIC_API_KEY_HERE"

# Rotterdam Harbour Bounding Box
MIN_LAT = 51.9040
MAX_LAT = 51.9180
MIN_LON = 4.4820
MAX_LON = 4.4960

# Convert Bounding Box into a closed Polygon string for Datalastic
COORDS = f"{MIN_LAT},{MIN_LON};{MAX_LAT},{MIN_LON};{MAX_LAT},{MAX_LON};{MIN_LAT},{MAX_LON};{MIN_LAT},{MIN_LON}"

OUTPUT_DIR = "ais_data_rotterdam"

# Datalastic Vessel in Polygon API endpoint
API_URL = "https://api.datalastic.com/api/v0/vessel_in_polygon"

os.makedirs(OUTPUT_DIR, exist_ok=True)

def fetch_ais_snapshot():
    """Fetches a single snapshot from Datalastic with a 3-retry limit."""
    max_retries = 3
    params = {
        "api-key": API_KEY,
        "coords": COORDS
    }
    
    for attempt in range(max_retries):
        try:
            response = requests.get(API_URL, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
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
                        "sog":         v.get("sog"), # Speed Over Ground
                        "cog":         v.get("cog"), # Course Over Ground
                        "heading":     v.get("heading"),
                        "nav_stat":    v.get("navigational_status"),
                        "received_ts": v.get("last_position_epoch")
                    })
                return results
            else:
                print(f"[AIS] Unexpected API format. Response: {str(data)[:100]}")
                return []

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            print(f"[AIS] Timeout/Connection error. Retrying {attempt + 1}/{max_retries}...")
            time.sleep(2)
        except json.JSONDecodeError:
            print(f"[AIS] API did not return JSON. Check your API key and limits.")
            break
        except requests.exceptions.RequestException as e:
            if e.response is not None:
                print(f"[AIS] Network Error: HTTP {e.response.status_code} - {e.response.text}")
            else:
                print(f"[AIS] Network Error: {e}")
            break 

    print(f"[AIS] Failed to fetch data after {max_retries} attempts.")
    return []

def main():
    if API_KEY == "YOUR_DATALASTIC_API_KEY_HERE":
        print("[ERROR] Execution stopped: You forgot to paste your API Key in the script!")
        return

    start_time = time.time()
    poll_count = 0

    print(f"[AIS] Starting Rotterdam Collection — polling every {args.interval}s for {args.duration}s")
    print(f"[AIS] Area: Rotterdam Bounding Box (Lat: {MIN_LAT} to {MAX_LAT}, Lon: {MIN_LON} to {MAX_LON})")

    while (time.time() - start_time) < args.duration:
        poll_count += 1
        timestamp = datetime.now(timezone.utc)
        epoch     = int(timestamp.timestamp())
        iso_ts    = timestamp.strftime("%Y%m%dT%H%M%SZ")

        print(f"[AIS] Poll #{poll_count} at {iso_ts}")
        
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

        print(f"[AIS] {len(vessels_found)} vessel(s) → {out_path}")

        # Sleep logic to maintain precise polling intervals
        elapsed   = time.time() - start_time
        remaining = args.duration - elapsed
        sleep_for = min(args.interval, remaining)
        if sleep_for > 0:
            time.sleep(sleep_for)

    print(f"[AIS] Done. {poll_count} snapshots saved to '{OUTPUT_DIR}'.")

if __name__ == "__main__":
    main()