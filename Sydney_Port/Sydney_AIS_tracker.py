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
# >>> YOU MUST PASTE YOUR MARINE TRAFFIC API KEY HERE <<<
API_KEY = ""

# Bounding Box for Sydney Harbour Webcam View (Southern Hemisphere = Negative Latitudes)
MINLAT = -33.8650  # Bottom edge (South: Circular Quay)
MAXLAT = -33.8450  # Top edge (North: Near Kirribilli camera)
MINLON = 151.1950  # Left edge (West: Past the Harbour Bridge)
MAXLON = 151.2250  # Right edge (East: Past the Opera House)

OUTPUT_DIR = "ais_data_sydney"

# MarineTraffic Export Vessels API (PS04 - Custom Area)
# Using protocol:jsono for nicely formatted JSON objects and msgtype:extended
API_URL = f"https://services.marinetraffic.com/api/exportvessels/v:8/{API_KEY}/MINLAT:{MINLAT}/MAXLAT:{MAXLAT}/MINLON:{MINLON}/MAXLON:{MAXLON}/protocol:jsono/msgtype:extended"

os.makedirs(OUTPUT_DIR, exist_ok=True)

def fetch_ais_snapshot():
    # Retry Logic in case the server hiccups
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # MarineTraffic puts parameters straight into the URL
            response = requests.get(API_URL, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            # MarineTraffic returns a direct list of objects when using protocol:jsono
            if isinstance(data, list):
                results = []
                for v in data:
                    results.append({
                        "mmsi":        v.get("MMSI"),
                        "name":        v.get("SHIPNAME", "Unknown"),
                        "type":        v.get("SHIPTYPE"),
                        "lat":         float(v.get("LAT")) if v.get("LAT") else None,
                        "lon":         float(v.get("LON")) if v.get("LON") else None,
                        # Fix: MarineTraffic speed is usually in 1/10 knots (e.g. 142 = 14.2 knots)
                        "speed":       float(v.get("SPEED", 0)) / 10.0 if v.get("SPEED") is not None else None, 
                        "course":      v.get("COURSE"), 
                        "heading":     v.get("HEADING"),
                        "nav_stat":    v.get("STATUS"),
                        "received_ts": v.get("TIMESTAMP") # MT provides an ISO timestamp string
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
            print(f"[AIS Sydney] Network Error: {e}")
            break 

    print("[AIS Sydney] Failed to fetch data after multiple attempts.")
    return []

def main():
    if API_KEY == "YOUR_MARINETRAFFIC_API_KEY_HERE":
        print("[ERROR] Execution stopped: You forgot to paste your API Key in the script!")
        return

    start_time = time.time()
    poll_count = 0

    print(f"[AIS Sydney] Starting — polling MarineTraffic every {args.interval}s")
    print(f"[AIS Sydney] Area: Sydney Harbour (Lat: {MINLAT} to {MAXLAT}, Lon: {MINLON} to {MAXLON})")

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