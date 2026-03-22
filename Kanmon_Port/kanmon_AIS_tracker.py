import requests
import json
import time
import os
import argparse
from datetime import datetime, timezone

# ── CLI arguments ────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--interval", type=int, default=10, 
                    help="Seconds between AIS polls (default: 10)")
parser.add_argument("--duration", type=int, default=900,
                    help="Total recording duration in seconds (default: 900 = 15 mins)")
args = parser.parse_args()

# ── Configuration ────────────────────────────────────────────────
# >>> YOU MUST PASTE YOUR DATALASTIC TRIAL API KEY HERE <<<
API_KEY = "YOUR_DATALASTIC_API_KEY_HERE"

# Kanmon Straits Center Point for Datalastic's "vessel_inradius" API
CENTER_LAT = 33.9500
CENTER_LON = 130.9500
RADIUS_NM = 10 # 10 Nautical Miles covers the entire strait perfectly

OUTPUT_DIR = "ais_data_kanmon"
API_URL = "https://api.datalastic.com/api/v0/vessel_inradius"

os.makedirs(OUTPUT_DIR, exist_ok=True)

def fetch_ais_snapshot():
    # Datalastic passes the API key directly in the URL parameters
    params = {
        "api-key": API_KEY,
        "lat": CENTER_LAT, 
        "lon": CENTER_LON,  
        "radius": RADIUS_NM
    }

    # Retry Logic in case the server hiccups
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.get(API_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # Datalastic returns data inside {"data": {"vessels": [...]}}
            if "data" in data and "vessels" in data["data"]:
                vessels_list = data["data"]["vessels"]
                
                results = []
                for v in vessels_list:
                    results.append({
                        "mmsi":        v.get("mmsi"),
                        "name":        v.get("name", "Unknown"),
                        "type":        v.get("type"),
                        "lat":         v.get("lat"),
                        "lon":         v.get("lon"),
                        "speed":       v.get("sog"), # Speed Over Ground
                        "course":      v.get("cog"), # Course Over Ground
                        "heading":     v.get("heading"),
                        "nav_stat":    v.get("nav_status"),
                        "received_ts": v.get("last_position_epoch") # Epoch timestamp
                    })
                return results
            else:
                print(f"[AIS] Unexpected API format or no vessels found right now.")
                return []

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            print(f"[AIS] Server slow. Retrying {attempt + 1}/{max_retries}...")
            time.sleep(2)
        except requests.exceptions.RequestException as e:
            print(f"[AIS] Network Error: {e}")
            break 

    print("[AIS] Failed to fetch data after multiple attempts.")
    return []

def main():
    if API_KEY == "YOUR_DATALASTIC_API_KEY_HERE":
        print("[ERROR] Execution stopped: You forgot to paste your API Key in the script!")
        return

    start_time = time.time()
    poll_count = 0

    print(f"[AIS] Starting — polling Datalastic every {args.interval}s")
    print(f"[AIS] Area: Kanmon Strait ({CENTER_LAT} N, {CENTER_LON} E, Radius: {RADIUS_NM} NM)")

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