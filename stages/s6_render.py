#!/usr/bin/env python3
"""Stage 6 (v2): render — chapter-structured documentary at NATIVE 720p.

Rebuilt after R13 verdict (distortion + slideshow + broken labels):
  - native 1280x720@30 from real-footage scene cuts (NO upscale, NO zoompan)
  - high quality: crf 17 per-scene caption pass, crf 18 final
  - chapter cards regenerated via drawtext (old cards were black/corrupted)
  - per-segment chunks with xfade inside, clean re-encoded concat between
    chunks (fixes the -c copy timestamp bug for good)
  - audio: narration timeline + sidechain-ducked bed + loudnorm, FIXED labels
  - trailer cut from the finished master
"""
import json, os, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(__file__))

W, H = 1280, 720
FPS = 30
XF = 0.5          # crossfade seconds inside a segment chunk
CARD = 2.6        # chapter card seconds
TAIL = 0.8        # silence tail after narration in each scene
MIN_SCENE = 3.5
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
GOLD = "0xC9A227"
BG = "0x0B0E13"
NUMW = ["ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"]


def sh(cmd, timeout=1800):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-400:]}")
    return r


def esc_textfile(run_dir, sc, text):
    p = os.path.join(run_dir, "04_media", f"scene_{sc['id']:02d}.txt")
    with open(p, "w") as fh:
        fh.write(text.replace("\n", " ").strip()[:72])
    return p


def make_card(out, kicker, title, dur=CARD):
    """Awards-style chapter card: dark bg, gold rule, kicker, title."""
    fc = (
        f"color=c={BG}:s={W}x{H}:d={dur:.2f}:r={FPS},"
        f"drawbox=x=(w-170)/2:y=300:w=170:h=3:color={GOLD}@0.95:t=fill,"
        f"drawtext=fontfile={FONT}:text='{kicker}':fontsize=30:fontcolor={GOLD}"
        f":x=(w-tw)/2:y=336,"
        f"drawtext=fontfile={FONT}:text='{title}':fontsize=52:fontcolor=white"
        f":x=(w-tw)/2:y=392,"
        f"fade=t=in:d=0.4,fade=t=out:st={dur-0.4:.2f}:d=0.4,format=yuv420p"
    )
    sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={BG}:s={W}x{H}:d={dur:.2f}:r={FPS}",
        "-vf", fc.split(",", 1)[1] if fc.startswith("color=") else fc,
        "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "medium", "-crf", "17",
        "-an", out])


def kicker_for(idx):
    return f"C H A P T E R   {NUMW[idx]}" if idx < len(NUMW) else f"CHAPTER {idx+1}"


def sanitize_title(t):
    return (t or "").replace("\\", "").replace("'", "").replace(":", " -").replace('"', "")


def build_timeline(run_dir):
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    timings = {t["id"]: t["audio"] for t in
               json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]}
    segs = plan.get("segments") or [{"id": "all", "title": plan.get("title", ""),
                                     "scenes": plan["scenes"]}]
    items = []          # ordered: {kind: card|scene, ...}
    for si, seg in enumerate(segs):
        if seg["id"] not in ("cold_open", "all", "outro"):
            items.append({"kind": "card", "seg": seg["id"], "dur": CARD,
                          "kicker": kicker_for(max(si - 1, 0)),
                          "title": sanitize_title(seg.get("title", seg["id"]))})
        for sc in seg["scenes"]:
            d = max(MIN_SCENE, timings.get(sc["id"], 4.0) + TAIL)
            items.append({"kind": "scene", "sc": sc, "dur": round(d, 2)})
    items.append({"kind": "endcard", "dur": CARD,
                  "title": sanitize_title(plan.get("title", "BLACKPINK")),
                  "kicker": "A  V F A C T O R Y   D O C U M E N T A R Y"})
    return items, plan


def pass_a(run_dir, items, title):
    """Caption overlays on scene clips + regenerate all cards (resumable)."""
    work = os.path.join(run_dir, "06_final")
    v2 = os.path.join(work, ".v2")
    if not os.path.isdir(work) or not os.path.exists(v2):
        if os.path.isdir(os.path.join(run_dir, "06_final_old")):
            shutil.rmtree(os.path.join(run_dir, "06_final_old"), ignore_errors=True)
        if os.path.isdir(work):
            shutil.move(work, os.path.join(run_dir, "06_final_old"))
    os.makedirs(work, exist_ok=True)
    open(v2, "w").write("2")
    clip_dir = os.path.join(work, "clips")
    os.makedirs(clip_dir, exist_ok=True)
    first_title_done = False
    out_items = []
    for it in items:
        if it["kind"] in ("card", "endcard"):
            out = os.path.join(clip_dir, f"card_{it.get('seg', 'end')}_{len(out_items):02d}.mp4")
            if not (os.path.isfile(out) and ffprobe_dur_safe(out) > it["dur"] - 0.2):
                make_card(out, it["kicker"], it["title"])
            it = {**it, "path": out}
        else:
            sc = it["sc"]
            src = os.path.join(run_dir, "04_media", "scenes", f"scene_{sc['id']:02d}.mp4")
            out = os.path.join(clip_dir, f"clip_{sc['id']:02d}.mp4")
            cap = esc_textfile(run_dir, sc, sc.get("on_screen", ""))
            if not first_title_done:
                # opening title over the cold-open footage
                t1 = sanitize_title(title)
                vf = (f"drawtext=fontfile={FONT}:text='{t1}':fontsize=58:fontcolor=white"
                      f":borderw=2:bordercolor=black@0.7:box=1:boxcolor=black@0.30"
                      f":boxborderw=18:x=(w-tw)/2:y=(h-th)/2-70,"
                      f"drawbox=x=(w-140)/2:y=(h/2)+18:w=140:h=3:color={GOLD}@0.95:t=fill,"
                      f"drawtext=fontfile={FONT}:textfile={cap}:fontsize=38:fontcolor=white"
                      f":borderw=2:bordercolor=black@0.6:box=1:boxcolor=black@0.35"
                      f":boxborderw=14:x=(w-tw)/2:y=(h/2)+64")
                first_title_done = True
            else:
                vf = (f"drawtext=fontfile={FONT}:textfile={cap}:fontsize=40:fontcolor=white"
                      f":borderw=2:bordercolor=black@0.6:box=1:boxcolor=black@0.35"
                      f":boxborderw=14:x=(w-tw)/2:y=h-150")
            dur = it["dur"]
            if not (os.path.isfile(out) and abs(ffprobe_dur_safe(out) - dur) < 0.6):
                sh(["ffmpeg", "-y", "-v", "error", "-i", src,
                    "-vf", f"{vf},format=yuv420p", "-t", f"{dur:.2f}",
                    "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17",
                    "-r", str(FPS), out], timeout=900)
            it = {**it, "path": out}
        out_items.append(it)
    return out_items


def ffprobe_dur_safe(path):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", path],
                           capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def chunk_of(items, work, name):
    """xfade chain within one segment chunk -> chunk mp4 (resumable)."""
    out = os.path.join(work, f"{name}.mp4")
    meta_p = os.path.join(work, f"{name}.json")
    want = round(sum(i["dur"] for i in items) - XF * (len(items) - 1), 3)
    if os.path.isfile(out) and os.path.isfile(meta_p):
        try:
            if abs(json.load(open(meta_p))["total"] - want) < 0.2:
                return out, want
        except Exception:
            pass
    inputs = []
    for it in items:
        inputs += ["-i", it["path"]]
    fc = []
    if len(items) == 1:
        fc.append(f"[0:v]format=yuv420p[vout]")
    else:
        prev, off = "[0:v]", items[0]["dur"] - XF
        for i in range(1, len(items)):
            trans = "fadeblack" if items[i - 1]["kind"] in ("card", "endcard") or items[i]["kind"] in ("card", "endcard") else "fade"
            lbl = f"[vx{i}]"
            fc.append(f"{prev}[{i}:v]xfade=transition={trans}:duration={XF}"
                      f":offset={off:.3f}{lbl}")
            prev = lbl
            off += items[i]["dur"] - XF
        fc.append(f"{prev}format=yuv420p[vout]")
    script = os.path.join(work, f"{name}.fc")
    with open(script, "w") as fh:
        fh.write(";".join(fc))
    out = os.path.join(work, f"{name}.mp4")
    sh(["ffmpeg", "-y", "-v", "error"] + inputs +
       ["-filter_complex_script", script, "-map", "[vout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(FPS), out], timeout=3600)
    total = sum(i["dur"] for i in items) - XF * (len(items) - 1)
    json.dump({"total": round(total, 3)}, open(meta_p, "w"))
    return out, round(total, 3)


def pass_b(items, run_dir):
    """Group items by segment chunk -> render chunks -> concat (re-encode)."""
    work = os.path.join(run_dir, "06_final")
    groups, cur = [], []
    for it in items:
        if it["kind"] == "card" and cur:
            groups.append(cur)
            cur = []
        cur.append(it)
        if it["kind"] == "endcard":
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    chunks, offsets, acc = [], [], 0.0
    for gi, grp in enumerate(groups):
        path, local_total = chunk_of(grp, work, f"chunk_{gi:02d}")
        # global start of each scene inside this chunk
        lo = 0.0
        for it in grp:
            if it["kind"] == "scene":
                offsets.append((it["sc"]["id"], round(acc + (lo if lo > 0 else 0.0), 3)))
            lo += it["dur"] - (XF if it is not grp[-1] else 0.0) if len(grp) > 1 else 0.0
        chunks.append(path)
        acc += local_total
    total = round(acc, 3)

    concat_script = os.path.join(work, "concat.fc")
    video = os.path.join(work, "video.mp4")
    if not (os.path.isfile(video) and os.path.isfile(os.path.join(work, "concat.json"))
            and abs(json.load(open(os.path.join(work, "concat.json")))["total"] - total) < 0.5):
        # Livelock fix: the old one-shot medium re-encode of the whole film
        # exceeded every tool window and restarted from zero on each kill.
        # Now: fades baked into first/last chunks (small re-encodes), the
        # uniform medium/crf18 chunks stream-copy concat (no generation loss),
        # duration verified afterwards (guards the historical -c copy bug).
        def bake(src, dst, mode):
            okp = dst + ".ok"
            if os.path.isfile(dst) and os.path.isfile(okp):
                return
            dur = ffprobe_dur_safe(src)
            vf = "fade=t=in:d=0.5" if mode == "in" else \
                 f"fade=t=out:st={max(dur - 0.9, 0):.3f}:d=0.9"
            print(f"[s6] bake {os.path.basename(src)} -> {os.path.basename(dst)} "
                  f"({dur:.0f}s, {mode})", flush=True)
            sh(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", vf,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p", "-r", str(FPS),
                "-movflags", "+faststart", dst], timeout=1800)
            open(okp, "w").write("1")
            print(f"[s6] bake done", flush=True)
        bake(chunks[0], os.path.join(work, "chunk_00f.mp4"), "in")
        bake(chunks[-1], os.path.join(work, f"chunk_{len(chunks)-1:02d}f.mp4"), "out")
        lst = os.path.join(work, "concat_list.txt")
        with open(lst, "w") as fh:
            for i, c in enumerate(chunks):
                use = c if 0 < i < len(chunks) - 1 else \
                    os.path.join(work, f"chunk_{i:02d}f.mp4")
                fh.write(f"file '{os.path.abspath(use)}'\n")
        print(f"[s6] copy-concat {len(chunks)} chunks -> video.mp4", flush=True)
        sh(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
            "-i", lst, "-c", "copy", "-movflags", "+faststart", video],
           timeout=600)
        vd = ffprobe_dur_safe(video)
        if vd < total - 5.0 or vd > total + 300:
            raise RuntimeError(f"concat -c copy bad duration: {vd} vs {total}")
        json.dump({"total": total}, open(os.path.join(work, "concat.json"), "w"))

    starts = {}
    for sid, st in offsets:
        starts.setdefault(sid, st)
    return video, starts, total


def pass_c(run_dir, starts, total, video):
    """Narration timeline + ducked bed + loudnorm (labels FIXED)."""
    timings = json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]
    bed = None
    for cand in (os.path.join(run_dir, "05_music", "bed.wav"),
                 os.path.join(run_dir, "05_audio", "bed.wav")):
        if os.path.isfile(cand):
            bed = cand
            break
    if bed is None:
        raise RuntimeError("no music bed found (run s5 first)")
    work = os.path.join(run_dir, "06_final")
    inputs = ["-i", bed]
    for t in timings:
        inputs += ["-i", t["wav"]]
    fc = [f"[0:a]aformat=channel_layouts=stereo,aresample=48000,"
          f"atrim=0:{total:.2f},apad=whole_dur={total:.2f}[bed]"]
    mix_in = ""
    for n, t in enumerate(timings, 1):
        st = starts.get(t["id"], 0.0) + 0.35
        ms = int(max(st, 0.0) * 1000)
        fc.append(f"[{n}:a]aformat=channel_layouts=stereo,aresample=48000,"
                  f"adelay={ms}|{ms}[s{n}]")
        mix_in += f"[s{n}]"
    fc.append(f"{mix_in}amix=inputs={len(timings)}:duration=longest:normalize=0[nar]")
    fc.append("[bed][nar]sidechaincompress=threshold=0.015:ratio=8:attack=40"
              ":release=700:makeup=1[ducked]")
    fc.append("[nar][ducked]amix=inputs=2:duration=longest:normalize=0[mixout]")
    fc.append(f"[mixout]loudnorm=I=-14:TP=-1.5:LRA=11,atrim=0:{total:.2f},"
              f"afade=t=out:st={max(total - 1.0, 0):.2f}:d=1.0[aout]")
    script = os.path.join(work, "passc.fc")
    with open(script, "w") as fh:
        fh.write(";".join(fc))
    mix_wav = os.path.join(work, "mix.wav")
    if not (os.path.isfile(mix_wav) and os.path.isfile(os.path.join(work, "mix.ok"))):
        print(f"[s6] audio mix ({len(timings)} narrations + bed, {total:.0f}s)", flush=True)
        sh(["ffmpeg", "-y", "-v", "error"] + inputs +
           ["-filter_complex_script", script, "-map", "[aout]",
            "-ar", "48000", mix_wav], timeout=1800)
        open(os.path.join(work, "mix.ok"), "w").write("1")
    final = os.path.join(run_dir, "final.mp4")
    if not (os.path.isfile(final) and ffprobe_dur_safe(final) > total - 3.0):
        sh(["ffmpeg", "-y", "-v", "error", "-i", video, "-i", mix_wav,
            "-map", "0:v", "-map", "1:a", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-shortest",
            "-movflags", "+faststart", final], timeout=900)
    return final


def make_trailer(run_dir, starts, total):
    """55s trailer: hook + 3 chapter peaks + ending, cut from the master."""
    trailer = os.path.join(run_dir, "trailer.mp4")
    if os.path.isfile(trailer) and ffprobe_dur_safe(trailer) > 40:
        return trailer
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    timings = {t["id"]: t["audio"] for t in
               json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]}
    scenes = plan["scenes"] if "scenes" in plan else \
        [s for seg in plan["segments"] for s in seg["scenes"]]
    ids = [s["id"] for s in scenes]
    picks = [ids[0]]
    for frac in (0.42, 0.62, 0.85):
        picks.append(ids[min(int(len(ids) * frac), len(ids) - 1)])
    spans = []
    for sid in picks:
        st = starts.get(sid, 0.0)
        d = max(3.5, timings.get(sid, 4.0) + TAIL)
        spans.append((max(st - 0.2, 0.0), min(d + 0.4, 9.0)))
    spans.append((max(total - 5.5, 0.0), 5.5))          # ending card
    work = os.path.join(run_dir, "06_final")
    parts = []
    for i, (st, d) in enumerate(spans):
        p = os.path.join(work, f"tr_{i}.mp4")
        sh(["ffmpeg", "-y", "-v", "error", "-ss", f"{st:.2f}", "-t", f"{d:.2f}",
            "-i", os.path.join(run_dir, "final.mp4"), p], timeout=600)
        parts.append(p)
    trailer = os.path.join(run_dir, "trailer.mp4")
    sh(["ffmpeg", "-y", "-v", "error"] + sum([["-i", p] for p in parts], []) +
       ["-filter_complex",
        ";".join(f"[{i}:v]scale={W}:{H},setsar=1,fps={FPS}[v{i}];"
                 f"[{i}:a]aformat=channel_layouts=stereo,aresample=48000[a{i}]"
                 for i in range(len(parts))) + ";" +
        "".join(f"[v{i}][a{i}]" for i in range(len(parts))) +
        f"concat=n={len(parts)}:v=1:a=1,fade=t=in:d=0.4,"
        f"fade=t=out:st=48.0:d=1.2,format=yuv420p[vout]",
        "-map", "[vout]", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", trailer],
       timeout=1200)
    for p in parts:
        os.remove(p)
    return trailer


def run(run_dir):
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    plan0 = json.load(open(os.path.join(run_dir, "02_script.json")))
    title = plan0.get("title", topic["topic"])
    items, plan = build_timeline(run_dir)
    items = pass_a(run_dir, items, title)
    video, starts, total = pass_b(items, run_dir)
    final = pass_c(run_dir, starts, total, video)
    trailer = make_trailer(run_dir, starts, total)
    n_scenes = sum(1 for i in items if i["kind"] == "scene")
    json.dump({"durations": {str(i["sc"]["id"]): i["dur"] for i in items if i["kind"] == "scene"},
               "starts": {str(k): v for k, v in starts.items()},
               "total": total, "scenes": n_scenes, "res": f"{W}x{H}"},
              open(os.path.join(run_dir, "06_timeline.json"), "w"), indent=1)
    print(f"render done: {total/60:.2f} min, {n_scenes} scenes, 720p30", flush=True)
    return {"final": final, "trailer": trailer, "total": total, "scenes": n_scenes}


if __name__ == "__main__":
    print(run(sys.argv[1]))
