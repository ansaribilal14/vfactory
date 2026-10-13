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
    # proven path: ytagent cobalt ladder on this server
    for cli in (["python3", "-m", "ytagent", "download", vid],
                ["ytagent", "download", vid]):
        try:
            r = subprocess.run(cli, capture_output=True, text=True,
                               timeout=540, cwd="/home/z/my-project/agent-tools/ytagent")
            if r.returncode == 0:
                moved = _collect(vid, out)
                if moved:
                    print(f"  {key}: ytagent ok -> {out}", flush=True)
                    return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
    print(f"  {key}: ytagent failed — trying yt-dlp direct", flush=True)
    r = subprocess.run(["yt-dlp", "-f", "bv*[height<=720]+ba/b[height<=720]",
                        "-o", out, "--no-part", "--no-warnings",
                        f"https://www.youtube.com/watch?v={vid}"],
                       capture_output=True, text=True, timeout=540)
    return os.path.isfile(out) and os.path.getsize(out) > 1_000_000


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
    mf = POOL + "/manifest.json"
    manifest = json.load(open(mf)) if os.path.isfile(mf) else {}
    for key, q in QUERIES.items():
        if key in manifest and manifest[key].get("id"):
            continue
        vid, title = search_id(q)
        if not vid and key in SEED:
            vid, title = SEED[key], q
        if not vid:
            print(f"  {key}: SEARCH FAILED — skipping", flush=True)
            continue
        manifest[key] = {"id": vid, "title": title, "query": q}
        json.dump(manifest, open(mf, "w"), indent=1)   # checkpoint each entry
        print(f"  {key}: {vid} ({title[:40]})", flush=True)
    json.dump(manifest, open(mf, "w"), indent=1)
    ok = fail = 0
    for key, meta in manifest.items():
        if download(key, meta["id"]):
            ok += 1
        else:
            fail += 1
            print(f"  {key}: DOWNLOAD FAILED", flush=True)
    print(f"pool ready: {ok} ok, {fail} failed, {len(manifest)} keys", flush=True)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
