#!/usr/bin/env python3
"""build_presence.py — AHYEON PRESENCE MAP (the Director's ground truth).

For every pool source, sample frames densely (every 2.0s, 480px) and
vision-classify each frame AGAINST THE VERIFIED AHYEON REFERENCE IMAGE:

  subject: ahyeon_alone     — Ahyeon clearly the main subject (premium)
           ahyeon_in_group  — she is visible among members
           not_ahyeon       — other members / no one identifiable
           graphics         — title card / logo / non-people shot
  energy:  high | mid | low
  note:    short description (outfit, action)

Output: runs/ahyeon-it-girl-v3/04_media/presence/<key>.json
        {meta:{dur,step}, frames:[{t,subject,energy,note}], segments:[...]}

segments = contiguous spans of non-(not_ahyeon|graphics) — the Director's
selectable footage; spans led by ahyeon_alone are marked premium.

Resumable: per-frame verdicts cached in <key>.frames.json; re-runs only
classify uncached frames. Adaptive pacing on 429s (sleep grows, never shrinks).
"""
import json, os, subprocess, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = os.path.join(BASE, "runs", "ahyeon-it-girl-v3")
POOL = os.path.join(RUN, "04_media", "pool")
PRES = os.path.join(RUN, "04_media", "presence")
FRAMES = os.path.join(PRES, "frames")
REF = os.path.join(RUN, "04_media", "reference", "ahyeon_ref.jpg")
STEP = 2.0
BATCH = 8
MINSPAN = 3.0

sys.path.insert(0, BASE)
from lib import vision  # noqa: E402

PROMPT = ("Image 1 is the REFERENCE: it shows AHYEON of BABYMONSTER "
          "(round face, full cheeks, dark eyes). BABYMONSTER has 7 members: "
          "Ruka, Pharita, Asa, AHYEON, Rami, Rora, Chiquita — several look "
          "similar to her at small sizes. For each of the following frames "
          "(numbered 2..{n} in order), classify:\n"
          "- subject: ahyeon_alone (the reference person, face comparable to "
          "image 1: same round face, same features) | ahyeon_in_group (the "
          "reference person visible among members) | not_ahyeon (ANY other "
          "BABYMONSTER member — Ruka/Pharita/Asa/Rami/Rora/Chiquita — or "
          "other people) | graphics (title card, logo, text, empty set)\n"
          "- energy: high (dancing/hype) | mid (performing/walking) | "
          "low (calm/ballad/thoughtful)\n"
          "- note: max 6 words (action + outfit color)\n"
          "IDENTITY RULE: when unsure whether the face matches the reference, "
          "answer not_ahyeon — false negatives are fixed by re-verification, "
          "false positives poison the edit. Reply ONLY JSON: "
          '[{{"n":2,...}},...] for frames 2..{n}.')


def extract_frames(key, src, dur):
    """Sample a frame every STEP seconds at 480px width."""
    os.makedirs(os.path.join(FRAMES, key), exist_ok=True)
    ts, t = [], STEP
    while t < dur - 1.0:
        fp = os.path.join(FRAMES, key, f"{t:07.1f}.jpg")
        if not os.path.isfile(fp) or os.path.getsize(fp) < 1500:
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", src,
                 "-frames:v", "1", "-vf", "scale=640:-2", fp],
                capture_output=True, timeout=60)
        if os.path.isfile(fp) and os.path.getsize(fp) > 1500:
            ts.append(t)
        t += STEP
    return ts


def classify(key, ts, state):
    """Vision-classify uncached frames in batches. Returns frames verdicts."""
    todo = [t for t in ts if str(t) not in state]
    i = 0
    while i < len(todo):
        chunk = todo[i:i + BATCH]
        imgs = [REF] + [os.path.join(FRAMES, key, f"{t:07.1f}.jpg")
                        for t in chunk]
        rep = vision.ask_json(PROMPT.format(n=len(chunk) + 1), imgs,
                              timeout=240, retries=2)
        if not isinstance(rep, list) or not rep:
            print(f"    [429/fail] {key} @ batch {i//BATCH}: backing off...",
                  flush=True)
            time.sleep(60)
            rep = vision.ask_json(PROMPT.format(n=len(chunk) + 1), imgs,
                                  timeout=240, retries=1)
        if isinstance(rep, list) and rep:
            by_n = {}
            for e in rep:
                try:
                    by_n[int(e.get("n"))] = e
                except (TypeError, ValueError):
                    continue
            for j, t in enumerate(chunk, 2):
                e = by_n.get(j)
                if not e:
                    continue
                subj = str(e.get("subject", "")).strip().lower()
                if subj not in ("ahyeon_alone", "ahyeon_in_group", "not_ahyeon",
                                "graphics"):
                    subj = "not_ahyeon"
                state[str(t)] = {"subject": subj,
                                 "energy": str(e.get("energy", "mid")).lower(),
                                 "note": str(e.get("note", ""))[:60]}
            i += len(chunk)
            json.dump(state, open(os.path.join(PRES, f"{key}.frames.json"), "w"))
            time.sleep(2.0)              # gentle pacing; adaptive on 429 above
        else:
            print(f"    [skip] {key}: batch undecodable, advancing", flush=True)
            i += len(chunk)
    return state


def segments_of(ts, state):
    """Contiguous non-negative spans (selectable footage)."""
    segs, cur = [], None
    for t in ts:
        v = state.get(str(t)) or {}
        subj = v.get("subject", "not_ahyeon")
        if subj in ("ahyeon_alone", "ahyeon_in_group"):
            if cur is None:
                cur = {"start": t, "end": t + STEP, "subjects": [subj]}
            else:
                cur["end"] = t + STEP
                cur["subjects"].append(subj)
        else:
            if cur is not None:
                segs.append(cur)
                cur = None
    if cur is not None:
        segs.append(cur)
    out = []
    for s in segs:
        if s["end"] - s["start"] < MINSPAN:
            continue
        alone = sum(1 for x in s["subjects"] if x == "ahyeon_alone")
        out.append({"start": round(s["start"], 1), "end": round(s["end"], 1),
                    "dur": round(s["end"] - s["start"], 1),
                    "premium": alone >= max(1, len(s["subjects"]) // 2),
                    "n_frames": len(s["subjects"]),
                    "alone_ratio": round(alone / max(1, len(s["subjects"])), 2)})
    return out


def run(only=None):
    os.makedirs(PRES, exist_ok=True)
    manifest = json.load(open(os.path.join(POOL, "manifest.json")))
    for key, meta in sorted(manifest.items()):
        if only and key not in only:
            continue
        if meta.get("state") != "ok":
            continue
        src = os.path.join(POOL, f"{key}.mp4")
        if not os.path.isfile(src):
            continue
        t0 = time.time()
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", src],
                           capture_output=True, text=True)
        dur = float(r.stdout.strip() or 0)
        ts = extract_frames(key, src, dur)
        state = {}
        fcache = os.path.join(PRES, f"{key}.frames.json")
        if os.path.isfile(fcache):
            try:
                state = json.load(open(fcache))
            except Exception:
                state = {}
        print(f"[presence] {key}: {dur:.0f}s -> {len(ts)} frames "
              f"({len(state)} cached)", flush=True)
        state = classify(key, ts, state)
        json.dump(state, open(fcache, "w"))
        segs = segments_of(ts, state)
        json.dump({"meta": {"dur": dur, "step": STEP,
                            "title": meta.get("title", ""),
                            "kind": meta.get("kind", ""),
                            "dedicated": "ahyeon_dedicated"
                                         in (meta.get("subject_tags") or [])},
                   "frames": [{"t": t, **state[str(t)]} for t in ts
                              if str(t) in state],
                   "segments": segs},
                  open(os.path.join(PRES, f"{key}.json"), "w"), indent=1)
        n_alone = sum(1 for v in state.values()
                      if v.get("subject") == "ahyeon_alone")
        n_group = sum(1 for v in state.values()
                      if v.get("subject") == "ahyeon_in_group")
        print(f"  -> {len(segs)} segments, {n_alone} ahyeon_alone / "
              f"{n_group} in_group frames, {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    run(sys.argv[1:] or None)
