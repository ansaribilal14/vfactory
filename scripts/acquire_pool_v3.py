#!/usr/bin/env python3
"""acquire_pool_v3.py — DEDICATED-FIRST Ahyeon footage acquisition (v3).

User verdict on v2: "still using random music videos instead of ahyeon
dedicated direction". Root cause: the pool was dominated by full-group MVs
(where Ahyeon is on screen a small fraction of the time) and dedicated
sources were diluted. v3 inverts the ratio:

  BACKBONE (kind=fancam/cover/doc/interview): fixed-camera AHYEON footage —
  facecams per song, the Dangerously cover, Last Evaluation cuts, interviews,
  the member reveal. 100% Ahyeon by construction.

  SECONDARY (kind=mv/stage): group MVs and stages — used by the Director
  ONLY at presence-map-verified "Ahyeon clearly on screen" spans.

Acquisition rail: dailymotion public search API + yt_dlp (YouTube is
bot-walled in this sandbox; AGENT.md forbids GitHub-Actions YT fetching).
Every key carries full provenance in the manifest.
"""
import json, os, re, subprocess, sys, time, urllib.parse, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = os.path.join(BASE, "runs", "ahyeon-it-girl-v3")
POOL = os.path.join(RUN, "04_media", "pool")
DL_PY = "/usr/bin/python3"          # venv python lacks yt_dlp; system python has it
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) vfactory/3.0"}

# key -> (kind, title, search queries (tried in order), dur_range, subject_tags)
# dedicated sources get tag "ahyeon_dedicated" appended automatically.
PLAN = {
    # ---------------- dedicated backbone ----------------
    "fc_sheesh":     ("fancam", "AHYEON (BABYMONSTER) SHEESH facecam/fancam",
                      ["BABYMONSTER AHYEON SHEESH fancam", "AHYEON SHEESH 직캠",
                       "AHYEON SHEESH facecam", "베이비몬스터 아현 직캠", "AHYEON SHEESH cam 4k"], (90, 400),
                      ["ahyeon", "sheesh", "stage", "2024", "comeback"]),
    "fc_drip":       ("fancam", "AHYEON (BABYMONSTER) DRIP facecam/fancam",
                      ["BABYMONSTER AHYEON DRIP fancam", "AHYEON DRIP 직캠",
                       "AHYEON DRIP facecam", "베이비몬스터 아현 드립 직캠"], (90, 400),
                      ["ahyeon", "drip", "stage", "2024"]),
    "fc_forever":    ("fancam", "AHYEON (BABYMONSTER) FOREVER facecam/fancam",
                      ["BABYMONSTER AHYEON FOREVER fancam", "AHYEON FOREVER 직캠"],
                      (90, 400), ["ahyeon", "forever", "stage", "2024"]),
    "fc_batterup":   ("fancam", "AHYEON (BABYMONSTER) BATTER UP facecam/fancam",
                      ["BABYMONSTER AHYEON BATTER UP fancam", "AHYEON BATTER UP 직캠"],
                      (90, 400), ["ahyeon", "batterup", "stage", "2023", "debut"]),
    "fc_sitm":       ("fancam", "AHYEON (BABYMONSTER) STUCK IN THE MIDDLE fancam",
                      ["BABYMONSTER AHYEON STUCK IN THE MIDDLE fancam",
                       "AHYEON STUCK IN THE MIDDLE 직캠"], (90, 400),
                      ["ahyeon", "stuck", "ballad", "stage", "2024"]),
    "fc_hotsauce":   ("fancam", "AHYEON (BABYMONSTER) HOT SAUCE facecam/fancam",
                      ["BABYMONSTER AHYEON HOT SAUCE fancam", "AHYEON HOT SAUCE 직캠"],
                      (90, 400), ["ahyeon", "hotsauce", "stage", "2025"]),
    "fc_wegoup":     ("fancam", "AHYEON (BABYMONSTER) WE GO UP facecam/fancam",
                      ["BABYMONSTER AHYEON WE GO UP fancam", "AHYEON WE GO UP 직캠"],
                      (90, 400), ["ahyeon", "wegoup", "stage", "2025"]),
    "cov_dangerously": ("cover", "AHYEON — Dangerously (Charlie Puth) cover",
                        ["BABYMONSTER AHYEON Dangerously cover",
                         "AHYEON Dangerously"], (80, 300),
                        ["ahyeon", "dangerously", "cover", "vocals", "predebut"]),
    "eval_ahyeon":   ("doc", "BABYMONSTER Last Evaluation — Ahyeon cut",
                      ["BABYMONSTER Last Evaluation Ahyeon",
                       "BABYMONSTER Last Evaluation performance",
                       "BABYMONSTER Last Evaluation",
                       "BABYMONSTER evaluation Ahyeon danger"], (120, 900),
                      ["ahyeon", "trainee", "evaluation", "predebut", "yg"]),
    "reveal_ahyeon": ("doc", "BABYMONSTER member reveal — AHYEON",
                      ["BABYMONSTER AHYEON reveal", "BABYMONSTER AHYEU",
                       "BABYMONSTER Ahyeon introduction"], (30, 400),
                      ["ahyeon", "reveal", "predebut", "yg"]),
    "int_ahyeon":    ("interview", "AHYEON interview / speaking cuts",
                      ["BABYMONSTER AHYEON interview english",
                       "BABYMONSTER interview ahyeon",
                       "AHYEON speaking english interview"],
                      (60, 900), ["ahyeon", "interview", "personality", "english"]),
    # ---------------- group secondary ----------------
    "mv_batterup":   ("mv", "BABYMONSTER - 'BATTER UP' M/V",
                      ["BABYMONSTER BATTER UP MV", "BABYMONSTER BATTER UP"],
                      (150, 300),
                      ["ahyeon", "babymonster", "batterup", "debut", "2023"]),
    "mv_sheesh":     ("mv", "BABYMONSTER - 'SHEESH' M/V",
                      ["BABYMONSTER SHEESH MV"], (150, 320),
                      ["ahyeon", "babymonster", "sheesh", "2024"]),
    "mv_forever":    ("mv", "BABYMONSTER - 'FOREVER' M/V",
                      ["BABYMONSTER FOREVER MV"], (150, 320),
                      ["ahyeon", "babymonster", "forever", "2024"]),
    "mv_drip":       ("mv", "BABYMONSTER - 'DRIP' M/V",
                      ["BABYMONSTER DRIP MV"], (150, 320),
                      ["ahyeon", "babymonster", "drip", "2024"]),
    "mv_sitm":       ("mv", "BABYMONSTER - 'STUCK IN THE MIDDLE' M/V",
                      ["BABYMONSTER STUCK IN THE MIDDLE MV"], (150, 320),
                      ["ahyeon", "babymonster", "stuck", "ballad", "2024"]),
    "mv_hotsauce":   ("mv", "BABYMONSTER - 'HOT SAUCE' M/V",
                      ["BABYMONSTER HOT SAUCE MV"], (150, 320),
                      ["ahyeon", "babymonster", "hotsauce", "2025"]),
    "mv_wegoup":     ("mv", "BABYMONSTER - 'WE GO UP' M/V",
                      ["BABYMONSTER WE GO UP MV"], (150, 320),
                      ["ahyeon", "babymonster", "wegoup", "2025"]),
    "stage_sheesh":  ("stage", "BABYMONSTER SHEESH group music-show stage",
                      ["BABYMONSTER SHEESH Inkigayo", "BABYMONSTER SHEESH stage"],
                      (140, 330), ["ahyeon", "babymonster", "sheesh", "stage"]),
    "stage_drip":    ("stage", "BABYMONSTER DRIP group music-show stage",
                      ["BABYMONSTER DRIP stage inkigayo", "BABYMONSTER DRIP live"],
                      (140, 330), ["ahyeon", "babymonster", "drip", "stage"]),
}

BAD_TITLE = re.compile(
    r"shorts|tiktok|reaction|reaccion|edit\b|fmv|ai\b|ranking|top\s*10|tier\s*list|"
    r"vs\b|dance practice mirrored|mirror[^e]|slowed|sped up|nightcore|1\s*hour|"
    r"instrumental|karaoke|lyric|lirik|terjemahan|sub esp|color coded|audio|"
    r"playlist|compilation|megamix", re.I)
GOOD_TITLE = re.compile(r"ahyeon|아현|babymonster|베이비몬스터", re.I)

# per-key REQUIRED title tokens (any-of) — guarantees song/subject match so a
# video can never be reused under the wrong key. Fancam keys additionally
# REQUIRE a fancam/facecam token so group MVs never pose as dedicated footage.
REQ_TOKENS = {
    "fc_sheesh":   ("sheesh", "시시"),
    "fc_drip":     ("drip", "드립"),
    "fc_forever":  ("forever",),
    "fc_batterup": ("batter", "배터"),
    "fc_sitm":     ("stuck", "middle", "스틱"),
    "fc_hotsauce": ("hot sauce", "hotsauce", "핫소스"),
    "fc_wegoup":   ("we go up", "wegoup", "go up"),
    "cov_dangerously": ("dangerously",),
    "eval_ahyeon": ("evaluation", "eval"),
    "reveal_ahyeon": ("reveal", "ahyeu", "introduc", "profile", "아현"),
    "int_ahyeon":  ("interview", "speak", "talk", "radio", "vlog", "english interview"),
    "mv_batterup": ("batter",),
    "mv_sheesh":   ("sheesh",),
    "mv_forever":  ("forever",),
    "mv_drip":     ("drip",),
    "mv_sitm":     ("stuck", "middle"),
    "mv_hotsauce": ("hot sauce", "hotsauce"),
    "mv_wegoup":   ("we go up", "wegoup", "go up"),
    "stage_sheesh": ("sheesh",),
    "stage_drip":  ("drip",),
}
FANCAM_TOKEN = re.compile(r"fancam|facecam|직캠|페이스캠|cam\b", re.I)
DEDICATED_KEYS = {"fc_sheesh", "fc_drip", "fc_forever", "fc_batterup",
                  "fc_sitm", "fc_hotsauce", "fc_wegoup", "cov_dangerously",
                  "eval_ahyeon", "reveal_ahyeon", "int_ahyeon"}


def http_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def dm_search(query, limit=40, page=1):
    q = urllib.parse.quote(query)
    url = ("https://api.dailymotion.com/videos?search=" + q +
           f"&fields=id,title,duration,views_total,created_time&limit={limit}"
           f"&page={page}")
    try:
        return http_json(url).get("list", [])
    except Exception as e:
        print(f"    search fail: {e}", flush=True)
        return []


def title_ok(title, key, kind):
    """Hard gate: required song/subject tokens must be present. Fancam keys
    must ALSO show a fancam token (group MVs never pose as dedicated)."""
    t = title.lower()
    req = REQ_TOKENS.get(key, ())
    if req and not any(r in t for r in req):
        return False
    if key in DEDICATED_KEYS and not ("ahyeon" in t or "아현" in t
                                      or "babymonster" in t or "베이비몬스터" in t):
        return False
    if key.startswith("fc_"):
        if not re.search(r"ahyeon|아현", t):
            return False            # the facecam must name AHYEON herself
        # unit cams ("ahyeon & asa") pass; other-member solo cams rejected
        others = [m for m in ("ruka", "pharita", "asa", "rora", "chiquita", "rami")
                  if m in t]
        if others and not re.search(r"ahyeon", t):
            return False
    if key.startswith("mv_"):
        if FANCAM_TOKEN.search(t):
            return False      # a fancam never serves as the MV key
        if re.search(r"mashup|cover|mix\b|remix", t):
            return False
    if key.startswith("stage_") and not re.search(
            r"stage|live|inkigayo|인기가요|music.?bank|music.?core|show.?champion|"
            r"comeback|festival|performance|kcon|mama|stage.?mix", t, re.I):
        return False
    if "english song" in t or "eng sub" in t:
        return False
    return True


def title_score(title, key, kind, query_terms):
    t = title.lower()
    if BAD_TITLE.search(t):
        return -50.0
    s = 0.0
    if GOOD_TITLE.search(t):
        s += 3.0
    if "ahyeon" in t or "아현" in t:
        s += 5.0                      # dedicated beats group content
    if "4k" in t:
        s += 0.5
    if "직캠" in t or "fancam" in t or "facecam" in t or "페이스캠" in t:
        s += 4.0 if kind == "fancam" else -2.0
    for w in query_terms:
        if w.lower() in t:
            s += 1.0
    return s


def rank_candidates(items, dur_range):
    lo, hi = dur_range
    out = []
    for it in items:
        d = it.get("duration") or 0
        if not (lo <= d <= hi):
            continue
        out.append(it)
    return out


def dl(url, out):
    fmt = "b[height<=720][ext=mp4]/b[height<=720]/bv*[height<=720]+ba/b"
    cmd = [DL_PY, "-m", "yt_dlp", "--no-cache-dir", "--no-check-certificates",
           "--js-runtimes", "node", "--socket-timeout", "25", "--retries", "2",
           "-f", fmt, "--merge-output-format", "mp4", "--no-part",
           "-o", out, url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=560)
    except subprocess.TimeoutExpired:
        return False, "timeout", 0
    ok = r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 1_000_000
    return ok, (r.stderr or "")[-180:], (os.path.getsize(out) if os.path.exists(out) else 0)


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=height:format=duration",
                        "-of", "json", path], capture_output=True, text=True)
    try:
        j = json.loads(r.stdout)
        return (float(j["format"]["duration"]),
                int(j["streams"][0].get("height") or 0))
    except Exception:
        return 0.0, 0


def acquire():
    t0 = time.time()
    budget = float(os.environ.get("VF_BUDGET", "540"))   # checkpoint window (s)
    os.makedirs(POOL, exist_ok=True)
    manifest_p = os.path.join(POOL, "manifest.json")
    manifest = {}
    if os.path.isfile(manifest_p):
        try:
            manifest = json.load(open(manifest_p))
        except Exception:
            manifest = {}
    # global exclusivity: a video id may serve ONE key only (v3.1 fix — the
    # v3.0 run reused the Dangerously cover for five different fancam keys)
    used_ids = set()
    for k, v in manifest.items():
        u = v.get("source_url") or ""
        if v.get("state") == "ok" and "/video/" in u:
            used_ids.add(u.rsplit("/", 1)[-1])
    only = sys.argv[1:] if len(sys.argv) > 1 else None
    n_ok = 0
    for key, (kind, title, queries, drange, tags) in PLAN.items():
        if only and key not in only:
            continue
        out = os.path.join(POOL, f"{key}.mp4")
        if os.path.isfile(out) and os.path.getsize(out) > 1_000_000:
            d, h = probe(out)
            if d >= drange[0] * 0.5:
                manifest[key] = manifest.get(key) or {
                    "title": title, "kind": kind, "subject_tags": tags,
                    "source_url": "cached", "duration": round(d, 1), "height": h,
                    "state": "ok"}
                n_ok += 1
                continue
        got = False
        for q in queries:
            items = dm_search(q)
            cands = [it for it in rank_candidates(items, drange)
                     if title_ok(it.get("title", ""), key, kind)
                     and it.get("id") not in used_ids]
            terms = q.split()
            cands.sort(key=lambda it: -title_score(it.get("title", ""), key, kind, terms))
            print(f"[{key}] '{q}': {len(items)} hits, {len(cands)} valid",
                  flush=True)
            for it in cands[:4]:
                vid = it.get("id")
                if not vid:
                    continue
                url = f"https://www.dailymotion.com/video/{vid}"
                print(f"    try {vid}: {it.get('title','')[:70]} "
                      f"({it.get('duration')}s)", flush=True)
                ok, err, size = dl(url, out)
                if ok:
                    d, h = probe(out)
                    if d < drange[0] * 0.5 or (0 < h < 432):
                        if os.path.exists(out):
                            os.remove(out)
                        continue
                    manifest[key] = {
                        "title": it.get("title", title)[:120], "kind": kind,
                        "subject_tags": tags + (["ahyeon_dedicated"]
                                                if kind in ("fancam", "cover",
                                                            "doc", "interview")
                                                else []),
                        "query": q, "source_url": url, "mirror": "dailymotion",
                        "dm_id": vid, "youtube_id": None,
                        "duration": round(d, 1), "height": h,
                        "size_bytes": size, "state": "ok"}
                    used_ids.add(vid)
                    print(f"    OK  {key} <- {vid} ({d:.0f}s, {h}p, "
                          f"{size//1048576}MB)", flush=True)
                    got = True
                    break
                else:
                    if os.path.exists(out):
                        os.remove(out)
                    print(f"    fail: {err}", flush=True)
            if got:
                break
        if not got:
            manifest[key] = {"title": title, "kind": kind,
                             "subject_tags": tags, "source_url": None,
                             "state": "gap"}
            print(f"    GAP {key}: no usable mirror candidate", flush=True)
        n_ok += int(got)
        json.dump(manifest, open(manifest_p, "w"), indent=1)
        if time.time() - t0 > budget:
            print(f"[budget] {time.time()-t0:.0f}s elapsed — checkpointing "
                  f"(re-run to continue)", flush=True)
            break
    json.dump(manifest, open(manifest_p, "w"), indent=1)
    n_ded = sum(1 for v in manifest.values()
                if v.get("state") == "ok" and "ahyeon_dedicated" in v.get("subject_tags", []))
    print(f"\nPOOL: {n_ok}/{len(PLAN)} acquired "
          f"({n_ded} dedicated) -> {manifest_p}", flush=True)


if __name__ == "__main__":
    acquire()
