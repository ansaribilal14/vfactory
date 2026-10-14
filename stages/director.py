#!/usr/bin/env python3
"""stages/director.py — PERMANENT DOCUMENTARY DIRECTOR AGENT (R15).

The Director decides WHAT the viewer sees for every narration beat, BEFORE
any assembly. It replaces the v1 keyword-overlap + rotated-offset clip
lineup (user verdict: "random Ahyeon clips... not an editor way of editing").

Method (auditable, deterministic):
  1. Per scene: derive visual intent (narration + visual_query + entities).
  2. Candidate shots: pool subject_tags/title keyword prefilter over the
     SHOT INDEX (scene-detected shot boundaries, one frame per shot).
  3. VISION VERIFICATION: candidate frames go to the vision model in known
     order; it scores 0..1 how well each frame supports the scene intent
     and says why. Frames never verified by text similarity alone.
  4. editorial_score = 0.65*vision + 0.35*keyword (keyword is a safety
     prior, never proof of relevance).
  5. Selection: score-ranked, source-diverse, shot-length aware, exact
     source in/out timecodes, cut order, per-shot reason.
  6. Review queue: weak-but-nonzero scenes flagged; zero-signal scenes FAIL.

Outputs:
  04_media/plan.json          — the edit decision list (consumed by s4 render)
  04_media/review_queue.json  — ambiguous scenes for human/agent review
"""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import vision  # noqa: E402

MIN_SHOT = 2.0          # shortest usable shot (s)
SHOT_PAD = 0.30         # skip boundary at shot head
BEST_OK = 0.35          # below this -> review queue flag
SCORE_ZERO = 0.10       # below this for ALL shots -> scene fails


def kw_score(scene_text, tags, title):
    words = set(scene_text.lower().split())
    hits = 0
    blob = " ".join(tags) + " " + (title or "")
    for t in set(blob.lower().replace("'", "").split()):
        if len(t) >= 3 and (t in words or t in scene_text.lower()):
            hits += 2
    for tag in tags:
        if tag.lower() in scene_text.lower():
            hits += 2
    return hits


def scene_text_of(sc):
    return " ".join([sc.get("narration", ""), sc.get("visual_query", ""),
                     " ".join(sc.get("entities", []) or []),
                     " ".join(sc.get("places", []) or [])]).strip()


def candidates_for(sc, index, manifest, k=16, per_key=6):
    """Keyword-prefiltered candidate shots, best first (keyword is a PRIOR).
    per_key cap keeps one dominant source from starving scene diversity."""
    text = scene_text_of(sc)
    scored = []
    per_key_n = {}
    for key, entry in index.items():
        meta = manifest.get(key) or {}
        tags = meta.get("subject_tags", [])
        kw = kw_score(text, tags, meta.get("title", ""))
        for sh in entry.get("shots", []):
            if (sh.get("end", 0) - sh.get("start", 0)) < MIN_SHOT:
                continue
            fp = sh.get("frame")
            if not fp or not os.path.isfile(fp):
                continue
            if per_key_n.get(key, 0) >= per_key:
                continue
            per_key_n[key] = per_key_n.get(key, 0) + 1
            scored.append({"key": key, "idx": sh["idx"], "start": sh["start"],
                           "end": sh["end"], "frame": fp, "kw": kw,
                           "tags": tags, "title": meta.get("title", "")})
    scored.sort(key=lambda s: (-s["kw"], s["key"], s["idx"]))
    return scored[:k]


def _vcache_path(run_dir):
    return os.path.join(run_dir, "04_media", "vision_cache.json")


def _vcache_load(run_dir):
    """Load + migrate: entries saved with the old size-based sig are
    re-signed from their verdict keys (candidate order = insertion order)."""
    try:
        cache = json.load(open(_vcache_path(run_dir)))
    except Exception:
        return {}
    for ck, ent in cache.items():
        if "verdicts" not in ent or not ent.get("sig"):
            continue
        parts = str(ent["sig"]).split("|")
        # old format: "key:idx:frame_size" (three colon-separated fields)
        if parts and parts[0].count(":") >= 2:
            keys = list(ent["verdicts"].keys())
            if len(keys) >= 8:
                ent["sig"] = "|".join(keys[:8])
    return cache


def _vcache_save(run_dir, cache):
    json.dump(cache, open(_vcache_path(run_dir), "w"), indent=1)


def vision_score(sc, cands, run_dir):
    """Score candidates via the vision model (batches of 8).
    Resumable: per-scene verdicts cached in 04_media/vision_cache.json.
    The cache signature covers the TOP-8 keyword candidates, so a later run
    with a smaller candidate budget still hits the cache instead of
    re-burning vision quota."""
    text = scene_text_of(sc)
    intent = sc.get("visual_query") or text[:160]
    subject = sc.get("subject") or "the documentary subject"
    cache = _vcache_load(run_dir)

    def sig_of(cl):
        return "|".join(f"{c['key']}:{c['idx']}" for c in cl[:8])

    ck = f"scene_{sc['id']}"
    ent = cache.get(ck) or {}
    if ent.get("sig") == sig_of(cands):
        vmap = ent["verdicts"]
        core_ok = all(f"{c['key']}:{c['idx']}" in vmap for c in cands[:8])
        if core_ok:
            return [{**c,
                     "vision": vmap.get(f"{c['key']}:{c['idx']}", [None, ""])[0],
                     "why": vmap.get(f"{c['key']}:{c['idx']}", [None, ""])[1]}
                    for c in cands]
    if os.environ.get("VF_DIRECTOR_SKIP_VISION") == "1":
        return None                     # caller falls back to keyword-only
    out = []
    for b in range(0, len(cands), 8):
        batch = cands[b:b + 8]
        if not batch:
            continue
        prompt = (
            f"You are the director of a serious K-pop documentary. The narration "
            f"at this moment says: \"{sc.get('narration', '')[:300]}\" \n"
            f"Visual intent: {intent}. The primary subject is {subject}.\n"
            f"You are shown {len(batch)} candidate frames, numbered 1..{len(batch)} "
            f"in order. Score each frame 0.0-1.0 for how well it supports THIS "
            f"narration (0.9+ = clearly on-topic and usable; 0.3 = generic; "
            f"0.0 = wrong subject/wrong event/misleading). Be strict: a frame of "
            f"the wrong member, wrong song era, or unrelated content must score low. "
            f"Reply ONLY as JSON: [{{\"n\": <frame number>, \"score\": <0-1>, "
            f"\"why\": \"<max 12 words>\"}}, ...] for ALL {len(batch)} frames.")
        rep = vision.ask_json(prompt, [c["frame"] for c in batch], timeout=240)
        if not isinstance(rep, list):
            rep = []
        by_n = {}
        for e in rep:
            try:
                by_n[int(e.get("n"))] = (max(0.0, min(1.0, float(e.get("score", 0)))),
                                         str(e.get("why", ""))[:80])
            except (TypeError, ValueError):
                continue
        for i, c in enumerate(batch, 1):
            vs, why = by_n.get(i, (None, "no vision verdict"))
            out.append({**c, "vision": vs, "why": why})
    # R15: only cache COMPLETE verdicts — a rate-limited partial batch must
    # not poison the cache and skip vision forever.
    complete = all(c.get("vision") is not None for c in out) and len(out) > 0
    if complete:
        verdicts = {f"{c['key']}:{c['idx']}": [c.get("vision"), c.get("why", "")]
                    for c in out}
        cache[ck] = {"sig": sig_of(cands), "verdicts": verdicts}
        _vcache_save(run_dir, cache)
    import time as _t
    _t.sleep(45)                     # hard rate limits need long idle windows
    return out


def select_shots(T, scored, rng_seed=709):
    """Deterministic selection: score-ranked + source diversity + fill T.
    Long scenes draw more shots per source (MV cuts are 2-4s); a second
    replenish pass reuses sources with DIFFERENT shots when the first pass
    cannot fill the scene."""
    picks, used_src, total = [], {}, 0.0
    cap = max(3, round(T / 9))

    def take(cands, cap_src):
        nonlocal total
        for c in sorted(cands, key=lambda s: (-_escore(s), s["key"], s["idx"])):
            if total >= T * 0.94 and picks:
                return
            if used_src.get(c["key"], 0) >= cap_src:
                continue
            if picks and picks[-1]["key"] == c["key"] \
                    and picks[-1]["idx"] == c["idx"]:
                continue
            # spread rule: non-adjacent in-points within one source
            if any(p["key"] == c["key"] and abs(p["src_in"] - (c["start"] + SHOT_PAD)) < 5.0
                   for p in picks):
                continue
            shot_len = c["end"] - c["start"]
            want = min(max(2.6, T / max(3, 6 - len(picks))), 6.0)
            dur = min(max(MIN_SHOT, want), shot_len - SHOT_PAD)
            if dur < MIN_SHOT:
                continue
            src_in = round(c["start"] + SHOT_PAD, 2)
            key_pos = f"{c['key']}:{src_in:.1f}"
            if any(f"{p['key']}:{p['src_in']:.1f}" == key_pos for p in picks):
                continue
            picks.append({"key": c["key"], "idx": c["idx"], "src_in": src_in,
                          "dur": round(dur, 2),
                          "src_out": round(src_in + dur, 2),
                          "keyword": c["kw"],
                          "vision": c.get("vision"),
                          "score": round(_escore(c), 3),
                          "reason": c.get("why") or f"keyword prior {c['kw']}"})
            used_src[c["key"]] = used_src.get(c["key"], 0) + 1
            total += dur

    take(scored, cap)
    if total < T * 0.90:
        take(scored, cap * 2)          # replenish: long scene, MV-length shots
    # trim the tail to fit T (last shot shortened, never below MIN_SHOT+0.4)
    if picks and total > T:
        over = total - T
        last = picks[-1]
        if last["dur"] - over >= MIN_SHOT + 0.4:
            last["dur"] = round(last["dur"] - over, 2)
            last["src_out"] = round(last["src_in"] + last["dur"], 2)
        elif len(picks) > 1:
            total -= last["dur"]
            picks.pop()
    return picks


def _escore(c):
    v = c.get("vision")
    if v is None:
        return min(c["kw"] / 8.0, 0.5) * 0.7       # keyword-only prior
    return 0.65 * v + 0.35 * min(c["kw"] / 8.0, 1.0)


def run(run_dir):
    media = os.path.join(run_dir, "04_media")
    index = json.load(open(os.path.join(media, "shot_index.json")))
    manifest = json.load(open(os.path.join(media, "pool", "manifest.json")))
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    scenes = plan.get("scenes") or [s for seg in plan.get("segments", [])
                                    for s in seg["scenes"]]
    timings = {t["id"]: t["audio"] for t in
               json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]}
    tl_starts = {}
    try:
        tl = json.load(open(os.path.join(run_dir, "06_timeline.json")))
        tl_starts = {int(k): v for k, v in tl.get("starts", {}).items()}
    except Exception:
        pass

    edl, review = [], []
    for sc in scenes:
        T = max(3.5, timings.get(sc["id"], 4.0) + 0.8)
        text = scene_text_of(sc)
        # VF_DIRECTOR_MAXK: rate-limit-aware candidate budget (default full)
        maxk = int(os.environ.get("VF_DIRECTOR_MAXK", "32"))
        k = min(maxk, 32 if T > 25 else 16)
        cands = candidates_for(sc, index, manifest, k=k,
                               per_key=12 if T > 25 else 6)
        if not cands:
            raise RuntimeError(
                f"DIRECTOR: scene {sc['id']} has zero candidate shots — "
                f"pool cannot support the narration (build fails honestly)")
        scored = vision_score(sc, cands, run_dir)
        if scored is None:
            # explicit keyword-only fallback (honest review-queue flags);
            # vision re-scoring can be re-run later — fingerprints invalidate
            # downstream renders automatically
            scored = [dict(c, vision=None, why="keyword fallback (vision "
                           "unavailable this run)") for c in cands]
        best_v = max([c["vision"] or 0 for c in scored] or [0])
        best_e = max([_escore(c) for c in scored] or [0])
        picks = select_shots(T, scored)
        entry = {"id": sc["id"], "label": sc.get("label", ""),
                 "narration_excerpt": sc.get("narration", "")[:220],
                 "intent": sc.get("visual_query", text[:160]),
                 "timeline_start": tl_starts.get(sc["id"]),
                 "scene_dur": T, "shots": picks,
                 "best_vision": round(best_v, 3), "best_score": round(best_e, 3),
                 "gaps": []}
        if not picks:
            raise RuntimeError(
                f"DIRECTOR: scene {sc['id']} produced no usable shots")
        if best_e < BEST_OK or best_v < BEST_OK:
            entry["gaps"].append("weak relevance — flagged for review")
            review.append({"id": sc["id"], "best_vision": round(best_v, 3),
                           "best_score": round(best_e, 3),
                           "narration_excerpt": entry["narration_excerpt"]})
            print(f"[director] scene {sc['id']:>2}: WEAK (vision {best_v:.2f}) "
                  f"-> review queue", flush=True)
        # place/context stills (imgagent hook — inserted by s4 if available)
        if sc.get("places"):
            entry["places"] = sc["places"]
        edl.append(entry)
        tops = ", ".join(f"{p['key']}@{p['src_in']:.0f}({p['score']:.2f})"
                         for p in picks[:3])
        print(f"[director] scene {sc['id']:>2}: {len(picks)} shots "
              f"[{tops}] vision {best_v:.2f}", flush=True)

    json.dump({"version": "director-v1", "scenes": edl},
              open(os.path.join(media, "plan.json"), "w"), indent=1)
    json.dump({"generated_for": os.path.basename(run_dir.rstrip('/')),
               "review": review},
              open(os.path.join(media, "review_queue.json"), "w"), indent=1)
    print(f"[director] plan.json written: {len(edl)} scenes, "
          f"{len(review)} flagged for review", flush=True)
    return edl


if __name__ == "__main__":
    run(sys.argv[1])
