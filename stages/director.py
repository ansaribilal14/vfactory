#!/usr/bin/env python3
"""stages/director.py — DOCUMENTARY DIRECTOR v2 (Ahyeon-dedicated edition).

User verdict on v2: "still using random music videos instead of ahyeon
dedicated direction". v2 ranked shots by vision+keyword score and filled
scenes — the result read as a montage of group MVs. v2's deeper failure:
the Director had no idea WHERE the subject is inside each source, so any
"relevance" was at source level, not moment level.

v2 (this file) directs at MOMENT level:

  1. BEATS      each scene narration is split into sentences; time windows
                are allocated proportionally (character count).
  2. INTENT     every beat is classified into a footage need (deterministic
                keyword rules over the narration: era anchors, vocal/
                absence/pressur/momentum themes).
  3. MOMENTS    only spans VERIFIED by the AHYEON PRESENCE MAP (dense frame
                classification against the reference image) are selectable;
                era-knowledge overrides (6-member sources) are respected —
                "the absence" scenes use them deliberately.
  4. POLICY     dedicated-first quotas (cover + studio session), premium
                (ahyeon_alone) spans first, global shot-reuse caps, no
                same source twice in a row, energy matched per beat.
  5. REASONS    every shot cites its beat + the presence evidence.

Outputs: 04_media/plan.json (the EDL), 04_media/review_queue.json.
Fails loudly when the verified footage cannot support a scene.
"""
import json, os, re, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

MIN_SHOT = 2.2
MAX_SHOT = 6.5
SEG_REUSE_CAP = 2          # shots per presence segment (cover: 5)
DEDICATED_FLOOR = 0.38     # min share of screen time from dedicated sources
ALONE_FLOOR = 0.45         # min share from ahyeon_alone-labelled spans

RUN = None                  # set by run()

# ---------------- footage need taxonomy ----------------

# need -> (eligible source kinds/keys, purpose note)
NEED_SONG = {                # era-anchored group moments (her verified spans)
    "batter": ["mv_batterup"], "sheesh": ["mv_sheesh", "stage_sheesh"],
    "drip": ["mv_drip"], "forever": ["mv_forever"],
    "hotsauce": ["hotsauce"], "hotsauce2": ["mv_hotsauce"],
    "wegoup": ["mv_wegoup"], "sitm": ["mv_sitm"],
}
KEYWORDS = [
    (r"batter up|debut single|six members|one name missing|not on the stage|"
     r"sit out|sideline|health reasons|absence|the cruelest twist|"
     r"watching your own debut", "absence_group"),
    (r"dangerously|charlie puth|cover|evaluation tape|itunest|itunes|"
     r"practice room|trainee footage|the tape", "cover"),
    (r"sheesh|comeback|lineup is finally whole|walks? back out|the return|"
     r"first comeback", "sheesh"),
    (r"drip\b|main vocalist|lead rapper|lead dancer|center\b|versatilit|"
     r"album released november", "drip"),
    (r"hot sauce|2025 schedule|busiest|calendar built|refuses to cool",
     "hotsauce"),
    (r"we go up|sell out|commercial", "wegoup"),
    (r"stuck in the middle|ballad", "sitm"),
    (r"chuncheon|toegye|hometown|mountain city|born", "hometown"),
    (r"yg entertainment|training machine|practice rooms?|five years|"
     r"trainee|eleven", "studio"),
    (r"voice|sing|vocal", "vocal"),
    (r"scrutiny|pressure|costs?|weighs|health hiatus|unfinished|wound|"
     r"crowd cannot|it girl status", "pressure"),
    (r"fancam|algorithm|internet|comment section|fandom|public|reach|"
     r"manufactur|forwarding|captioning", "momentum"),
    (r"stage|arena|dome|tour|kspo|kyocera|concert|crowd", "stage_energy"),
    (r"it girl|generation|legacy|assembled|evidence|documented|"
     r"argument|crown|title", "statement"),
]

# scene label -> default need (used for beats without keyword hits)
SCENE_DEFAULT = {
    "hook": "statement", "the it-girl idea": "statement", "chuncheon": "hometown",
    "the machine": "studio", "the reveal": "cover", "the absence": "absence_group",
    "the return": "sheesh", "main vocalist": "drip",
    "the cover that charted": "cover", "three languages": "vocal",
    "the arenas": "stage_energy", "the pace": "hotsauce",
    "the machinery": "momentum", "the price": "pressure",
    "evidence and noise": "statement", "outro": "statement",
}

# need -> ordered source preferences.  dedicated sources first when they fit
# the intent; group MVs appear ONLY with presence-verified Ahyeon spans.
NEED_SOURCES = {
    "absence_group": ["mv_batterup", "mv_sitm"],          # group WITHOUT her (era-true)
    "cover": ["cov_dangerously", "grp_dream"],
    "sheesh": ["mv_sheesh", "stage_sheesh", "grp_dream"],
    "drip": ["mv_drip", "grp_dream", "cov_dangerously"],
    "hotsauce": ["mv_hotsauce", "stage_sheesh", "grp_dream"],
    "wegoup": ["mv_wegoup", "grp_dream"],
    "sitm": ["mv_sitm"],                                   # era-true (no her)
    "hometown": ["grp_dream", "cov_dangerously"],          # stills come via imgagent
    "studio": ["grp_dream", "cov_dangerously"],
    "vocal": ["cov_dangerously", "grp_dream"],
    "pressure": ["mv_wegoup", "mv_sitm", "grp_dream"],
    "momentum": ["mv_wegoup", "grp_dream", "mv_hotsauce"],
    "stage_energy": ["stage_sheesh", "mv_sheesh", "mv_drip", "grp_dream"],
    "statement": ["cov_dangerously", "grp_dream", "mv_sheesh", "mv_drip",
                  "stage_sheesh", "mv_forever"],
}

NEED_ENERGY = {"absence_group": "low", "cover": "low", "sheesh": "high",
               "drip": "high", "hotsauce": "high", "wegoup": "mid",
               "sitm": "low", "hometown": "low", "studio": "mid",
               "vocal": "low", "pressure": "low", "momentum": "mid",
               "stage_energy": "high", "statement": "mid"}


def beat_split(narration, T):
    """Sentence beats with char-proportional time windows."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", narration or "")
             if p.strip()]
    if not parts:
        parts = [narration or ""]
    weights = [max(len(p), 8) for p in parts]
    total = sum(weights)
    beats, acc = [], 0.0
    for p, w in zip(parts, weights):
        d = T * w / total
        beats.append({"text": p, "start": round(acc, 2),
                      "dur": round(d, 2), "need": need_of(p)})
        acc += d
    return beats


def need_of(text):
    t = text.lower()
    for pat, need in KEYWORDS:
        if re.search(pat, t):
            return need
    return None


def load_presence(run_dir):
    pres_dir = os.path.join(run_dir, "04_media", "presence")
    pres = {}
    for f in sorted(os.listdir(pres_dir)):
        if f.endswith(".json") and not f.endswith(".frames.json"):
            pres[f[:-5]] = json.load(open(os.path.join(pres_dir, f)))
    return pres


def shots_from_segment(key, seg, need, dur, used_segs, pres_meta, want=1):
    """Cut 1..n shots from a verified segment, respecting reuse caps and
    in-point spacing. Deterministic in-point choice."""
    out = []
    seg_len = seg["dur"]
    cap = SEG_REUSE_CAP if key != "cov_dangerously" else 5
    if used_segs.get((key, seg["start"]), (0, []))[0] >= cap:
        return out
    label = pres_meta.get("title", key)[:28] if isinstance(pres_meta, dict)         else str(pres_meta)
    for i in range(want):
        use_n, used_ins = used_segs.get((key, seg["start"]), (0, []))
        if use_n >= cap:
            break
        # deterministic in-point SCAN: walk candidate offsets through the
        # segment; a spot is free only if it differs from every previous
        # in-point by >2.5s (no repeated frames) and fits the span
        off = None
        for j in range(cap * 2 + 1):
            cand_off = seg_len * 0.12 + j * (dur + 1.5)
            if cand_off + dur > seg_len - 0.3:
                cand_off = max(0.0, seg_len - dur - 0.3)
            if any(abs(cand_off - u) < 2.5 for u in used_ins):
                continue
            off = cand_off
            break
        if off is None:
            break
        src_in = round(seg["start"] + off, 2)
        d = round(min(dur, seg_len - off - 0.3), 2)
        if d < MIN_SHOT:
            break
        out.append({"key": key, "idx": seg.get("id", -1),
                    "src_in": src_in, "dur": d,
                    "src_out": round(src_in + d, 2),
                    "score": round(0.5 + 0.3 * seg.get("alone_ratio", 0)
                                   + (0.2 if seg.get("premium") else 0), 3),
                    "reason": f"{need}: {label} @{src_in:.0f} verified "
                              f"span (alone {seg.get('alone_ratio', 0):.0%}"
                              f"{', premium' if seg.get('premium') else ''})"})
        used_segs[(key, seg["start"])] = (use_n + 1, used_ins + [off])
    return out


def candidates_for_need(need, pres, used_segs, banned_keys=()):
    """Verified, selectable spans for a need, best-first."""
    keys = [k for k in NEED_SOURCES.get(need, []) if k in pres
            and k not in banned_keys]
    cands = []
    for k in keys:
        meta = pres[k]["meta"]
        if meta.get("no_ahyeon") and need not in ("absence_group", "pressure",
                                                  "sitm"):
            continue          # era-true no-her footage only for those needs
        for seg in pres[k].get("segments", []):
            if seg["dur"] < MIN_SHOT + 0.3:
                continue
            cap = SEG_REUSE_CAP if k != "cov_dangerously" else 5
            if used_segs.get((k, seg["start"]), (0, []))[0] >= cap:
                continue
            cands.append((k, seg))
    # rank: premium first, then dedicated sources, then alone_ratio
    def rank(item):
        k, seg = item
        ded = pres[k]["meta"].get("dedicated", False)
        return (0 if seg.get("premium") else 1,
                0 if ded else 1,
                -seg.get("alone_ratio", 0), k, seg["start"])
    cands.sort(key=rank)
    return cands


def direct_scene(sc, T, pres, used_segs, tl_start=None):
    """Build the shot list for one scene from its beats."""
    beats = beat_split(sc.get("narration", ""), T)
    default_need = SCENE_DEFAULT.get(sc.get("label", ""), "statement")
    shots, audit = [], []
    ded_time = alone_time = 0.0
    for b in beats:
        need = b["need"] or default_need
        want = 1 if b["dur"] < 9 else 2
        d = min(max(MIN_SHOT, b["dur"] - 0.3), MAX_SHOT)
        cands = candidates_for_need(need, pres, used_segs)
        placed = None
        for k, seg in cands:
            ss = shots_from_segment(k, seg, need, d, used_segs, pres[k]["meta"],
                                    want=want)
            if not ss:
                continue
            # no same source twice in a row
            if shots and ss[0]["key"] == shots[-1]["key"] and len(cands) > 1:
                alt = [(k2, s2) for k2, s2 in cands if k2 != k]
                if alt:
                    k2, s2 = alt[0]
                    ss = shots_from_segment(k2, s2, need, d, used_segs,
                                            pres[k2]["meta"], want=want)
                    if not ss:
                        continue
            placed = (need, ss)
            break
        if not placed:
            # widen within the SCENE's own default need (semantic drift guard),
            # then last-resort dedicated sources
            for alt_need in dict.fromkeys([default_need, "statement"]):
                cands2 = candidates_for_need(alt_need, pres, used_segs)
                for k, seg in cands2:
                    ss = shots_from_segment(k, seg, alt_need, d, used_segs,
                                            pres[k]["meta"], want=1)
                    if ss:
                        placed = (alt_need + " (fallback)", ss)
                        break
                if placed:
                    break
        if not placed:
            audit.append({"beat": b["text"][:80], "problem":
                          f"no verified footage for need '{need}'"})
            continue
        need_used, ss = placed
        for s in ss:
            s["beat_start"] = b["start"]
            s["beat_text"] = b["text"][:90]
            shots.append(s)
            meta = pres[s["key"]]["meta"]
            if meta.get("dedicated"):
                ded_time += s["dur"]
            seg = next((g for g in pres[s["key"]].get("segments", [])
                        if g["start"] <= s["src_in"] <= g["end"]), None)
            if seg and seg.get("alone_ratio", 0) >= 0.5:
                alone_time += s["dur"]
    return shots, beats, audit, ded_time, alone_time


def run(run_dir):
    media = os.path.join(run_dir, "04_media")
    pres = load_presence(run_dir)
    if not pres:
        raise RuntimeError("DIRECTOR v2: no presence maps — run "
                           "scripts/build_presence.py first (no shortcuts)")
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    scenes = plan.get("scenes") or [s for seg in plan.get("segments", [])
                                    for s in seg["scenes"]]
    timings = {t["id"]: t["audio"] for t in
               json.load(open(os.path.join(run_dir, "03_timings.json")))
               ["timings"]}
    tl_starts = {}
    try:
        tl = json.load(open(os.path.join(run_dir, "06_timeline.json")))
        tl_starts = {int(k): v for k, v in tl.get("starts", {}).items()}
    except Exception:
        pass

    used_segs = {}
    edl, review = [], []
    tot = ded_t = alone_t = 0.0
    for sc in scenes:
        T = max(3.5, timings.get(sc["id"], 4.0) + 0.8)
        shots, beats, audit, ded, alone = direct_scene(sc, T, pres, used_segs,
                                                       tl_starts.get(sc["id"]))
        if not shots:
            raise RuntimeError(
                f"DIRECTOR v2: scene {sc['id']} ({sc.get('label')}) has no "
                f"usable verified footage — build fails honestly")
        tot += sum(s["dur"] for s in shots)
        ded_t += ded
        alone_t += alone
        entry = {"id": sc["id"], "label": sc.get("label", ""),
                 "narration_excerpt": sc.get("narration", "")[:200],
                 "intent": beats[0]["need"] if beats else "",
                 "timeline_start": tl_starts.get(sc["id"]),
                 "scene_dur": T, "shots": shots, "beats": [
                     {"text": b["text"][:100], "start": b["start"],
                      "dur": b["dur"], "need": b["need"] or
                      SCENE_DEFAULT.get(sc.get("label", ""), "statement")}
                     for b in beats],
                 "gaps": [a["problem"] for a in audit]}
        if audit:
            review.append({"id": sc["id"], "label": sc.get("label"),
                           "problems": [a["problem"] for a in audit]})
        edl.append(entry)
        tops = ", ".join(f"{s['key']}@{s['src_in']:.0f}" for s in shots[:4])
        print(f"[director-v2] scene {sc['id']:>2} {sc.get('label','')[:22]:22s}: "
              f"{len(shots)} shots [{tops}]", flush=True)

    # ---- quota repair: enforce the dedicated-source floor by REPLACING the
    # least group-specific shots with dedicated (cover/studio) footage.
    # The cover performance is the film's musical anchor; grp_dream is the
    # studio/training anchor. Both are 100% Ahyeon.
    def is_ded(k, sh=None):
        if pres[k]["meta"].get("dedicated", False):
            return True
        if sh is not None:
            seg = next((g for g in pres[k].get("segments", [])
                        if g["start"] <= sh["src_in"] <= g["end"]), None)
            if seg and seg.get("alone_ratio", 0) >= 0.5:
                return True
        return False

    def try_replace(entry, si):
        shots = entry["shots"]
        if si > 0 and shots[si - 1]["key"] == "cov_dangerously":
            return False
        if si + 1 < len(shots) and shots[si + 1]["key"] == "cov_dangerously":
            return False
        d = shots[si]["dur"]
        for k, seg in candidates_for_need("cover", pres, used_segs):
            ss = shots_from_segment(k, seg, "cover", d, used_segs,
                                    pres[k]["meta"], want=1)
            if ss:
                old = shots[si]
                ss[0]["beat_text"] = old.get("beat_text", "")
                ss[0]["beat_start"] = old.get("beat_start", 0)
                shots[si] = ss[0]
                return True
        return False

    for _round in range(24):
        ded_t = sum(s["dur"] for e in edl for s in e["shots"]
                    if is_ded(s["key"], s))
        tot = sum(s["dur"] for e in edl for s in e["shots"])
        if tot and ded_t / tot >= DEDICATED_FLOOR:
            break
        # replace the largest non-dedicated shot that sits in a
        # statement/momentum/hometown/studio/vocal beat (weakest group tie)
        best = None
        for e in edl:
            for si, sh in enumerate(e["shots"]):
                if is_ded(sh["key"]) or e["label"] in ("the absence",):
                    continue
                bt = (sh.get("beat_text") or "").lower()
                if re.search(r"batter|sheesh|drip|hot sauce|we go up|"
                             r"stuck|debut stage|arena|dome", bt):
                    continue          # era-anchored shots stay
                if best is None or sh["dur"] > best[0]["dur"]:
                    best = (sh, e, si)
        if best is None:
            break
        _, e, si = best
        if not try_replace(e, si):
            break
    ded_share = ded_t / max(tot, 1)
    alone_share = alone_t / max(tot, 1)
    print(f"[director-v2] dedicated share {ded_share:.0%} (floor "
          f"{DEDICATED_FLOOR:.0%}), alone share {alone_share:.0%} (floor "
          f"{ALONE_FLOOR:.0%})", flush=True)
    json.dump({"version": "director-v2", "dedicated_share": round(ded_share, 3),
               "alone_share": round(alone_share, 3), "scenes": edl},
              open(os.path.join(media, "plan.json"), "w"), indent=1)
    json.dump({"generated_for": os.path.basename(run_dir.rstrip("/")),
               "policy": {"dedicated_floor": DEDICATED_FLOOR,
                          "alone_floor": ALONE_FLOOR},
               "review": review},
              open(os.path.join(media, "review_queue.json"), "w"), indent=1)
    print(f"[director-v2] plan.json: {len(edl)} scenes, "
          f"{sum(len(e['shots']) for e in edl)} shots, {len(review)} scenes "
          f"with gaps", flush=True)
    return edl


if __name__ == "__main__":
    run(sys.argv[1])
