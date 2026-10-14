#!/usr/bin/env python3
"""research_v2.py — verified fact ledger for the Ahyeon documentary (R15 §6).

Fixed query set (deterministic), web-search via zai, then per-fact verdicts
(confirmed / plausible / unverified) with source URLs. The script stage may
use ONLY confirmed facts — s2 cross-checks every number/date against this
ledger and fails the build on an unsupported claim.
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import zai  # noqa: E402

RUN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "runs", "ahyeon-it-girl-v3")

QUERIES = [
    "Ahyeon BABYMONSTER born April 11 2007 Chuncheon",
    "Ahyeon BABYMONSTER YG trainee how many years before debut",
    "BABYMONSTER members reveal YG NEXT MOVEMENT January 2023",
    "Ahyeon Last Evaluation Dangerously Charlie Puth cover BABYMONSTER",
    "BABYMONSTER BATTER UP debut November 2023 Ahyeon hiatus health",
    "Ahyeon returned BABYMONSTER SHEESH April 2024 comeback",
    "BABYMONSTER DRIP first full album November 2024 Ahyeon",
    "Ahyeon Dangerously cover iTunes chart record K-pop",
    "BABYMONSTER MAMA Awards 2025 stage GOLDEN",
    "BABYMONSTER HELLO MONSTERS tour 2025 KSPO DOME Kyocera Dome",
    "BABYMONSTER HOT SAUCE 2025 comeback Ahyeon",
    "Ahyeon BABYMONSTER main vocalist position languages English",
    "5th generation K-pop it girl meaning trend fourth generation",
    "Ahyeon most searched fifth generation idol Google trends",
    "BABYMONSTER debut showcase press 2023 Ahyeon center",
]

FACT_QUESTIONS = [
    ("birth", "When and where was Ahyeon of BABYMONSTER born? Exact date and city."),
    ("training", "How long was Ahyeon a YG trainee before BABYMONSTER's debut, and when did she join?"),
    ("reveal", "When were BABYMONSTER members first revealed, and when was Ahyeon's reveal video?"),
    ("evaluation", "What did Ahyeon perform on BABYMONSTER's Last Evaluation, and when did it air?"),
    ("debut_and_absence", "When did BABYMONSTER debut with BATTER UP, and was Ahyeon present? What happened?"),
    ("return", "When did Ahyeon return to BABYMONSTER, and with which release?"),
    ("drip", "When did BABYMONSTER release DRIP and what is it (album type)? What role did Ahyeon have?"),
    ("itunes_cover", "Did Ahyeon's 'Dangerously' cover chart on iTunes? What record is claimed?"),
    ("mama", "Did BABYMONSTER perform at MAMA 2025? What did they perform or win?"),
    ("tour", "What 2025-2026 tours did BABYMONSTER do (venues: KSPO DOME, Kyocera Dome)?"),
    ("hotsauce", "What is BABYMONSTER's 2025 output (HOT SAUSE, SUGAR HONEY ICE TEA, CHOOM)?"),
    ("positions", "What are Ahyeon's official positions in BABYMONSTER? Which languages does she speak?"),
    ("itgirl_5thgen", "What does 'fifth generation it girl' mean in K-pop discourse, and is Ahyeon called that by media?"),
    ("search_claims", "Is there a reliable source that Ahyeon was the most-searched fifth-generation female idol on Google?"),
    ("showcase", "When was BABYMONSTER's debut showcase and what happened?"),
]


def search_all():
    out = []
    for q in QUERIES:
        res = zai.search(q, num=6) or []
        out.append({"query": q, "results": [
            {"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": (r.get("snippet") or r.get("content") or "")[:400]}
            for r in res if isinstance(r, dict)]})
        print(f"[research] {q}: {len(out[-1]['results'])} results", flush=True)
    return out


def build_ledger(raw):
    corpus = "\n\n".join(
        f"### QUERY: {b['query']}\n" + "\n".join(
            f"- {r['title']} ({r['url']}): {r['snippet']}"
            for r in b["results"]) for b in raw)
    ledger = []
    for key, q in FACT_QUESTIONS:
        p = (f"FACT QUESTION: {q}\n\nUsing ONLY the search corpus below, answer "
             f"in 2-4 sentences. Cite source URLs from the corpus for every "
             f"concrete claim. If the corpus does not settle it, say "
             f"UNVERIFIED explicitly. No invention.\n\nCORPUS:\n{corpus[:22000]}")
        a = zai.chat(p, timeout=180) or ""
        verdict = "unverified"
        if "UNVERIFIED" not in a.upper()[:80] and len(a) > 60:
            verdict = "confirmed" if re.search(r"https?://", a) else "plausible"
        ledger.append({"key": key, "question": q, "answer": a.strip(),
                       "verdict": verdict,
                       "sources": re.findall(r"https?://\S+", a)[:4]})
        print(f"[ledger] {key}: {verdict}", flush=True)
    return ledger


def main():
    os.makedirs(RUN, exist_ok=True)
    raw_p = os.path.join(RUN, "01_research_raw.json")
    if os.path.isfile(raw_p):
        raw = json.load(open(raw_p))
        print("[research] raw cache hit")
    else:
        raw = search_all()
        json.dump(raw, open(raw_p, "w"), indent=1)
    ledger = build_ledger(raw)
    confirmed = sum(1 for f in ledger if f["verdict"] == "confirmed")
    out = {"topic": "Ahyeon BABYMONSTER the 5th generation it girl",
           "queries": raw, "ledger": ledger,
           "confirmed": confirmed, "total": len(ledger)}
    json.dump(out, open(os.path.join(RUN, "01_research.json"), "w"), indent=1)
    print(f"[research] ledger: {confirmed}/{len(ledger)} confirmed facts")


if __name__ == "__main__":
    main()
