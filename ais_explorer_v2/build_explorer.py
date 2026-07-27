"""
AIS Trajectory Explorer v2 — adds an "All vessels" overview mode.

Sidebar:
  Session dropdown
  Mode dropdown: [All vessels] or [Single vessel]
  In single-vessel mode: vessel dropdown + ping table (as before)
  In all-vessels mode: vessel list (color swatch, name, MMSI, ping count, type)
                       hovering highlights the track on the map
                       clicking a row switches to single-vessel mode for that MMSI
Map:
  All vessels mode → every vessel's trajectory + every ping marker
  Single vessel mode → focused on one MMSI with start/end markers and ping popups

Data sources supported (both can exist in the same session's "ais" folder):
  - *.json  → Datalastic-style snapshots: {"epoch": ..., "vessels": [{"mmsi", "lat", "lon", ...}]}
  - *.csv   → AISStream.io output: one row per ping, columns
              time_utc, mmsi, ship_name, latitude, longitude, speed_knots, course,
              seconds_since_last_update
"""
import csv
import json
import os
import glob
import hashlib
from collections import defaultdict
from datetime import datetime, timezone

ROOT = "/mnt/d/rotterdam_data/sessions"
OUT_DIR = "."
os.makedirs(OUT_DIR, exist_ok=True)


def color_for(mmsi):
    h = hashlib.md5(mmsi.encode()).hexdigest()
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if r + g + b > 600: r, g, b = r // 2, g // 2, b // 2
    if r + g + b < 200: r, g, b = min(r+80,255), min(g+80,255), min(b+80,255)
    return f"#{r:02x}{g:02x}{b:02x}"


def fmt_dt(epoch):
    if not epoch: return ""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def parse_csv_time_to_epoch(time_utc_str):
    """Parse AISStream's 'time_utc' string (e.g. '2026-07-26 11:24:01.085605936 +0000 UTC') to epoch seconds."""
    if not time_utc_str:
        return None
    try:
        cleaned = time_utc_str.split(" +")[0].split(".")[0]
        dt = datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, AttributeError):
        return None


def load_json_snapshot(fp, vessels):
    """Load one Datalastic-style JSON snapshot file into the shared vessels dict."""
    src = os.path.basename(fp)
    try:
        d = json.load(open(fp))
    except Exception:
        return 0

    ep = d.get("epoch")
    n_points = 0
    for v in d.get("vessels", []):
        mmsi = str(v.get("mmsi", ""))
        if not mmsi: continue
        lat, lon = v.get("lat"), v.get("lon")
        if lat is None or lon is None: continue
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180): continue

        if vessels[mmsi]["name"] is None:
            vessels[mmsi]["name"] = v.get("name") or "Unknown"
            vessels[mmsi]["type"] = v.get("type") or "Unknown"

        vessels[mmsi]["points"].append({
            "epoch": ep, "dt": fmt_dt(ep),
            "lat": lat, "lon": lon,
            "speed": v.get("speed"), "course": v.get("course"),
            "heading": v.get("heading"), "nav_stat": v.get("nav_stat"),
            "received_ts": v.get("received_ts"),
            "source": src,
        })
        n_points += 1
    return n_points


def load_csv_file(fp, vessels):
    """Load one AISStream-style CSV file (one row per ping) into the shared vessels dict."""
    src = os.path.basename(fp)
    n_points = 0
    try:
        with open(fp, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                mmsi = (row.get("mmsi") or "").strip()
                if not mmsi: continue

                try:
                    lat = float(row.get("latitude"))
                    lon = float(row.get("longitude"))
                except (TypeError, ValueError):
                    continue
                if not (-90 <= lat <= 90) or not (-180 <= lon <= 180): continue

                ep = parse_csv_time_to_epoch(row.get("time_utc"))
                name = (row.get("ship_name") or "").strip() or "Unknown"

                if vessels[mmsi]["name"] is None:
                    vessels[mmsi]["name"] = name
                    # AISStream PositionReports don't include vessel type; ShipStaticData would, if collected separately
                    vessels[mmsi]["type"] = "Unknown"

                def to_float(val):
                    try:
                        return float(val) if val not in (None, "") else None
                    except ValueError:
                        return None

                vessels[mmsi]["points"].append({
                    "epoch": ep, "dt": fmt_dt(ep) if ep else (row.get("time_utc") or ""),
                    "lat": lat, "lon": lon,
                    "speed": to_float(row.get("speed_knots")),
                    "course": to_float(row.get("course")),
                    "heading": None, "nav_stat": None,
                    "received_ts": ep,
                    "source": src,
                })
                n_points += 1
    except Exception as e:
        print(f"  Warning: failed to read {fp}: {e}")
    return n_points


def load_session(session_dir):
    vessels = defaultdict(lambda: {"name": None, "type": None, "points": []})
    ais_dir = os.path.join(session_dir, "ais")

    json_files = sorted(glob.glob(os.path.join(ais_dir, "*.json")))
    csv_files = sorted(glob.glob(os.path.join(ais_dir, "*.csv")))

    n_points = 0
    for fp in json_files:
        n_points += load_json_snapshot(fp, vessels)
    for fp in csv_files:
        n_points += load_csv_file(fp, vessels)

    for info in vessels.values():
        info["points"].sort(key=lambda p: p["epoch"] or 0)

    stats = {
        "n_json_polls": len(json_files),
        "n_csv_files": len(csv_files),
        "n_points": n_points,
    }
    return stats, dict(vessels)


sessions = {}
for sd in sorted(glob.glob(os.path.join(ROOT, "*"))):
    if not os.path.isdir(sd): continue
    label = os.path.basename(sd)
    stats, vessels = load_session(sd)
    if not vessels:
        print(f"  {label}: SKIPPED (0 valid vessels found)")
        continue

    vlist = []
    for mmsi, info in vessels.items():
        vlist.append({
            "mmsi": mmsi,
            "name": info["name"],
            "type": info["type"],
            "color": color_for(mmsi),
            "n_pings": len(info["points"]),
            "points": info["points"],
        })
    vlist.sort(key=lambda v: (v["name"].lower(), v["mmsi"]))

    sessions[label] = {
        "n_polls": stats["n_json_polls"],   # kept for backward compatibility with existing viewer UI
        "n_csv_files": stats["n_csv_files"],
        "n_points": stats["n_points"],
        "vessels": vlist,
    }
    print(
        f"  {label}: {stats['n_json_polls']} JSON polls, "
        f"{stats['n_csv_files']} CSV file(s), "
        f"{stats['n_points']} total points, "
        f"{len(vlist)} vessels"
    )

with open(os.path.join(OUT_DIR, "data.js"), "w") as f:
    f.write("const AIS_DATA = " + json.dumps(sessions, separators=(',', ':')) + ";\n")
print(f"\nWrote data.js ({os.path.getsize(os.path.join(OUT_DIR,'data.js'))/1024:.0f} KB)")