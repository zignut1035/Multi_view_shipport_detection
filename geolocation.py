import requests
import json
import time
import os
import argparse
from datetime import datetime, timezone

# ── CLI arguments ────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--interval", type=int, default=10,
                    help="Seconds between AIS polls (default: 30)")
parser.add_argument("--duration", type=int, default=600,
                    help="Total recording duration in seconds (default: 600 = 10 mins)")
args = parser.parse_args()

# ── Configuration ────────────────────────────────────────────────
MIN_LAT = 60.10
MAX_LAT = 60.30
MIN_LON = 24.70
MAX_LON = 25.30
OUTPUT_DIR       = "ais_data"

LOCATIONS_URL = "https://meri.digitraffic.fi/api/ais/v1/locations"
VESSELS_URL   = "https://meri.digitraffic.fi/api/ais/v1/vessels"

os.makedirs(OUTPUT_DIR, exist_ok=True)


def fetch_ais_snapshot():
    try:
        loc_resp = requests.get(LOCATIONS_URL, timeout=10)
        loc_resp.raise_for_status()
        locations = loc_resp.json().get("features", [])
    except requests.exceptions.RequestException as e:
        print(f"[AIS] Error fetching locations: {e}")
        return []

    try:
        ves_resp = requests.get(VESSELS_URL, timeout=10)
        ves_resp.raise_for_status()
        vessels = {v["mmsi"]: v for v in ves_resp.json()}
    except requests.exceptions.RequestException as e:
        print(f"[AIS] Error fetching vessels: {e}")
        vessels = {}

    results = []
    for feature in locations:
        coords = feature.get("geometry", {}).get("coordinates", [])
        if len(coords) != 2:
            continue
        lon, lat = coords
        if MIN_LAT <= lat <= MAX_LAT and MIN_LON <= lon <= MAX_LON:
            mmsi        = feature.get("mmsi")
            props       = feature.get("properties", {})
            vessel_info = vessels.get(mmsi, {})
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

        # Sleep until next poll, respecting total duration
        elapsed   = time.time() - start_time
        remaining = args.duration - elapsed
        sleep_for = min(args.interval, remaining)
        if sleep_for > 0:
            time.sleep(sleep_for)

    print(f"[AIS] Done. {poll_count} snapshots saved.")


if __name__ == "__main__":
    main()