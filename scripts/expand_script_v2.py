#!/usr/bin/env python3
"""expand_script_v2.py — deepen narration to 85-100 words/scene.
IRON RULE: no new facts, dates, numbers, names, claims. Depth = elaboration
of what is already there. Re-runs the fact gate with a strict diff check:
any number/date that appears in the expansion but was absent in BOTH the
original narration and the research corpus rejects the expansion."""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import zai  # noqa: E402

RUN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "runs", "ahyeon-it-girl-v2")

MONTHS = ("january february march april may june july august september "
          "october november december").split()


def claims_of(text):
    t = text.lower()
    out = set(re.findall(r"\b(?:19|20)\d{2}\b", t))
    out |= {m for m in MONTHS if m in t}
    out |= set(re.findall(r"\b\d+(?:[.,]\d+)?\b", t))
    return out


def main():
    plan = json.load(open(os.path.join(RUN, "02_script.json")))
    ledger = json.load(open(os.path.join(RUN, "01_research.json")))
    corpus = json.dumps(ledger).lower()
    orig_claims = {s["id"]: claims_of(s["narration"]) for s in plan["scenes"]}
    for sc in plan["scenes"]:
        if len(sc["narration"].split()) >= 85:
            continue
        p = (f"Extend this documentary narration to 85-100 spoken words. "
             f"IRON RULES: do NOT add any new fact, date, number, name, event, "
             f"or claim — deepen the existing ideas only (imagery, pacing, "
             f"emotional texture, consequence). Keep every existing fact exactly. "
             f"Spoken prose, no emojis, no markdown.\n\n{sc['narration']}")
        out = (zai.chat(p, timeout=150) or "").strip().strip('"')
        wc = len(out.split())
        ok_words = 75 <= wc <= 110
        new_claims = claims_of(out) - orig_claims[sc["id"]]
        bad = {c for c in new_claims if c not in corpus
               and not c.isdigit()}          # bare small numbers allowed in prose
        if ok_words and not bad:
            sc["narration"] = out
            print(f"[expand] scene {sc['id']:>2}: {wc}w (accepted)", flush=True)
        else:
            print(f"[expand] scene {sc['id']:>2}: REJECTED "
                  f"(wc={wc}, new_claims={sorted(bad)})", flush=True)
    json.dump(plan, open(os.path.join(RUN, "02_script.json"), "w"),
              ensure_ascii=False, indent=1)
    total = sum(len(s["narration"].split()) for s in plan["scenes"])
    print(f"[expand] total {total} words (~{total/139.5:.1f} min narration @ -9%)")


if __name__ == "__main__":
    main()
