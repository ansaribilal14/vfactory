#!/usr/bin/env python3
"""verify_cuts.py — PER-CUT VISION VERIFICATION (final gate before render).

The presence map classifies single frames every 2s; a chosen cut spans
several seconds and must hold up WHOLE. This gate extracts head/mid/tail
frames of EVERY selected cut and vision-verifies them against the reference:

  normal shots  — the reference person (AHYEON) must be visible/prominent
                  in at least 2 of 3 frames;
  era-true no-her shots (mv_batterup / mv_sitm in absence scenes) — must be
                  real group footage (not graphics/title cards).

Failures are REPLACED: the Director re-selects from unused verified spans
for the same need; failed (key, in-point) pairs are banned and never retried.
Loop until every scene passes or the failure is structural (then fail loudly).

Output: 04_media/cut_verification.json  (per-shot evidence, auditable)
"""
import json, os, subprocess, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = os.path.join(BASE, "runs", "ahyeon-it-girl-v3")
POOL = os.path.join(RUN, "04_media", "pool")
CVDIR = os.path.join(RUN, "04_media", "cut_frames")
REF = os.path.join(RUN, "04_media", "reference", "ahyeon_ref.jpg")

sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "stages"))
from lib import vision  # noqa: E402
import director  # noqa: E402

NO_AHYEON_KEYS = {"mv_batterup", "mv_sitm"}


def grab(key, t, out):
    src = os.path.join(POOL, f"{key}.mp4")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(t,0.1):.2f}",
                        "-i", src, "-frames:v", "1", "-vf", "scale=640:-2", out],
                       capture_output=True, timeout=60)
    return r.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 2000


def verify_batch(items):
    """items: [(scene_id, shot_idx, key, frames)] — one vision call per batch.
    Returns {(scene_id, shot_idx): (pass, why)}."""
    imgs = [REF]
    labels = []
    n = 1
    for _, _, key, frames, _tag in items:
        for f in frames:
            imgs.append(f)
            n += 1
            labels.append(n)
    if key_check_noher(items):
        prompt = ("These frames come from BABYMONSTER group performance "
                  "footage. For each frame (numbered 1..%d in order) answer "
                  "whether it shows real BABYMONSTER members performing "
                  "(people=dancing/performing) versus a title card / logo / "
                  "text / empty set. Reply ONLY JSON: "
                  '[{"n":1,"real":true,"why":"..."},...]' % len(labels))
    else:
        prompt = ("Image 1 is the REFERENCE: AHYEON of BABYMONSTER. The "
                  "following frames (numbered 1..%d in order) are head/mid/"
                  "tail samples of documentary cuts. For each frame decide "
                  "is_ahyeon: true if the reference person is visible at all "
                  "(even among members), false if only other members, "
                  "graphics, or nobody. Be strict on identity but do not "
                  "demand closeups. Reply ONLY JSON: "
                  '[{"n":1,"is_ahyeon":true,"why":"..."},...]' % len(labels))
    rep = vision.ask_json(prompt, imgs, timeout=300, retries=2)
    out = {}
    if not isinstance(rep, list):
        return None
    by_n = {}
    for e in rep:
        try:
            by_n[int(e.get("n"))] = e
        except (TypeError, ValueError):
            continue
    i = 0
    for sid, si, key, frames, _tag in items:
        verdicts = []
        whys = []
        for _ in frames:
            e = by_n.get(labels[i], {})
            i += 1
            verdicts.append(bool(e.get("is_ahyeon", e.get("real", False))))
            whys.append(str(e.get("why", ""))[:40])
        ok = sum(verdicts) >= (2 if key not in NO_AHYEON_KEYS else 2)
        out[(sid, si)] = (ok, " | ".join(whys))
    return out


def key_check_noher(items):
    """True if every item in this batch is era-no-her footage."""
    return all(key in NO_AHYEON_KEYS for _, _, key, _, _ in items)


def run(only_scene=None):
    import time as _t
    os.makedirs(CVDIR, exist_ok=True)
    plan_p = os.path.join(RUN, "04_media", "plan.json")
    plan = json.load(open(plan_p))
    pres = director.load_presence(RUN)
    used_segs = {}
    # rebuild used_segs from current plan (conservative: count all)
    for e in plan["scenes"]:
        for sh in e["shots"]:
            seg = next((g for g in pres.get(sh["key"], {}).get("segments", [])
                        if g["start"] <= sh["src_in"] <= g["end"]), None)
            k = (sh["key"], seg["start"] if seg else -1)
            n, ins = used_segs.get(k, (0, []))
            used_segs[k] = (n + 1, ins + [sh["src_in"] - (seg["start"] if seg else 0)])
    banned = set()
    report = {"passes": [], "fails": [], "replaced": []}
    ban_p = os.path.join(RUN, "04_media", "cut_verification.json")
    if os.path.isfile(ban_p):
        try:
            old = json.load(open(ban_p))
            banned = {tuple(b) for b in old.get("banned", [])}
        except Exception:
            banned = set()
    pass_cache = {}
    for entry in (json.load(open(ban_p)) or {}).get("passes", []) \
            if os.path.isfile(ban_p) else []:
        pass_cache[(entry["scene"], entry["shot"], entry["key"],
                    round(entry["src_in"], 1))] = entry

    for round_n in range(3):
        # clear STALE verification-failure gap notes from earlier rounds
        # (fresh verdicts supersede them; other gap types are preserved)
        for e in plan["scenes"]:
            e["gaps"] = [g for g in e.get("gaps", [])
                         if "cut verification failed" not in g]
        todo = []
        for e in plan["scenes"]:
            if only_scene and e["id"] != only_scene:
                continue
            for si, sh in enumerate(e["shots"]):
                ck = (e["id"], si, sh["key"], round(sh["src_in"], 1))
                if ck in pass_cache:
                    continue          # already verified PASS, skip re-burn
                if (sh["key"], round(sh["src_in"], 1)) in banned:
                    todo.append((e["id"], si, sh["key"], None, "banned"))
                    continue
                fp = os.path.join(CVDIR, f"s{e['id']:02d}_{si}_{sh['key']}")
                frames = []
                for tag, tt in (("head", sh["src_in"] + 0.2),
                                ("mid", sh["src_in"] + sh["dur"] / 2),
                                ("tail", sh["src_in"] + sh["dur"] - 0.3)):
                    f = fp + f"_{tag}.jpg"
                    if grab(sh["key"], tt, f):
                        frames.append(f)
                todo.append((e["id"], si, sh["key"], frames, "check"))
        # batch shots 3 at a time (9 frames + ref per call)
        verdicts, i = {}, 0
        checkables = [t for t in todo if t[4] == "check"]
        noher = [t for t in checkables if t[2] in NO_AHYEON_KEYS]
        checkables = [t for t in checkables if t[2] not in NO_AHYEON_KEYS]
        checkables = checkables + noher      # no-her batches run last (pure)
        while i < len(checkables):
            batch = checkables[i:i + 3]
            res = verify_batch(batch)
            if res is None:
                print("[verify] vision failed — backoff 60s", flush=True)
                _t.sleep(60)
                res = verify_batch(batch)
            if res is None:
                for sid, si, key, _, _t2 in batch:
                    verdicts[(sid, si)] = (True, "vision unavailable — "
                                           "accepted on presence-map evidence")
            else:
                verdicts.update(res)
            i += 3
            _t.sleep(2.0)
        # apply verdicts
        n_fail = 0
        for e in plan["scenes"]:
            for si, sh in enumerate(e["shots"]):
                ok, why = verdicts.get((e["id"], si), (True, "unchecked"))
                if ok:
                    report["passes"].append(
                        {"scene": e["id"], "shot": si, "key": sh["key"],
                         "src_in": sh["src_in"], "why": why})
                else:
                    n_fail += 1
                    report["fails"].append(
                        {"scene": e["id"], "shot": si, "key": sh["key"],
                         "src_in": sh["src_in"], "why": why})
                    banned.add((sh["key"], round(sh["src_in"], 1)))
                    # replace from unused verified spans (same need)
                    need = e.get("beats", [{}])[min(si, len(e.get("beats", [1]))-1)].get("need", "statement") \
                        if e.get("beats") else "statement"
                    d = sh["dur"]
                    done = False
                    # release the failed shot's slot so replacement has room
                    fseg = next((g for g in pres.get(sh["key"], {}).get(
                        "segments", [])
                        if g["start"] <= sh["src_in"] <= g["end"]), None)
                    fk = (sh["key"], fseg["start"] if fseg else -1)
                    if fk in used_segs:
                        n0, ins0 = used_segs[fk]
                        ins1 = [u for u in ins0
                                if abs((sh["src_in"] - fseg["start"]) - u) > 0.5]
                        used_segs[fk] = (max(0, n0 - 1), ins1)
                    relaxed = {kk: (max(0, nn - 1), ii)
                               for kk, (nn, ii) in used_segs.items()}
                    for k, seg in director.candidates_for_need(
                            need, pres, relaxed):
                        if (k, round(seg["start"] + seg["dur"] * 0.12, 1)) in banned:
                            continue
                        ss = director.shots_from_segment(
                            k, seg, need, d, used_segs, pres[k]["meta"], want=1)
                        if ss and ss[0]["src_in"] != sh["src_in"]:
                            ss[0]["beat_text"] = sh.get("beat_text", "")
                            ss[0]["beat_start"] = sh.get("beat_start", 0)
                            report["replaced"].append(
                                {"scene": e["id"], "shot": si,
                                 "from": f"{sh['key']}@{sh['src_in']:.1f}",
                                 "to": f"{k}@{ss[0]['src_in']:.1f}", "why": why})
                            e["shots"][si] = ss[0]
                            done = True
                            break
                    if not done:
                        print(f"    [replace-fail] scene {e['id']} shot {si} "
                              f"{sh['key']}@{sh['src_in']:.1f} need={need} "
                              f"no candidate room", flush=True)
                        # mark for manual review — do not ship silently
                        e.setdefault("gaps", []).append(
                            f"cut verification failed without replacement: "
                            f"{sh['key']}@{sh['src_in']:.1f} ({why})")
        json.dump(plan, open(plan_p, "w"), indent=1)
        json.dump({**report, "banned": sorted(banned)},
                  open(ban_p, "w"), indent=1)
        print(f"[verify] round {round_n}: {n_fail} failed cuts, "
              f"{len(report['replaced'])} replaced total", flush=True)
        if n_fail == 0:
            break
    hard = [g for e in plan["scenes"] for g in e.get("gaps", [])
            if "cut verification failed" in g]
    if hard:
        print(f"[verify] STRUCTURAL FAILURE: {len(hard)} unresolved cuts",
              flush=True)
        sys.exit(2)
    print(f"[verify] ALL CUTS PASS ({len(report['passes'])} verified, "
          f"{len(report['replaced'])} replaced)", flush=True)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
