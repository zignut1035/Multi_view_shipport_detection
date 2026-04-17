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
parser.add_argument("--duration", type=int, default=1200,
                    help="Total recording duration in seconds (default: 1200 = 20 mins)")
args = parser.parse_args()

# ── Configuration ────────────────────────────────────────────────
# Rotterdam Harbour Bounding Box
MIN_LAT = 51.9040
MAX_LAT = 51.9180
MIN_LON = 4.4820
MAX_LON = 4.4960

OUTPUT_DIR = "ais_data_rotterdam"

# Digitraffic API Endpoints
LOCATIONS_URL = "https://meri.digitraffic.fi/api/ais/v1/locations"
VESSELS_URL   = "https://meri.digitraffic.fi/api/ais/v1/vessels"

os.makedirs(OUTPUT_DIR, exist_ok=True)

def fetch_with_retry(url, retries=3):
    """Helper: Fetches a URL with a 30s timeout and 3 retry attempts."""
    for attempt in range(retries):
        try:
            # FIXED: Timeout increased from 10 to 30 seconds
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            print(f"[AIS] Timeout/Connection error. Retrying {attempt + 1}/{retries}...")
            time.sleep(2)
        except requests.exceptions.RequestException as e:
            print(f"[AIS] Error fetching {url}: {e}")
            return None
    print(f"[AIS] Failed to fetch {url} after {retries} attempts.")
    return None

def fetch_ais_snapshot():
    # 1. Fetch Locations
    locations_data = fetch_with_retry(LOCATIONS_URL)
    if not locations_data:
        return []
    
    locations = locations_data.get("features", [])

    # 2. Fetch Vessel Names (Metadata)
    # We try to get names, but if this fails, we still return the location data
    vessels_data = fetch_with_retry(VESSELS_URL)
    if vessels_data:
        vessels_map = {v["mmsi"]: v for v in vessels_data}
    else:
        vessels_map = {}

    results = []
    for feature in locations:
        coords = feature.get("geometry", {}).get("coordinates", [])
        if len(coords) != 2:
            continue
        lon, lat = coords
        
        # Filter: Only keep ships inside our Helsinki coordinates
        if MIN_LAT <= lat <= MAX_LAT and MIN_LON <= lon <= MAX_LON:
            mmsi        = feature.get("mmsi")
            props       = feature.get("properties", {})
            vessel_info = vessels_map.get(mmsi, {})
            
            results.append({
                "mmsi":     mmsi,
                "name":     vessel_info.get("name", "Unknown"),
                "lat":      lat,
                "lon":      lon,
                "sog":      props.get("sog"),
                "cog":      props.get("cog"),
                "heading":  props.get("heading"),
                "nav_stat": props.get("navStat"),
            })
    return results

def main():
    start_time = time.time()
    poll_count = 0

    print(f"[AIS] Starting — polling every {args.interval}s for {args.duration}s → ./{OUTPUT_DIR}/")

    while (time.time() - start_time) < args.duration:
        poll_count += 1
        timestamp = datetime.now(timezone.utc)
        epoch     = int(timestamp.timestamp())
        iso_ts    = timestamp.strftime("%Y%m%dT%H%M%SZ")

        print(f"[AIS] Poll #{poll_count} at {iso_ts}")
        
        vessels_found = fetch_ais_snapshot()

        snapshot = {
            "timestamp_utc":    timestamp.isoformat(),
            "epoch":            epoch,
            "poll_index":       poll_count,
            "vessel_count":     len(vessels_found),
            "vessels":          vessels_found,
        }

        out_path = os.path.join(OUTPUT_DIR, f"ais_{iso_ts}_epoch{epoch}.json")
        with open(out_path, "w") as f:
            json.dump(snapshot, f, indent=2)

        print(f"[AIS] {len(vessels_found)} vessel(s) → {out_path}")

        # Sleep logic
        elapsed   = time.time() - start_time
        remaining = args.duration - elapsed
        sleep_for = min(args.interval, remaining)
        if sleep_for > 0:
            time.sleep(sleep_for)

    print(f"[AIS] Done. {poll_count} snapshots saved.")

if __name__ == "__main__":
    main()
