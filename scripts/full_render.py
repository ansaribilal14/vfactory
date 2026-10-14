#!/usr/bin/env python3
"""full_render.py — complete Ahyeon v2 documentary render through s5+s6.
Writes a preliminary timeline so s5 derives real act sections, then runs the
full s6 path (cards, chunks, concat, fingerprinted mix + gates, trailer)."""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "stages"))
from stages import s5_music, s6_render  # noqa: E402

RUN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "runs", "ahyeon-it-girl-v3")


def main():
    run_dir = RUN
    items, plan = s6_render.build_timeline(run_dir)
    total_est = round(sum(i["dur"] for i in items) - s6_render.XF * (len(items) - 1), 3)
    print(f"[full] timeline: {len(items)} items, ~{total_est:.1f}s", flush=True)

    # preliminary timeline for s5 sections (real starts approximated: cards +
    # xfade overlaps are tiny relative to scene lengths)
    starts, acc = {}, 0.0
    for it in items:
        if it["kind"] == "scene":
            starts[it["sc"]["id"]] = round(acc, 2)
        acc += it["dur"] - s6_render.XF
    json.dump({"durations": {str(i["sc"]["id"]): i["dur"] for i in items
                             if i["kind"] == "scene"},
               "starts": {str(k): v for k, v in starts.items()},
               "total": total_est, "scenes": sum(1 for i in items if i["kind"] == "scene"),
               "res": f"{s6_render.W}x{s6_render.H}", "preliminary": True},
              open(os.path.join(run_dir, "06_timeline.json"), "w"), indent=1)

    s5_music.run(run_dir, total_est)          # full-length score, act sections
    info = s6_render.run(run_dir)             # full render + gates + trailer
    print(f"[full] RENDER DONE: {info['total']:.1f}s, {info['scenes']} scenes",
          flush=True)
    qc = json.load(open(os.path.join(run_dir, "06_final", "qc_report.json")))
    print(f"[full] mix cache: {qc.get('cache')}, loudness: {qc.get('mix_loudness')}",
          flush=True)
    vr = (qc.get("final_narration_verification") or {})
    for s in vr.get("scenes", []):
        print(f"[full] final narration scene {s['id']}: corr {s.get('corr')} "
              f"{'PASS' if s.get('pass') else 'FAIL'}", flush=True)
    print(f"[full] verdict: {vr.get('verdict')}", flush=True)


if __name__ == "__main__":
    main()
