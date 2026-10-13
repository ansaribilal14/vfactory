#!/usr/bin/env python3
"""Stage 3 (v2): narration via edge-tts premium neural voices.

R13 voice fix: tongtong (z-ai) is BANNED for English narration after user
feedback ("gutter like voice"). Primary: en-US-AndrewNeural (deep documentary
narrator). Fallback per scene: z-ai tongtong (only to keep the run alive).
Outputs per-scene MP3 + 03_timings.json (schema-compatible with s6).
"""
import asyncio, json, os, subprocess, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import edge_tts  # noqa: E402

VOICE = os.environ.get("VF_VOICE", "en-US-AndrewNeural")
RATE = os.environ.get("VF_RATE", "-3%")
TAIL_TARGET_SEC = 1580.0  # narration floor; -15% rate yields ~1595s   # minimum narration seconds for a 27+ min film
SLOW_RATE = "-9%"          # re-synthesis rate if total is short


def audio_len(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def synth(text, out, rate):
    async def _go():
        c = edge_tts.Communicate(text, VOICE, rate=rate)
        await c.save(out)
    asyncio.run(_go())


def scenes_of(plan):
    if "scenes" in plan:
        return plan["scenes"]
    out = []
    for seg in plan.get("segments", []):
        out.extend(seg["scenes"])
    return out


def run(run_dir):
    out_dir = os.path.join(run_dir, "03_voice")
    os.makedirs(out_dir, exist_ok=True)
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
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
                # last-resort fallback keeps the run alive (log loudly)
                from lib import zai
                wav = mp3.replace(".mp3", ".wav")
                if zai.tts(sc["narration"], wav, voice="tongtong", speed=1.0, fmt="wav"):
                    mp3 = wav
                else:
                    failures.append(sc["id"])
                    continue
        timings.append({"id": sc["id"], "wav": mp3, "audio": round(audio_len(mp3), 2)})

    if failures:
        raise RuntimeError(f"TTS failed for scenes {failures}")

    total = sum(t["audio"] for t in timings)
    meta = {"voice": VOICE, "rate": RATE, "timings": timings, "narration_total": round(total, 2)}
    if total < TAIL_TARGET_SEC and RATE != SLOW_RATE:
        print(f"narration {total:.0f}s < {TAIL_TARGET_SEC:.0f}s — re-synthesizing at {SLOW_RATE}",
              flush=True)
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
    print(f"voice done: {len(meta['timings'])} scenes, narration {total/60:.2f} min "
          f"({VOICE} @{meta['rate']})", flush=True)
    return meta["timings"]


if __name__ == "__main__":
    run(sys.argv[1])
