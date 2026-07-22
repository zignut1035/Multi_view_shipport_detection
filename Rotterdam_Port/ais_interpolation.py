"""
Rotterdam Port AIS Interpolator (Unified Script)
Loads raw AIS data, isolates session 2026-05-27_15-35, filters out coordinates 
outside the Rotterdam bounding box, and upsamples the data to 10-second intervals.
"""

import os
import glob
import json
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


def load_ais_folder(folder: str, pattern: str = "*.json", recursive: bool = True) -> pd.DataFrame:
    """Load and concatenate every AIS snapshot JSON file under the folder."""
    if recursive:
        files = sorted(glob.glob(os.path.join(folder, "**", pattern), recursive=True))
    else:
        files = sorted(glob.glob(os.path.join(folder, pattern)))

    if not files:
        raise FileNotFoundError(f"No files matching {pattern} under {folder}")

    all_records = []
    for fp in files:
        with open(fp) as f:
            try:
                loaded = json.load(f)
                all_records.extend(_extract_records(loaded))
            except (json.JSONDecodeError, ValueError) as e:
                print(f"Skipping malformed file {fp}: {e}")
                continue

    if not all_records:
        raise ValueError(f"No valid records found in JSON files under {folder}")

    df = pd.DataFrame(all_records)
    
    # Standardize column name for the per-vessel real fix time
    if "received_ts" in df.columns:
        df = df.rename(columns={"received_ts": "timestamp"})
        
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", errors="coerce")
    df = df.dropna(subset=["timestamp", "lat", "lon", "mmsi"])

    # De-duplicate: Same real fix appearing across multiple API polls counts once
    df = df.drop_duplicates(subset=["mmsi", "timestamp"])
    df = df.sort_values(["mmsi", "timestamp"]).reset_index(drop=True)
    
    return df


def load_all_sessions(sessions_root: str, ais_subfolder: str = "ais") -> pd.DataFrame:
    """Load AIS data across ALL session subfolders and tag rows with folder names."""
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
        except (FileNotFoundError, ValueError):
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

    # Linear interpolation in time for coordinates and speed
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
    # PATH CONFIGURATION
    # -----------------------------------------------------------------------
    RAW_DATA_PATH = "/mnt/d/rotterdam_data/sessions" 
    TARGET_SESSION = "2026-05-27_15-35"
    
    print("Step 1: Loading raw AIS folders...")
    try:
        raw_df = load_all_sessions(RAW_DATA_PATH)
        print(f"-> Loaded {len(raw_df)} total pings across all database files.")
    except FileNotFoundError as e:
        print(f"Error loading path: {e}")
        print("Please check that RAW_DATA_PATH points to your folder.")
        exit()

    print(f"\nStep 2: Isolating chosen session: {TARGET_SESSION}...")
    if 'session_id' in raw_df.columns:
        session_df = raw_df[raw_df['session_id'] == TARGET_SESSION].copy()
        print(f"-> Session isolated. {len(session_df)} pings remaining.")
    else:
        print("-> Error: 'session_id' marker was missing. Processing all data instead.")
        session_df = raw_df.copy()

    # Define the Rotterdam Port Bounding Box limits
    MIN_LAT = 51.8800
    MAX_LAT = 51.9900
    MIN_LON = 3.9500
    MAX_LON = 4.5000

    print("\nStep 3: Applying bounding box to clean geographic boundaries...")
    in_area_df = filter_by_bounding_box(session_df, MIN_LAT, MAX_LAT, MIN_LON, MAX_LON)
    print(f"-> Kept {in_area_df['mmsi'].nunique()} active vessels inside Rotterdam boundaries.")

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
            
            # Define the exact repo folder where the fusion script will look for it
            repo_path = "/home/treenut/multi_view/ships"
            
            # Name it 'rotterdam' to match the fusion script, and join it with the repo path
            output_filename = os.path.join(repo_path, f"real_rotterdam_interpolated_{TARGET_SESSION}.csv")
            
            filled_df.to_csv(output_filename, index=False)
            print(f"\n*** SUCCESS! Saved clean upsampled tracking to: {output_filename} ***")
            print("\nData Preview (First 10 records):")
            print(filled_df[['timestamp', 'mmsi', 'lat', 'lon', 'is_interpolated']].head(10))
        else:
            print("-> Interpolation yielded empty dataframe. Check if vessels had multiple pings.")
    else:
        print("-> No valid moving vessel tracking paths left to compute.")