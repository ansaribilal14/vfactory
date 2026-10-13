#!/usr/bin/env python3
"""Stage 5: background music bed — synthesized, zero licensing risk.
Two moods: 'dark' (documentary/cinematic) and 'bright' (hype/explainer).
Recipe proven in scripts/doc_audio_proof.sh (Session 28): drone layers +
tremolo + filtered air, ducked under VO in stage 6 via sidechaincompress."""
import json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(__file__))


def run(run_dir, total_dur, mood=None):
    out_dir = os.path.join(run_dir, "05_music")
    os.makedirs(out_dir, exist_ok=True)
    bed = os.path.join(out_dir, "bed.wav")
    dur = int(total_dur + 2)
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    mood = mood or ("dark" if topic.get("style", "documentary") in
                    ("documentary", "cinematic", "dark") else "bright")

    if mood == "dark":
        # R14 rebalance: user heard NO music on phone speakers — the old bed
        # was sub-bass dominated (55Hz) + crushed by 8:1 ducking. Mids up,
        # sub down, overall hotter; audibility gate added at the end.
        layers = [
            ("sine=frequency=55:duration=%d", 0.20, 0.15, 0.35),
            ("sine=frequency=110:duration=%d", 0.42, 0.11, 0.45),
            ("sine=frequency=164.81:duration=%d", 0.34, 0.10, 0.50),
            ("sine=frequency=220.5:duration=%d", 0.30, 0.12, 0.60),
            ("sine=frequency=329.6:duration=%d", 0.16, 0.09, 0.55),
        ]
    else:  # bright — C major-ish stack
        layers = [
            ("sine=frequency=65.41:duration=%d", 0.20, 0.15, 0.35),
            ("sine=frequency=130.81:duration=%d", 0.40, 0.11, 0.45),
            ("sine=frequency=196.00:duration=%d", 0.32, 0.10, 0.50),
            ("sine=frequency=261.63:duration=%d", 0.28, 0.12, 0.60),
            ("sine=frequency=392.00:duration=%d", 0.16, 0.09, 0.55),
        ]

    inputs, chains = [], []
    names = ["drone", "sub", "fifth", "pad", "spark"]
    for idx, (src, vol, tf, td) in enumerate(layers):
        inputs += ["-f", "lavfi", "-i", src % dur]
        chains.append(f"[{idx}]volume={vol},tremolo=f={tf}:d={td}[{names[idx]}]")
    noise_idx = len(layers)
    inputs += ["-f", "lavfi", "-i", f"anoisesrc=color=brown:duration={dur}:amplitude=0.05"]
    chains.append(f"[{noise_idx}]lowpass=f=500,volume=0.10[air]")
    mix_in = "".join(f"[{n}]" for n in names) + "[air]"

    n_in = len(layers) + 1
    fc = (";".join(chains) + ";" + mix_in +
          f"amix=inputs={n_in}:duration=longest:normalize=0,"
          f"lowpass=f=1400,aecho=0.7:0.6:311|433:0.25|0.18,"
          f"apulsator=hz=0.08:width=0.6,"
          f"afade=t=in:d=4,afade=t=out:st={max(dur - 6, 1)}:d=6,"
          f"aformat=channel_layouts=stereo[bed]")
    proc = subprocess.run(["ffmpeg", "-y", "-v", "error"] + inputs +
                          ["-filter_complex", fc, "-map", "[bed]", "-ar", "48000", bed],
                          capture_output=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"bed synth failed: {proc.stderr.decode()[-400:]}")
    # AUDIBILITY GATE: the bed must actually register on a meter
    chk = subprocess.run(["ffmpeg", "-hide_banner", "-i", bed, "-t", "120",
                          "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True)
    mean = mx = None
    for ln in chk.stderr.splitlines():
        if "mean_volume" in ln:
            mean = float(ln.split("mean_volume:")[1].split("dB")[0])
        if "max_volume" in ln:
            mx = float(ln.split("max_volume:")[1].split("dB")[0])
    if mx is None or mx < -22.0:
        raise RuntimeError(f"bed too quiet to hear (max {mx} dB) — refusing")
    json.dump({"mood": mood, "path": bed, "duration": dur},
              open(os.path.join(run_dir, "05_music.json"), "w"), indent=1)
    return bed


if __name__ == "__main__":
    run_dir = sys.argv[1]
    t = json.load(open(os.path.join(run_dir, "06_timeline.json")))
    run(run_dir, t["total"])
    print("music done")
