#!/usr/bin/env python3
"""Re-farm the MV footage pool on OUR OWN SERVER (R13: never GH Actions).

1. Resolve each pool key to an official video id via yt-dlp ytsearch
   (metadata only) with seed overrides for ids verified in the v1 run.
2. Write 04_media/pool/manifest.json (key -> {id, title}).
3. Download each video (720p) via the ytagent cobalt ladder; fall back to
   yt-dlp only if the ladder is down.
"""
import json, os, subprocess, sys

BASE = "/home/z/my-project/vfactory"
YT = BASE + "/runs/blackpink-gamble/04_media"
POOL = YT + "/pool"

# ids verified working in the v1 pool (from actual downloaded files)
SEED = {
    "ddudu": "IHNzOHi8sJs",
    "boombayah": "bwmSjveL3Lc",
    "hylt": "ioNng23DkIM",
    "deadline_tr": "5eeO8wMjL3k",
    "goyang_bts": "zTnAvaoHR4I",
    "jennie_mantra": "bB3-CUMERIU",
    "asiif": "Amq-qlqbjYA",
}
QUERIES = {
    "whistle": "BLACKPINK WHISTLE official MV",
    "killthis": "BLACKPINK Kill This Love official MV",
    "stay": "BLACKPINK STAY official MV",
    "pinkvenom": "BLACKPINK Pink Venom official MV",
    "shutdown": "BLACKPINK Shut Down official MV",
    "lovesick": "BLACKPINK Lovesick Girls official MV",
    "playingfire": "BLACKPINK Playing with Fire official MV",
    "jennie_solo": "JENNIE SOLO official MV",
    "lisa_lalisa": "LISA LALISA official MV",
    "lisa_rock": "LISA ROCKSTAR official MV",
    "rose_apt": "ROSÉ APT. official MV bruno mars",
    "rose_otg": "ROSÉ On The Ground official MV",
    "jisoo_flower": "JISOO FLOWER official MV",
    "jisoo_quake": "JISOO QUAKE official MV",
    "jump_mv": "BLACKPINK JUMP official MV",
    "jump_live": "BLACKPINK JUMP live stage",
}


def search_id(query):
    r = subprocess.run(
        ["yt-dlp", "--no-warnings", "--print", "%(id)s|%(title)s",
         f"ytsearch1:{query}"], capture_output=True, text=True, timeout=60)
    for ln in r.stdout.strip().splitlines():
        if "|" in ln:
            vid, title = ln.split("|", 1)
            if vid and len(vid) == 11:
                return vid, title
    return None, None


def download(key, vid):
    out = f"{POOL}/{key}_{vid}.mp4"
    if os.path.isfile(out) and os.path.getsize(out) > 1_000_000:
        print(f"  {key}: already downloaded", flush=True)
        return True
    import shutil
    bare = f"{POOL}/{vid}.mp4"          # raw-id file from an earlier run
    if os.path.isfile(bare) and os.path.getsize(bare) > 1_000_000:
        shutil.move(bare, out)
        print(f"  {key}: renamed existing {vid}.mp4", flush=True)
        return True
    # proven path: ytagent cobalt ladder on this server (R13 compliant)
    env = dict(os.environ, PYTHONPATH="/home/z/my-project/agent-tools/ytagent/src")
    try:
        r = subprocess.run(
            ["python3", "-m", "ytagent.cli", "download", vid,
             "--out-dir", "/tmp/ytfarm"],
            capture_output=True, text=True, timeout=540, env=env,
            cwd="/home/z/my-project/agent-tools/ytagent")
    except subprocess.TimeoutExpired:
        r = None
    # ytagent writes /tmp/ytfarm/<ID>.mp4 (or its own tree) — locate + move
    import glob, shutil
    for pat in (f"/tmp/ytfarm/**/*{vid}*.mp4",
                f"/home/z/my-project/agent-tools/ytagent/**/*{vid}*.mp4",
                f"/tmp/**/{vid}.mp4"):
        for c in glob.glob(pat, recursive=True):
            if os.path.isfile(c) and os.path.getsize(c) > 1_000_000:
                shutil.move(c, out)
                print(f"  {key}: ok {os.path.getsize(out)//1048576}MB", flush=True)
                return True
    print(f"  {key}: ytagent failed ({(r.stderr[-120:] if r else 'timeout')})",
          flush=True)
    return False


def _collect(vid, out):
    """ytagent writes somewhere under its tree; find and move the file."""
    import glob, shutil, time
    pats = ["/home/z/my-project/agent-tools/ytagent/**/*%s*.mp4" % vid,
            "/home/z/my-project/agent-tools/ytagent/downloads/**/%s*" % vid,
            "/tmp/*%s*" % vid]
    for pat in pats:
        for c in glob.glob(pat, recursive=True):
            if os.path.isfile(c) and os.path.getsize(c) > 1_000_000:
                if os.path.abspath(c) != os.path.abspath(out):
                    shutil.move(c, out)
                return True
    return False


def main():
    os.makedirs(POOL, exist_ok=True)
    os.makedirs("/tmp/ytfarm", exist_ok=True)
    mf = POOL + "/manifest.json"
    manifest = json.load(open(mf)) if os.path.isfile(mf) else {}
    # merge resolved search ids
    sp = YT + "/search_ids.json"
    if os.path.isfile(sp):
        found = json.load(open(sp))
        for key, hits in found.items():
            if hits and key not in manifest:
                manifest[key] = {"id": hits[0]["id"], "title": hits[0]["title"],
                                 "query": "web-search"}
    for key, vid in SEED.items():
        manifest.setdefault(key, {"id": vid, "title": key, "query": "seed"})
    # dedupe identical ids (first key wins)
    seen, dedup = {}, {}
    for key in sorted(manifest):
        vid = manifest[key]["id"]
        if vid in seen:
            print(f"  dedupe: {key} shares {vid} with {seen[vid]} — dropped", flush=True)
            continue
        seen[vid] = key
        dedup[key] = manifest[key]
    manifest = dedup
    json.dump(manifest, open(mf, "w"), indent=1)
    print(f"manifest: {len(manifest)} keys", flush=True)
    ok = fail = 0
    for key, meta in sorted(manifest.items()):
        if download(key, meta["id"]):
            ok += 1
        else:
            fail += 1
            print(f"  {key}: DOWNLOAD FAILED", flush=True)
    print(f"pool ready: {ok} ok, {fail} failed, {len(manifest)} keys", flush=True)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
