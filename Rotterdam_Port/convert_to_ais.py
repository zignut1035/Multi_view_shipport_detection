"""
Convert a synthetic_ais_log.csv (produced by SyntheticAISRegistry.save_to_csv()
during a main_dual_fusion.py run) into the same format as the real
rotterdam_interpolated_<session>.csv, so it can be fed into AISPRO on a
later run exactly like real AIS data.

WHY THIS CONVERSION IS NEEDED (not just a straight copy):
  The synthetic log stores 'timestamp' as a raw Unix epoch-ms integer
  (matching the console's "Stamp: 1779864060000" values throughout this
  project). AISPRO's CSV loader calls pd.to_datetime() on the timestamp
  column WITHOUT specifying unit='ms' -- for a raw integer, pandas
  defaults to interpreting it as nanoseconds-since-epoch, silently
  producing a garbage date (1970, not 2026). This script converts the
  raw epoch-ms values into proper "YYYY-MM-DD HH:MM:SS" UTC date
  strings, matching exactly what the real AIS CSV already uses.

USAGE:
  python3 convert_synthetic_to_ais.py \
      --synthetic-csv /path/to/result_dual/<session>/synthetic_ais_log.csv \
      --out /path/to/rotterdam_interpolated_<session>_with_synthetic.csv \
      [--merge-with /path/to/rotterdam_interpolated_<session>.csv]

  If --merge-with is given, the real AIS rows and converted synthetic
  rows are combined into one file (sorted by timestamp), ready to use
  directly as the --ais-root input for a later main_dual_fusion.py run.
  If omitted, only the converted synthetic rows are written.
"""
import argparse
import pandas as pd


def convert_synthetic_csv(synthetic_csv_path):
    df = pd.read_csv(synthetic_csv_path)

    if df.empty:
        print(f"[convert] {synthetic_csv_path} has no rows -- nothing to convert.")
        return df

    # Raw epoch-ms -> proper UTC date string, matching the real AIS CSV format
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')

    # Fill in placeholder identity fields so the row looks complete, same
    # as a real AIS row would, while is_synthetic keeps it honestly marked
    df['name'] = df['mmsi'].apply(lambda m: f'SYNTH-{m}')
    df['type'] = df['type'].fillna('Unknown') if 'type' in df.columns else 'Unknown'

    # Column order matches the real AIS CSV exactly, with the two extra
    # transparency columns appended at the end (harmless to AISPRO, which
    # only reads the columns it needs by name)
    cols = ['timestamp', 'mmsi', 'name', 'type', 'lat', 'lon', 'speed',
            'course', 'heading', 'nav_stat', 'session_id',
            'is_interpolated', 'is_synthetic', 'source_camera']
    df = df[[c for c in cols if c in df.columns]]

    print(f"[convert] Converted {len(df)} synthetic rows from {synthetic_csv_path}")
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--synthetic-csv", required=True, help="Path to synthetic_ais_log.csv")
    ap.add_argument("--out", required=True, help="Output CSV path")
    ap.add_argument("--merge-with", default=None,
                    help="Optional: path to the real AIS CSV to merge with")
    args = ap.parse_args()

    synthetic_df = convert_synthetic_csv(args.synthetic_csv)

    if args.merge_with:
        real_df = pd.read_csv(args.merge_with)
        # Real rows don't have is_synthetic/source_camera -- mark them
        # explicitly so the merged file distinguishes real from synthetic
        # just as clearly as the synthetic log already does on its own
        real_df['is_synthetic'] = False
        real_df['source_camera'] = ''
        combined = pd.concat([real_df, synthetic_df], ignore_index=True)
        combined['_sort_ts'] = pd.to_datetime(combined['timestamp'], errors='coerce')
        combined = combined.sort_values('_sort_ts').drop(columns='_sort_ts')
        combined.to_csv(args.out, index=False)
        print(f"[convert] Merged {len(real_df)} real rows + {len(synthetic_df)} "
              f"synthetic rows -> {args.out}")
    else:
        synthetic_df.to_csv(args.out, index=False)
        print(f"[convert] Wrote {len(synthetic_df)} synthetic rows -> {args.out}")


if __name__ == "__main__":
    main()