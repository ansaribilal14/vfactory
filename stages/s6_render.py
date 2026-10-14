#!/usr/bin/env python3
"""Stage 6 (v2): render — chapter-structured documentary at NATIVE 720p.

Rebuilt after R13 verdict (distortion + slideshow + broken labels):
  - native 1280x720@30 from real-footage scene cuts (NO upscale, NO zoompan)
  - high quality: crf 17 per-scene caption pass, crf 18 final
  - chapter cards regenerated via drawtext (old cards were black/corrupted)
  - per-segment chunks with xfade inside, clean re-encoded concat between
    chunks (fixes the -c copy timestamp bug for good)
  - audio: narration (compressed) + sidechain-ducked bed + limiter +
    TWO-PASS LINEAR loudnorm (opuscar technique; kills the distortion)
  - trailer cut from the finished master
"""
import json, os, shutil, subprocess, sys, hashlib

import numpy as np

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

# ---- R15: dependency fingerprints (stale-output ban) -----------------------
# A cached artifact is ONLY valid when the content hash of every upstream
# input matches the fingerprint recorded at build time. Existence, .ok
# markers, and durations are NEVER sufficient on their own.
MIX_FP_VERSION = "s6-mix-v3-voicewise"
FINAL_FP_VERSION = "s6-final-v3"


def sha256_file(path, block=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(block)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def mix_fingerprint(timings, bed_path, starts, total):
    """Content hash of every input the mix depends on."""
    parts = [MIX_FP_VERSION]
    for t in timings:
        p = t["wav"]
        if not os.path.isfile(p):
            raise RuntimeError(f"narration file missing: {p}")
        parts.append(f"{t['id']}:{sha256_file(p)}:{t['audio']:.3f}")
    parts.append(f"bed:{sha256_file(bed_path)}")
    parts.append("starts:" + json.dumps(
        {str(k): round(v, 3) for k, v in sorted(starts.items())}, sort_keys=True))
    parts.append(f"total:{total:.3f}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def load_mix_meta_proof(work, suffix=""):
    p = os.path.join(work, f"mix{suffix}.meta.json")
    try:
        return json.load(open(p))
    except Exception:
        return None


def load_mix_meta(work):
    p = os.path.join(work, "mix.meta.json")
    try:
        return json.load(open(p))
    except Exception:
        return None


# ---- R15: voice-presence verification (the gate v1 lacked) -----------------
# Envelope cross-correlation of the ACTUAL mix against the ACTUAL narration
# files at their expected offsets. A music-only mix scores noise (~0.1); a
# mix containing the narration at the right place scores high (~0.6+).
# Per-scene check => intentional pauses elsewhere are permitted; we only
# require the scripted narration to be present at its scripted position.
ENV_HZ = 200


def _env(path, t0=0.0, dur=None):
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}"]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-i", path, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=900)
    x = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    w = 16000 // ENV_HZ
    n = (len(x) // w) * w
    if n == 0:
        return np.zeros(1, np.float32)
    return np.sqrt((x[:n].reshape(-1, w) ** 2).mean(axis=1))


def _xcorr(seg, tpl):
    """Best normalized correlation of template tpl sliding over seg."""
    seg = seg - seg.mean()
    tpl = tpl - tpl.mean()
    nb = len(tpl)
    denom_t = float(np.linalg.norm(tpl))
    if denom_t < 1e-9 or len(seg) < nb:
        return 0.0
    best = 0.0
    for lag in range(0, len(seg) - nb + 1, 1):
        s = seg[lag:lag + nb]
        d = float(np.linalg.norm(s))
        if d < 1e-9:
            continue
        c = float(np.dot(s, tpl)) / (d * denom_t)
        if c > best:
            best = c
    return best


def verify_narration_in_mix(audio_path, timings, starts, total,
                            corr_min=0.40, sample=None):
    """Independent narration QC on a MIXED audio file (mix.wav OR final.mp4).

    Returns (ok, report). Fails when a scripted narration segment cannot be
    found (correlated) at its expected position — this catches music-only
    mixes, silent narration, and misaligned narration alike. Only the
    narration positions themselves are checked, so deliberate silence
    between scenes remains permitted.
    """
    ids = [t["id"] for t in timings]
    if sample:
        keep = set(ids[::max(1, len(ids) // sample)] + [ids[0], ids[-1]])
        ids = [i for i in ids if i in keep]
    tm_by_id = {t["id"]: t for t in timings}
    report = {"audio": audio_path, "env_hz": ENV_HZ, "corr_min": corr_min,
              "scenes": [], "verdict": "fail"}
    ok_all = True
    for sid in ids:
        t = tm_by_id[sid]
        nenv = _env(t["wav"])
        nd = len(nenv) / ENV_HZ
        if nd < 1.0:
            report["scenes"].append({"id": sid, "error": "narration file too short"})
            ok_all = False
            continue
        exp = max(starts.get(sid, 0.0), 0.0) + 0.35
        lo = max(0.0, exp - 2.0)
        dur = min((exp - lo) + nd + 4.0, max(total - lo, 1.0))
        fenv = _env(audio_path, lo, dur)
        peak = _xcorr(fenv, nenv)
        entry = {"id": sid, "expected_start": round(exp, 2), "narr_dur": round(nd, 2),
                 "corr": round(peak, 3), "pass": bool(peak >= corr_min)}
        report["scenes"].append(entry)
        if not entry["pass"]:
            ok_all = False
    report["verdict"] = "pass" if ok_all else "fail"
    return ok_all, report


def volumedetect(path, tlimit=None):
    cmd = ["ffmpeg", "-hide_banner", "-i", path]
    if tlimit:
        cmd += ["-t", str(tlimit)]
    cmd += ["-af", "volumedetect", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    mean = mx = None
    for ln in r.stderr.splitlines():
        if "mean_volume" in ln:
            mean = float(ln.split("mean_volume:")[1].split("dB")[0])
        if "max_volume" in ln:
            mx = float(ln.split("max_volume:")[1].split("dB")[0])
    return mean, mx


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
    """Premium minimal chapter card: dark radial-lit bg, thin gold frame,
    letterspaced kicker, clean title. No boxy caption fills."""
    fc = (
        f"drawbox=x=(w-170)/2:y=306:w=170:h=2:color={GOLD}@0.9:t=fill,"
        f"drawtext=fontfile={FONT}:text='{kicker}':fontsize=26:fontcolor={GOLD}"
        f":x=(w-tw)/2:y=348,"
        f"drawtext=fontfile={FONT}:text='{title}':fontsize=54:fontcolor=0xF2F2F0"
        f":x=(w-tw)/2:y=404,"
        f"drawbox=x=44:y=40:w={W}-88:h={H}-80:color={GOLD}@0.18:t=2,"
        f"fade=t=in:d=0.5,fade=t=out:st={dur-0.5:.2f}:d=0.5,format=yuv420p"
    )
    sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", f"color=c={BG}:s={W}x{H}:d={dur:.2f}:r={FPS}",
        "-vf", fc, "-t", f"{dur:.2f}", "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "19", "-an", out])


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
    """R14: NO on-scene captions (user: stale captions -> not have them at
    all). Scene cuts from s4 are already 1280x720@30 — passthrough by
    reference (saves a full re-encode). Cards regenerated (restyled)."""
    work = os.path.join(run_dir, "06_final")
    v2 = os.path.join(work, ".v3")
    if os.path.isdir(work) and not os.path.exists(v2):
        shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    open(v2, "w").write("3")
    clip_dir = os.path.join(work, "clips")
    os.makedirs(clip_dir, exist_ok=True)
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
            if not os.path.isfile(src):
                raise RuntimeError(f"missing scene cut {src} — run s4 first")
            if abs(ffprobe_dur_safe(src) - it["dur"]) > 1.2:
                raise RuntimeError(f"scene {sc['id']} duration drift: "
                                   f"{ffprobe_dur_safe(src)} vs {it['dur']} — re-run s4")
            it = {**it, "path": src}     # passthrough, zero re-encode
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


def chunk_of(items, work, name, deps_fp=None):
    """xfade chain within one segment chunk -> chunk mp4 (resumable).
    R15: cache valid only when the recorded upstream fingerprint matches."""
    out = os.path.join(work, f"{name}.mp4")
    meta_p = os.path.join(work, f"{name}.json")
    want = round(sum(i["dur"] for i in items) - XF * (len(items) - 1), 3)
    if os.path.isfile(out) and os.path.isfile(meta_p):
        try:
            m = json.load(open(meta_p))
            if (abs(m["total"] - want) < 0.2
                    and (deps_fp is None or m.get("deps_fp") == deps_fp)):
                return out, want
        except Exception:
            pass
    inputs = []
    for it in items:
        inputs += ["-i", it["path"]]
    # timebase/fps normalization per input — xfade demands identical
    # timebases; lavfi cards (1/15360) vs passthrough mp4 cuts (1/1000000)
    # otherwise fail with "main timebase do not match".
    # tpad clone-hold covers each scene's cut shortfall (s4 tolerance) so
    # chunk actuals match the expected timeline — keeps narration sync AND
    # the 27-minute floor. Holds are masked by the xfade crossfades.
    norms = []
    for i, it in enumerate(items):
        have = ffprobe_dur_safe(it["path"])
        gap = max(0.0, round(it["dur"] - have, 3))
        pad = f",tpad=stop_mode=clone:stop_duration={gap:.3f}" if gap > 0.05 else ""
        norms.append(f"[{i}:v]settb=AVTB,fps={FPS}{pad},format=yuv420p[n{i}]")
    fc = []
    fc.extend(norms)
    if len(items) == 1:
        fc.append(f"[n0:v]format=yuv420p[vout]")
    else:
        prev, off = "[n0]", items[0]["dur"] - XF
        for i in range(1, len(items)):
            trans = "fadeblack" if items[i - 1]["kind"] in ("card", "endcard") or items[i]["kind"] in ("card", "endcard") else "fade"
            lbl = f"[vx{i}]"
            fc.append(f"{prev}[n{i}]xfade=transition={trans}:duration={XF}"
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
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(FPS), out], timeout=3600)
    total = sum(i["dur"] for i in items) - XF * (len(items) - 1)
    json.dump({"total": round(total, 3), "deps_fp": deps_fp},
              open(meta_p, "w"))
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

    # R15: one fingerprint over every upstream frame source — any scene-cut
    # or card change invalidates all chunks, the concat and the bakes.
    src_fp = hashlib.sha256("|".join(
        f"{it['path']}:{sha256_file(it['path'])}" for it in items
        if os.path.isfile(it["path"])).encode()).hexdigest()
    chunks, offsets, acc = [], [], 0.0
    for gi, grp in enumerate(groups):
        path, local_total = chunk_of(grp, work, f"chunk_{gi:02d}", deps_fp=src_fp)
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
    cmeta = None
    try:
        cmeta = json.load(open(os.path.join(work, "concat.json")))
    except Exception:
        pass
    if not (os.path.isfile(video) and cmeta
            and abs(cmeta["total"] - total) < 0.5
            and cmeta.get("deps_fp") == src_fp):
        # Livelock fix: the old one-shot medium re-encode of the whole film
        # exceeded every tool window and restarted from zero on each kill.
        # Now: fades baked into first/last chunks (small re-encodes), the
        # uniform medium/crf18 chunks stream-copy concat (no generation loss),
        # duration verified afterwards (guards the historical -c copy bug).
        def bake(src, dst, mode):
            okp = dst + ".ok"
            if os.path.isfile(dst) and os.path.isfile(okp):
                try:
                    if open(okp).read().strip() == src_fp:
                        return
                except Exception:
                    pass
            dur = ffprobe_dur_safe(src)
            vf = "fade=t=in:d=0.5" if mode == "in" else \
                 f"fade=t=out:st={max(dur - 0.9, 0):.3f}:d=0.9"
            print(f"[s6] bake {os.path.basename(src)} -> {os.path.basename(dst)} "
                  f"({dur:.0f}s, {mode})", flush=True)
            sh(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", vf,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p", "-r", str(FPS),
                "-movflags", "+faststart", dst], timeout=1800)
            open(okp, "w").write(src_fp)
            print(f"[s6] bake done", flush=True)
        bake(chunks[0], os.path.join(work, "chunk_00f.mp4"), "in")
        bake(chunks[-1], os.path.join(work, f"chunk_{len(chunks)-1:02d}f.mp4"), "out")
        lst = os.path.join(work, "concat_list.txt")
        with open(lst, "w") as fh:
            for i, c in enumerate(chunks):
                use = c if 0 < i < len(chunks) - 1 else \
                    os.path.join(work, f"chunk_{i:02d}f.mp4")
                fh.write(f"file '{os.path.abspath(use)}'\n")
        print(f"[s6] concat re-encode (veryfast) {len(chunks)} chunks -> video.mp4",
              flush=True)
        # R14: copy-concat dropped ~27s (timebase re-timing alters real chunk
        # lengths vs metas). Concat-filter re-encode rewrites timestamps.
        with open(concat_script, "w") as fh:
            fh.write("".join(f"[{i}:v]" for i in range(len(chunks))) +
                     f"concat=n={len(chunks)}:v=1:a=0,"
                     f"fade=t=in:d=0.5,fade=t=out:st={max(total-0.9,0):.3f}:d=0.9,"
                     f"format=yuv420p[vout]")
        sh(["ffmpeg", "-y", "-v", "error"] + sum([["-i", c] for c in chunks], []) +
           ["-filter_complex_script", concat_script, "-map", "[vout]",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-r", str(FPS), video], timeout=3400)
        vd = ffprobe_dur_safe(video)
        if vd < total - 5.0 or vd > total + 300:
            raise RuntimeError(f"concat bad duration: {vd} vs {total}")
        json.dump({"total": total, "deps_fp": src_fp},
                  open(os.path.join(work, "concat.json"), "w"))

    starts = {}
    for sid, st in offsets:
        starts.setdefault(sid, st)
    return video, starts, total


def pass_c(run_dir, starts, total, video, timings=None, bed_path=None,
           proof=False):
    """Narration timeline + ducked bed + loudnorm (+ R15 fingerprint gates).
    proof=True renders proof.mp4 with the same gates but isolated artifact
    names (never clobbers the real mix/final metadata)."""
    suffix = "_proof" if proof else ""
    if timings is None:
        timings = json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]
    bed = bed_path
    if bed is None:
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
                  f"acompressor=threshold=0.08:ratio=2.5:attack=15:release=200"
                  f":makeup=2,adelay={ms}|{ms}[s{n}]")
        mix_in += f"[s{n}]"
    fc.append(f"{mix_in}amix=inputs={len(timings)}:duration=longest:normalize=0[nar]")
    # R15 CRITICAL FIX: [nar] feeds BOTH the sidechain key AND the final mix.
    # A filter label can only be consumed once — the v1 film shipped silent
    # because the second [nar] reference silently vanished. asplit is MANDATORY.
    fc.append("[nar]asplit=2[nar_key][nar_mix]")
    fc.append("[bed][nar_key]sidechaincompress=threshold=0.02:ratio=6:attack=30"
              ":release=600[ducked]")
    fc.append("[nar_mix][ducked]amix=inputs=2:duration=longest:normalize=0"
              f",atrim=0:{total:.2f}[araw]")
    script = os.path.join(work, "passc.fc")
    with open(script, "w") as fh:
        fh.write(";".join(fc))
    mix_wav = os.path.join(work, f"mix{suffix}.wav")
    mix_raw = os.path.join(work, f"mix_raw{suffix}.wav")
    lim = "alimiter=limit=0.891:attack=5:release=80"

    # R15: the mix cache is valid ONLY when its recorded fingerprint matches
    # the CURRENT content hashes of every narration file, the bed, the start
    # mapping and the code version. mix.ok existence proves nothing.
    fp = mix_fingerprint(timings, bed, starts, total)
    meta = load_mix_meta_proof(work, suffix)
    cache_ok = bool(
        os.path.isfile(mix_wav) and meta and meta.get("fingerprint") == fp
        and os.path.isfile(os.path.join(work, f"mix{suffix}.ok")))
    qc = {"mix_fingerprint": fp, "cache": "hit" if cache_ok else "miss"}

    if not cache_ok:
        print(f"[s6] audio mix ({len(timings)} narrations + bed, {total:.0f}s)",
              flush=True)
        sh(["ffmpeg", "-y", "-v", "error"] + inputs +
           ["-filter_complex_script", script, "-map", "[araw]",
            "-ar", "48000", mix_raw], timeout=1800)
        # TWO-PASS loudnorm (opuscar): pass 1 measures on the limited signal,
        # pass 2 applies linear gain — no dynamic pumping = no distortion
        p1 = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", mix_raw,
             "-af", f"{lim},loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
             "-f", "null", "-"], capture_output=True, text=True, timeout=1800)
        jtxt = p1.stderr[p1.stderr.rfind("{"):p1.stderr.rfind("}") + 1]
        m = json.loads(jtxt)
        ln2 = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}"
               f":measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
               f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}"
               f":linear=true")
        sh(["ffmpeg", "-y", "-v", "error", "-i", mix_raw,
            "-af", f"{lim},{ln2},afade=t=out:st={max(total - 1.0, 0):.2f}:d=1.0",
            "-ar", "48000", mix_wav], timeout=1800)
        os.remove(mix_raw)
        if os.path.exists(os.path.join(work, "mix.ok")):
            os.remove(os.path.join(work, "mix.ok"))
        # GATE 1 (necessary, not sufficient): loudness window
        mean, mx = volumedetect(mix_wav, tlimit=300)
        print(f"[s6] mix gate: mean={mean}dB max={mx}dB", flush=True)
        if mx is None or mx < -12.0 or mean is None or mean < -45.0:
            os.remove(mix_wav)
            raise RuntimeError(f"AUDIO GATE FAILED: mean={mean} max={mx} — "
                               f"narration or bed missing from mix")
        if mx > -0.7:
            os.remove(mix_wav)
            raise RuntimeError(f"CLIP GATE FAILED: max={mx}dB — distortion ban (R1)")
        qc["mix_loudness"] = {"mean_db": mean, "max_db": mx}
        # GATE 2 (the one v1 lacked): is the SCRIPTED NARRATION actually in
        # the mix, at its scripted position? A loud music-only mix must not
        # pass. Voice presence is verified per scene against the source files.
        ok, voicerep = verify_narration_in_mix(mix_wav, timings, starts, total)
        qc["mix_narration_verification"] = voicerep
        bad = [s for s in voicerep["scenes"] if not s.get("pass")]
        print(f"[s6] voice gate: {len(voicerep['scenes']) - len(bad)}/"
              f"{len(voicerep['scenes'])} scenes verified (min corr "
              f"{min([s.get('corr', 0) for s in voicerep['scenes']] or [0]):.2f})",
              flush=True)
        if not ok:
            os.remove(mix_wav)
            json.dump(qc, open(os.path.join(work, f"qc_report{suffix}.json"), "w"), indent=1)
            raise RuntimeError(
                f"NARRATION GATE FAILED on mix.wav: {len(bad)} scene(s) missing or "
                f"misplaced (ids {[b['id'] for b in bad][:6]}...) — music-only or "
                f"stale mix is a release-blocking failure")
        open(os.path.join(work, f"mix{suffix}.ok"), "w").write("1")
        json.dump({"fingerprint": fp, "total": total,
                   "starts": {str(k): v for k, v in starts.items()}},
                  open(os.path.join(work, f"mix{suffix}.meta.json"), "w"), indent=1)
    else:
        print("[s6] mix cache HIT (fingerprint match)", flush=True)
        # even on cache hit, the voice gate must hold for THIS build
        ok, voicerep = verify_narration_in_mix(mix_wav, timings, starts, total)
        qc["mix_narration_verification"] = voicerep
        if not ok:
            os.remove(mix_wav)
            if os.path.exists(os.path.join(work, "mix.ok")):
                os.remove(os.path.join(work, "mix.ok"))
            raise RuntimeError("NARRATION GATE FAILED on cached mix — invalidated")

    final = os.path.join(run_dir, f"final{suffix}.mp4")
    # R15: final.mp4 cache is valid ONLY if video.mp4 AND mix.wav content
    # hashes match what the shipped file was built from. Duration alone is
    # NEVER a reuse condition (that is how the silent v1 shipped).
    final_fp = None
    if os.path.isfile(final):
        final_fp = hashlib.sha256(
            f"{FINAL_FP_VERSION}|{sha256_file(video)}|{sha256_file(mix_wav)}"
        .encode()).hexdigest()
        fmeta = None
        try:
            fmeta = json.load(open(os.path.join(run_dir, f"final{suffix}.meta.json")))
        except Exception:
            pass
        mux_ok = bool(fmeta and fmeta.get("fingerprint") == final_fp)
        qc["final_fingerprint"] = final_fp
        qc["final_cache"] = "hit" if mux_ok else "miss"
    else:
        mux_ok = False
        qc["final_cache"] = "no-file"
    if not mux_ok:
        print("[s6] mux video.mp4 + mix.wav -> final.mp4", flush=True)
        sh(["ffmpeg", "-y", "-v", "error", "-i", video, "-i", mix_wav,
            "-map", "0:v", "-map", "1:a", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-shortest",
            "-movflags", "+faststart", final], timeout=900)
        mean, mx = volumedetect(final, tlimit=300)
        print(f"[s6] final gate: mean={mean}dB max={mx}dB", flush=True)
        if mx is None or mx < -12.0:
            os.remove(final)
            raise RuntimeError(f"FINAL AUDIO GATE FAILED: max={mx}dB — mux broken")
        qc["final_loudness"] = {"mean_db": mean, "max_db": mx}
        # GATE 3: narration verified on the SHIPPED FILE's audio stream —
        # beginning, middle and end of the actual deliverable.
        ok, voicerep = verify_narration_in_mix(final, timings, starts, total)
        qc["final_narration_verification"] = voicerep
        if not ok:
            os.remove(final)
            json.dump(qc, open(os.path.join(work, f"qc_report{suffix}.json"), "w"), indent=1)
            raise RuntimeError("NARRATION GATE FAILED on final.mp4 audio stream — "
                               "mux produced a narration-free deliverable")
        json.dump({"fingerprint": final_fp,
                   "video_sha256": sha256_file(video),
                   "mix_sha256": sha256_file(mix_wav)},
                  open(os.path.join(run_dir, f"final{suffix}.meta.json"), "w"), indent=1)
    else:
        print("[s6] final cache HIT (fingerprint match)", flush=True)
        # R15: record evidence even on cache hit — the QC report must always
        # contain the shipped-file narration verification.
        ok, voicerep = verify_narration_in_mix(final, timings, starts, total)
        qc["final_narration_verification"] = voicerep
        if not ok:
            os.remove(final)
            json.dump(qc, open(os.path.join(work, f"qc_report{suffix}.json"),
                               "w"), indent=1)
            raise RuntimeError("NARRATION GATE FAILED on cached final.mp4 — "
                               "invalidated")
        mean, mx = volumedetect(final, tlimit=300)
        qc["final_loudness"] = {"mean_db": mean, "max_db": mx}
    json.dump(qc, open(os.path.join(work, f"qc_report{suffix}.json"), "w"), indent=1)
    return final


def make_trailer(run_dir, starts, total):
    """55s trailer: hook + 3 chapter peaks + ending, cut from the master.
    Skippable via VF_NO_TRAILER=1 (speed priority)."""
    trailer = os.path.join(run_dir, "trailer.mp4")
    if os.environ.get("VF_NO_TRAILER") == "1":
        return trailer if os.path.isfile(trailer) else None
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
