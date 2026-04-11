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

API_KEY = "YOUR_MARINETRAFFIC_API_KEY_HERE"

# Bounding Box defined by your 4 exact landmarks
MINLAT = 33.9420  # Bottom edge (Furthest South: Mojiko Retro)
MAXLAT = 33.9680  # Top edge (Furthest North: Shimonoseki Bridge Pole)
MINLON = 130.9220 # Left edge (Furthest West: Kaikyo Yume Tower)
MAXLON = 130.9700 # Right edge (Furthest East: Moji Bridge Pole)

OUTPUT_DIR = "ais_data_kanmon"

# MarineTraffic Export Vessels API (PS04 - Custom Area)
API_URL = f"https://services.marinetraffic.com/api/exportvessels/v:8/{API_KEY}/MINLAT:{MINLAT}/MAXLAT:{MAXLAT}/MINLON:{MINLON}/MAXLON:{MAXLON}/protocol:jsono/msgtype:extended"

os.makedirs(OUTPUT_DIR, exist_ok=True)

def fetch_ais_snapshot():
    # Retry Logic in case the server hiccups
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # MarineTraffic puts parameters straight into the URL, so no `params=` dict is needed
            response = requests.get(API_URL, timeout=30)
            response.raise_for_status()
            
            # If the API key is bad, MT sometimes returns HTML or an error string.
            # json() will fail if it's not valid JSON.
            data = response.json()
            
            # MarineTraffic returns a direct list of objects when using protocol:jsono
            if isinstance(data, list):
                results = []
                for v in data:
                    results.append({
                        "mmsi":        v.get("MMSI"),
                        "name":        v.get("SHIPNAME", "Unknown"),
                        "type":        v.get("SHIPTYPE"),
                        "lat":         v.get("LAT"),
                        "lon":         v.get("LON"),
                        # Note: MarineTraffic speed is usually in 1/10 knots (e.g. 142 = 14.2 knots)
                        "speed":       v.get("SPEED"), 
                        "course":      v.get("COURSE"), 
                        "heading":     v.get("HEADING"),
                        "nav_stat":    v.get("STATUS"),
                        "received_ts": v.get("TIMESTAMP") # MT provides an ISO timestamp string
                    })
                return results
            else:
                print(f"[AIS] Unexpected API format. Response: {str(data)[:100]}")
                return []

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            print(f"[AIS] Server slow. Retrying {attempt + 1}/{max_retries}...")
            time.sleep(2)
        except json.JSONDecodeError:
            print(f"[AIS] API did not return JSON. Check your API key and limits.")
            break
        except requests.exceptions.RequestException as e:
            print(f"[AIS] Network Error: {e}")
            break 

    print("[AIS] Failed to fetch data after multiple attempts.")
    return []

def main():
    if API_KEY == "YOUR_MARINETRAFFIC_API_KEY_HERE":
        print("[ERROR] Execution stopped: You forgot to paste your API Key in the script!")
        return

    start_time = time.time()
    poll_count = 0

    print(f"[AIS] Starting — polling MarineTraffic every {args.interval}s")
    print(f"[AIS] Area: Kanmon Strait Bounding Box (Lat: {MINLAT} to {MAXLAT}, Lon: {MINLON} to {MAXLON})")

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