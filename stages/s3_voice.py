#!/usr/bin/env python3
"""Stage 3 (v2): narration via edge-tts premium neural voices.

R13 voice fix: tongtong (z-ai) is BANNED for English narration after user
feedback ("gutter like voice"). Primary + ONLY voice: en-US-AndrewNeural.
R15: the tongtong "keep the run alive" fallback is REMOVED — a failed scene
fails the build loudly. A missing, silent, undecodable, duplicated or
mis-mapped narration segment is a release-blocking failure, and every run
emits a voice validation report (03_voice/validation.json).
"""
import asyncio, json, os, subprocess, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import edge_tts  # noqa: E402

VOICE = os.environ.get("VF_VOICE", "en-US-AndrewNeural")
RATE = os.environ.get("VF_RATE", "-3%")
SLOW_RATE = "-9%"          # re-synthesis rate if a project floor demands it


def audio_len(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def peak_db(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af",
                        "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    for ln in r.stderr.splitlines():
        if "max_volume" in ln:
            try:
                return float(ln.split("max_volume:")[1].split("dB")[0])
            except ValueError:
                pass
    return -99.0


def synth(text, out, rate):
    async def _go():
        c = edge_tts.Communicate(text, VOICE, rate=rate)
        await c.save(out)
    asyncio.run(_go())


def validate_voice_assets(run_dir, plan, timings):
    """R15: per-segment narration validation report (release-blocking).

    Checks every scripted scene has EXACTLY one narration file that is
    present, decodable, non-empty, non-silent, of sane duration, and mapped
    to the right scene id. Missing / duplicated / out-of-range / misaligned
    segments are reported and FAIL the stage.
    """
    want = [sc["id"] for sc in scenes_of(plan)]
    by_id = {}
    dups = []
    for t in timings:
        by_id.setdefault(t["id"], []).append(t)
    entries, problems = [], []
    for sid in want:
        got = by_id.get(sid, [])
        if not got:
            problems.append({"id": sid, "issue": "missing narration segment"})
            continue
        if len(got) > 1:
            dups.append(sid)
        t = got[0]
        p = t["wav"]
        ent = {"id": sid, "wav": p}
        if not os.path.isfile(p):
            ent["issue"] = "file not found"
            problems.append(ent)
            entries.append(ent)
            continue
        d = audio_len(p)
        pk = peak_db(p)
        ent.update({"dur_s": round(d, 2), "peak_db": round(pk, 1)})
        if d < 1.5:
            ent["issue"] = f"too short ({d:.2f}s) — likely truncated TTS"
        elif d > 240.0:
            ent["issue"] = f"implausibly long ({d:.1f}s) — mapping suspect"
        elif pk < -40.0:
            ent["issue"] = f"silent audio (peak {pk}dB)"
        elif d < t.get("audio", 0) - 1.5:
            ent["issue"] = "timings duration exceeds actual audio"
        if "issue" in ent:
            problems.append(ent)
        entries.append(ent)
    extra = sorted(set(by_id) - set(want))
    for sid in extra:
        problems.append({"id": sid, "issue": "unmapped/orphan narration segment"})
    if dups:
        problems.append({"issue": f"duplicated scene ids: {dups}"})
    report = {"voice": VOICE, "rate": RATE, "expected": len(want),
              "found": len(by_id), "segments": entries,
              "problems": problems,
              "verdict": "pass" if not problems else "fail"}
    json.dump(report, open(os.path.join(run_dir, "03_voice", "validation.json"),
                           "w"), indent=1)
    if problems:
        raise RuntimeError(f"VOICE VALIDATION FAILED ({len(problems)} problem(s)): "
                           f"{json.dumps(problems[:5])} — see 03_voice/validation.json")
    print(f"[s3] validation: {len(want)}/{len(want)} narration segments OK",
          flush=True)
    return report


def scenes_of(plan):
    if "scenes" in plan:
        return plan["scenes"]
    out = []
    for seg in plan.get("segments", []):
        out.extend(seg["scenes"])
    return out


def canonical_wav_map(plan, existing_files):
    """Map scene ids -> recovered ch*/outro/cold_open wav filenames.

    Chapter-grouped naming: cold_open_s01/s02 -> 1,2; chN_sXX runs s03..s49;
    outro_s50/s51 -> 50,51. Strays from chapter-boundary duplication
    (ch4_s18, ch7_s50, outro_s52) are excluded: the canonical owner of an id
    is the group whose segment range covers it in the script.
    """
    segs = plan.get("segments") or []
    rng = {}
    for seg in segs:
        ids = [s["id"] for s in seg["scenes"]]
        if ids:
            rng[seg["id"]] = (min(ids), max(ids))
    wavmap = {}
    want = {s["id"] for s in scenes_of(plan)}
    for f in sorted(existing_files):
        stem = f[:-4]
        if "_" not in stem:
            continue
        grp, snum = stem.rsplit("_", 1)
        if not snum.startswith("s") or not snum[1:].isdigit():
            continue
        sid = int(snum[1:])
        if sid not in want:
            continue                      # orphan (e.g. outro_s52)
        lo, hi = rng.get(grp, (sid, sid))
        if not (lo <= sid <= hi):
            continue                      # boundary stray (e.g. ch4_s18)
        wavmap.setdefault(sid, f)         # first canonical owner wins
    return wavmap


def run(run_dir):
    out_dir = os.path.join(run_dir, "03_voice")
    os.makedirs(out_dir, exist_ok=True)
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))

    # R14 fast path: the Andrew @ -15% re-narration WAVs survived the sandbox
    # wipe (git-tracked). Map them canonically instead of re-synthesizing.
    existing = {f for f in os.listdir(out_dir) if f.endswith(".wav")}
    if existing and not any(f.startswith("scene_") for f in existing):
        wavmap = canonical_wav_map(plan, existing)
        if wavmap and len(wavmap) >= len(scenes_of(plan)):
            timings = []
            bad = []
            for sc in scenes_of(plan):
                w = wavmap[sc["id"]]
                p = os.path.join(out_dir, w)
                # hard audio gate: a silent narration must never ship again
                r = subprocess.run(["ffmpeg", "-hide_banner", "-i", p, "-af",
                                    "volumedetect", "-f", "null", "-"],
                                   capture_output=True, text=True)
                mx = 0.0
                for ln in r.stderr.splitlines():
                    if "max_volume" in ln:
                        mx = float(ln.split("max_volume:")[1].split("dB")[0])
                if mx < -40.0:
                    bad.append((sc["id"], mx))
                timings.append({"id": sc["id"], "wav": p,
                                "audio": round(audio_len(p), 2)})
            if bad:
                raise RuntimeError(f"SILENT narration detected {bad} — refusing")
            total = sum(t["audio"] for t in timings)
            floor = plan.get("target_sec", 0)
            if floor and total < floor:
                raise RuntimeError(f"narration total {total:.0f}s < {floor:.0f}s floor "
                                   f"— wav mapping suspect")
            meta = {"voice": VOICE, "rate": os.environ.get("VF_RATE", "-15%"),
                    "timings": timings, "narration_total": round(total, 2),
                    "source": "recovered-wavs"}
            json.dump(meta, open(os.path.join(run_dir, "03_timings.json"), "w"),
                      indent=1)
            print(f"voice RECOVERED: {len(timings)} scenes, "
                  f"narration {total/60:.2f} min (volume gate passed)",
                  flush=True)
            return timings

    timings, failures = [], []

    for sc in scenes_of(plan):
        mp3 = os.path.join(out_dir, f"scene_{sc['id']:02d}.mp3")
        if not (os.path.exists(mp3) and os.path.getsize(mp3) > 3000
                and audio_len(mp3) > 1.5):
            ok = False
            for attempt in range(3):
                try:
                    synth(sc["narration"], mp3, RATE)
                    if os.path.getsize(mp3) > 3000 and audio_len(mp3) > 1.5:
                        ok = True
                        break
                except Exception:
                    time.sleep(2 + attempt * 3)
            if not ok:
                # R15: NO voice substitution. A failed TTS scene fails the
                # build loudly — never silently ship another voice.
                failures.append(sc["id"])
                continue
        timings.append({"id": sc["id"], "wav": mp3, "audio": round(audio_len(mp3), 2)})

    if failures:
        raise RuntimeError(f"TTS failed for scenes {failures}")

    total = sum(t["audio"] for t in timings)
    meta = {"voice": VOICE, "rate": RATE, "timings": timings, "narration_total": round(total, 2)}
    floor = plan.get("target_sec", 0)   # project-scoped length floor (R12 was blackpink-only)
    if floor and total < floor and RATE != SLOW_RATE:
        print(f"narration {total:.0f}s < project floor {floor:.0f}s — "
              f"re-synthesizing at {SLOW_RATE}", flush=True)
        for t in timings:
            os.remove(t["wav"]) if t["wav"].endswith(".mp3") and os.path.exists(t["wav"]) else None
        timings2 = []
        for sc in scenes_of(plan):
            mp3 = os.path.join(out_dir, f"scene_{sc['id']:02d}.mp3")
            synth(sc["narration"], mp3, SLOW_RATE)
            timings2.append({"id": sc["id"], "wav": mp3, "audio": round(audio_len(mp3), 2)})
        total = sum(t["audio"] for t in timings2)
        meta = {"voice": VOICE, "rate": SLOW_RATE, "timings": timings2,
                "narration_total": round(total, 2)}

    json.dump(meta, open(os.path.join(run_dir, "03_timings.json"), "w"), indent=1)
    # R15: release-blocking per-segment validation report
    validate_voice_assets(run_dir, plan, meta["timings"])
    print(f"voice done: {len(meta['timings'])} scenes, narration {total/60:.2f} min "
          f"({VOICE} @{meta['rate']})", flush=True)
    return meta["timings"]


if __name__ == "__main__":
    run(sys.argv[1])
