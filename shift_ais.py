"""
Shift one vessel's timestamps in an already-generated interpolated AIS CSV,
so its data window starts earlier (or later) than it actually did.

This is a deliberate data fabrication for a single-ship demo -- the shifted
rows are NOT real AIS data at those times, they're the real track just
relabeled with different timestamps. Every other vessel in the CSV is left
completely untouched.

Usage:
    python3 shift_ais_time.py rotterdam_interpolated_2026-05-27_15-35.csv \\
        --mmsi 244700444 --shift-seconds -60 --out rotterdam_interpolated_shifted.csv
"""
import argparse
import pandas as pd

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_path")
    ap.add_argument("--mmsi", type=int, required=True)
    ap.add_argument("--shift-seconds", type=float, required=True,
                     help="negative = earlier, positive = later")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    df = pd.read_csv(args.csv_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    mask = df["mmsi"] == args.mmsi
    n = mask.sum()
    if n == 0:
        print(f"No rows found for mmsi {args.mmsi} -- nothing changed.")
    else:
        df.loc[mask, "timestamp"] = df.loc[mask, "timestamp"] + pd.Timedelta(seconds=args.shift_seconds)
        print(f"Shifted {n} row(s) for mmsi {args.mmsi} by {args.shift_seconds}s.")
        print(f"New range for this mmsi: "
              f"{df.loc[mask, 'timestamp'].min()} to {df.loc[mask, 'timestamp'].max()}")

    sort_cols = ["session_id", "mmsi", "timestamp"] if "session_id" in df.columns else ["mmsi", "timestamp"]
    df = df.sort_values(sort_cols)
    df.to_csv(args.out, index=False)
    print(f"Saved to {args.out}")