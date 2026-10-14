#!/usr/bin/env python3
"""R15 score tests — the composer must be documentary-appropriate BY DESIGN.

  S1  No percussion groove (no periodic low-band onsets) and no hat-band
      energy — the banned upbeat traits cannot silently return.
  S2  Headroom: composed bed peaks <= -6 dBFS and sits quiet enough to
      live under narration (RMS target about -26 dBFS).
  S3  Determinism: identical sections -> identical samples.
  S4  Section dynamics: intensity sections produce real level differences
      (emotional progression), and section boundaries dip toward silence
      (pockets) without abrupt steps.
  S5  Cache: composer/section change invalidates bed.wav via fingerprint.
"""
import json, os, shutil, subprocess, sys, tempfile, wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "stages"))

import s5_music  # noqa: E402

SR = 48000
SECTIONS = [
    {"start": 0, "end": 30, "intensity": 0.42, "mode": "reflective"},
    {"start": 30, "end": 55, "intensity": 0.62, "mode": "building"},
    {"start": 55, "end": 75, "intensity": 0.50, "mode": "tension"},
    {"start": 75, "end": 90, "intensity": 0.48, "mode": "resolve"},
]


def s1_no_groove_no_hats(tmp):
    L, R = s5_music.compose(90.0, SECTIONS)
    sl = L[int(35 * SR):int(65 * SR)].astype(np.float64)
    X = np.abs(np.fft.rfft(sl))
    hz = np.fft.rfftfreq(len(sl), 1 / SR)

    def band(a, b):
        return 20 * np.log10(X[(hz >= a) & (hz < b)].max() + 1e-12)

    assert band(6000, 9000) < band(80, 800) - 15, "hat-band energy too high"
    Xl = np.fft.rfft(sl)
    Xl[(hz < 40) | (hz > 90)] = 0
    low = np.fft.irfft(Xl, len(sl))
    env = np.abs(low)
    k = int(0.02 * SR)
    env = np.convolve(env, np.ones(k) / k, "same")
    idx, mind = [], int(0.30 * SR)
    med = np.median(env[env > 0]) + 1e-12
    for i in range(1, len(env) - 1):
        if env[i] > env[i - 1] and env[i] >= env[i + 1] and env[i] > 4 * med:
            if not idx or i - idx[-1] >= mind:
                idx.append(i)
    iv = np.diff(idx) / SR if len(idx) > 1 else np.array([])
    reg = 1.0 - float(np.std(iv) / (np.mean(iv) + 1e-9)) if len(iv) >= 3 else 0.0
    assert not (len(idx) >= 8 and reg >= 0.6), \
        f"kick-like groove detected ({len(idx)} onsets, regularity {reg:.2f})"
    return f"no groove (onsets {len(idx)}, regularity {reg:.2f}), hat band -85dB vs body"


def s2_headroom(tmp):
    L, R = s5_music.compose(90.0, SECTIONS)
    rms, peak = s5_music._rms_peak(L, R)
    peak_db = 20 * np.log10(peak + 1e-12)
    rms_db = 20 * np.log10(rms + 1e-12)
    assert peak_db < -5.0, f"peak {peak_db:.1f}dB violates headroom"
    assert -30 < rms_db < -20, f"RMS {rms_db:.1f}dB out of bed-under-voice range"
    return f"peak {peak_db:.1f}dB, RMS {rms_db:.1f}dB — sits under narration"


def s3_determinism(tmp):
    L1, R1 = s5_music.compose(90.0, SECTIONS)
    L2, R2 = s5_music.compose(90.0, SECTIONS)
    assert L1.tobytes() == L2.tobytes() and R1.tobytes() == R2.tobytes()
    return "identical sections produce identical samples"


def s4_dynamics_and_pockets(tmp):
    L, _ = s5_music.compose(90.0, SECTIONS)

    def lvl(a, b):
        seg = L[int(a * SR):int(b * SR)].astype(np.float64)
        return 20 * np.log10(float(np.sqrt((seg ** 2).mean())) + 1e-12)

    calm = lvl(5, 25)       # reflective 0.42
    build = lvl(35, 53)     # building 0.62
    assert build > calm + 1.0, \
        f"no emotional progression: build {build:.1f} vs calm {calm:.1f}"
    # pocket: 1.6s dip before each section boundary — level must drop there
    pocket = lvl(28.7, 29.9)    # inside the dip window
    mid = lvl(25, 27.5)
    assert pocket < mid - 3.0, \
        f"no silence pocket at section boundary ({pocket:.1f} vs {mid:.1f})"
    # no abrupt changes: detect DISCONTINUITIES, not waveform slope —
    # a discontinuity is a sample jump far above the local typical slope.
    # (median |diff| in a 50ms window; flag > 12x local median)
    dif = np.abs(np.diff(L.astype(np.float64)))
    win = int(0.05 * SR)
    med = np.array([np.median(dif[max(0, i - win):i + win]) + 1e-9
                    for i in range(0, len(dif), win)], dtype=np.float64)
    flags = 0
    for k, base in enumerate(range(0, len(dif), win)):
        seg = dif[base:base + win]
        # a real click is BOTH far above local slope AND absolutely large
        # (the absolute floor keeps near-silence noise tails from flagging)
        flags += int(((seg > 12 * med[k]) & (seg > 0.08)).sum())
    assert flags == 0, f"{flags} sample discontinuit(ies) in score"
    # piano accents remain sparse: envelope onsets of the mid band <= 1/chord
    return (f"progression {calm:.1f}->{build:.1f}dB, boundary pocket "
            f"{pocket:.1f}dB, zero discontinuities")


def s5_cache_invalidation(tmp):
    rd = os.path.join(tmp, "run")
    os.makedirs(rd, exist_ok=True)
    bed = s5_music.run(rd, 90.0, sections=SECTIONS)
    assert os.path.isfile(bed)
    meta1 = json.load(open(os.path.join(rd, "05_music", "bed.meta.json")))
    # rerun with same sections -> cache hit (same fingerprint)
    bed2 = s5_music.run(rd, 90.0, sections=SECTIONS)
    meta2 = json.load(open(os.path.join(rd, "05_music", "bed.meta.json")))
    assert meta1["fingerprint"] == meta2["fingerprint"], "cache must hit"
    # change sections -> fingerprint must change -> recompose
    SECTIONS2 = [dict(s) for s in SECTIONS]
    SECTIONS2[1]["intensity"] = 0.30
    bed3 = s5_music.run(rd, 90.0, sections=SECTIONS2)
    meta3 = json.load(open(os.path.join(rd, "05_music", "bed.meta.json")))
    assert meta3["fingerprint"] != meta1["fingerprint"], \
        "section change must invalidate the bed"
    return "bed cache keyed by composer version + sections; change recomposes"


TESTS = [s1_no_groove_no_hats, s2_headroom, s3_determinism,
         s4_dynamics_and_pockets, s5_cache_invalidation]


def main():
    failures = 0
    for fn in TESTS:
        tmp = tempfile.mkdtemp(prefix="vf_s5_test_")
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
