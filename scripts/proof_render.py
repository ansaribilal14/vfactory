#!/usr/bin/env python3
"""proof_render.py — 60-90s proof-of-quality excerpt (R15 directive §8).

Renders scenes 1-3 (hook / it-girl idea / chuncheon+YG stills) through the
REAL pipeline code paths: s6 build_timeline -> pass_a -> pass_b (chunks),
s5 score (real sections), s6 pass_c (mix + fingerprint + narration gates).
The proof must FAIL if narration is missing, music overwhelms speech, or
the edit is wrong — same gates as the full film.
"""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "stages"))
from stages import s5_music, s6_render  # noqa: E402

RUN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "runs", "ahyeon-it-girl-v3")
PROOF_IDS = [1, 2, 3]


def main():
    run_dir = RUN
    work = os.path.join(run_dir, "06_final")
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    timings_all = {t["id"]: t["audio"] for t in
                   json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]}

    # ---- restricted timeline (proof scenes only) ----
    items = []
    starts_map = {}
    acc = 0.0
    for sc in plan["scenes"]:
        if sc["id"] not in PROOF_IDS:
            continue
        d = max(3.5, timings_all.get(sc["id"], 4.0) + s6_render.TAIL)
        items.append({"kind": "scene", "sc": sc, "dur": round(d, 2)})
        starts_map[sc["id"]] = round(acc, 3)
        acc += d
    total = round(acc, 3)
    print(f"[proof] scenes {PROOF_IDS}, total {total:.2f}s", flush=True)

    items = s6_render.pass_a(run_dir, items, plan.get("title", "proof"))
    video, starts, total_v = s6_render.pass_b(items, run_dir)
    print(f"[proof] video path: {video} ({total_v:.2f}s)", flush=True)

    # ---- score for the proof duration ----
    sections = []
    for e in items:
        if e["kind"] != "scene":
            continue
        it, mode = s5_music.LABEL_ARC.get(
            (e["sc"].get("label") or "").lower().strip(), (0.5, "reflective"))
        sections.append({"start": starts.get(e["sc"]["id"], 0.0),
                         "end": starts.get(e["sc"]["id"], 0.0) + e["dur"],
                         "intensity": it, "mode": mode})
    bed = s5_music.run(run_dir, total_v, sections=sections)
    print(f"[proof] bed: {bed}", flush=True)

    # ---- mix + gates (identical to full render path) ----
    timings = [{"id": sc["id"], "wav": t["wav"], "audio": t["audio"]}
               for sc, t in zip(
                   [s for s in plan["scenes"] if s["id"] in PROOF_IDS],
                   [])]
    # rebuild timings restricted to proof scenes
    tjson = json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]
    timings = [t for t in tjson if t["id"] in PROOF_IDS]
    final = s6_render.pass_c(run_dir, starts, total_v, video, timings=timings,
                             bed_path=bed, proof=True)
    print(f"[proof] FINAL: {final}", flush=True)


if __name__ == "__main__":
    main()
