#!/usr/bin/env python3
"""Stage 4 (v3): EDITORIAL FOOTAGE STAGE — shot-indexed, Director-planned.

R15 rebuild after the user verdict ("random Ahyeon clips... not an editor
way of editing"). Pipeline:

  1. INDEX   — scene-detect every pool source into SHOTS with boundaries;
               one mid-frame per shot (vision substrate) + contact sheets.
  2. PLAN    — the PERMANENT Director agent (stages/director.py) assigns
               vision-verified shots with exact in/out timecodes per scene;
               place/entity context images via lib/imgagent (narrow scope).
  3. RENDER  — deterministic EDL cuts (hard cuts, varied lengths), plus
               verified place stills with a slow one-way push (the ONLY
               still-image exception: places/entities, never the subject).

Outputs (all auditable):
  04_media/shot_index.json   — per-source shot boundaries + frames
  04_media/plan.json         — the edit decision list (Director output)
  04_media/review_queue.json — weak-relevance scenes flagged for review
  04_media/images/           — verified place imagery + provenance manifest
  04_media/scenes/scene_XX.mp4 + 04_media.json
"""
import hashlib, json, os, re, subprocess, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import imgagent  # noqa: E402
import director  # noqa: E402

W, H = 1280, 720
FPS = 30
INDEX_VERSION = "shotindex-v2"
SHEET_EVERY = 24          # max shots per source in the vision substrate
MIN_SHOT = 2.0            # matches director.MIN_SHOT (fill-integrity floor)


def ffprobe_dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


# ---------------- 1. INDEX ----------------

def detect_shots(path):
    """Scene-detect shot boundaries (luma, 320px proxy — fast, deterministic)."""
    cmd = ["ffmpeg", "-nostdin", "-v", "info", "-i", path,
           "-vf", "scale=320:-2,select='gt(scene,0.30)',showinfo",
           "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    ts = []
    for m in re.finditer(r"pts_time:([\d.]+)", r.stderr):
        ts.append(float(m.group(1)))
    ts = [t for t in ts if 0.5 < t < (ffprobe_dur(path) - 1.0)]
    # dedupe + head
    bounds = [0.0]
    for t in ts:
        if t - bounds[-1] >= 1.2:
            bounds.append(t)
    return bounds


def index_pool(media_dir):
    pool_dir = os.path.join(media_dir, "pool")
    frames_dir = os.path.join(media_dir, "frames")
    sheets_dir = os.path.join(media_dir, "sheets")
    for d in (frames_dir, sheets_dir):
        os.makedirs(d, exist_ok=True)
    manifest = json.load(open(os.path.join(pool_dir, "manifest.json")))
    index_p = os.path.join(media_dir, "shot_index.json")
    index = {}
    if os.path.isfile(index_p):
        try:
            index = json.load(open(index_p))
        except Exception:
            index = {}
    changed = False
    for key, meta in sorted(manifest.items()):
        p = os.path.join(pool_dir, f"{key}.mp4")
        if meta.get("state") not in ("ok", None) or not os.path.isfile(p):
            continue
        sig = f"{INDEX_VERSION}:{os.path.getsize(p)}:{int(os.path.getmtime(p))}"
        if index.get(key, {}).get("sig") == sig:
            continue
        dur = ffprobe_dur(p)
        if dur < 20:
            continue
        print(f"[s4] indexing {key} ({dur:.0f}s)...", flush=True)
        bounds = detect_shots(p)
        # cap very long shots (split > 12s into windows)
        shots = []
        for i, st in enumerate(bounds):
            en = bounds[i + 1] if i + 1 < len(bounds) else dur
            if en - st > 12.0:
                cur = st
                while cur < en - 4.0:
                    shots.append([round(cur, 2), round(min(cur + 9.0, en), 2)])
                    cur += 9.0
            else:
                shots.append([round(st, 2), round(en, 2)])
        entries = []
        for i, (st, en) in enumerate(shots):
            fp = os.path.join(frames_dir, f"{key}_{i:03d}.jpg")
            if not os.path.isfile(fp):
                mid = (st + en) / 2
                subprocess.run(
                    ["ffmpeg", "-y", "-v", "error", "-ss", f"{mid:.2f}", "-i", p,
                     "-frames:v", "1", "-vf", "scale=320:-2",
                     fp], capture_output=True, timeout=60)
            if os.path.isfile(fp) and os.path.getsize(fp) > 2000:
                entries.append({"idx": i, "start": st, "end": en, "frame": fp})
        # contact sheet per source (editorial inspection artifact)
        if entries:
            n = min(len(entries), SHEET_EVERY)
            step = max(1, len(entries) // n)
            picks = entries[::step][:SHEET_EVERY]
            _, tile = "x", min(6, max(2, int(len(picks) ** 0.5) + 1))
            inputs, parts = [], []
            for j, e in enumerate(picks):
                inputs += ["-i", e["frame"]]
                parts.append(f"[{j}:v]scale=320:-2,pad=324:188:2:2:black[f{j}]")
            grid = "x".join(str(x) for x in
                            (6, max(1, (len(picks) + 5) // 6)))
            fc = (";".join(parts) + ";" +
                  "".join(f"[f{j}]" for j in range(len(picks))) +
                  f"xstack=inputs={len(picks)}:layout=0_0" +
                  "|".join(f"{(j % 6) * 324}_{(j // 6) * 188}"
                           for j in range(1, len(picks))) +
                  f",scale=1280:-2[out]")
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error"] + inputs +
                ["-filter_complex", fc, "-map", "[out]", "-frames:v", "1",
                 os.path.join(sheets_dir, f"{key}.jpg")],
                capture_output=True, timeout=120)
        index[key] = {"sig": sig, "dur": round(dur, 2), "shots": entries}
        changed = True
        json.dump(index, open(index_p, "w"))
        print(f"[s4]   {key}: {len(entries)} shots", flush=True)
    if not index:
        raise RuntimeError("shot index empty — pool missing? run acquisition first")
    return index


# ---------------- 2. PLAN (Director + imgagent) ----------------

def build_plan(run_dir):
    director.run(run_dir)


def attach_place_stills(run_dir):
    """imgagent: verified place imagery for scenes that demand places.
    Narrow scope: places/entities only — never the subject."""
    media = os.path.join(run_dir, "04_media")
    plan = json.load(open(os.path.join(media, "plan.json")))
    img_dir = os.path.join(media, "images")
    script = json.load(open(os.path.join(run_dir, "02_script.json")))
    scenes = {s["id"]: s for s in (script.get("scenes") or
              [x for seg in script.get("segments", []) for x in seg["scenes"]])}
    changed = False
    for e in plan["scenes"]:
        sc = scenes.get(e["id"], {})
        places = sc.get("places") or ([] if "places" not in sc else sc["places"])
        if not places:
            continue
        for p in places[:1]:                     # <= 1 still per scene (spare)
            key = "s%02d_%s" % (e["id"], re.sub(r"[^a-z0-9]+", "_", p.lower())[:30])
            rec = imgagent.fetch_place(p, img_dir, key)
            if rec and rec.get("verified"):
                e.setdefault("stills", []).append({
                    "path": rec["path"], "place": p, "dur": 5.0,
                    "source_url": rec["source_url"],
                    "sha256": rec["sha256"], "why": rec["why"]})
                changed = True
            else:
                e["gaps"].append(f"place imagery unavailable: {p}")
    if changed:
        json.dump(plan, open(os.path.join(media, "plan.json"), "w"), indent=1)


# ---------------- 3. RENDER from EDL ----------------

def zoompan_still(path, dur):
    """Still image -> slow one-way push clip (the R15 place-imagery treatment)."""
    return (f"zoompan=z='min(1.0+0.010*on/{max(dur, 0.1):.2f}\\,1.10)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(dur * FPS)}:"
            f"s={W}x{H}:fps={FPS}")


def render_scene(pool_dir, edl_entry, T, out):
    inputs, parts, refs, total = [], [], [], 0.0
    shots = edl_entry["shots"]
    stills = edl_entry.get("stills") or []
    plan_items = []
    for s in shots:
        plan_items.append(("video", s))
    # interleave one place still early in the scene (establishing context)
    if stills and shots:
        plan_items.insert(min(1, len(plan_items)), ("still", stills[0]))
    # trim to scene length: stills take their dur out of the video budget
    budget = T
    cut_items, acc = [], 0.0
    for kind, it in plan_items:
        d = it["dur"] if kind == "still" else it["dur"]
        if acc + d > budget + 0.05:
            d = max(0.0, budget - acc)
            if d < 1.2:
                break
            cut_items.append((kind, it, d))
            acc += d
            break
        cut_items.append((kind, it, d))
        acc += d
    if acc < budget - 0.9:                 # under-fill: drop the still
        cut_items = [(k, it, min(it["dur"], budget)) for k, it, _ in cut_items
                     if k == "video"][:8]
        acc = sum(d for _, _, d in cut_items)
    if not cut_items:
        raise RuntimeError(f"scene {edl_entry['id']}: empty cut list")
    # R15 fill integrity: extend the LAST (then FIRST) video item's out-point
    # into the following footage so the scene cut matches the narration
    # duration exactly — detected boundaries are guidance, not walls.
    shortfall = round(budget - acc, 2)
    if shortfall > 0.2:
        src_dur = {}
        vids = [i for i, (k, _, _) in enumerate(cut_items) if k == "video"]
        for i in (vids[-1], vids[0]) if vids else ():
            if shortfall <= 0.2:
                break
            kind, it, d = cut_items[i]
            if kind != "video" or it["dur"] - d > 2.0:
                continue
            if it["key"] not in src_dur:
                src_dur[it["key"]] = ffprobe_dur(
                    os.path.join(pool_dir, f"{it['key']}.mp4"))
            room = src_dur[it["key"]] - it["src_in"] - 0.3
            new_d = min(d + shortfall, max(room, MIN_SHOT + 0.4))
            if new_d > d + 0.2:
                cut_items[i] = (kind, dict(it, dur=round(new_d, 2),
                                           src_out=round(it["src_in"] + new_d, 2)),
                                new_d)
                shortfall = round(shortfall - (new_d - d), 2)
                acc = round(acc + (new_d - d), 2)
    for i, (kind, it, d) in enumerate(cut_items):
        if kind == "video":
            src = os.path.join(pool_dir, f"{it['key']}.mp4")
            inputs += ["-ss", f"{it['src_in']:.2f}", "-t", f"{d:.2f}", "-i", src]
            parts.append(
                f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},setsar=1,fps={FPS},trim=duration={d:.2f},"
                f"setpts=PTS-STARTPTS[v{i}]")
        else:
            inputs += ["-loop", "1", "-t", f"{d:.2f}", "-i", it["path"]]
            parts.append(
                f"[{i}:v]{zoompan_still(it['path'], d)},"
                f"scale={W}:{H},setsar=1,fps={FPS},trim=duration={d:.2f},"
                f"setpts=PTS-STARTPTS[v{i}]")
        refs.append(f"[v{i}]")
        total += d
    fc = (";".join(parts) + ";" + "".join(refs) +
          f"concat=n={len(cut_items)}:v=1:a=0,fade=t=in:d=0.30,fade=t=out:"
          f"st={max(total - 0.35, 0):.2f}:d=0.35,trim=duration={T:.2f},"
          f"setpts=PTS-STARTPTS[out]")
    cmd = (["ffmpeg", "-y", "-v", "error", "-nostdin"] + inputs +
           ["-filter_complex", fc, "-map", "[out]", "-t", f"{T:.2f}",
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17",
            "-pix_fmt", "yuv420p", out])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg scene cut failed: {r.stderr[-300:]}")


def r2_check(edl_entry, manifest):
    """R2 subject-sync: scene tags must intersect every selected source's tags."""
    sc_tags = set(edl_entry.get("tags", []) or ["ahyeon"])
    wild = {"ahyeon", "babymonster", "yg", "industry"}
    problems = []
    for s in edl_entry["shots"]:
        stags = set((manifest.get(s["key"], {}) or {}).get("subject_tags", []))
        if not (stags & (sc_tags | wild)):
            problems.append({"shot": s["key"], "src_tags": sorted(stags)})
    return problems


def render(run_dir):
    media = os.path.join(run_dir, "04_media")
    scenes_dir = os.path.join(media, "scenes")
    os.makedirs(scenes_dir, exist_ok=True)
    pool_dir = os.path.join(media, "pool")
    plan = json.load(open(os.path.join(media, "plan.json")))
    manifest = json.load(open(os.path.join(pool_dir, "manifest.json")))
    plan_fp = hashlib.sha256(
        json.dumps(plan, sort_keys=True).encode()).hexdigest()
    fp_p = os.path.join(media, ".plan_fp")
    old_fp = None
    if os.path.isfile(fp_p):
        try:
            old_fp = open(fp_p).read().strip()
        except Exception:
            pass
    if old_fp != plan_fp:
        for f in os.listdir(scenes_dir):
            if f.endswith(".mp4"):
                os.remove(os.path.join(scenes_dir, f))
        open(fp_p, "w").write(plan_fp)
    out_manifest, problems_all = {}, {}
    for e in plan["scenes"]:
        sid = e["id"]
        T = e["scene_dur"]
        out = os.path.join(scenes_dir, f"scene_{sid:02d}.mp4")
        if not (os.path.isfile(out) and abs(ffprobe_dur(out) - T) < 1.0):
            render_scene(pool_dir, e, T, out)
        d = ffprobe_dur(out)
        probs = r2_check(e, manifest)
        if probs:
            problems_all[str(sid)] = probs
        out_manifest[str(sid)] = {
            "path": out, "kind": "video", "dur": round(d, 2),
            "shots": [{"src": s["key"], "idx": s["idx"], "start": s["src_in"],
                       "len": s["dur"], "score": s["score"],
                       "reason": s["reason"]} for s in e["shots"]],
            "stills": [{"place": s["place"], "source_url": s["source_url"]}
                       for s in (e.get("stills") or [])],
            "gaps": e.get("gaps", []),
            "r2_problems": probs}
        print(f"[s4] scene {sid:>2}: {d:5.1f}s  "
              f"shots={[(s['key'], round(s['src_in'])) for s in e['shots']]}",
              flush=True)
    out_manifest["_plan_fingerprint"] = plan_fp
    out_manifest["_r2_problems"] = problems_all
    json.dump(out_manifest, open(os.path.join(run_dir, "04_media.json"), "w"),
              indent=1)
    n_stills = sum(len(m.get("stills") or []) for m in out_manifest.values()
                   if isinstance(m, dict) and m.get("kind") == "video")
    print(f"[s4] done: {len(plan['scenes'])} scenes, {n_stills} verified place "
          f"stills, {len(problems_all)} R2 problem scene(s)", flush=True)
    return out_manifest


def run(run_dir):
    index_pool(os.path.join(run_dir, "04_media"))
    build_plan(run_dir)
    attach_place_stills(run_dir)
    return render(run_dir)


if __name__ == "__main__":
    run(sys.argv[1])
