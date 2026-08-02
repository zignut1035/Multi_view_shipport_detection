"""
Example: Connect to aisstream.io WebSocket API to receive live AIS (ship) data.

This version saves every qualifying position update to a CSV file, counts
how many updates each ship sends (printed live + in a final summary), and
only keeps ships that fall inside TRACK_POLYGON (the real river shape),
even though the API subscription itself uses a wider rectangle.

Install dependency first:
    pip install websockets

Docs: https://aisstream.io/documentation
"""

import argparse
import asyncio
import csv
import json
import os
import time
from datetime import datetime, timezone
import websockets

API_KEY = "3bc41ba393f4d7e6b396b1912c291aaf46fd9ca9"  # <-- put your aisstream.io API key here

# Set True (or pass --debug on the command line) to print every raw message
# received and a periodic heartbeat, so you can tell the difference between
# "no data is arriving" and "the script is just sitting there".
DEBUG = False
HEARTBEAT_SECONDS = 10

# Tracks the last time (monotonic clock) we received ANY message, for the heartbeat
_last_message_time = None

# Bounding box for the AISStream *subscription*. This MUST be an axis-aligned
# rectangle (the API doesn't support arbitrary polygons), so it's the smallest
# rectangle that contains all 4 corners of TRACK_POLYGON below. It will include
# a bit of land on both riverbanks -- that's fine, because every incoming
# message is also checked against the tighter polygon further down before
# it's counted/printed.
# Format: [[lat_min, lon_min], [lat_max, lon_max]]
BOUNDING_BOXES = [[[51.900167045601776, 4.469956776065645], [51.91678085261953, 4.498532769928525]]]

# The actual area you care about: the river stretch around Kop van Zuid,
# Rotterdam, extended further north/east toward Erasmusbrug. Order matters --
# these should go around the shape (clockwise or counter-clockwise), not skip
# across it.
TRACK_POLYGON = [
    (51.91678085261953, 4.4920395843147265),   # upper corner (extended toward Erasmusbrug)
    (51.9123941749813, 4.498532769928525),     # upper corner (extended east)
    (51.900167045601776, 4.473634393385168),   # south corner
    (51.90262219299869, 4.469956776065645),    # southwest corner
]


def point_in_polygon(lat, lon, polygon):
    """Ray-casting point-in-polygon test. polygon is a list of (lat, lon) tuples."""
    if lat is None or lon is None:
        return False
    n = len(polygon)
    inside = False
    x, y = lon, lat
    x1, y1 = polygon[0][1], polygon[0][0]
    for i in range(1, n + 1):
        x2, y2 = polygon[i % n][1], polygon[i % n][0]
        if y > min(y1, y2):
            if y <= max(y1, y2):
                if x <= max(x1, x2):
                    if y1 != y2:
                        xinters = (y - y1) * (x2 - x1) / (y2 - y1) + x1
                    if x1 == x2 or x <= xinters:
                        inside = not inside
        x1, y1 = x2, y2
    return inside

# Optional: filter to specific ships by MMSI, or leave empty for all ships in the box
FILTER_MMSI = []  # e.g. ["368207620", "367719770"]

# Optional: filter message types (e.g. only position reports)
MESSAGE_TYPES = ["PositionReport"]  # other options: "ShipStaticData", etc.

# Only count vessels that are actually moving (speed strictly greater than this, in knots).
# Set to 0 (or a negative number) to include stationary vessels again.
MIN_SPEED_KNOTS = 0

# Default CSV filename. The folder portion gets overridden by the --output
# command-line argument when run from the bash orchestrator script.
CSV_FILE = "ais_data_rotterdam/ais_data.csv"
CSV_FIELDS = [
    "time_utc",
    "mmsi",
    "ship_name",
    "latitude",
    "longitude",
    "speed_knots",
    "course",
    "update_count",
]

# Tracks how many updates have been seen per vessel (keyed by MMSI)
update_counts = {}      # mmsi -> number of updates seen
vessel_names = {}       # mmsi -> most recently seen ship name
last_seen = {}          # mmsi -> last seen datetime (used only for live gap display)


def parse_time_utc(time_utc: str):
    """Parse aisstream's time_utc string (e.g. '2024-01-01 12:00:00.000000000 +0000 UTC')."""
    try:
        cleaned = time_utc.split(" +")[0].split(".")[0]
        return datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def ensure_csv_header():
    """Create the output folder (if needed) and CSV file with a header row if it doesn't exist."""
    output_folder = os.path.dirname(CSV_FILE)
    if output_folder:
        os.makedirs(output_folder, exist_ok=True)

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
    """Print total update count per vessel, sorted by most updates first."""
    if not update_counts:
        print("\nNo updates recorded yet.")
        return

    print("\n" + "=" * 55)
    print("UPDATE COUNT SUMMARY (per vessel)")
    print("=" * 55)
    print(f"{'Ship Name':<22}{'MMSI':<12}{'#Updates'}")
    print("-" * 55)

    summary_rows = sorted(
        update_counts.items(), key=lambda item: item[1], reverse=True
    )

    for mmsi, count in summary_rows:
        name = vessel_names.get(mmsi, "Unknown") or "Unknown"
        print(f"{name:<22}{mmsi:<12}{count}")

    print("=" * 55)


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
                    global _last_message_time
                    _last_message_time = time.monotonic()

                    message = json.loads(message_json)
                    message_type = message.get("MessageType")

                    if DEBUG:
                        print(f"[DEBUG] RAW MESSAGE TYPE: {message_type}")
                        print(f"[DEBUG] {json.dumps(message)[:500]}")

                    if message_type == "PositionReport":
                        ais_message = message["Message"]["PositionReport"]
                        meta = message.get("MetaData", {})
                        mmsi = ais_message.get("UserID")
                        time_utc_str = meta.get("time_utc", "N/A")

                        speed = ais_message.get("Sog") or 0
                        # Skip stationary vessels if MIN_SPEED_KNOTS filter is active
                        if speed <= MIN_SPEED_KNOTS:
                            continue

                        lat = ais_message.get("Latitude")
                        lon = ais_message.get("Longitude")
                        # Skip anything outside the real river polygon, even though
                        # it's inside the (larger) rectangular subscription box
                        if not point_in_polygon(lat, lon, TRACK_POLYGON):
                            continue

                        ship_name = meta.get("ShipName", "Unknown").strip()
                        vessel_names[mmsi] = ship_name or vessel_names.get(mmsi, "Unknown")

                        # Bump the running count for this ship
                        update_counts[mmsi] = update_counts.get(mmsi, 0) + 1

                        # Just for a nice live "Xs since last update" display
                        current_time = parse_time_utc(time_utc_str)
                        gap_str = "first update seen"
                        if current_time is not None:
                            previous_time = last_seen.get(mmsi)
                            if previous_time is not None:
                                gap = (current_time - previous_time).total_seconds()
                                gap_str = f"{gap:.0f}s since last update"
                            last_seen[mmsi] = current_time

                        row = {
                            "time_utc": time_utc_str,
                            "mmsi": mmsi,
                            "ship_name": ship_name,
                            "latitude": lat,
                            "longitude": lon,
                            "speed_knots": ais_message.get("Sog"),
                            "course": ais_message.get("Cog"),
                            "update_count": update_counts[mmsi],
                        }
                        append_to_csv(row)

                        print(
                            f"[{time_utc_str}] "
                            f"Ship: {ship_name} "
                            f"MMSI: {mmsi} "
                            f"Updates so far: {update_counts[mmsi]} "
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


async def heartbeat():
    """Periodically reassure the user the script is alive, even with zero traffic."""
    global _last_message_time
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        if _last_message_time is None:
            print(
                f"[HEARTBEAT] Still connected, but 0 messages received in the last "
                f"{HEARTBEAT_SECONDS}s. If this continues, check your API_KEY and "
                f"bounding box (no ships may be transmitting in that area right now)."
            )
        else:
            idle_for = time.monotonic() - _last_message_time
            print(f"[HEARTBEAT] Alive. Last message received {idle_for:.0f}s ago.")


async def run_with_duration(duration_seconds):
    """Run the stream indefinitely, or stop automatically after duration_seconds if given."""
    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        if duration_seconds:
            try:
                await asyncio.wait_for(connect_ais_stream(), timeout=duration_seconds)
            except asyncio.TimeoutError:
                print(f"\nReached configured duration ({duration_seconds}s). Stopping.")
        else:
            await connect_ais_stream()
    finally:
        heartbeat_task.cancel()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stream live AIS data from aisstream.io, save to CSV, and count updates per ship."
    )
    parser.add_argument(
        "--output", type=str, default=os.path.dirname(CSV_FILE) or ".",
        help="Folder to save the CSV file to (default: %(default)s)",
    )
    parser.add_argument(
        "--duration", type=int, default=None,
        help="Optional: stop automatically after this many seconds. "
             "If omitted, runs until stopped externally (Ctrl+C, or a wrapping `timeout` command).",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Print every raw message received from aisstream.io, to help diagnose why no data is showing up.",
    )
    args = parser.parse_args()

    if args.debug:
        DEBUG = True

    # Redirect the CSV output into whatever folder was passed in via --output
    CSV_FILE = os.path.join(args.output, os.path.basename(CSV_FILE))
    ensure_csv_header()

    try:
        asyncio.run(run_with_duration(args.duration))
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        print_summary()