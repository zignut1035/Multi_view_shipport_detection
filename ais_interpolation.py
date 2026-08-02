"""
Rotterdam Port AIS Interpolator (Unified Script)
Loads raw AIS data, isolates a chosen session, filters out coordinates
outside the Rotterdam bounding box, and upsamples the data to 10-second intervals.
"""

import os
import glob
import json
import argparse
import numpy as np
import pandas as pd

# ===========================================================================
# 1. DATA LOADING FUNCTIONS
# ===========================================================================
def _extract_records(loaded):
    """Handle both a bare list of vessel dicts and standard API dict wrappers."""
    if isinstance(loaded, list):
        return loaded
    if isinstance(loaded, dict):
        for key in ("data", "vessels", "ships", "result", "results"):
            if key in loaded and isinstance(loaded[key], list):
                return loaded[key]
        for v in loaded.values():
            if isinstance(v, list):
                return v
    raise ValueError("Could not find a list of vessel records in this JSON file")


def _parse_csv_time(time_utc_str):
    """Parse rotterdam_aisstream.py's 'time_utc' string
    (e.g. '2026-07-26 11:24:01.085605936 +0000 UTC') into a UTC Timestamp."""
    if pd.isna(time_utc_str):
        return pd.NaT
    try:
        cleaned = str(time_utc_str).split(" +")[0].split(".")[0]
        return pd.to_datetime(cleaned, format="%Y-%m-%d %H:%M:%S", utc=True)
    except (ValueError, TypeError):
        return pd.NaT


def _load_json_file(fp: str) -> pd.DataFrame:
    """Load one Datalastic-style JSON snapshot file (epoch-second timestamps)."""
    with open(fp) as f:
        loaded = json.load(f)
    records = _extract_records(loaded)
    df = pd.DataFrame(records)
    if "received_ts" in df.columns:
        df = df.rename(columns={"received_ts": "timestamp"})
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", errors="coerce")
    return df


def _load_csv_file(fp: str) -> pd.DataFrame:
    """Load one rotterdam_aisstream.py-style CSV file (one row per ping).
    Columns: time_utc, mmsi, ship_name, latitude, longitude, speed_knots,
    course, update_count -- renamed here to match the JSON path's schema
    (timestamp, mmsi, lat, lon, speed, course, name) so both sources feed
    the same downstream interpolation code."""
    df = pd.read_csv(fp)
    rename_map = {
        "time_utc": "timestamp",
        "latitude": "lat",
        "longitude": "lon",
        "speed_knots": "speed",
        "ship_name": "name",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    if "timestamp" in df.columns:
        df["timestamp"] = df["timestamp"].apply(_parse_csv_time)
    return df


def load_ais_folder(folder: str, recursive: bool = True) -> pd.DataFrame:
    """Load and concatenate every AIS file (.json snapshots and/or .csv pings)
    under the folder. Both formats can coexist in the same session's 'ais'
    folder -- e.g. if you've collected with different scripts over time."""
    REQUIRED_COLS = ["timestamp", "lat", "lon", "mmsi"]

    glob_kwargs = {"recursive": True} if recursive else {}
    json_pattern = os.path.join(folder, "**", "*.json") if recursive else os.path.join(folder, "*.json")
    csv_pattern = os.path.join(folder, "**", "*.csv") if recursive else os.path.join(folder, "*.csv")
    json_files = sorted(glob.glob(json_pattern, **glob_kwargs))
    csv_files = sorted(glob.glob(csv_pattern, **glob_kwargs))

    if not json_files and not csv_files:
        raise FileNotFoundError(f"No .json or .csv AIS files found under {folder}")

    frames = []
    for fp in json_files:
        try:
            frame = _load_json_file(fp)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Skipping malformed file {fp}: {e}")
            continue
        missing = [c for c in REQUIRED_COLS if c not in frame.columns]
        if missing:
            print(f"Skipping {fp}: missing expected column(s) {missing} "
                  f"(schema mismatch -- found columns: {list(frame.columns)})")
            continue
        frames.append(frame)
    for fp in csv_files:
        try:
            frame = _load_csv_file(fp)
        except (pd.errors.ParserError, ValueError) as e:
            print(f"Skipping malformed file {fp}: {e}")
            continue
        missing = [c for c in REQUIRED_COLS if c not in frame.columns]
        if missing:
            print(f"Skipping {fp}: missing expected column(s) {missing} "
                  f"(schema mismatch -- found columns: {list(frame.columns)})")
            continue
        frames.append(frame)

    if not frames:
        raise ValueError(f"No valid records found in AIS files under {folder}")

    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=REQUIRED_COLS)

    # De-duplicate: Same real fix appearing across multiple API polls counts once
    df = df.drop_duplicates(subset=["mmsi", "timestamp"])
    df = df.sort_values(["mmsi", "timestamp"]).reset_index(drop=True)

    return df


def load_all_sessions(sessions_root: str, ais_subfolder: str = "ais") -> pd.DataFrame:
    """Load AIS data across ALL session subfolders and tag rows with folder names.
    A single malformed/incompatible session is skipped with a warning rather than
    crashing the whole run -- catches KeyError too, not just FileNotFoundError/
    ValueError, since a schema mismatch inside load_ais_folder's own dropna()
    call would otherwise propagate up as an uncaught KeyError."""
    session_dirs = sorted(d for d in glob.glob(os.path.join(sessions_root, "*")) if os.path.isdir(d))
    frames = []

    for session_dir in session_dirs:
        ais_dir = os.path.join(session_dir, ais_subfolder)
        if not os.path.isdir(ais_dir):
            continue
        try:
            df = load_ais_folder(ais_dir)
            df["session_id"] = os.path.basename(session_dir)
            frames.append(df)
        except (FileNotFoundError, ValueError, KeyError) as e:
            print(f"Skipping session {os.path.basename(session_dir)}: {e}")
            continue

    if not frames:
        raise FileNotFoundError(f"No session with an '{ais_subfolder}' folder found under {sessions_root}")

    return pd.concat(frames, ignore_index=True)


# ===========================================================================
# 2. FILTERING FUNCTIONS
# ===========================================================================
def filter_by_bounding_box(df: pd.DataFrame, min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> pd.DataFrame:
    """Keeps only the AIS pings that fall within a specific geographical rectangle."""
    mask = (
        (df['lat'] >= min_lat) &
        (df['lat'] <= max_lat) &
        (df['lon'] >= min_lon) &
        (df['lon'] <= max_lon)
    )
    return df[mask].reset_index(drop=True)


def _point_in_polygon(lat: float, lon: float, polygon) -> bool:
    """Ray-casting point-in-polygon test. polygon is a list of (lat, lon)
    tuples, in order around the shape (not skipping across it). Same
    approach used for the live TRACK_POLYGON filter in rotterdam_aisstream.py."""
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


def filter_by_polygon(df: pd.DataFrame, polygon) -> pd.DataFrame:
    """Keeps only the AIS pings whose (lat, lon) falls inside the given
    polygon, at EVERY timestamp -- not just a bounding rectangle. Applied
    row-by-row since each row can be a different moment for a different
    vessel; a vessel drifting outside the polygon at some timestamp and
    back inside at another is filtered independently at each point."""
    if df.empty:
        return df
    mask = df.apply(lambda row: _point_in_polygon(row['lat'], row['lon'], polygon), axis=1)
    return df[mask].reset_index(drop=True)


# ===========================================================================
# 3. INTERPOLATION MATH
# ===========================================================================
def interpolate_bearing(course: pd.Series) -> pd.Series:
    """Interpolate compass bearings correctly across the 0/360 degree wrap."""
    rad = np.deg2rad(course.astype(float))
    sin_i = np.sin(rad).interpolate(method="index")
    cos_i = np.cos(rad).interpolate(method="index")
    return (np.rad2deg(np.arctan2(sin_i, cos_i)) + 360) % 360


def interpolate_vessel(group: pd.DataFrame, step: str = "10s") -> pd.DataFrame:
    """Resamples a single vessel group to a fixed step and linearly interpolates."""
    group = group.drop_duplicates(subset="timestamp").set_index("timestamp")

    # Build the regular uniform time grid
    full_index = pd.date_range(group.index.min(), group.index.max(), freq=step)

    # Reindex onto that grid, merging with original fixes, then interpolate
    combined_index = full_index.union(group.index)
    resampled = group.reindex(combined_index)

    # Linear interpolation in time for coordinates and speed. method="index"
    # interpolates proportionally to the actual elapsed time between
    # surrounding real fixes (not just a straight row-count average),
    # which is what makes this genuinely LINEAR interpolation in time
    # for lat/lon rather than a naive midpoint.
    numeric_cols = [c for c in ["lat", "lon", "speed"] if c in resampled.columns]
    resampled[numeric_cols] = resampled[numeric_cols].interpolate(method="index")

    # Wrap bearings properly using trigonometry
    if "course" in resampled.columns:
        resampled["course"] = interpolate_bearing(resampled["course"])

    # Carry forward text data like name and type so they don't become blank
    cols_to_fill = [c for c in ["name", "type", "heading", "nav_stat"] if c in resampled.columns]
    if cols_to_fill:
        resampled[cols_to_fill] = resampled[cols_to_fill].ffill().bfill()

    if "mmsi" in group.columns:
        resampled["mmsi"] = group["mmsi"].iloc[0]

    # Flag generated rows so you can filter or style them differently later
    resampled["is_interpolated"] = ~resampled.index.isin(group.index)

    # Trim final output strictly to the uniform 10-second grid intervals
    resampled = resampled.reindex(full_index)
    resampled.index.name = "timestamp"
    return resampled.reset_index()


def interpolate_all(df: pd.DataFrame, step: str = "10s") -> pd.DataFrame:
    """Run interpolation routines across all unique vessels and sessions."""
    group_cols = ["session_id", "mmsi"] if "session_id" in df.columns else ["mmsi"]
    results = []

    for key, g in df.groupby(group_cols):
        # We need at least 2 pings to calculate a line between them
        if len(g) < 2:
            continue

        result = interpolate_vessel(g, step=step)

        if len(group_cols) == 1:
            result["mmsi"] = key
        else:
            for col, val in zip(group_cols, key):
                result[col] = val
        results.append(result)

    if not results:
        return pd.DataFrame()

    return pd.concat(results, ignore_index=True)


# ===========================================================================
# 4. MAIN CONFIGURATION AND EXECUTION
# ===========================================================================
if __name__ == "__main__":

    # -----------------------------------------------------------------------
    # PATH CONFIGURATION -- session comes from --session instead of being
    # hardcoded, matching the pattern used by fusion_dual_camera.py.
    # -----------------------------------------------------------------------
    ap = argparse.ArgumentParser(description="Interpolate raw Rotterdam AIS pings to a uniform 10s grid.")
    ap.add_argument("--session", required=True,
                    help="Session ID, e.g. 2026-07-27_17-38 (matches the sessions/ subfolder name)")
    ap.add_argument("--sessions-root", default="/mnt/d/rotterdam_data/sessions",
                    help="Root folder containing per-session subfolders")
    ap.add_argument("--repo-path", default="/home/treenut/multi_view/ships",
                    help="Folder to write the interpolated CSV into -- this must match "
                         "fusion_dual_camera.py's --ais-root for it to be found automatically")
    ap.add_argument("--timestamp-shift-minutes", type=float, default=0.0,
                    help="Optional: shift ALL real AIS timestamps by this many minutes "
                         "before interpolating (negative = earlier, positive = later). "
                         "Default 0 = no shift, use real AIS timestamps as-is. Only set "
                         "this if you've confirmed a specific, consistent clock offset "
                         "for this session -- it should not be a permanent hardcoded value.")
    cli_args = ap.parse_args()

    RAW_DATA_PATH = cli_args.sessions_root
    TARGET_SESSION = cli_args.session

    # No shift by default -- use real AIS timestamps as reported. This does
    # NOT affect the lat/lon interpolation MATH itself (still plain linear
    # interpolation in time, via interpolate_vessel above); it only matters
    # if --timestamp-shift-minutes is explicitly passed to correct for a
    # known, confirmed clock offset for this specific session.
    TIMESTAMP_SHIFT = pd.Timedelta(minutes=cli_args.timestamp_shift_minutes)

    print("Step 1: Loading raw AIS folders...")
    try:
        raw_df = load_all_sessions(RAW_DATA_PATH)
        print(f"-> Loaded {len(raw_df)} total pings across all database files.")
    except FileNotFoundError as e:
        print(f"Error loading path: {e}")
        print("Please check that --sessions-root points to your folder.")
        exit()

    print(f"\nStep 2: Isolating chosen session: {TARGET_SESSION}...")
    if 'session_id' in raw_df.columns:
        session_df = raw_df[raw_df['session_id'] == TARGET_SESSION].copy()
        print(f"-> Session isolated. {len(session_df)} pings remaining.")
    else:
        print("-> Error: 'session_id' marker was missing. Processing all data instead.")
        session_df = raw_df.copy()

    if TIMESTAMP_SHIFT != pd.Timedelta(0):
        print(f"\nStep 2b: Shifting all timestamps back by {-TIMESTAMP_SHIFT}...")
        session_df["timestamp"] = session_df["timestamp"] + TIMESTAMP_SHIFT
    else:
        print("\nStep 2b: No timestamp shift applied (using real AIS timestamps as-is).")

    # NOTE: no geographic filtering here anymore -- interpolation uses the
    # FULL raw AIS dataset for this session, unfiltered. Restricting the
    # tracked-area display to TRACK_POLYGON now happens later, at AIS/video
    # display time in utils/AIS_utils.py's AISPRO class, not here. This
    # keeps interpolation quality intact (a vessel's real fixes just
    # outside the polygon still help interpolate its track correctly while
    # it's inside), while the fusion script only ever shows/matches ships
    # actually within the polygon during playback.
    print("\nStep 3: Using full AIS dataset for interpolation (no geographic filter here).")
    in_area_df = session_df

    # Remove stationary assets (tugs, docked ships, anchors) to clear channel tracks
    if 'speed' in in_area_df.columns:
        moving_df = in_area_df[in_area_df['speed'] > 1.0].copy()
        print(f"-> Removed stationary vessels. Processing {moving_df['mmsi'].nunique()} moving tracks.")
    else:
        moving_df = in_area_df.copy()

    if not moving_df.empty:
        print("\nStep 4: Interpolating positions to clean 10-second intervals...")
        filled_df = interpolate_all(moving_df, step="10s")

        if not filled_df.empty:

            # Filename now matches fusion_dual_camera.py's default expectation
            # exactly: rotterdam_interpolated_<session>.csv (no "real_" prefix),
            # so it's found automatically without needing --ais-csv.
            output_filename = os.path.join(cli_args.repo_path, f"rotterdam_interpolated_{TARGET_SESSION}.csv")

            filled_df.to_csv(output_filename, index=False)
            print(f"\n*** SUCCESS! Saved clean upsampled tracking to: {output_filename} ***")
            print("\nData Preview (First 10 records):")
            print(filled_df[['timestamp', 'mmsi', 'lat', 'lon', 'is_interpolated']].head(10))
        else:
            print("-> Interpolation yielded empty dataframe. Check if vessels had multiple pings.")
    else:
        print("-> No valid moving vessel tracking paths left to compute.")