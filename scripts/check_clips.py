#!/usr/bin/env python3
"""Find partial/corrupt clips: compare 06_final/clips durations vs expectations."""
import json, subprocess, os, sys

run = "runs/blackpink-gamble"
td = json.load(open(f"{run}/03_timings.json"))["timings"]
bad = []
n_clips = 0
for t in td:
    sid = t["id"]
    n = int(sid) if isinstance(sid, int) else int(str(sid).lstrip("s"))
    c = f"{run}/06_final/clips/clip_{n:02d}.mp4"
    if not os.path.isfile(c):
        bad.append((sid, "MISSING"))
        continue
    n_clips += 1
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", c], capture_output=True, text=True, timeout=20)
    try:
        d = float(r.stdout.strip())
    except Exception:
        d = 0.0
    if d < 1.0:
        bad.append((sid, f"CORRUPT d={d:.2f}"))
print("bad clips:", bad if bad else "NONE - all clean")
print("clip files:", n_clips)
sys.exit(0)
