#!/usr/bin/env python3
"""acquire_pool_v2.py — re-acquire the Ahyeon footage pool (R8: local server
only, NO GitHub Actions). YouTube direct is bot-walled in this sandbox, so
acquisition walks the mirror ladder used successfully for ahyeon v1.0
(vkvideo.ru / dailymotion / bilibili), 720p cap, resumable, ffprobe-verified.

Output: runs/ahyeon-it-girl-v2/04_media/pool/<key>.mp4
        runs/ahyeon-it-girl-v2/04_media/pool/manifest.json
         (per key: title, kind, subject_tags, mirrors_tried, source_url,
          youtube_id where known, size, duration — full provenance)
"""
import json, os, subprocess, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = os.path.join(BASE, "runs", "ahyeon-it-girl-v2")
POOL = os.path.join(RUN, "04_media", "pool")
LS = "/home/z/my-project/last-stop"

# key -> (title, kind, subject_tags, youtube_id or None)
SOURCES = {
    "drip":          ("BABYMONSTER - 'DRIP' M/V", "mv",
                      ["ahyeon", "drip", "mv", "2024", "comeback"], "Zp-Jhuhq0bQ"),
    "sheesh":        ("BABYMONSTER - 'SHEESH' M/V", "mv",
                      ["ahyeon", "sheesh", "mv", "2024", "debut"], "2wA_b6YHjqQ"),
    "forever":       ("BABYMONSTER - 'FOREVER' M/V", "mv",
                      ["ahyeon", "forever", "mv", "2024"], "eJCHKjt0MPw"),
    "batterup":      ("BABYMONSTER - 'BATTER UP' M/V", "mv",
                      ["ahyeon", "batterup", "mv", "2023", "debut"], "olDWm2veCrM"),
    "moon":          ("BABYMONSTER - 'MOON' M/V", "mv",
                      ["ahyeon", "moon", "mv", "2024"], "xXZwZ0DolJc"),
    "hotsauce":      ("BABYMONSTER - 'HOT SAUSE' M/V", "mv",
                      ["ahyeon", "hotsauce", "mv", "2025", "comeback"], "xn8mQqz2xmM"),
    "shit":          ("BABYMONSTER - 'SUGAR HONEY ICE TEA' M/V", "mv",
                      ["ahyeon", "sugarhoney", "mv", "2025"], None),
    "choom":         ("BABYMONSTER - 'CHOOM' M/V", "mv",
                      ["ahyeon", "choom", "mv", "2025", "dance"], None),
    "sitm":          ("BABYMONSTER - 'STUCK IN THE MIDDLE' M/V", "mv",
                      ["ahyeon", "stuck", "ballad", "mv", "2024"], "GsV1i0QHi-o"),
    "dream":         ("BABYMONSTER - 'DREAM' M/V", "mv",
                      ["ahyeon", "dream", "mv", "2023", "predebut"], None),
    "nextmovement":  ("BABYMONSTER 'YG NEXT MOVEMENT' (pre-debut reveal)", "doc",
                      ["ahyeon", "trainee", "predebut", "yg", "reveal"], None),
    "leval1":        ("BABYMONSTER Last Evaluation EP.1", "doc",
                      ["ahyeon", "trainee", "evaluation", "yg", "predebut"], "k2GNcev8kaA"),
    "leval_ahyeon":  ("BABYMONSTER Last Evaluation — Ahyeon", "doc",
                      ["ahyeon", "trainee", "evaluation", "vocals", "predebut"], None),
    "reveal_ahyeon": ("BABYMONSTER 'AHYEON' live performance reveal", "doc",
                      ["ahyeon", "reveal", "predebut", "vocals"], None),
    "dangerously":   ("Ahyeon — Dangerously (Charlie Puth cover)", "doc",
                      ["ahyeon", "cover", "dangerously", "vocals", "itunest chart"], None),
    "batterup_stage": ("BABYMONSTER BATTER UP — Inkigayo debut stage", "stage",
                       ["ahyeon", "batterup", "stage", "debut", "inkigayo"], None),
    "sheesh_stage":  ("BABYMONSTER SHEESH — Inkigayo comeback stage", "stage",
                      ["ahyeon", "sheesh", "stage", "comeback", "inkigayo"], "0fbEdyV1dMA"),
    "mama_golden":   ("BABYMONSTER — 2025 MAMA Awards stage", "stage",
                      ["ahyeon", "mama", "awards", "stage", "2025"], None),
    "kspo":          ("BABYMONSTER KSPO DOME — Hello Monsters tour", "stage",
                      ["ahyeon", "tour", "concert", "kspo", "2025"], None),
    "dome_fancam":   ("BABYMONSTER Kyocera Dome Osaka concert", "stage",
                      ["ahyeon", "tour", "dome", "concert", "japan"], None),
    "choom_stage":   ("BABYMONSTER CHOOM — Music Core comeback stage", "stage",
                      ["ahyeon", "choom", "stage", "musiccore", "2025"], None),
    "likethat":      ("BABYMONSTER 'LIKE THAT' performance", "misc",
                      ["ahyeon", "likethat", "bside", "2024"], "M8r3x4Re8-I"),
    "reallylikeyou": ("BABYMONSTER 'REALLY LIKE YOU' stage", "misc",
                      ["ahyeon", "reallylikeyou", "stage", "2024"], None),
    "interview":     ("BABYMONSTER Ahyeon interview (English)", "misc",
                      ["ahyeon", "interview", "english", "personality"], None),
}


def probe_dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def dl(mirror, out):
    fmt = "b[height<=720][ext=mp4]/b[height<=720]/bv*[height<=720]+ba/b"
    cmd = ["python3", "-m", "yt_dlp", "--no-cache-dir", "--no-check-certificates",
           "--js-runtimes", "node", "-f", fmt, "--merge-output-format", "mp4",
           "--no-part", "-o", out, mirror]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=580)
    ok = r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 1_000_000
    if ok:
        d = probe_dur(out)
        ok = d > 20.0
    return ok, (r.stderr or "")[-200:]


def main():
    os.makedirs(POOL, exist_ok=True)
    try:
        mirrors = json.load(open(os.path.join(LS, "projects", "ahyeon", "mirrors.json")))
    except Exception:
        mirrors = {}
    manifest_p = os.path.join(POOL, "manifest.json")
    manifest = {}
    if os.path.isfile(manifest_p):
        manifest = json.load(open(manifest_p))
    only = sys.argv[1:] if len(sys.argv) > 1 else None
    got = 0
    for key, (title, kind, tags, ytid) in SOURCES.items():
        if only and key not in only:
            continue
        out = os.path.join(POOL, f"{key}.mp4")
        if os.path.isfile(out) and os.path.getsize(out) > 1_000_000 and probe_dur(out) > 20:
            manifest[key] = manifest.get(key) or {
                "title": title, "kind": kind, "subject_tags": tags,
                "youtube_id": ytid, "source_url": "cached"}
            got += 1
            continue
        cands = mirrors.get(key, [])
        # last resort: search-based mirror probing is NOT allowed (determinism);
        # a source without a mirror is recorded as a gap
        if not cands:
            print(f"GAP {key}: no mirror candidates — recorded, not faked", flush=True)
            manifest[key] = {"title": title, "kind": kind, "subject_tags": tags,
                             "youtube_id": ytid, "source_url": None, "state": "gap"}
            continue
        ok, err = False, ""
        for u in cands:
            try:
                ok, err = dl(u, out)
            except subprocess.TimeoutExpired:
                ok, err = False, "timeout"
            if ok:
                manifest[key] = {"title": title, "kind": kind, "subject_tags": tags,
                                 "youtube_id": ytid, "source_url": u,
                                 "size_bytes": os.path.getsize(out),
                                 "duration": round(probe_dur(out), 1),
                                 "state": "ok"}
                print(f"OK  {key} <- {u} ({manifest[key]['duration']}s, "
                      f"{manifest[key]['size_bytes']//1048576}MB)", flush=True)
                break
        if not ok:
            if os.path.exists(out):
                os.remove(out)
            print(f"FAIL {key}: {err}", flush=True)
            manifest[key] = {"title": title, "kind": kind, "subject_tags": tags,
                             "youtube_id": ytid, "source_url": None,
                             "state": "failed", "error": err}
        got += int(ok)
        json.dump(manifest, open(manifest_p, "w"), indent=1)
    json.dump(manifest, open(manifest_p, "w"), indent=1)
    n_ok = sum(1 for v in manifest.values() if v.get("state") == "ok"
               or os.path.isfile(os.path.join(POOL, f"{list(SOURCES)[0]}.mp4")) and False)
    n_ok = sum(1 for k, v in manifest.items()
               if v.get("state") == "ok" or (os.path.isfile(os.path.join(POOL, f"{k}.mp4"))
                                             and v.get("source_url")))
    print(f"\nPOOL: {n_ok}/{len(SOURCES)} sources acquired", flush=True)


if __name__ == "__main__":
    main()
