#!/usr/bin/env python3
"""Stage 5 (v3): RESTRAINED CINEMATIC DOCUMENTARY SCORE.

Rebuilt after R15 user verdict: the opuscar pop-engine (kick + hats + 8th-note
bass + 16th plucks) reads as upbeat/dance — wrong for a serious documentary.

Design contract (user directive, R15):
  - sparse, atmospheric, reflective, cinematic
  - SLOW harmonic movement: one chord per two bars (66 bpm), minor key
  - soft pads, sustained low textures, sparse piano-like accents only
  - emotional progression across chapters (section intensity curve), with
    deliberate near-silence pockets where statements need room to land
  - BANNED: kick patterns, hats, dance/pop energy, fast plucks, busy
    arpeggios, pulsing bass grooves, continuous celebratory music, abrupt
    changes, distortion
  - mix headroom: RMS ~ -26 dBFS, peak <= -6 dBFS (s6 loudnorms the MIX with
    voice to -14 LUFS; the bed must sit beneath narration, never lead it)
Deterministic (seeded RNG). Cache: bed.meta.json carries a fingerprint of
composer version + sections + duration — ANY change recomposes and thereby
invalidates every downstream artifact (s6 fingerprints the bed content).
"""
import hashlib
import json
import os
import subprocess
import sys
import wave

import numpy as np

SR = 48000
COMPOSER_VERSION = "cinematic-documentary-v1"
SEED = 709

# ---- harmonic material (D minor center; voicings >= MIDI 46) ---------------
PROGS = {
    "reflective": [
        {"root": 38, "voicing": (50, 53, 57, 60, 64)},   # Dm9
        {"root": 34, "voicing": (46, 50, 53, 57)},       # Bbmaj7
        {"root": 41, "voicing": (53, 57, 60)},           # F
        {"root": 36, "voicing": (48, 52, 55, 60)},       # Cadd9
    ],
    "building": [
        {"root": 38, "voicing": (50, 53, 57, 62)},       # Dm
        {"root": 43, "voicing": (55, 58, 62, 65)},       # Gm7
        {"root": 34, "voicing": (46, 50, 53, 58)},       # Bb6
        {"root": 45, "voicing": (57, 61, 64)},           # A (V of Dm)
    ],
    "tension": [
        {"root": 38, "voicing": (50, 53, 57)},           # Dm
        {"root": 39, "voicing": (51, 55, 58)},           # Eb (neapolitan colour)
        {"root": 43, "voicing": (55, 58, 62, 65)},       # Gm7
        {"root": 45, "voicing": (57, 61, 64)},           # A
    ],
    "resolve": [
        {"root": 38, "voicing": (50, 53, 57, 60, 64)},   # Dm9
        {"root": 34, "voicing": (46, 50, 53, 57)},       # Bbmaj7
        {"root": 43, "voicing": (55, 58, 62)},           # Gm7
        {"root": 38, "voicing": (50, 53, 57)},           # Dm (home)
    ],
}
# per-scene label -> (intensity, mode)
LABEL_ARC = {
    "hook": (0.55, "reflective"),
    "cold_open": (0.55, "reflective"),
    "early life": (0.42, "reflective"),
    "background": (0.42, "reflective"),
    "training days": (0.45, "reflective"),
    "trainee": (0.45, "reflective"),
    "multilingual talent": (0.48, "reflective"),
    "debut anticipation": (0.52, "building"),
    "debut moment": (0.62, "building"),
    "record-breaking moment": (0.70, "building"),
    "international recognition": (0.66, "building"),
    "commercial success": (0.68, "building"),
    "work ethic": (0.58, "reflective"),
    "maintaining momentum": (0.62, "building"),
    "pressure of fame": (0.50, "tension"),
    "scrutiny": (0.50, "tension"),
    "cultural impact": (0.56, "reflective"),
    "outro": (0.48, "resolve"),
}
DEFAULT_ARC = [(0.50, "reflective"), (0.60, "building"), (0.50, "tension"),
               (0.55, "building"), (0.45, "resolve")]


def m2f(m):
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


def fft_shape(x, func):
    X = np.fft.rfft(x)
    hz = np.fft.rfftfreq(len(x), 1.0 / SR)
    X *= func(hz)
    return np.fft.irfft(X, len(x))


# ---------------- instruments (all percussion-free) -------------------------

def pad_chord(notes, dur, intensity=0.6):
    """Soft detuned triad stack, LP-tilted, very slow edges (2.2s in, 2.8s out)."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    rng = np.random.default_rng(7000 + sum(notes))
    for m in notes:
        f = m2f(m)
        for det, g in ((-0.004, 0.5), (0.0, 1.0), (0.004, 0.5)):
            fd = f * (1.0 + det)
            ph = rng.uniform(0, 2 * np.pi, 6)
            v = np.zeros(n)
            for h in range(1, 7):
                v += (1.0 / h ** 1.8) * np.sin(2 * np.pi * h * fd * t + ph[h - 1])
            out += g * v / (9.0 * len(notes) ** 0.5)
    out = fft_shape(out, lambda h: 1.0 / np.sqrt(1.0 + (h / 1200.0) ** 4))
    a = int(2.2 * SR)
    r = int(2.8 * SR)
    env = np.ones(n)
    if n > a + r:
        env[:a] = np.linspace(0, 1, a) ** 2
        env[-r:] *= np.linspace(1, 0, r) ** 1.5
    return out * env * (0.55 + 0.45 * intensity)


def low_string(root_midi, dur, intensity=0.6):
    """Sustained low layer: detuned saw-ish stack, LP 700 Hz, 3 s swell."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = m2f(root_midi)
    out = np.zeros(n)
    rng = np.random.default_rng(8800 + root_midi)
    for det in (-0.006, -0.002, 0.003, 0.007):
        ph = rng.uniform(0, 2 * np.pi)
        # band-limited-ish saw via first 8 harmonics
        v = np.zeros(n)
        for h in range(1, 9):
            v += (1.0 / h) * np.sin(2 * np.pi * h * f * (1 + det) * t + ph * h)
        out += v / 8.0
    out = fft_shape(out, lambda h: 1.0 / np.sqrt(1.0 + (h / 700.0) ** 4))
    a = int(3.0 * SR)
    r = int(2.0 * SR)
    env = np.ones(n)
    if n > a + r:
        env[:a] = np.linspace(0, 1, a) ** 1.5
        env[-r:] *= np.linspace(1, 0, r)
    return out * env * (0.30 + 0.55 * intensity)


def piano_tone(midi, vel=0.5):
    """Sparse accent: felt-piano-like decaying tone (fundamental + soft
    partials), 5 s natural decay. Used at most once every two bars."""
    dur = 5.0
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = m2f(midi)
    rng = np.random.default_rng(6600 + midi)
    x = (np.sin(2 * np.pi * f * t)
         + 0.42 * np.sin(2 * np.pi * 2 * f * t + rng.uniform(0, 6))
         + 0.18 * np.sin(2 * np.pi * 3.01 * f * t)
         + 0.08 * np.sin(2 * np.pi * 4.02 * f * t))
    x *= np.exp(-t * 1.05)
    attack = int(0.006 * SR)
    x[:attack] *= np.linspace(0, 1, attack)
    x = fft_shape(x, lambda h: 1.0 / np.sqrt(1.0 + (h / 2600.0) ** 3))
    return x * vel


def sub_root(root_midi, dur):
    """Deep sustained root, two octaves down, near-imperceptible glue."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = m2f(root_midi - 12)
    x = np.sin(2 * np.pi * f * t)
    a = int(0.8 * SR)
    x[:a] *= np.linspace(0, 1, a)
    x[-a:] *= np.linspace(1, 0, a)
    return x * 0.8


def air_bed(dur):
    """Brownian 'air' floor, 60s crossfade-looped (memory-safe)."""
    seg = 60.0
    n = int(seg * SR)
    rng = np.random.default_rng(777)
    x = np.cumsum(rng.uniform(-1, 1, n))
    x /= np.abs(x).max() + 1e-9
    x = fft_shape(x, lambda h: 1.0 / np.sqrt(1.0 + (h / 400.0) ** 4))
    x /= np.abs(x).max() + 1e-9
    xf = int(2.0 * SR)
    loop = x[:n - xf].copy()
    w = np.linspace(0, 1, xf)
    loop[-xf:] = x[n - xf:] * (1 - w) + x[:xf] * w
    reps = int(np.ceil(dur / (seg - 2.0)))
    return np.tile(loop.astype(np.float32), reps)[:int((dur + 1.0) * SR)]


# ---------------- score assembly ----------------

def sections_from_run(run_dir, total):
    """Derive (start, end, intensity, mode) sections from script labels."""
    try:
        plan = json.load(open(os.path.join(run_dir, "02_script.json")))
        tl = json.load(open(os.path.join(run_dir, "06_timeline.json")))
        starts = {int(k): v for k, v in tl.get("starts", {}).items()}
        durs = {int(k): v for k, v in tl.get("durations", {}).items()}
        scenes = plan.get("scenes") or [s for seg in plan.get("segments", [])
                                        for s in seg["scenes"]]
        if not scenes or not starts:
            raise ValueError("no timeline")
        secs = []
        for sc in scenes:
            sid = sc["id"]
            st = starts.get(sid)
            d = durs.get(sid, 6.0)
            if st is None:
                continue
            it, mode = LABEL_ARC.get((sc.get("label") or "").lower().strip(),
                                     (0.52, "reflective"))
            secs.append({"start": round(st, 2), "end": round(st + d, 2),
                         "intensity": it, "mode": mode})
        if secs:
            secs[-1]["end"] = round(total, 2)
            return secs
    except Exception:
        pass
    # fallback: even five-act arc
    edges = np.linspace(0, total, len(DEFAULT_ARC) + 1)
    return [{"start": round(float(edges[i]), 2), "end": round(float(edges[i + 1]), 2),
             "intensity": it, "mode": mode}
            for i, (it, mode) in enumerate(DEFAULT_ARC)]


def intensity_at(sections, t):
    for s in sections:
        if s["start"] <= t < s["end"]:
            return s["intensity"], s["mode"]
    return sections[-1]["intensity"], sections[-1]["mode"]


def compose(total_dur, sections):
    """Render the score into L/R float32 buffers. Deterministic."""
    bpm = 66.0
    beat = 60.0 / bpm
    bar = 4 * beat                # 3.636 s
    chord_dur = 2 * bar           # slow harmonic movement: 7.27 s per chord
    n_total = int((total_dur + 1.0) * SR)
    L = np.zeros(n_total, np.float32)
    R = np.zeros(n_total, np.float32)

    def add(snd, at, gl, gr):
        i0 = int(at * SR)
        if i0 >= n_total or i0 < 0:
            return
        i1 = min(i0 + len(snd), n_total)
        seg = snd[:i1 - i0]
        if seg.dtype != np.float32:
            seg = seg.astype(np.float32)
        L[i0:i1] += seg * np.float32(gl)
        R[i0:i1] += seg * np.float32(gr)

    # chord timeline: walk the section modes, chord index advances slowly
    chords = []
    t = 0.0
    ci = 0
    while t < total_dur:
        _, mode = intensity_at(sections, t)
        prog = PROGS[mode]
        chords.append((t, prog[ci % len(prog)], mode))
        ci += 1
        t += chord_dur

    # pads + sub + low strings per chord slot (crossfaded tails)
    pad_cache = {}
    for (t0, ch, mode) in chords:
        key = (tuple(ch["voicing"]), round(intensity_at(sections, t0)[0], 2))
        if key not in pad_cache:
            pad_cache[key] = pad_chord(list(ch["voicing"]),
                                       chord_dur + 3.0, key[1])
        inten, mode_now = intensity_at(sections, min(t0 + 0.1, total_dur - 0.01))
        g = 0.16 * (0.35 + 0.95 * inten)
        add(pad_cache[key], t0, g, g)
        add(sub_root(ch["root"], chord_dur + 0.5), t0,
            0.10 * (0.5 + inten), 0.10 * (0.5 + inten))
        if inten >= 0.42:      # low strings enter with the development
            add(low_string(ch["root"] + 12, chord_dur + 1.0, inten), t0,
                0.05 + 0.11 * inten, 0.05 + 0.11 * inten)
        if inten >= 0.55:      # airy bloom at emotional peaks
            hp = pad_chord([m + 12 for m in ch["voicing"]], chord_dur + 3.0, inten)
            add(hp, t0, 0.045 + 0.05 * inten, 0.045 + 0.05 * inten)

    # sparse piano accents: at most one per 2 chords (14.5 s), chord tones,
    # velocity follows intensity — a deliberate accent, never a pattern
    rng = np.random.default_rng(SEED)
    for k, (t0, ch, mode) in enumerate(chords):
        if k % 2 == 1 or rng.uniform() > 0.75:
            continue
        inten, _ = intensity_at(sections, t0)
        tones = list(ch["voicing"]) + [ch["voicing"][-1] + 7]   # add a 9th option
        m = int(tones[rng.integers(0, len(tones))]) + 12
        note = piano_tone(m, vel=0.12 + 0.30 * inten)
        when = t0 + rng.uniform(0.3, 2.2)
        add(note, when, 0.30, 0.26)     # slightly off-center stereo

    # air floor
    add(air_bed(total_dur + 1.0), 0.0, 0.045, 0.045)

    # section dynamics + silence pockets: near-silence (air only) in the last
    # 1.6s of every section, eased with cosine ramps (never abrupt)
    for i, s in enumerate(sections[:-1]):
        b0 = max(s["end"] - 1.6, s["start"])
        i0, i1 = int(b0 * SR), int(s["end"] * SR)
        if i1 <= i0 or i1 > n_total:
            continue
        dip = (0.12 + 0.88 * np.abs(np.cos(np.linspace(0, np.pi / 2, i1 - i0)))
               ).astype(np.float32)  # 1.0 -> 0.12
        L[i0:i1] *= dip
        R[i0:i1] *= dip
        # gentle re-bloom into the next section (1.2s)
        j0, j1 = i1, min(int((s["end"] + 1.2) * SR), n_total)
        if j1 > j0:
            bloom = (0.3 + 0.7 * np.linspace(0, 1, j1 - j0)).astype(np.float32)
            L[j0:j1] *= bloom
            R[j0:j1] *= bloom

    # global fade-out last 4 s
    f = min(int(4.0 * SR), n_total)
    ramp = np.linspace(1, 0, f).astype(np.float32)
    L[-f:] *= ramp
    R[-f:] *= ramp
    return L, R


def _rms_peak(L, R):
    n2 = 2.0 * len(L)
    rms = float(np.sqrt((np.dot(L, L) + np.dot(R, R)) / n2))
    peak = float(max(-L.min(), L.max(), -R.min(), R.max()))
    return rms, peak


def run(run_dir, total_dur, sections=None):
    out_dir = os.path.join(run_dir, "05_music")
    os.makedirs(out_dir, exist_ok=True)
    bed = os.path.join(out_dir, "bed.wav")
    if sections is None:
        sections = sections_from_run(run_dir, total_dur)
    fp_src = json.dumps({"v": COMPOSER_VERSION, "total": round(total_dur, 2),
                         "sections": sections, "seed": SEED}, sort_keys=True)
    fp = hashlib.sha256(fp_src.encode()).hexdigest()
    meta_p = os.path.join(out_dir, "bed.meta.json")
    if os.path.isfile(bed) and os.path.isfile(meta_p):
        try:
            if json.load(open(meta_p)).get("fingerprint") == fp:
                print(f"[s5] bed cache HIT (fingerprint match)", flush=True)
                return bed
        except Exception:
            pass
    print(f"[s5] composing cinematic score ({COMPOSER_VERSION}) for "
          f"{total_dur:.0f}s, {len(sections)} sections", flush=True)
    L, R = compose(total_dur, sections)
    # headroom mix: RMS target -26 dBFS, hard cap peak -6 dBFS
    rms, peak = _rms_peak(L, R)
    scale = (10 ** (-26 / 20)) / max(rms, 1e-9)
    if peak * scale > 0.501:
        scale = 0.501 / peak
    L *= np.float32(scale)
    R *= np.float32(scale)
    with wave.open(bed, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        chunk = 30 * SR
        for i in range(0, len(L), chunk):
            cl = np.clip(L[i:i + chunk] * np.float32(32767), -32768, 32767)
            cr = np.clip(R[i:i + chunk] * np.float32(32767), -32768, 32767)
            fr = np.empty((len(cl), 2), np.int16)
            fr[:, 0] = cl
            fr[:, 1] = cr
            w.writeframes(fr.tobytes())
    del L, R
    # safety limiter pass (idempotent)
    sh = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", bed,
         "-af", "alimiter=limit=0.501:attack=8:release=120",
         "-c:a", "pcm_s16le", "-f", "wav", bed + ".lim"],
        timeout=900, capture_output=True)
    if sh.returncode == 0:
        os.replace(bed + ".lim", bed)
    else:
        raise RuntimeError(f"bed limiter failed: {sh.stderr.decode()[-300:]}")
    json.dump({"fingerprint": fp, "engine": COMPOSER_VERSION,
               "sections": sections, "duration": total_dur + 1, "seed": SEED},
              open(meta_p, "w"), indent=1)
    json.dump({"engine": COMPOSER_VERSION, "path": bed,
               "duration": total_dur + 1, "sections": len(sections),
               "fingerprint": fp},
              open(os.path.join(run_dir, "05_music.json"), "w"), indent=1)
    # GATES: subtle by design, never clipping, never inaudible
    chk = subprocess.run(["ffmpeg", "-hide_banner", "-i", bed, "-t", "120",
                          "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True)
    mean = mx = None
    for ln in chk.stderr.splitlines():
        if "mean_volume" in ln:
            mean = float(ln.split("mean_volume:")[1].split("dB")[0])
        if "max_volume" in ln:
            mx = float(ln.split("max_volume:")[1].split("dB")[0])
    print(f"[s5] bed gate: mean={mean}dB max={mx}dB", flush=True)
    if mx is None or mx < -24.0 or mx > -5.0:
        raise RuntimeError(f"bed loudness out of documentary range "
                           f"(max {mx} dB) — refusing")
    if mean is None or mean < -50.0:
        raise RuntimeError(f"bed too quiet (mean {mean} dB) — refusing")
    return bed


if __name__ == "__main__":
    run_dir = sys.argv[1]
    t = json.load(open(os.path.join(run_dir, "06_timeline.json")))
    run(run_dir, t["total"])
    print("music done")
