import requests
import json
import time
import os
import argparse
from datetime import datetime, timezone

# ── Configuration ────────────────────────────────────────────────
# >>> YOU MUST PASTE YOUR DATALASTIC API KEY HERE <<<
API_KEY = ""

CENTER_LAT = 51.908490
CENTER_LON  = 4.485581
RADIUS      = 0.35  # nautical miles
 
OUTPUT_DIR = "ais_data_rotterdam"
API_URL    = "https://api.datalastic.com/api/v0/vessel_inradius"
 
os.makedirs(OUTPUT_DIR, exist_ok=True)
 
# ── AIS Fetch ─────────────────────────────────────────────────────
 
def fetch_ais_snapshot():
    # Retry logic in case the server hiccups
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Datalastic prefers parameters passed via the requests 'params' dictionary
            params = {
                "api-key": API_KEY,
                "lat":     CENTER_LAT,
                "lon":     CENTER_LON,
                "radius":  RADIUS,
            }
 
            response = requests.get(API_URL, params=params, timeout=30)
            response.raise_for_status()
 
            data = response.json()
 
            # The radius endpoint puts the list inside data -> vessels
            # We use an empty dict {} as a fallback to prevent NoneType errors
            vessels_list = data.get("data", {}).get("vessels", [])
 
            if isinstance(vessels_list, list):
                results = []
                for v in vessels_list:
                    results.append({
                        "mmsi":        v.get("mmsi") or v.get("uuid"),
                        "name":        v.get("name", "Unknown"),
                        "type":        v.get("type"),
                        "lat":         v.get("lat"),
                        "lon":         v.get("lon"),
                        "speed":        v.get("speed"),
                        "course":       v.get("course"),
                        "heading":     v.get("heading"),
                        "nav_stat":    v.get("navigational_status"),
                        "received_ts": v.get("last_position_epoch"),  # Epoch timestamp of the vessel update
                    })
                return results
            else:
                print(f"[AIS] Unexpected API format. Response: {str(data)[:100]}")
                return []
 
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            print(f"[AIS] Server slow. Retrying {attempt + 1}/{max_retries}...")
            time.sleep(2)
        except json.JSONDecodeError:
            print("[AIS] API did not return JSON. Check your API key and limits.")
            break
        except requests.exceptions.RequestException as e:
            # Special handling to show Datalastic API error messages if available
            if e.response is not None:
                print(f"[AIS] Network Error: HTTP {e.response.status_code} - {e.response.text}")
            else:
                print(f"[AIS] Network Error: {e}")
            break
 
    print("[AIS] Failed to fetch data after multiple attempts.")
    return []
 
# ── Main ──────────────────────────────────────────────────────────
 
def main():
    if API_KEY == "YOUR_DATALASTIC_API_KEY_HERE":
        print("[ERROR] Execution stopped: You forgot to paste your API Key in the script!")
        return
 
    # Setup argparse so command line arguments work
    parser = argparse.ArgumentParser(description="Fetch AIS data from Datalastic.")
    parser.add_argument("--interval", type=int, default=30,          help="Seconds to wait between API calls (default: 60)")
    parser.add_argument("--duration", type=int, default=900,        help="Total duration to run script in seconds (default: 1800)")
    parser.add_argument("--output",   type=str, default="ais_data_rotterdam", help="Folder to save JSON snapshots (default: ais_data_rotterdam)")
    args = parser.parse_args()
 
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)
 
    start_time = time.time()
    poll_count = 0
 
    print(f"[AIS] Starting — polling Datalastic every {args.interval}s")
    print(f"[AIS] Area: Rotterdam Port Radius (Center: {CENTER_LAT}, {CENTER_LON} | Radius: {RADIUS} NM)")
    print(f"[AIS] Saving to: {output_dir}")
 
    while (time.time() - start_time) < args.duration:
        poll_count += 1
        timestamp = datetime.now(timezone.utc)
        epoch     = int(timestamp.timestamp())
        iso_ts    = timestamp.strftime("%Y%m%dT%H%M%SZ")
 
        vessels_found = fetch_ais_snapshot()
 
        snapshot = {
            "timestamp_utc": timestamp.isoformat(),
            "epoch":         epoch,
            "poll_index":    poll_count,
            "vessel_count":  len(vessels_found),
            "vessels":       vessels_found,
        }
 
        out_path = os.path.join(output_dir, f"ais_{iso_ts}_epoch{epoch}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
 
        print(f"[AIS] Poll #{poll_count} | {len(vessels_found)} vessel(s) saved.")
 
        elapsed   = time.time() - start_time
        remaining = args.duration - elapsed
        sleep_for = min(args.interval, remaining)
        if sleep_for > 0:
            time.sleep(sleep_for)
 
    print(f"[AIS] Finished. Saved to '{output_dir}' directory.")
 
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAIS tracker stopped.", flush=True)