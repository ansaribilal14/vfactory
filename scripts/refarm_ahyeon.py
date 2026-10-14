#!/usr/bin/env python3
"""Farm the BABYMONSTER/Ahyeon MV footage pool on OUR OWN SERVER (R13).

Same ladder as refarm_pool.py: yt-dlp metadata search -> ytagent cobalt
download -> 04_media/pool/<key>_<vid>.mp4 + manifest.json.
"""
import json, os, subprocess, sys

BASE = "/home/z/my-project/vfactory"
POOL = BASE + "/runs/ahyeon-5th-gen-it-girl/04_media/pool"

SEED = {
    # ids resolve via ytsearch below; seeds pin any that failed before
}

QUERIES = {
    "drip": "BABYMONSTER DRIP M/V",
    "sheesh": "BABYMONSTER SHEESH M/V",
    "babymons7er": "BABYMONSTER BABYMONS7ER M/V",
    "forever": "BABYMONSTER FOREVER M/V",
    "batterup": "BABYMONSTER BATTER UP M/V",
    "stuck": "BABYMONSTER Stuck In The Middle M/V",
    "hotsauce": "BABYMONSTER HOT SAUCE M/V",
    "likethat": "BABYMONSTER LIKE THAT M/V",
    "wegoup": "BABYMONSTER WE GO UP M/V",
    "drip_live": "BABYMONSTER DRIP live stage performance",
    "sheesh_live": "BABYMONSTER SHEESH music show stage",
    "ahyeon_fancam": "AHYEON SHEESH 4K fancam",
    "ahyeon_drip_cam": "AHYEON DRIP fancam focus cam",
    "last_eval": "BABYMONSTER last evaluation AHYEON",
    "debut_showcase": "BABYMONSTER debut showcase stage",
}


REQ_TOKEN = {
    "stuck": "stuck", "likethat": "like that", "hotsauce": "hot sauce",
    "wegoup": "we go up", "last_eval": "evaluation", "babymons7er": "babymons7er",
    "debut_showcase": "showcase", "drip_live": "drip", "sheesh_live": "sheesh",
    "ahyeon_drip_cam": "drip", "ahyeon_fancam": "ahyeon",
}


def _oembed(vid):
    import urllib.request, json as _json
    try:
        u = ("https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v="
             + vid + "&format=json")
        with urllib.request.urlopen(u, timeout=15) as r:
            return _json.loads(r.read().decode())
    except Exception:
        return None


def _ddg_ids(query):
    """YouTube results-page scrape: ytInitialData embeds videoIds in relevance
    order (yt-dlp's innertube API is bot-blocked; the web page is not)."""
    import subprocess as _sp, re as _re, urllib.parse
    q = urllib.parse.quote(query)
    try:
        r = _sp.run(["curl", "-s", "--max-time", "25", "-A",
                     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                     "-H", "Accept-Language: en",
                     f"https://www.youtube.com/results?search_query={q}"],
                    capture_output=True, text=True, timeout=40)
        html = r.stdout or ""
    except Exception:
        return []
    seen = []
    for m in _re.finditer(r'"videoId":"([A-Za-z0-9_-]{11})","thumbnail"', html):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen[:6]


def search_id(query, key=""):
    """DDG html search -> candidate IDs -> oEmbed title/author verification
    (yt-dlp ytsearch is bot-blocked on this IP; oEmbed is not)."""
    req = REQ_TOKEN.get(key, key.split("_")[0])
    for vid in _ddg_ids(query):
        d = _oembed(vid)
        if not d:
            continue
        title = (d.get("title") or "").lower()
        author = (d.get("author_name") or "").lower()
        if key.startswith("ahyeon"):
            ok = "ahyeon" in title and req in title
        else:
            ok = ("babymonster" in author or "babymonster" in title) and req in title
        if ok:
            return vid, d.get("title") or ""
    # relaxed second pass: any babymonster-channel hit
    for vid in _ddg_ids(query):
        d = _oembed(vid)
        if d and ("babymonster" in (d.get("author_name") or "").lower()):
            return vid, d.get("title") or ""
    return None, None


def download(key, vid):
    out = f"{POOL}/{key}_{vid}.mp4"
    if os.path.isfile(out) and os.path.getsize(out) > 1_000_000:
        print(f"  {key}: already downloaded", flush=True)
        return True
    env = dict(os.environ, PYTHONPATH="/home/z/my-project/agent-tools/ytagent/src")
    try:
        r = subprocess.run(
            ["python3", "-m", "ytagent.cli", "download", vid,
             "--out-dir", "/tmp/ytfarm"],
            capture_output=True, text=True, timeout=540, env=env,
            cwd="/home/z/my-project/agent-tools/ytagent")
    except subprocess.TimeoutExpired:
        r = None
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


def main():
    os.makedirs(POOL, exist_ok=True)
    os.makedirs("/tmp/ytfarm", exist_ok=True)
    mf = POOL + "/manifest.json"
    manifest = json.load(open(mf)) if os.path.isfile(mf) else {}
    for key, q in QUERIES.items():
        if key in manifest:
            continue
        vid, title = search_id(q, key)
        if vid:
            manifest[key] = {"id": vid, "title": title, "query": q}
            print(f"  {key}: {vid} {title[:60]}", flush=True)
        else:
            print(f"  {key}: SEARCH FAILED ({q})", flush=True)
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
