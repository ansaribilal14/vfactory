#!/usr/bin/env python3
"""lib/imgagent.py — PERMANENT contextual-image specialist (Bilal140202/imgagent
methodology, R15 amendment to the zero-slideshow rule).

Scope (narrow, by design):
  - ONLY for place/entity context the narration demands (e.g. "YG
    Entertainment headquarters", "Chuncheon") — NEVER for the documentary
    subject (the subject is covered by real footage, R3).
  - Every image: web-search candidates -> downloaded -> VISION-VERIFIED to
    actually depict the requested place/entity -> provenance recorded.
  - A failed/unverified search is an HONEST GAP (no random substitutions).

Usage:
    from lib import imgagent
    rec = imgagent.fetch_place("YG Entertainment headquarters building",
                               out_dir, key="yg_building")
    # rec = {path, source_url, source_host, caption, sha256, verified, why}
      or None (gap).
"""
import hashlib, json, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import vision, zai  # noqa: E402

VERSION = "imgagent-v1"


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def verify_frame(path, query):
    """Vision gate: does this image actually depict the requested place/entity?"""
    rep = vision.ask_json(
        f"Does this image clearly show: \"{query}\"? Reply ONLY JSON: "
        f"{{\"match\": true/false, \"score\": 0.0-1.0, \"why\": \"<10 words>\"}}",
        [path], timeout=180)
    if not isinstance(rep, dict):
        return False, 0.0, "vision unavailable"
    try:
        return (bool(rep.get("match")), float(rep.get("score", 0)),
                str(rep.get("why", ""))[:80])
    except (TypeError, ValueError):
        return False, 0.0, "bad verdict"


def fetch_place(query, out_dir, key, min_score=0.55, candidates=8):
    """Search + download + vision-verify one place/entity image.
    Returns record or None (honest gap)."""
    os.makedirs(out_dir, exist_ok=True)
    manifest_p = os.path.join(out_dir, "images_manifest.json")
    manifest = {}
    if os.path.isfile(manifest_p):
        try:
            manifest = json.load(open(manifest_p))
        except Exception:
            manifest = {}
    if key in manifest and manifest[key].get("verified"):
        rec = manifest[key]
        if os.path.isfile(rec.get("path", "")):
            return rec
    results = zai.image_search(query, count=candidates) or []
    tried = []
    for r in results:
        url = (r.get("original_url") or r.get("url") or "")
        if not url.startswith("http"):
            continue
        ext = ".jpg"
        p = os.path.join(out_dir, f"{key}{ext}")
        if not zai.download(url, p, min_bytes=8000):
            continue
        # reject tiny/likely-thumbnail images
        try:
            from PIL import Image
            with Image.open(p) as im:
                if im.size[0] < 640:
                    os.remove(p)
                    continue
        except Exception:
            pass
        match, score, why = verify_frame(p, query)
        tried.append({"url": url, "score": score, "why": why})
        if match and score >= min_score:
            rec = {"key": key, "query": query, "path": p,
                   "source_url": url,
                   "source_host": url.split("/")[2] if "/" in url else url,
                   "caption": (r.get("caption") or "")[:120],
                   "sha256": _sha256(p), "verified": True,
                   "vision_score": score, "why": why,
                   "retrieved_at": time.strftime("%Y-%m-%d"),
                   "agent": VERSION, "attempts": tried}
            manifest[key] = rec
            json.dump(manifest, open(manifest_p, "w"), indent=1)
            print(f"[imgagent] {key}: VERIFIED {url} ({score:.2f}) — {why}",
                  flush=True)
            return rec
        if os.path.exists(p):
            os.remove(p)
    manifest[key] = {"key": key, "query": query, "verified": False,
                     "state": "gap", "attempts": tried,
                     "agent": VERSION,
                     "retrieved_at": time.strftime("%Y-%m-%d")}
    json.dump(manifest, open(manifest_p, "w"), indent=1)
    print(f"[imgagent] {key}: HONEST GAP after {len(tried)} candidates",
          flush=True)
    return None
