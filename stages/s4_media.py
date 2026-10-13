#!/usr/bin/env python3
"""Stage 4 (v2): REAL-footage b-roll editor — no images, no slideshow.

User hard rules (R2/R5/R10/R13, re-confirmed 2026-10-13):
  - image slideshows are FORBIDDEN; visuals must be real footage
  - footage must match scene semantics (era / member / song / event)
  - dynamic multi-cut pacing: 2-6 distinct shots per scene, hard cuts,
    NO long single slow-zoom segment per scene
  - all downloads happen on OUR OWN SERVER (ytagent ladder) — never GH Actions

Input:  02_script.json, 04_media/pool/*.mp4 + pool/manifest.json
        (optional 04_media/pool1080/*.mp4 — preferred when present)
Output: 04_media/scenes/scene_XX.mp4 (1280x720@30, crf 17, exact scene dur)
        04_media.json (scene -> segments used, fully auditable)
"""
import json, os, re, shutil, subprocess, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

W, H = 1280, 720
FPS = 30
SKIP_HEAD = 8.0     # skip MV intros (logos)
SKIP_TAIL = 6.0     # skip outros
MIN_SEG, MAX_SEG = 3.0, 9.0
GAP = 6.0           # min gap between reused ranges in one source

# extra semantic hints per pool key (filename stem before "_<videoid>")
ALIASES = {
    "ddudu": ["ddu-du", "ddu", "tiger", "identity", "signature", "2018", "debut era", "iconic"],
    "hylt": ["how you like that", "hylt", "comeback", "2020", "return", "anthem"],
    "jump_mv": ["jump", "2025", "reunion", "deadline", "new song", "comeback single"],
    "jump_live": ["jump", "live", "stage", "concert", "tour", "deadline tour", "fans"],
    "boombayah": ["boombayah", "debut", "2016", "first", "whistle", "square one", " rookie"],
    "whistle": ["whistle", "debut", "2016", "square one", "wind"],
    "killthis": ["kill this love", "2019", "coachella", "war", "comeback"],
    "stay": ["stay", "acoustic", "ballad", "soft", "emotional", "quiet"],
    "pinkvenom": ["pink venom", "born pink", "2022", "comeback", "venom"],
    "shutdown": ["shut down", "born pink", "2022", "classical", "piacente", "tpok"],
    "lovesick": ["lovesick girls", "born pink", "2022", "love", "pain", "girls"],
    "playingfire": ["playing with fire", "2016", "square two", "fire"],
    "jennie_solo": ["jennie", "solo", "2018", "first solo", "independent"],
    "jennie_mantra": ["jennie", "mantra", "2024", "solo", "ruby", "return"],
    "lisa_lalisa": ["lisa", "lalisa", "2021", "solo", "first solo", "thailand"],
    "lisa_rock": ["lisa", "rockstar", "2024", "rockstar", "solo", "new soul"],
    "rose_apt": ["rose", "rosie", "apt", "apartment", "bruno", "2024", "record", "billboard"],
    "rose_otg": ["rose", "on the ground", "2021", "solo", "r", "gone"],
    "jisoo_flower": ["jisoo", "flower", "2023", "solo", "me"],
    "jisoo_quake": ["jisoo", "quake", "2024", "amen", "solo", "return"],
    "deadline_tr": ["deadline", "tour", "2025", "rehearsal", "trailer", "reunion", "stadium"],
    "goyang_bts": ["deadline", "goyang", "rehearsal", "behind", "2025", "practice", "tour"],
    "asiif": ["blackpink", "members", "group", "documentary", "profile"],
}

MEMBERS = ["jennie", "lisa", "jisoo", "rose", "rosie", "rosé"]


def ffprobe_dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def load_pool(media_dir):
    """pool key -> {path, dur, title} preferring 1080p upgrades."""
    manifest = json.load(open(os.path.join(media_dir, "pool", "manifest.json")))
    up_dir = os.path.join(media_dir, "pool1080")
    pool = {}
    for key, meta in manifest.items():
        vid = meta["id"]
        cands = []
        if os.path.isdir(up_dir):
            for f in os.listdir(up_dir):
                if vid in f and f.endswith(".mp4"):
                    p = os.path.join(up_dir, f)
                    if os.path.getsize(p) > 1_000_000:
                        cands.append((1, p))          # 1080 upgrade
        p720 = os.path.join(media_dir, "pool", f"{key}_{vid}.mp4")
        if os.path.isfile(p720) and os.path.getsize(p720) > 1_000_000:
            cands.append((0, p720))
        if not cands:
            continue
        cands.sort(reverse=True)
        pool[key] = {"path": cands[0][1], "title": (meta.get("title") or "").lower(),
                     "id": vid, "dur": 0.0}
    for k, v in pool.items():
        v["dur"] = ffprobe_dur(v["path"])
    return pool


def score_scene(text, key, meta):
    tags = set(re.findall(r"[a-z0-9']+", key)) | set(ALIASES.get(key, []))
    tags |= set(re.findall(r"[a-z0-9']+", meta["title"]))
    hits = 0
    words = set(re.findall(r"[a-z0-9']+", text))
    for t in tags:
        if len(t) < 3:
            continue
        if t in text or t in words:
            hits += 2
    # member-name boost
    for m in MEMBERS:
        if m in text and m in meta["title"] + key + " ".join(ALIASES.get(key, [])):
            hits += 2
    return hits


def pick_ranges(pool, ranked, T, nseg, used, rot):
    """Choose nseg (key, start, len) shots filling ~T seconds."""
    seglen = max(MIN_SEG, min(MAX_SEG, T / max(nseg, 1)))
    picks = []
    for key in ranked:
        if len(picks) >= nseg:
            break
        meta = pool[key]
        usable = meta["dur"] - SKIP_TAIL - seglen
        if usable <= SKIP_HEAD:
            continue
        intervals = used.get(key, [])
        start = SKIP_HEAD + (rot * seglen * 1.7) % max(usable - SKIP_HEAD, 1)
        for _ in range(60):
            if all(abs(start - s) > GAP + seglen for s, _ in intervals):
                picks.append((key, round(start, 2), round(seglen, 2)))
                used.setdefault(key, []).append((start, start + seglen))
                break
            start += seglen + GAP
            if start > usable:
                start = SKIP_HEAD + (start - usable) % max(usable - SKIP_HEAD, 1)
    # top up if pool ran thin (allow repeats with fresh offsets)
    i = 0
    while len(picks) < nseg and ranked:
        key = ranked[i % len(ranked)]
        meta = pool[key]
        usable = meta["dur"] - SKIP_TAIL - seglen
        if usable > SKIP_HEAD:
            start = SKIP_HEAD + ((rot + 13 * (i + 1)) * 4.3) % max(usable - SKIP_HEAD, 1)
            picks.append((key, round(start, 2), round(seglen, 2)))
        i += 1
        if i > 12:
            break
    return picks


def cut_scene(pool, picks, T, out):
    """Hard-cut multi-shot scene: input-seek each shot, concat, cap to T."""
    if not picks:
        raise RuntimeError("no footage picks for scene")
    inputs, fparts, refs = [], [], []
    for i, (key, start, ln) in enumerate(picks):
        inputs += ["-ss", f"{start:.2f}", "-t", f"{ln:.2f}", "-i", pool[key]["path"]]
        fparts.append(
            f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1,fps={FPS},trim=duration={ln:.2f},"
            f"setpts=PTS-STARTPTS[v{i}]")
        refs.append(f"[v{i}]")
    total = sum(p[2] for p in picks)
    fc = (";".join(fparts) + ";" + "".join(refs) +
          f"concat=n={len(picks)}:v=1:a=0,fade=t=in:d=0.30,fade=t=out:"
          f"st={max(total - 0.35, 0):.2f}:d=0.35,trim=duration={T:.2f},"
          f"setpts=PTS-STARTPTS[out]")
    cmd = (["ffmpeg", "-y", "-v", "error"] + inputs +
           ["-filter_complex", fc, "-map", "[out]", "-t", f"{T:.2f}",
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17",
            "-pix_fmt", "yuv420p", out])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg scene cut failed: {r.stderr[-300:]}")


def run(run_dir):
    media_dir = os.path.join(run_dir, "04_media")
    scenes_dir = os.path.join(media_dir, "scenes")
    os.makedirs(scenes_dir, exist_ok=True)
    # one-time purge of the legacy (zoompan/image) scene cuts
    marker = os.path.join(media_dir, ".v2")
    if not os.path.exists(marker):
        shutil.rmtree(scenes_dir, ignore_errors=True)
        os.makedirs(scenes_dir, exist_ok=True)
        open(marker, "w").write("2")
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    timings = {t["id"]: t["audio"] for t in
               json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]}
    pool = load_pool(media_dir)
    if not pool:
        raise RuntimeError("footage pool empty — s4 refuses to build an image slideshow")

    scenes = plan["scenes"] if "scenes" in plan else \
        [s for seg in plan["segments"] for s in seg["scenes"]]

    used, manifest, rot = {}, {}, 0
    for sc in scenes:
        T = max(3.5, timings.get(sc["id"], 4.0) + 0.8)
        out = os.path.join(scenes_dir, f"scene_{sc['id']:02d}.mp4")
        # resume: existing clip with the right duration is kept
        if os.path.isfile(out):
            d0 = ffprobe_dur(out)
            if abs(d0 - T) < 1.0:
                manifest[str(sc["id"])] = {"path": out, "kind": "video",
                                           "dur": round(d0, 2), "shots": []}
                print(f"scene {sc['id']:>2}: resume ({d0:.1f}s)", flush=True)
                rot = (rot + 1) % 7
                continue
        text = " ".join([sc.get("narration", ""), sc.get("visual_query", ""),
                         sc.get("on_screen", ""), sc.get("notes", "")]).lower()
        ranked = sorted(pool, key=lambda k: -score_scene(text, k, pool[k]))
        nseg = max(2, min(6, round(T / 7)))
        picks = pick_ranges(pool, ranked, T, nseg, used, rot)
        cut_scene(pool, picks, T, out)
        dur = ffprobe_dur(out)
        manifest[str(sc["id"])] = {"path": out, "kind": "video", "dur": round(dur, 2),
                                   "shots": [{"src": k, "start": s, "len": l}
                                             for k, s, l in picks]}
        rot = (rot + 1) % 7
        print(f"scene {sc['id']:>2}: {dur:5.1f}s  shots={[(k, s) for k, s, _ in picks]}",
              flush=True)

    json.dump(manifest, open(os.path.join(run_dir, "04_media.json"), "w"), indent=1)
    print(f"s4 done: {len(manifest)} real-footage scenes (no images, no cards)", flush=True)
    return manifest


if __name__ == "__main__":
    run(sys.argv[1])
