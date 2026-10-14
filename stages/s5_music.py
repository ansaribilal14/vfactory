#!/usr/bin/env python3
"""Stage 5: background music — COMPOSED SCORE (technique learned from lemo-opuscar).

Old bug (user: "weird distortion sound in background"): 5 static sine drones
summed to ~1.4 amplitude then slammed with volume=2.8 -> hard digital
clipping. Fixed by composing music instead of droning:

opuscar TECHNIQUE.md rules applied here:
  - real chord progression (pads) + bass with 2nd/3rd harmonics so it speaks
    on phone speakers; sub kept low
  - pad voicings skip notes below MIDI 48; low end ~-3 dB relative to rest
  - round-robin pluck variants to avoid the machine-gun effect
  - mix with headroom (peak <= -6 dB, RMS-targeted), NO output gain slam
  - s6 does voice compression + limiter + two-pass linear loudnorm
Deterministic: seeded RNG (default_rng(709)); every render identical.
"""
import json, os, subprocess, sys, wave

import numpy as np

SR = 48000
PROG = {
    # dark: Am F C G (A minor) — documentary/cinematic minor lift
    "dark": {
        "bpm": 88,
        "pads": [(57, 60, 64), (53, 57, 60), (55, 60, 64), (55, 59, 62)],
        "bass": [45, 41, 48, 43],          # A2 F2 C3 G2 (>= ~87 Hz fundamentals)
        "pluck": [(69, 72, 76, 81), (65, 69, 72, 77), (67, 72, 76, 79), (67, 71, 74, 79)],
        "kick_beats": (0, 2),
    },
    # bright: C G Am F — hype/explainer
    "bright": {
        "bpm": 100,
        "pads": [(60, 64, 67), (59, 62, 67), (57, 60, 64), (53, 57, 60)],
        "bass": [48, 43, 45, 41],          # C3 G2 A2 F2
        "pluck": [(72, 76, 79, 84), (67, 71, 74, 79), (69, 72, 76, 81), (65, 69, 72, 77)],
        "kick_beats": (0, 1, 2, 3),
    },
}
# stem gain plan (peak-safe: worst transient sum ~0.95, RMS far lower)
G = {"sub": 0.11, "bass": 0.21, "pad": 0.15, "pluck": 0.12,
     "kick": 0.30, "hat": 0.055, "air": 0.05}


def m2f(m):
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


def fft_shape(x, func):
    """Apply spectral envelope func(hz)->gain via FFT (fast, loop-free)."""
    X = np.fft.rfft(x)
    hz = np.fft.rfftfreq(len(x), 1.0 / SR)
    X *= func(hz)
    return np.fft.irfft(X, len(x))


# ---------------- instruments ----------------

def ks_pluck(freq, dur=1.4, seed=1):
    """Karplus-Strong pluck (opuscar pluck.py equivalent, numpy period loop)."""
    period = max(int(round(SR / freq)), 2)
    rng = np.random.default_rng(seed)
    buf = rng.uniform(-1.0, 1.0, period)
    out = np.empty(int(dur * SR))
    take = min(period, len(out))
    out[:take] = buf[:take]
    i = period
    d = 0.9962
    while i < len(out):
        buf = d * 0.5 * (buf + np.roll(buf, -1))
        take = min(period, len(out) - i)
        out[i:i + take] = buf[:take]
        i += take
    return fft_shape(out, lambda h: 1.0 / np.sqrt(1.0 + (h / 3200.0) ** 2))


def pad_chord(notes, dur):
    """Detuned soft-saw triad, LP-tilted, slow edges; notes all >= MIDI 48."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    rng = np.random.default_rng(7000 + int(notes[0] * 10))
    for m in notes:
        f = m2f(m)
        for det, g in ((-0.0035, 0.5), (0.0, 1.0), (0.0035, 0.5)):
            fd = f * (1.0 + det)
            ph = rng.uniform(0, 2 * np.pi, 6)
            v = np.zeros(n)
            for h in range(1, 7):
                v += (1.0 / h ** 1.7) * np.sin(2 * np.pi * h * fd * t + ph[h - 1])
            out += g * v / 9.0
    out = fft_shape(out, lambda h: 1.0 / np.sqrt(1.0 + (h / 1500.0) ** 4))
    a = int(0.9 * SR); r = int(0.45 * SR)
    env = np.ones(n)
    env[:a] = np.linspace(0, 1, a) ** 2
    env[-r:] *= np.linspace(1, 0, r)
    return out * env


def bass_pulse(f, dur):
    """8th-note bass: fundamental + 2nd + 3rd harmonics (phone-speaker trick)."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    w = (np.sin(2 * np.pi * f * t) + 0.55 * np.sin(2 * np.pi * 2 * f * t)
         + 0.28 * np.sin(2 * np.pi * 3 * f * t))
    env = np.minimum(t / 0.008, 1.0) * np.exp(-t * 3.0)
    return w * env


def kick_drum():
    n = int(0.30 * SR)
    t = np.arange(n) / SR
    f = 48 + (115 - 48) * np.exp(-t / 0.032)
    w = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.078)
    rng = np.random.default_rng(99)
    click = rng.uniform(-1, 1, int(0.004 * SR)) * 0.4
    w[:len(click)] += click
    return fft_shape(w, lambda h: h < 7000)


def hat():
    n = int(0.09 * SR)
    rng = np.random.default_rng(1234)
    x = rng.uniform(-1, 1, n) * np.exp(-np.arange(n) / SR / 0.024)
    return fft_shape(x, lambda h: (h > 6000).astype(float))


def air_bed(dur):
    """Low 'air' noise floor. Rendered 60s and crossfade-looped (a full-length
    FFT would need >1 GB of temporaries on 27-min films)."""
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
    loop[-xf:] = x[n - xf:] * (1 - w) + x[:xf] * w   # tail fades out, head fades in
    reps = int(np.ceil(dur / (seg - 2.0)))
    out = np.tile(loop.astype(np.float32), reps)[:int((dur + 1.0) * SR)]
    return out


# ---------------- score assembly ----------------

def compose(total_dur, mood):
    cfg = PROG[mood]
    beat = 60.0 / cfg["bpm"]
    bar = 4 * beat
    eighth = beat / 2.0
    six = beat / 4.0
    n_total = int((total_dur + 1.0) * SR)
    L = np.zeros(n_total, np.float32)
    R = np.zeros(n_total, np.float32)

    def add(snd, at, gl, gr):
        i0 = int(at * SR)
        if i0 >= n_total:
            return
        i1 = min(i0 + len(snd), n_total)
        seg = snd[:i1 - i0]
        s32 = seg if seg.dtype == np.float32 else seg.astype(np.float32)
        L[i0:i1] += s32 * np.float32(gl)
        R[i0:i1] += s32 * np.float32(gr)

    # prerender repeating material (round-robin variants per opuscar)
    pads = [pad_chord(ch, bar + 0.9) for ch in cfg["pads"]]
    basses = {}
    plucks = {}
    for root, tones in zip(cfg["bass"], cfg["pluck"]):
        basses[root] = bass_pulse(m2f(root), eighth * 1.9)
        basses[root + 12] = bass_pulse(m2f(root + 12), eighth * 1.9)
        for k, m in enumerate(tones):
            plucks[m] = [ks_pluck(m2f(m), 1.3, seed=m * 31 + v) for v in range(3)]
    kick = kick_drum()
    hats = [hat(), hat() * 0.8]
    air = air_bed(total_dur + 1.0)

    sub_f = [m2f(root - 12) for root in cfg["bass"]]
    rr = 0
    n_bars = int(np.ceil(total_dur / bar))
    brk0 = max(4, (n_bars * 2) // 3)          # breakdown bars (variation)
    for b in range(n_bars):
        t0 = b * bar
        if t0 >= total_dur:
            break
        ch = b % 4
        in_intro = t0 < 8 * beat
        in_brk = brk0 <= b < brk0 + 4
        # pad (every bar, crossfaded tail)
        add(pads[ch], t0, G["pad"] * 0.5, G["pad"] * 0.5)
        # sub: sustained sine per bar
        dur_s = min(bar, total_dur - t0)
        tt = np.arange(int(dur_s * SR)) / SR
        sub = np.sin(2 * np.pi * sub_f[ch] * tt) * np.minimum(tt / 0.05, 1.0)
        sub *= np.exp(-tt / (dur_s * 1.2))
        add(sub, t0, G["sub"], G["sub"])
        if in_intro or in_brk:
            continue                           # pad + sub + air only
        # kick
        for kbeat in cfg["kick_beats"]:
            add(kick, t0 + kbeat * beat, G["kick"], G["kick"])
        # hats on offbeat 8ths
        for e in range(4):
            add(hats[(b + e) % 2], t0 + e * beat + eighth, G["hat"], G["hat"] * 1.1)
        # bass 8ths (accent downbeat), last 8th of bar 4 walks up an octave
        for e in range(8):
            root = cfg["bass"][ch]
            if ch == 3 and e == 7:
                root += 12
            g = G["bass"] * (1.0 if e % 2 == 0 else 0.78)
            add(basses[root], t0 + e * eighth, g, g)
        # pluck 16ths, round-robin, alternating pan
        patt = (0, 2, 1, 3, 2, 0, 3, 1, 0, 2, 1, 3, 2, 3, 1, 2)
        tones = cfg["pluck"][ch]
        for e in range(16):
            m = tones[patt[e]]
            v = plucks[m][rr % 3]
            rr += 1
            pan = 0.35 if e % 2 else -0.35
            add(v, t0 + e * six, G["pluck"] * (1 - pan) / 2 + G["pluck"] / 2,
                G["pluck"] * (1 + pan) / 2 + G["pluck"] / 2)
    add(air, 0, G["air"], G["air"])
    del air

    # global fade-out last 4s
    f = int(4.0 * SR)
    tail = min(f, n_total)
    ramp = np.linspace(1, 0, tail).astype(np.float32)
    L[-tail:] *= ramp
    R[-tail:] *= ramp
    return L, R


def run(run_dir, total_dur, mood=None):
    out_dir = os.path.join(run_dir, "05_music")
    os.makedirs(out_dir, exist_ok=True)
    bed = os.path.join(out_dir, "bed.wav")
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    mood = mood or ("dark" if topic.get("style", "documentary") in
                    ("documentary", "cinematic", "dark") else "bright")
    if not (os.path.isfile(bed) and os.path.isfile(bed + ".ok")):
        print(f"[s5] composing {mood} score for {total_dur:.0f}s", flush=True)
        L, R = compose(total_dur, mood)
        # headroom mix: RMS target -23 dBFS, hard cap peak -6 dB
        # (dot-product RMS + min/max peak: no full-size temporaries)
        n2 = 2.0 * len(L)
        rms = float(np.sqrt((np.dot(L, L) + np.dot(R, R)) / n2))
        scale = (10 ** (-23 / 20)) / max(rms, 1e-9)
        peak = float(max(-L.min(), L.max(), -R.min(), R.max()))
        if peak * scale > 0.501:
            scale = 0.501 / peak
        L *= np.float32(scale); R *= np.float32(scale)
        with wave.open(bed, "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
            chunk = 30 * SR
            for i in range(0, len(L), chunk):
                cl = np.clip(L[i:i + chunk] * np.float32(32767), -32768, 32767)
                cr = np.clip(R[i:i + chunk] * np.float32(32767), -32768, 32767)
                fr = np.empty((len(cl), 2), np.int16)
                fr[:, 0] = cl; fr[:, 1] = cr
                w.writeframes(fr.tobytes())
        del L, R
        # safety limiter pass (idempotent, in-place)
        sh = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", bed,
             "-af", "alimiter=limit=0.891:attack=5:release=80",
             "-c:a", "pcm_s16le", "-f", "wav", bed + ".lim"],
            timeout=600, capture_output=True)
        if sh.returncode == 0:
            os.replace(bed + ".lim", bed)
            open(bed + ".ok", "w").write("1")
        else:
            raise RuntimeError(f"bed limiter failed: {sh.stderr.decode()[-300:]}")
    # GATES: audible on phone speakers AND not clipping
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
    if mx is None or mx < -22.0:
        raise RuntimeError(f"bed too quiet to hear (max {mx} dB) — refusing")
    if mx > -0.7:
        raise RuntimeError(f"bed clipping (max {mx} dB) — refusing (distortion ban)")
    json.dump({"mood": mood, "path": bed, "duration": total_dur + 1,
               "mean_db": mean, "max_db": mx, "engine": "opuscar-composer-v1"},
              open(os.path.join(run_dir, "05_music.json"), "w"), indent=1)
    return bed


if __name__ == "__main__":
    run_dir = sys.argv[1]
    t = json.load(open(os.path.join(run_dir, "06_timeline.json")))
    run(run_dir, t["total"])
    print("music done")
