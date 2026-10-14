#!/usr/bin/env python3
"""Stage 2: research -> scene plan JSON (title + narration scenes + visual queries).
FACT discipline: the LLM must only use supplied sources; unknowns get hedged."""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import zai  # noqa: E402

SYSTEM = (
    "You are a documentary scriptwriter for YouTube films. "
    "STRICT FACT RULES: use ONLY facts present in the SOURCES block. "
    "Never invent numbers, dates, quotes or statistics. If sources are thin, "
    "write in safe general terms. Narration is spoken text: clean sentences, "
    "no emojis, no markdown, no stage directions."
)

TEMPLATE = {
    "title": "short punchy video title",
    "logline": "one sentence what this video is",
    "scenes": [
        {"id": 1, "label": "hook", "narration": "2 spoken sentences max",
         "on_screen": "3-5 word caption", "visual_query": "concrete imageable scene"},
    ],
}


def expand_thin_scenes(plan):
    """Per-scene expansion (facts locked). Terse models routinely return
    ~28-word scenes despite explicit floors; one focused call per scene
    reliably lands 45-70 words. Scenes already >=45 words are kept."""
    for sc in plan["scenes"]:
        if len(sc["narration"].split()) >= 45:
            continue
        p = f"""Expand this documentary scene's narration to 45-70 spoken words (at least 3 sentences).
IRON RULES: keep every existing fact EXACTLY as stated (dates, numbers, names, claims). Do NOT add any new facts, numbers, dates or names. Spoken style, smooth storytelling, no emojis, no markdown.
Current narration: {sc['narration']}
Return ONLY the expanded narration text, nothing else."""
        out = zai.chat(p, system=SYSTEM, timeout=150)
        txt = (out or "").strip().strip('"')
        wc = len(txt.split())
        if 40 <= wc <= 95:
            sc["narration"] = txt
    return plan


def run(run_dir, topic, style="documentary", n_scenes=7, region="us"):
    out_path = os.path.join(run_dir, "02_script.json")
    research = json.load(open(os.path.join(run_dir, "01_research.json")))
    brief = research["brief"]

    shape = json.dumps(TEMPLATE, ensure_ascii=False)
    prompt = f"""TOPIC: {topic}
STYLE: {style}
SCENES: exactly {n_scenes} — id 1 is a HOOK (a cinematic cold-open: a question or bold image-driven statement, 2 sentences), ids 2..{n_scenes-1} are the body — build a NARRATIVE ARC, not a fact list: open with the person's world before fame, then the struggle/training years, the turning point, the rise, the proof (numbers, records, firsts), the scrutiny/pressure, and what she means to her generation. id {n_scenes} is an OUTRO (takeaway + forward-looking line).
Each scene: "narration" = 45-75 spoken words, AT LEAST 3 full sentences, written as CONNECTED STORYTELLING — vary sentence length, use concrete images and dates from sources, never open two scenes with the same word (ban openings like repeated "Ahyeon is/She is"), end body scenes on lines that pull the viewer forward. "on_screen" = 3-6 word caption. "visual_query" = a concrete visual search query in English (a place, person-performing, object, crowd, stage, screen — NOT abstract text).
Return ONLY valid JSON matching this shape exactly, no commentary:
{shape}

SOURCES (use only these facts):
{brief[:9000]}"""

    plan = zai.chat_json(prompt, system=SYSTEM, timeout=420)
    if not plan or "scenes" not in plan or not isinstance(plan["scenes"], list) or len(plan["scenes"]) < 3:
        raise RuntimeError("script model did not return a valid scene plan")
    for i, sc in enumerate(plan["scenes"], 1):
        sc["id"] = i
        for k in ("label", "narration", "on_screen", "visual_query"):
            sc.setdefault(k, "")
        sc["narration"] = sc["narration"].strip() or topic
        sc["visual_query"] = sc["visual_query"].strip() or topic
    # thin-scene expansion: terse models ignore word floors; expand per scene
    avg = sum(len(sc["narration"].split()) for sc in plan["scenes"]) / len(plan["scenes"])
    if avg < 38:
        plan = expand_thin_scenes(plan)
    plan["topic"] = topic
    plan["style"] = style
    plan["region"] = region
    json.dump(plan, open(out_path, "w"), ensure_ascii=False, indent=1)
    return plan


if __name__ == "__main__":
    d = json.load(open(sys.argv[1]))  # 00_topic.json
    run(os.path.dirname(sys.argv[1]), d["topic"], d.get("style", "documentary"),
        d.get("n_scenes", 7), d.get("region", "us"))
    print("script done:", d["topic"])
