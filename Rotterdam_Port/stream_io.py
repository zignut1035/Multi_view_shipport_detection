"""
Example: Connect to aisstream.io WebSocket API to receive live AIS (ship) data.

Install dependency first:
    pip install websockets

Docs: https://aisstream.io/documentation
"""

import asyncio
import csv
import json
import os
from datetime import datetime, timezone
import websockets

API_KEY = ""  # <-- put your aisstream.io API key here

# Bounding box for the area you want to track ships in.
# Format: [[lat_min, lon_min], [lat_max, lon_max]]
#
# Below covers the Kop van Zuid district of Rotterdam, including the
# Nieuwe Maas river stretch around the Erasmusbrug and Wilhelminapier.
BOUNDING_BOXES = [[[51.892, 4.462], [51.918, 4.515]]]

# Optional: filter to specific ships by MMSI, or leave empty for all ships in the box
FILTER_MMSI = []  # e.g. ["368207620", "367719770"]

# Optional: filter message types (e.g. only position reports)
MESSAGE_TYPES = ["PositionReport"]  # other options: "ShipStaticData", etc.

# Only show/save vessels that are actually moving (speed strictly greater than this, in knots).
# Set to 0 (or a negative number) to include stationary vessels again.
MIN_SPEED_KNOTS = 0

# CSV file to append AIS data to
CSV_FILE = "ais_data.csv"
CSV_FIELDS = [
    "time_utc",
    "mmsi",
    "ship_name",
    "latitude",
    "longitude",
    "speed_knots",
    "course",
    "seconds_since_last_update",
]

# Tracks the last-seen timestamp for each vessel (keyed by MMSI), kept in memory
last_seen = {}

# Tracks every observed gap (in seconds) per vessel, plus its name, for the end-of-run summary
vessel_intervals = {}   # mmsi -> list of seconds_since_last_update values
vessel_names = {}       # mmsi -> most recently seen ship name


def parse_time_utc(time_utc: str):
    """Parse aisstream's time_utc string (e.g. '2024-01-01 12:00:00.000000000 +0000 UTC')."""
    try:
        # Trim to seconds precision and drop the trailing zone label for reliable parsing
        cleaned = time_utc.split(" +")[0].split(".")[0]
        return datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def ensure_csv_header():
    """Create the CSV file with a header row if it doesn't already exist."""
    file_exists = os.path.isfile(CSV_FILE)
    if not file_exists:
        with open(CSV_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()


def append_to_csv(row: dict):
    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writerow(row)


def print_summary():
    """Print average/min/max update interval per vessel, sorted by most frequent first."""
    if not vessel_intervals:
        print("\nNo update intervals recorded yet.")
        return

    print("\n" + "=" * 70)
    print("UPDATE FREQUENCY SUMMARY (per vessel)")
    print("=" * 70)
    print(f"{'Ship Name':<22}{'MMSI':<12}{'Avg (s)':<10}{'Min (s)':<10}{'Max (s)':<10}{'#Updates'}")
    print("-" * 70)

    summary_rows = []
    for mmsi, intervals in vessel_intervals.items():
        avg_gap = sum(intervals) / len(intervals)
        summary_rows.append((mmsi, avg_gap, min(intervals), max(intervals), len(intervals)))

    # Sort by average interval, most frequent (smallest gap) first
    summary_rows.sort(key=lambda r: r[1])

    for mmsi, avg_gap, min_gap, max_gap, count in summary_rows:
        name = vessel_names.get(mmsi, "Unknown") or "Unknown"
        print(f"{name:<22}{mmsi:<12}{avg_gap:<10.1f}{min_gap:<10.1f}{max_gap:<10.1f}{count}")

    print("=" * 70)


async def connect_ais_stream():
    url = "wss://stream.aisstream.io/v0/stream"
    reconnect_delay = 5  # seconds, doubles on repeated failures up to max_delay
    max_delay = 60

    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as websocket:
                subscribe_message = {
                    "APIKey": API_KEY,
                    "BoundingBoxes": BOUNDING_BOXES,
                    "FilterMessageTypes": MESSAGE_TYPES,
                }

                if FILTER_MMSI:
                    subscribe_message["FiltersShipMMSI"] = FILTER_MMSI

                await websocket.send(json.dumps(subscribe_message))
                print(f"Connected to {url}")
                reconnect_delay = 5  # reset backoff after a successful connection

                async for message_json in websocket:
                    message = json.loads(message_json)
                    message_type = message.get("MessageType")

                    if message_type == "PositionReport":
                        ais_message = message["Message"]["PositionReport"]
                        meta = message.get("MetaData", {})
                        mmsi = ais_message.get("UserID")
                        time_utc_str = meta.get("time_utc", "N/A")

                        # Work out how long it's been since we last heard from this vessel
                        current_time = parse_time_utc(time_utc_str)
                        seconds_since_last = None
                        if current_time is not None:
                            previous_time = last_seen.get(mmsi)
                            if previous_time is not None:
                                seconds_since_last = (current_time - previous_time).total_seconds()
                                vessel_intervals.setdefault(mmsi, []).append(seconds_since_last)
                            last_seen[mmsi] = current_time

                        ship_name = meta.get("ShipName", "Unknown").strip()
                        vessel_names[mmsi] = ship_name or vessel_names.get(mmsi, "Unknown")
                        speed = ais_message.get("Sog") or 0

                        # Skip stationary vessels if MIN_SPEED_KNOTS filter is active
                        if speed <= MIN_SPEED_KNOTS:
                            continue

                        row = {
                            "time_utc": time_utc_str,
                            "mmsi": mmsi,
                            "ship_name": ship_name,
                            "latitude": ais_message.get("Latitude"),
                            "longitude": ais_message.get("Longitude"),
                            "speed_knots": ais_message.get("Sog"),
                            "course": ais_message.get("Cog"),
                            "seconds_since_last_update": seconds_since_last,
                        }
                        append_to_csv(row)

                        gap_str = (
                            f"{seconds_since_last:.0f}s since last update"
                            if seconds_since_last is not None
                            else "first update seen"
                        )
                        print(
                            f"[{row['time_utc']}] "
                            f"Ship: {row['ship_name']} "
                            f"MMSI: {row['mmsi']} "
                            f"Lat/Lon: {row['latitude']}, {row['longitude']} "
                            f"Speed: {row['speed_knots']} knots "
                            f"({gap_str})"
                        )
                    else:
                        # Print other message types (e.g. ShipStaticData) as raw JSON
                        print(json.dumps(message, indent=2))

        except websockets.exceptions.ConnectionClosed as e:
            print(f"\nConnection closed ({e!r}). Reconnecting in {reconnect_delay}s...")
        except (OSError, asyncio.TimeoutError) as e:
            print(f"\nConnection error ({e!r}). Reconnecting in {reconnect_delay}s...")

        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, max_delay)


if __name__ == "__main__":
    ensure_csv_header()
    try:
        asyncio.run(connect_ais_stream())
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        print_summary()