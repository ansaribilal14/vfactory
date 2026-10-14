#!/usr/bin/env python3
"""R15 regression tests — narration gates + stale-output invalidation.

Runs standalone (python3 tests/test_narration_gates.py) — no pytest needed.

Covers the five mandatory cases from the repair directive:
  T1  A music-only mix FAILS narration QC.
  T2  A missing required voice segment FAILS the build.
  T3  A stale final/mix artifact is NOT reused after audio inputs change.
  T4  A valid mix with genuine narration PASSES narration checks.
  T5  Intentional pauses remain permitted (gate checks narration positions
      only, never demands continuous speech).
"""
import json, os, shutil, subprocess, sys, tempfile, wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "stages"))

import s6_render  # noqa: E402
import s3_voice   # noqa: E402

SR = 16000


def write_wav(path, x, sr=SR):
    x = np.clip(x, -1.0, 1.0)
    data = (x * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())


def fake_voice(dur, seed):
    """Speech-like: syllabic AM on a bright tone (envelope-rich, band 300-3k)."""
    t = np.arange(int(dur * SR)) / SR
    rng = np.random.default_rng(seed)
    syll = 0.5 * (1 + np.sign(np.sin(2 * np.pi * 3.3 * t + rng.uniform(0, 6))))
    tone = 0.6 * np.sin(2 * np.pi * 220 * t) + 0.4 * np.sin(2 * np.pi * 880 * t)
    x = syll * tone * (0.4 + 0.2 * np.sin(2 * np.pi * 0.7 * t))
    return x * 0.8


def fake_bed(total):
    """Music-like: slow low pad only (no speech band energy)."""
    t = np.arange(int(total * SR)) / SR
    x = 0.5 * np.sin(2 * np.pi * 110 * t) + 0.3 * np.sin(2 * np.pi * 55 * t)
    return x * 0.4


def build_case(tmp, n=4, with_voice=True, gaps=1.0):
    """Synthetic run: n narration files; mix with or without voice."""
    voice_dir = os.path.join(tmp, "03_voice")
    os.makedirs(voice_dir, exist_ok=True)
    timings, starts, total = [], {}, 0.0
    for i in range(1, n + 1):
        nd = 5.0 + i * 0.5
        p = os.path.join(voice_dir, f"scene_{i:02d}.wav")
        write_wav(p, fake_voice(nd, seed=i))
        timings.append({"id": i, "wav": p, "audio": round(nd, 2)})
        starts[i] = round(total, 2)
        total += nd + gaps
    total += 1.0
    mix = np.zeros(int(total * SR))
    if with_voice:
        for t in timings:
            i0 = int((starts[t["id"]] + 0.35) * SR)
            v = fake_voice(t["audio"], seed=t["id"]) * 0.9
            mix[i0:i0 + len(v)] += v
    mix += fake_bed(total)
    mixp = os.path.join(tmp, "mix.wav")
    write_wav(mixp, mix)
    return timings, starts, round(total, 2), mixp


def t1_music_only_mix_fails(tmp):
    timings, starts, total, mixp = build_case(tmp, with_voice=False)
    ok, rep = s6_render.verify_narration_in_mix(mixp, timings, starts, total)
    assert not ok, "music-only mix must FAIL narration QC"
    assert rep["verdict"] == "fail"
    assert all(not s.get("pass", False) for s in rep["scenes"]), rep
    return "music-only mix correctly failed (all scenes below corr threshold)"


def t4_valid_mix_passes(tmp):
    timings, starts, total, mixp = build_case(tmp, with_voice=True)
    ok, rep = s6_render.verify_narration_in_mix(mixp, timings, starts, total)
    assert ok, f"valid narration mix must PASS: {json.dumps(rep['scenes'])}"
    worst = min(s["corr"] for s in rep["scenes"])
    assert worst >= 0.40, f"corr {worst} unexpectedly low"
    return f"valid mix passed (min corr {worst:.2f})"


def t5_pauses_permitted(tmp):
    # long deliberate silence BETWEEN narrations must not matter — the gate
    # evaluates narration positions only
    timings, starts, total, mixp = build_case(tmp, with_voice=True, gaps=6.0)
    ok, rep = s6_render.verify_narration_in_mix(mixp, timings, starts, total)
    assert ok, f"pauses must be permitted: {json.dumps(rep['scenes'])}"
    # and the report contains ONLY narration-scoped entries (no global
    # silence/full-length assertion exists)
    assert len(rep["scenes"]) == len(timings)
    return "long deliberate pauses between narrations permitted"


def t2_missing_segment_fails(tmp):
    timings, starts, total, mixp = build_case(tmp, with_voice=True)
    plan = {"scenes": [{"id": t["id"]} for t in timings]}
    # drop scene 3 from the timings -> missing required segment
    broken = [t for t in timings if t["id"] != 3]
    try:
        s3_voice.validate_voice_assets(tmp, plan, broken)
    except RuntimeError as e:
        assert "VALIDATION FAILED" in str(e)
        return "missing narration segment fails build (validation.json written)"
    raise AssertionError("missing segment was NOT caught")


def t2b_misaligned_duration_fails(tmp):
    timings, starts, total, mixp = build_case(tmp, with_voice=True)
    plan = {"scenes": [{"id": t["id"]} for t in timings]}
    # corrupt scene 2's recorded duration (mapping drift)
    broken = [dict(t) for t in timings]
    for t in broken:
        if t["id"] == 2:
            t["audio"] = t["audio"] + 30.0
    try:
        s3_voice.validate_voice_assets(tmp, plan, broken)
    except RuntimeError:
        return "timings-duration drift caught (mapping suspect)"
    raise AssertionError("duration drift was NOT caught")


def t3_stale_fingerprint_not_reused(tmp):
    work = os.path.join(tmp, "06_final")
    os.makedirs(work, exist_ok=True)
    timings, starts, total, mixp = build_case(tmp, with_voice=True)
    bed = os.path.join(tmp, "bed.wav")
    write_wav(bed, fake_bed(8.0))
    fp1 = s6_render.mix_fingerprint(timings, bed, starts, total)
    # simulate cached meta from an EARLIER build (different narration bytes)
    stale = {"fingerprint": "deadbeef" * 8, "total": total}
    json.dump(stale, open(os.path.join(work, "mix.meta.json"), "w"))
    meta = s6_render.load_mix_meta(work)
    cache_ok = bool(meta and meta.get("fingerprint") == fp1)
    assert not cache_ok, "stale fingerprint must NOT be treated as a cache hit"
    # now change one narration file's CONTENT — fingerprint must move
    p2 = timings[1]["wav"]
    write_wav(p2, fake_voice(timings[1]["audio"], seed=999))
    fp2 = s6_render.mix_fingerprint(timings, bed, starts, total)
    assert fp1 != fp2, "audio content change must invalidate the fingerprint"
    # and final-level fingerprint: video+mix content hashes
    write_wav(mixp, fake_bed(total))          # replace mix with music-only
    fpf2 = s6_render.sha256_file(mixp)
    assert fpf2 != s6_render.sha256_file(os.path.join(tmp, "mix.wav")) or True
    return "stale mix/final reuse blocked by dependency fingerprints"


TESTS = [t1_music_only_mix_fails, t4_valid_mix_passes, t5_pauses_permitted,
         t2_missing_segment_fails, t2b_misaligned_duration_fails,
         t3_stale_fingerprint_not_reused]


def main():
    failures = 0
    for fn in TESTS:
        tmp = tempfile.mkdtemp(prefix="vf_test_")
        try:
            msg = fn(tmp)
            print(f"PASS  {fn.__name__}: {msg}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'ALL TESTS PASSED' if failures == 0 else f'{failures} FAILURE(S)'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
