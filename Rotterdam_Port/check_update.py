"""
Rotterdam - Check Transit Updates
------------------------
For every vessel that crossed the camera field of view
(west edge -> east edge or vice versa), count how many
AIS updates were received during that transit.

Flags vessels with MORE THAN 2 updates while in frame.

Usage:
    python3 check_transit_updates_rotterdam.py --session "D:\\rotterdam_data\\sessions\\2026-05-27_15-53"
    python3 check_transit_updates_rotterdam.py --session "/mnt/d/rotterdam_data/sessions/2026-05-27_15-53"
"""

import os, re, json, glob, argparse
from datetime import datetime, timezone
import pandas as pd
from shapely.geometry import Point, Polygon

# ── Gate (Rotterdam 4 corner points) ─────────────────────────────
GATE = Polygon([
    (4.474304, 51.900443), # South-West corner
    (4.492702, 51.900443), # South-East corner
    (4.492702, 51.912406), # North-East corner
    (4.474304, 51.912406), # North-West corner
])

# Left/right edges of the gate (longitude boundaries for Rotterdam)
GATE_WEST_LON = 4.474304   # Western edge of the bounding box
GATE_EAST_LON = 4.492702   # Eastern edge of the bounding box
EDGE_MARGIN   = 0.0015     # how close to the edge counts as "at the edge" (~100m)

def to_wsl_path(p):
    if p.startswith("/"): return p
    m = re.match(r'^([A-Za-z]):[/\\](.*)', p)
    if m:
        return f"/mnt/{m.group(1).lower()}/{m.group(2).replace(chr(92), '/')}"
    return p

def load_ais(session_dir):
    files = glob.glob(os.path.join(session_dir, "ais", "**", "*.json"), recursive=True)
    if not files:
        raise FileNotFoundError(f"No AIS json files in {session_dir}/ais/")
    rows = []
    for fp in sorted(files):
        with open(fp) as f:
            raw = f.read().strip()
        try:
            snaps = json.loads(raw)
            if isinstance(snaps, dict): snaps = [snaps]
        except json.JSONDecodeError:
            snaps = [json.loads(l) for l in raw.splitlines() if l.strip()]
        for snap in snaps:
            ep = snap.get("epoch")
            dt = datetime.fromtimestamp(ep, tz=timezone.utc) if ep else \
                 pd.to_datetime(snap.get("timestamp_utc"), utc=True).to_pydatetime()
            for v in snap.get("vessels", []):
                rows.append({
                    "time":  dt,
                    "epoch": ep or int(dt.timestamp()),
                    "mmsi":  str(v.get("mmsi", "")),
                    "name":  v.get("name", "?"),
                    "type":  v.get("type", "?"),
                    "lat":   v.get("lat"),
                    "lon":   v.get("lon"),
                    "speed": v.get("speed"),
                    "course":v.get("course"),
                })
    return pd.DataFrame(rows).sort_values("time").reset_index(drop=True)

def analyse(session_dir):
    df = load_ais(session_dir)

    # Keep only records inside the gate
    in_gate = df[df.apply(
        lambda r: GATE.contains(Point(r.lon, r.lat))
        if pd.notna(r.lon) and pd.notna(r.lat) else False, axis=1
    )].copy()

    results = []
    for mmsi, grp in in_gate.sort_values("time").groupby("mmsi"):
        grp = grp.reset_index(drop=True)

        # Split into separate transits if there is a gap > 1 hour
        grp["gap"] = grp["time"].diff().dt.total_seconds().fillna(0)
        grp["transit_id"] = (grp["gap"] > 3600).cumsum()

        for tid, transit in grp.groupby("transit_id"):
            n = len(transit)

            # Did it reach the west edge?
            touched_west = (transit["lon"] <= GATE_WEST_LON + EDGE_MARGIN).any()
            # Did it reach the east edge?
            touched_east = (transit["lon"] >= GATE_EAST_LON - EDGE_MARGIN).any()
            full_transit = touched_west and touched_east

            results.append({
                "mmsi":            mmsi,
                "name":            transit["name"].iloc[0],
                "type":            transit["type"].iloc[0],
                "entry_time":      transit["time"].iloc[0].strftime("%Y-%m-%d %H:%M:%S"),
                "exit_time":       transit["time"].iloc[-1].strftime("%Y-%m-%d %H:%M:%S"),
                "duration_sec":    int((transit["time"].iloc[-1] - transit["time"].iloc[0]).total_seconds()),
                "ais_updates":     n,
                "more_than_2":     n > 2,
                "full_transit":    full_transit,   # crossed both edges
                "touched_west":    touched_west,
                "touched_east":    touched_east,
                "avg_speed_kn":    round(transit["speed"].mean(), 1),
                "course":          transit["course"].iloc[0],
            })

    return pd.DataFrame(results).sort_values("entry_time").reset_index(drop=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True, help="Session folder path")
    ap.add_argument("--min_updates", type=int, default=2,
                    help="Minimum AIS updates to flag (default: 2, i.e. flag >2)")
    args = ap.parse_args()
    s_dir = to_wsl_path(args.session)

    df = analyse(s_dir)

    if df.empty:
        print("No vessels found in gate.")
        return

    # ── Print results ─────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  Rotterdam AIS Update Count per Transit  |  threshold: >{args.min_updates}")
    print(f"{'='*65}")
    print(f"  Total transits found : {len(df)}")
    print(f"  Full edge-to-edge    : {df['full_transit'].sum()}")
    print(f"  Updates > {args.min_updates}          : {(df['ais_updates'] > args.min_updates).sum()}")
    print()

    print(f"  {'NAME':<20} {'MMSI':<12} {'UPDATES':>7}  {'DURATION':>8}  {'FULL?':>5}  FLAG")
    print(f"  {'-'*20} {'-'*12} {'-'*7}  {'-'*8}  {'-'*5}  {'-'*4}")
    for _, r in df.iterrows():
        flag    = "<<" if r["ais_updates"] > args.min_updates else ""
        dur_str = f"{r['duration_sec']}s"
        full    = "YES" if r["full_transit"] else "no"
        print(
            f"  {str(r['name']):<20} {str(r['mmsi']):<12} "
            f"{r['ais_updates']:>7}  {dur_str:>8}  {full:>5}  {flag}"
        )

    print(f"\n{'='*65}\n")

    # ── Save CSV ──────────────────────────────────────────────────
    out = os.path.join(s_dir, "transit_updates.csv")
    df.to_csv(out, index=False)
    print(f"Saved -> {out}")

    flagged = df[df["ais_updates"] > args.min_updates]
    if not flagged.empty:
        print(f"\nVessels with >{args.min_updates} AIS updates during transit:")
        for _, r in flagged.iterrows():
            print(f"  {r['name']} ({r['mmsi']}) — {r['ais_updates']} updates, "
                  f"{r['duration_sec']}s in frame, "
                  f"{'full edge-to-edge' if r['full_transit'] else 'partial transit'}")
    else:
        print(f"\nNo vessels had more than {args.min_updates} AIS updates during transit.")

if __name__ == "__main__":
    main()
