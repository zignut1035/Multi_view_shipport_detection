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
"""
import json, os, glob, hashlib
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


def load_session(session_dir):
    vessels = defaultdict(lambda: {"name": None, "type": None, "points": []})
    files = sorted(glob.glob(os.path.join(session_dir, "ais", "*.json")))
    for fp in files:
        src = os.path.basename(fp)
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        ep = d.get("epoch")
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
    for info in vessels.values():
        info["points"].sort(key=lambda p: p["epoch"] or 0)
    return len(files), dict(vessels)


sessions = {}
for sd in sorted(glob.glob(os.path.join(ROOT, "*"))):
    if not os.path.isdir(sd): continue
    label = os.path.basename(sd)
    n_polls, vessels = load_session(sd)
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
    sessions[label] = {"n_polls": n_polls, "vessels": vlist}
    print(f"  {label}: {n_polls} polls, {len(vlist)} vessels")

with open(os.path.join(OUT_DIR, "data.js"), "w") as f:
    f.write("const AIS_DATA = " + json.dumps(sessions, separators=(',', ':')) + ";\n")
print(f"\nWrote data.js ({os.path.getsize(os.path.join(OUT_DIR,'data.js'))/1024:.0f} KB)")
