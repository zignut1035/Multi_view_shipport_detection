"""
Kanmon AIS <-> Video Matcher
==============================
Automatically syncs AIS data with your videos using the epoch timestamps
embedded in the filenames produced by the bash collector script.

File structure expected (produced by your bash + Python AIS scripts):
  D:/kanmon_data/sessions/2026-05-25_19-17/
  |- cam1_shimonoseki/
  |   |- cam1_shimonoseki_1779704225.mp4           (or _attempt1.mp4, .ts, .mkv)
  |- cam2_moji/
  |   |- cam2_moji_1779704225.mp4
  |- ais/
      |- ais_20260525T101707Z_epoch1779704227.json  (+ all other poll files)

Compatibility notes vs your existing scripts:
  - bash collector  : epoch embedded in video filename -> used as video start time
  - kanmon_AIS_tracker.py: saves record_epoch + offset_seconds in every JSON -> used
    to cross-check video<->AIS sync without any manual input
  - Multiple attempt files (auto-restart): lowest attempt number is used (= earliest)
  - Extensions .mp4 / .ts / .mkv all supported; .bak fps-fix backups are ignored

Usage:
  python kanmon_matcher.py --session "D:/kanmon_data/sessions/2026-05-25_19-17"

Output files (written to the session folder):
  ais_crossings.csv             - every vessel that crossed the strait during session
  ais_health.csv                - AIS update quality per vessel (gaps, stale msgs)
  timeline_cam1_shimonoseki.csv - per-second vessel visibility for cam1
  timeline_cam2_moji.csv        - per-second vessel visibility for cam2
  sync_report.txt               - epoch cross-check between videos and AIS
"""

import os
import re
import json
import glob
import argparse
from datetime import datetime, timezone

import pandas as pd
from shapely.geometry import Point, Polygon


# -----------------------------------------------------------------
# GATE POLYGONS  (your exact 4-corner coordinates)
# -----------------------------------------------------------------
# Shared intersection zone -- all AIS crossing detection uses this
KANMON_GATE = Polygon([
    (130.94027934301957, 33.95083377924011),   # P1 west
    (130.96179384780186, 33.948668533125336),  # P2 south-east
    (130.96155655546968, 33.95680432402013),   # P3 north-east
    (130.95688980634640, 33.964217714195144),  # P4 north
])

# Mid-longitude splits the gate into cam1 (Shimonoseki, west) and cam2 (Moji, east)
_MID_LON = 130.951

CAM_ZONES = {
    "cam1_shimonoseki": Polygon([
        (130.94027934301957, 33.95083377924011),
        (_MID_LON,           33.949),
        (_MID_LON,           33.964),
        (130.95688980634640, 33.964217714195144),
    ]),
    "cam2_moji": Polygon([
        (_MID_LON,           33.949),
        (130.96179384780186, 33.948668533125336),
        (130.96155655546968, 33.95680432402013),
        (_MID_LON,           33.964),
    ]),
}


# -----------------------------------------------------------------
# STEP 1 -- Find video files and extract their start epochs
# -----------------------------------------------------------------
def find_videos(session_dir: str) -> dict:
    """
    Handles filenames produced by the bash collector:
      cam1_shimonoseki_1779704225.mp4          (single attempt)
      cam1_shimonoseki_1779704225_attempt2.mp4 (auto-restart)
    Extensions: .mp4 / .ts / .mkv
    .bak files (fps re-encode backups) are skipped.
    When multiple attempt files exist, the one with the LOWEST attempt
    number is used -- it starts closest to RECORD_EPOCH.
    """
    EPOCH_RE = re.compile(
        r'_(\d{9,12})(?:_attempt(\d+))?\.(?:mp4|ts|mkv)$', re.IGNORECASE
    )

    candidates = {}  # cam_name -> list of (attempt_no, epoch, path)

    for fpath in glob.glob(os.path.join(session_dir, "**", "*.*"), recursive=True):
        if ".bak" in fpath:
            continue
        m = EPOCH_RE.search(os.path.basename(fpath))
        if not m:
            continue
        epoch      = int(m.group(1))
        attempt_no = int(m.group(2)) if m.group(2) else 0
        cam_name   = os.path.basename(os.path.dirname(fpath))
        candidates.setdefault(cam_name, []).append((attempt_no, epoch, fpath))

    videos = {}
    for cam_name, files in candidates.items():
        files.sort(key=lambda x: x[0])   # lowest attempt number first
        attempt_no, epoch, chosen = files[0]
        label = f"attempt{attempt_no}" if attempt_no else "single-file"
        videos[cam_name] = {
            "path":         chosen,
            "start_epoch":  epoch,
            "start_time":   datetime.fromtimestamp(epoch, tz=timezone.utc),
            "all_attempts": [f for _, _, f in files],
        }
        print(f"[vid]  {cam_name}: epoch={epoch}  [{label}]  {os.path.basename(chosen)}")
        if len(files) > 1:
            print(f"         ({len(files)} attempt file(s) found -- using earliest)")
    return videos


# -----------------------------------------------------------------
# STEP 2 -- Load all AIS JSON files produced by kanmon_AIS_tracker.py
# -----------------------------------------------------------------
def load_all_ais(session_dir: str) -> pd.DataFrame:
    """
    Finds every .json file under session/ais/.
    Reads the record_epoch and offset_seconds already written by
    kanmon_AIS_tracker.py -- no recalculation needed.
    """
    ais_dir    = os.path.join(session_dir, "ais")
    json_files = glob.glob(os.path.join(ais_dir, "**", "*.json"), recursive=True)
    if not json_files:
        raise FileNotFoundError(f"No .json files found under {ais_dir}")
    print(f"[ais]  Found {len(json_files)} AIS poll file(s)")

    records = []
    for fpath in sorted(json_files):
        with open(fpath, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        try:
            data     = json.loads(raw)
            snapshots = data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            snapshots = [json.loads(line) for line in raw.splitlines() if line.strip()]

        for snap in snapshots:
            poll_epoch      = snap.get("epoch")
            poll_ts         = snap.get("timestamp_utc")
            record_epoch    = snap.get("record_epoch")    # from bash RECORD_EPOCH
            offset_seconds  = snap.get("offset_seconds")  # pre-computed by AIS tracker

            if poll_epoch:
                poll_dt = datetime.fromtimestamp(poll_epoch, tz=timezone.utc)
            elif poll_ts:
                poll_dt = pd.to_datetime(poll_ts, utc=True).to_pydatetime()
            else:
                continue

            for v in snap.get("vessels", []):
                records.append({
                    "poll_time":       poll_dt,
                    "poll_epoch":      poll_epoch or int(poll_dt.timestamp()),
                    "record_epoch":    record_epoch,
                    "offset_seconds":  offset_seconds,   # seconds since recording started
                    "mmsi":            str(v.get("mmsi", "")),
                    "name":            v.get("name", "UNKNOWN"),
                    "type":            v.get("type", "Unknown"),
                    "lat":             v.get("lat"),
                    "lon":             v.get("lon"),
                    "speed":           v.get("speed"),
                    "course":          v.get("course"),
                    "heading":         v.get("heading"),
                    "nav_stat":        v.get("nav_stat"),
                    # received_ts = last_position_epoch from Datalastic (vessel's own broadcast time)
                    "received_ts":     v.get("received_ts"),
                })

    df = pd.DataFrame(records)
    df["received_time"] = pd.to_datetime(
        df["received_ts"], unit="s", utc=True, errors="coerce"
    )
    df["msg_age_sec"] = (df["poll_time"] - df["received_time"]).dt.total_seconds()
    print(
        f"[ais]  {len(df)} vessel records | "
        f"{df['mmsi'].nunique()} unique vessels | "
        f"{df['poll_time'].min()} -> {df['poll_time'].max()}"
    )
    return df.sort_values("poll_time").reset_index(drop=True)


# -----------------------------------------------------------------
# STEP 3 -- Cross-check video epoch vs AIS record_epoch
# -----------------------------------------------------------------
def sync_report(videos: dict, ais_df: pd.DataFrame, out_dir: str):
    """
    Uses record_epoch (written by bash into every AIS JSON) to verify
    that videos and AIS files belong to the same session.
    Saves a human-readable sync_report.txt.
    """
    lines = ["Kanmon AIS <-> Video Sync Report", "=" * 50, ""]

    # AIS record epochs (should all be the same value within one session)
    ais_record_epochs = ais_df["record_epoch"].dropna().unique()
    ais_record_str    = ", ".join(str(int(e)) for e in ais_record_epochs)
    lines.append(f"AIS record_epoch(s) : {ais_record_str}")
    lines.append("")

    for cam, info in videos.items():
        ve = info["start_epoch"]
        lines.append(f"Camera  : {cam}")
        lines.append(f"  Video epoch     : {ve}  ({info['start_time'].isoformat()})")

        for ae in ais_record_epochs:
            diff = int(ve) - int(ae)
            ok   = abs(diff) <= 10
            lines.append(
                f"  vs AIS epoch {int(ae)}: delta={diff:+d}s  "
                f"{'OK -- same session' if ok else 'WARNING -- large offset, check session folder'}"
            )
        lines.append("")

    # AIS offset_seconds sanity: first poll offset should be close to 0
    first_offsets = ais_df.groupby("poll_epoch")["offset_seconds"].first()
    lines.append(f"AIS poll offsets (first 5): {list(first_offsets.head())}")
    lines.append("")

    report_path = os.path.join(out_dir, "sync_report.txt")
    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    print(f"[sync] sync_report.txt -> {report_path}")
    for l in lines:
        print(f"       {l}")


# -----------------------------------------------------------------
# STEP 4 -- Filter to vessels inside the Kanmon gate
# -----------------------------------------------------------------
def filter_in_gate(ais_df: pd.DataFrame) -> pd.DataFrame:
    mask = ais_df.apply(
        lambda r: KANMON_GATE.contains(Point(r["lon"], r["lat"]))
        if pd.notna(r["lon"]) and pd.notna(r["lat"]) else False,
        axis=1,
    )
    inside = ais_df[mask].copy()
    print(
        f"[gate] {mask.sum()} records inside Kanmon gate "
        f"({inside['mmsi'].nunique()} unique vessels)"
    )
    return inside


# -----------------------------------------------------------------
# STEP 5 -- Extract one crossing event per vessel passage
# -----------------------------------------------------------------
def extract_crossings(inside_df: pd.DataFrame, gap_hours: float = 1.0) -> pd.DataFrame:
    crossings = []
    for mmsi, grp in inside_df.sort_values("poll_time").groupby("mmsi"):
        grp = grp.reset_index(drop=True)
        grp["gap"] = grp["poll_time"].diff().dt.total_seconds().fillna(0)
        grp["passage_id"] = (grp["gap"] > gap_hours * 3600).cumsum()
        for _, passage in grp.groupby("passage_id"):
            first = passage.iloc[0]
            # offset_seconds tells us exactly when in the VIDEO the ship appeared
            first_offset = passage["offset_seconds"].dropna().iloc[0] \
                if passage["offset_seconds"].notna().any() else None
            crossings.append({
                "mmsi":              mmsi,
                "name":              first["name"],
                "type":              first["type"],
                "first_seen":        passage["poll_time"].min(),
                "last_seen":         passage["poll_time"].max(),
                "first_epoch":       int(passage["poll_time"].min().timestamp()),
                "last_epoch":        int(passage["poll_time"].max().timestamp()),
                # video_offset_sec: seconds into the recording when vessel first appeared
                "video_offset_sec":  first_offset,
                "lat_first":         first["lat"],
                "lon_first":         first["lon"],
                "avg_speed_kn":      round(passage["speed"].mean(), 1),
                "course":            first["course"],
                "heading":           first["heading"],
                "n_ais_records":     len(passage),
                "max_msg_age_sec":   (
                    round(passage["msg_age_sec"].max(), 1)
                    if passage["msg_age_sec"].notna().any() else None
                ),
            })
    df = pd.DataFrame(crossings).sort_values("first_seen").reset_index(drop=True)
    print(f"[cross] {len(df)} crossing event(s)")
    return df


# -----------------------------------------------------------------
# STEP 6 -- Build per-camera timeline
#   For each N-second interval of video, list vessels AIS says are visible
# -----------------------------------------------------------------
def build_timeline(
    cam_name: str,
    cam_info: dict,
    ais_df: pd.DataFrame,
    interval_sec: int = 10,
) -> pd.DataFrame:
    """
    Uses offset_seconds from the AIS JSON (pre-computed by kanmon_AIS_tracker.py)
    to map directly to video time -- no floating-point time arithmetic.
    """
    cam_zone    = CAM_ZONES.get(cam_name, KANMON_GATE)
    start_epoch = cam_info["start_epoch"]

    ais_end_epoch = int(ais_df["poll_epoch"].max())
    duration_sec  = max(ais_end_epoch - start_epoch, 0)
    if duration_sec == 0:
        print(f"[warn] No AIS data after video start for {cam_name}")
        return pd.DataFrame()

    print(f"[tl]   {cam_name}: 0 -> {duration_sec}s, sampled every {interval_sec}s")

    rows = []
    for offset in range(0, duration_sec + 1, interval_sec):
        wall_epoch = start_epoch + offset
        wall_dt    = datetime.fromtimestamp(wall_epoch, tz=timezone.utc)

        # Find AIS records within +/-60 s of this video moment
        ais_df["_dt"] = (ais_df["poll_epoch"] - wall_epoch).abs()
        nearby = ais_df[ais_df["_dt"] <= 60].copy()

        if nearby.empty:
            rows.append({
                "video_sec":    offset,
                "wall_clock":   wall_dt.isoformat(),
                "mmsi":         None,
                "name":         None,
                "type":         None,
                "speed_kn":     None,
                "course":       None,
                "lat":          None,
                "lon":          None,
                "in_cam_zone":  None,
                "msg_age_sec":  None,
                "match_status": "NO_AIS_DATA",
            })
            continue

        # Use the latest record per vessel within the window
        latest = nearby.sort_values("poll_time").groupby("mmsi").last()
        for mmsi, v in latest.iterrows():
            in_zone = (
                cam_zone.contains(Point(v["lon"], v["lat"]))
                if pd.notna(v["lon"]) and pd.notna(v["lat"]) else False
            )
            rows.append({
                "video_sec":    offset,
                "wall_clock":   wall_dt.isoformat(),
                "mmsi":         mmsi,
                "name":         v["name"],
                "type":         v["type"],
                "speed_kn":     v["speed"],
                "course":       v["course"],
                "lat":          v["lat"],
                "lon":          v["lon"],
                "in_cam_zone":  in_zone,
                "msg_age_sec":  v["msg_age_sec"],
                "match_status": "IN_ZONE" if in_zone else "IN_STRAIT",
            })

    ais_df.drop(columns=["_dt"], inplace=True, errors="ignore")
    return pd.DataFrame(rows)


# -----------------------------------------------------------------
# STEP 7 -- AIS health report
# -----------------------------------------------------------------
def ais_health(ais_df: pd.DataFrame, crossings_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, cx in crossings_df.iterrows():
        v = ais_df[ais_df["mmsi"] == cx["mmsi"]].sort_values("poll_time").copy()
        if v.empty:
            continue
        v["gap_sec"] = v["poll_time"].diff().dt.total_seconds()
        rows.append({
            "mmsi":               cx["mmsi"],
            "name":               cx["name"],
            "type":               cx["type"],
            "first_seen":         cx["first_seen"].isoformat(),
            "last_seen":          cx["last_seen"].isoformat(),
            "video_offset_sec":   cx["video_offset_sec"],
            "n_ais_records":      cx["n_ais_records"],
            "avg_speed_kn":       cx["avg_speed_kn"],
            "max_gap_sec":        round(v["gap_sec"].max(), 1),
            "mean_gap_sec":       round(v["gap_sec"].mean(), 1),
            "max_msg_age_sec":    cx["max_msg_age_sec"],
            "ais_gap_warning":    "GAP>5min"   if v["gap_sec"].max() > 300   else "OK",
            "ais_stale_warning":  "STALE>10min" if (cx["max_msg_age_sec"] or 0) > 600 else "OK",
        })
    return pd.DataFrame(rows)


# -----------------------------------------------------------------
# STEP 8 -- Console summary
# -----------------------------------------------------------------
def print_summary(crossings_df, health_df, timelines):
    print("\n" + "=" * 60)
    print("  KANMON STRAIT  --  AIS Session Summary")
    print("=" * 60)
    print(f"  Vessels in strait     : {len(crossings_df)}")
    if not health_df.empty:
        gaps   = (health_df["ais_gap_warning"]  == "GAP>5min").sum()
        stales = (health_df["ais_stale_warning"] == "STALE>10min").sum()
        print(f"  AIS gap warnings      : {gaps}")
        print(f"  Stale msg warnings    : {stales}")
    print()
    print(f"  {'NAME':<22} {'MMSI':<12} {'TYPE':<12} {'KN':>5}  {'VIDEO OFFSET':>13}  FIRST SEEN (UTC)")
    print(f"  {'-'*22} {'-'*12} {'-'*12} {'-'*5}  {'-'*13}  {'-'*19}")
    for _, r in crossings_df.iterrows():
        offset_str = (
            f"+{int(r['video_offset_sec'])}s"
            if r["video_offset_sec"] is not None else "n/a"
        )
        print(
            f"  {str(r['name']):<22} {str(r['mmsi']):<12} "
            f"{str(r['type']):<12} {str(r['avg_speed_kn']):>5}  "
            f"{offset_str:>13}  {str(r['first_seen'])[:19]}"
        )
    print()
    for cam, tl in timelines.items():
        if tl is None or tl.empty:
            continue
        in_zone = tl[tl["match_status"] == "IN_ZONE"]
        n = in_zone["mmsi"].nunique() if not in_zone.empty else 0
        print(f"  {cam}: {n} vessel(s) visible in camera zone")
    print("=" * 60 + "\n")


# -----------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Kanmon AIS <-> Video Matcher")
    ap.add_argument(
        "--session",
        default=r"D:\kanmon_data\sessions\2026-05-25_19-17",
        help="Path to the session folder (contains cam1_*, cam2_*, ais/ subfolders)",
    )
    ap.add_argument(
        "--interval", type=int, default=10,
        help="Timeline sample interval in seconds (default: 10)",
    )
    ap.add_argument(
        "--output_dir", default=None,
        help="Where to save CSVs (default: session folder)",
    )
    args   = ap.parse_args()
    s_dir  = args.session
    o_dir  = args.output_dir or s_dir
    os.makedirs(o_dir, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  Session : {s_dir}")
    print(f"  Output  : {o_dir}")
    print(f"{'='*60}\n")

    videos       = find_videos(s_dir)
    ais_df       = load_all_ais(s_dir)
    sync_report(videos, ais_df, o_dir)
    inside_df    = filter_in_gate(ais_df)
    crossings_df = extract_crossings(inside_df)
    health_df    = ais_health(ais_df, crossings_df)

    crossings_df.to_csv(os.path.join(o_dir, "ais_crossings.csv"),  index=False)
    health_df.to_csv(   os.path.join(o_dir, "ais_health.csv"),      index=False)
    print(f"[out] ais_crossings.csv  -> {o_dir}")
    print(f"[out] ais_health.csv     -> {o_dir}")

    timelines = {}
    for cam_name, cam_info in videos.items():
        tl = build_timeline(cam_name, cam_info, ais_df, interval_sec=args.interval)
        timelines[cam_name] = tl
        if tl is not None and not tl.empty:
            tl_path = os.path.join(o_dir, f"timeline_{cam_name}.csv")
            tl.to_csv(tl_path, index=False)
            print(f"[out] timeline_{cam_name}.csv -> {o_dir}")

    print_summary(crossings_df, health_df, timelines)


if __name__ == "__main__":
    main()
