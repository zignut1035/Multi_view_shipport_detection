# sync_check.py
import json, os, re, subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ── CONFIG ──────────────────────────────────────────────────────────────
AIS_DIR = Path("/mnt/d/kanmon_temp/ais_data_kanmon/first_session")
CAM_DIRS = {
    "cam1": Path("/mnt/d/kanmon_temp/cam1_shimonoseki"),
    "cam2": Path("/mnt/d/kanmon_temp/cam2_moji"),
}
# ────────────────────────────────────────────────────────────────────────

def ts_str(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def get_video_duration(path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10
        )
        return float(result.stdout.strip())
    except Exception:
        return None

# ── 1. Load AIS ──────────────────────────────────────────────────────────
vessels = defaultdict(list)
poll_epochs = []

for fname in sorted(AIS_DIR.iterdir()):
    if fname.suffix != ".json":
        continue
    # extract epoch from filename: ais_20260522T002840Z_epoch1779409720.json
    m = re.search(r"epoch(\d+)", fname.name)
    if not m:
        continue
    with open(fname) as f:
        poll = json.load(f)
    poll_epoch = poll.get("epoch", int(m.group(1)))
    poll_epochs.append(poll_epoch)
    for v in poll.get("vessels", []):
        vessels[v["mmsi"]].append({
            "name":        v["name"],
            "type":        v["type"],
            "poll_ts":     poll_epoch,
            "received_ts": v.get("received_ts"),
        })

if not poll_epochs:
    print("No AIS JSON files found — check AIS_DIR path.")
    exit(1)

ais_start = min(poll_epochs)
ais_end   = max(poll_epochs)
ais_span  = ais_end - ais_start

print("=" * 72)
print("AIS COVERAGE")
print("=" * 72)
print(f"  JSON files  : {len(poll_epochs)}")
print(f"  Start       : {ts_str(ais_start)}  (epoch {ais_start})")
print(f"  End         : {ts_str(ais_end)}  (epoch {ais_end})")
print(f"  Duration    : {ais_span // 60}m {ais_span % 60}s  ({ais_span}s total)")
print(f"  Vessels     : {len(vessels)}")
print()
print(f"  {'':2} {'MMSI':<14} {'Name':<22} {'Type':<12} {'Obs':>4}  "
      f"{'First (offset)':>14}  {'Last (offset)':>13}  {'AIS lag avg':>11}")
print(f"  {'-'*2} {'-'*13} {'-'*21} {'-'*11} {'-'*4}  {'-'*14}  {'-'*13}  {'-'*11}")

for mmsi, obs in sorted(vessels.items(), key=lambda x: x[1][0]["name"]):
    first = min(o["poll_ts"] for o in obs)
    last  = max(o["poll_ts"] for o in obs)
    lags  = [o["poll_ts"] - o["received_ts"] for o in obs
             if o.get("received_ts")]
    lag_str = f"{sum(lags)/len(lags):.0f}s" if lags else "n/a"
    flag = "✓"
    print(f"  {flag} {mmsi:<13} {obs[0]['name']:<22} {obs[0]['type']:<12} "
          f"{len(obs):>4}  +{first - ais_start:>6}s        "
          f"+{last - ais_start:>6}s  {lag_str:>11}")

# ── 2. Load Videos ───────────────────────────────────────────────────────
print()
print("=" * 72)
print("VIDEO COVERAGE")
print("=" * 72)

video_ranges = {}
for cam, cam_dir in CAM_DIRS.items():
    if not cam_dir.exists():
        print(f"  [{cam}] NOT FOUND: {cam_dir}")
        print()
        continue

    files = sorted(cam_dir.glob("*.mp4"))
    ranges = []
    for f in files:
        # filename: cam1_shimonoseki_1779409728.mp4  or  cam2_moji_1779409728.mp4
        m = re.search(r"_(\d{10})\.mp4$", f.name)
        if not m:
            continue
        start = int(m.group(1))
        dur   = get_video_duration(f)
        end   = start + dur if dur else None
        ranges.append((start, end, f))
    video_ranges[cam] = ranges

    total_dur = sum((e - s) for s, e, _ in ranges if e) 
    print(f"  [{cam}]  {len(ranges)} file(s)  —  "
          f"total ~{total_dur//60:.0f}m {total_dur%60:.0f}s")

    for start, end, f in ranges:
        overlaps = (start <= ais_end) and (end is None or end >= ais_start)
        flag     = "✓" if overlaps else "✗"
        offset   = start - ais_start
        dur_str  = f"{(end-start)//60:.0f}m {(end-start)%60:.0f}s" if end else "duration unknown (no ffprobe?)"
        print(f"    {flag} {f.name}")
        print(f"        start  : {ts_str(start)}  (offset from AIS start: {offset:+}s)")
        if end:
            print(f"        end    : {ts_str(end)}  ({dur_str})")
        print(f"        sync   : {'overlaps AIS ✓' if overlaps else 'NO AIS overlap ✗'}")
    print()

# ── 3. Per-vessel sync check ─────────────────────────────────────────────
print("=" * 72)
print("PER-VESSEL SYNC  (how many AIS pings land inside each video)")
print("=" * 72)

for mmsi, obs in sorted(vessels.items(), key=lambda x: x[1][0]["name"]):
    name  = obs[0]["name"]
    vtype = obs[0]["type"]
    print(f"\n  {name:<22} {vtype:<12} ({mmsi})")
    for cam, ranges in video_ranges.items():
        for start, end, f in ranges:
            inside = [o for o in obs
                      if o["poll_ts"] >= start and (end is None or o["poll_ts"] <= end)]
            pct    = 100 * len(inside) / len(obs)
            bar    = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            print(f"    [{cam}]  {bar}  {len(inside):>3}/{len(obs)} pings  ({pct:.0f}%)")

print()
print("Done.")