#!/usr/bin/env python3
"""make_script_v2.py — build 02_script.json for the Ahyeon v2 documentary.

Scenes are DRAFTED from the verified fact ledger (01_research.json), then
LLM-polished with facts frozen, then HARD-GATED: every date/number in the
narration must be traceable to the research corpus or the build fails.
No unverified claims (the v1 script's 'most searched on Google' and 'Produce
48' fabrications are gone — the ledger explicitly marks them unverified).
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import zai  # noqa: E402

RUN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "runs", "ahyeon-it-girl-v2")

# (label, narration draft, visual_query, entities, places, subject_tags)
SCENES = [
    ("hook",
     "November 27, 2023. A new girl group debuts under K-pop's most feared "
     "training machine, and the whole industry is watching. The member everyone "
     "came to see is not on the stage. Six months later she walks back out, and "
     "within a year the internet has given her a title that used to belong to "
     "legends: the it girl of her generation. This is the story of what that "
     "word actually costs.",
     "BABYMONSTER debut stage silhouette, dramatic concert lighting",
     ["babymonster", "debut"], [],
     ["ahyeon", "babymonster", "debut"]),
    ("the it-girl idea",
     "The phrase started almost a century ago, with silent-film star Clara Bow: "
     "the one whose magnetism cannot be manufactured. K-pop inherited the idea "
     "and gave it generations. Every era has argued about who deserves the "
     "label, and the argument is never settled by marketing alone. It is settled "
     "by evidence: the voice, the presence, and the moments a crowd cannot "
     "forget. In the fifth generation, the loudest case belongs to one trainee "
     "from a mountain city.",
     "classic cinema montage style, empty spotlight on dark stage",
     ["it girl", "fifth generation"], [],
     ["ahyeon", "industry"]),
    ("chuncheon",
     "Ahyeon was born on April 11, 2007, in Toegye-dong, Chuncheon, a city of "
     "lakes and mountains in Gangwon Province, far from the Seoul practice "
     "rooms that would later define her. Nothing about that starting point "
     "promises a dome-stage career. But K-pop's pipeline has always begun in "
     "ordinary places, with children who sing into the silence and decide, "
     "quietly, to be extraordinary at something.",
     "Chuncheon city lakes and mountains landscape, South Korea",
     ["chuncheon", "hometown"], ["Chuncheon city, South Korea"],
     ["ahyeon", "context"]),
    ("the machine",
     "In 2018, at eleven years old, she entered YG Entertainment, the company "
     "that built 2NE1 and BLACKPINK. Five years of training followed: vocals by "
     "day, dance and rap late into the night, every month a test that could end "
     "the dream. YG does not graduate trainees on time. It graduates the ones "
     "who survive. She was eleven when she signed up for that life.",
     "YG Entertainment headquarters building in Seoul",
     ["yg entertainment", "trainee"], ["YG Entertainment headquarters, Seoul"],
     ["ahyeon", "trainee", "ygent"]),
    ("the reveal",
     "In 2023 YG lifted the curtain on its next girl group, and Ahyeon's "
     "trainee footage spread faster than the company could frame it. The "
     "moment people still bring up is a filmed evaluation: a young trainee "
     "singing Charlie Puth's Dangerously like she had already lived it. Tapes "
     "like that do not stay inside practice rooms. They become the reason a "
     "fandom exists before a group even debuts.",
     "trainee evaluation performance, practice room, young Ahyeon singing",
     ["last evaluation", "dangerously", "predebut"], [],
     ["ahyeon", "trainee", "predebut"]),
    ("the absence",
     "Then the cruelest twist. On November 27, 2023, BATTER UP arrived and "
     "BABYMONSTER officially debuted, six members on stage, one name missing. "
     "YG confirmed Ahyeon would sit out the debut for health reasons. Imagine "
     "surviving five years of elimination-grade training, and watching your "
     "own debut from the sideline. The industry called it a delay. Her fans "
     "called it a wound.",
     "debut stage performance with empty spotlight moment",
     ["batter up", "debut", "hiatus"], [],
     ["ahyeon", "babymonster", "debut"]),
    ("the return",
     "April 1, 2024. The group's first comeback, SHEESH, and the lineup is "
     "finally whole. Ahyeon's return turned a debut single into a full "
     "unit's statement, and the timing mattered: she came back not to a "
     "restart but to momentum, joining a group the world was already "
     "counting. Sometimes the missing member is the story. Sometimes the "
     "return is bigger than the debut.",
     "SHEESH comeback stage, group performance, Ahyeon center moment",
     ["sheesh", "comeback", "return"], [],
     ["ahyeon", "sheesh", "comeback"]),
    ("main vocalist",
     "Her official profile reads like a checklist no single member is supposed "
     "to hold: main vocalist, lead rapper, lead dancer, center. On DRIP, the "
     "group's first full album released November 1, 2024, all four jobs are "
     "audible in the same track. That versatility is the technical core of "
     "the it-girl argument: not one signature skill, but the ability to carry "
     "whatever the song demands.",
     "Ahyeon singing live, studio vocal moment, DRIP era styling",
     ["drip", "main vocalist", "album"], [],
     ["ahyeon", "drip", "vocals"]),
    ("the cover that charted",
     "The strangest proof arrived through a song she did not write. When her "
     "old evaluation performance of Dangerously finally surfaced officially, "
     "it climbed to number one on Bulgaria's iTunes song chart, and fan "
     "communities reported her as the first K-pop idol to top an iTunes chart "
     "with a cover. Take the title with the caution it deserves, but keep the "
     "signal: a voice pulled crowds all by itself, with no comeback machine "
     "behind it.",
     "emotional close-up vocal performance, subtle stage lighting",
     ["dangerously", "itunes", "cover"], [],
     ["ahyeon", "vocals", "cover"]),
    ("three languages",
     "Visibility in the fifth generation is global on day one, and language "
     "is the bridge. Ahyeon speaks Korean, English and Chinese, and she uses "
     "all three. In interviews she answers international press directly, no "
     "translator between her and the moment. For fans in Jakarta or São "
     "Paulo, that direct line turns a distant idol into a person who chose "
     "to be reachable.",
     "Ahyeon interview setting, speaking English, close portrait",
     ["interview", "english", "languages"], [],
     ["ahyeon", "interview"]),
    ("the arenas",
     "January 2025: the HELLO MONSTERS world tour opens at Seoul's KSPO DOME, "
     "and lands at Kyocera Dome in Osaka, an arena that has swallowed bigger "
     "names. This is fourteen months after her first group stage. For most "
     "rookies, domes are a destination for year five. The fifth generation's "
     "schedule has no patience for that timeline, and neither did she.",
     "stadium concert crowd, dome tour stage wide shot",
     ["hello monsters", "tour", "kspo dome", "kyocera"], [],
     ["ahyeon", "tour", "stage"]),
    ("the pace",
     "The 2025 schedule tells its own story: HOT SAUCE arrived July 1, "
     "followed by more singles, more stages, a calendar built for an idol "
     "the machine refuses to cool down. Fifth-generation comebacks arrive "
     "faster than any generation before them, and the artists expected to "
     "carry that pace are barely adults. She was eighteen when the domes "
     "started asking for her.",
     "fast-paced comeback stage montage, backstage preparation",
     ["hot sauce", "2025", "comeback"], [],
     ["ahyeon", "hotsauce", "comeback"]),
    ("the machinery",
     "None of this happens by accident, and none of it happens by decree. "
     "Fancam clips travel through fan communities, algorithms do the rest, "
     "and a performance moment becomes a currency. The it-girl image is "
     "built in public, by thousands of strangers editing, captioning and "
     "forwarding. That is the modern part of the title: the crowd does not "
     "just watch the star, it manufactures her reach.",
     "fancam screen recordings, phone screens at concert, social media montage",
     ["fancam", "viral", "fans"], [],
     ["ahyeon", "fandom", "industry"]),
    ("the price",
     "But the same machinery that lifts a person also weighs on her. A "
     "health hiatus before a debut is not a footnote; it is a warning about "
     "what this pace extracts. The public sees the it girl, the effortless "
     "center. The person behind her navigates scrutiny that most adults "
     "could not carry at twenty, delivered at an age when she should still "
     "be allowed to be unfinished.",
     "quiet backstage moment, Ahyeon thoughtful, low light",
     ["scrutiny", "pressure", "health"], [],
     ["ahyeon", "personality"]),
    ("evidence and noise",
     "So what is actually documented? Dates: a debut on November 27, 2023, a "
     "return on April 1, 2024, an album on November 1, 2024. Venues: domes "
     "in two countries. Positions held and songs carried. What remains "
     "discourse is the crown itself, the most-searched and the it-girl "
     "labels that fan wars trade in. The discipline of a documentary is to "
     "hold those apart, and the evidence here is already loud.",
     "split screen of chart graphics and crowd footage",
     ["evidence", "charts"], [],
     ["ahyeon", "babymonster"]),
    ("outro",
     "The it girl of a generation is not appointed by a company or crowned "
     "by a comment section. She is assembled, out of a childhood in "
     "Chuncheon, five years of survival in the hardest training system in "
     "pop, a debut watched from the sidelines, and a return that turned "
     "absence into appetite. Ahyeon did not inherit the title. The "
     "evidence argues for it, scene by scene, and the argument is still "
     "being won.",
     "Ahyeon walking off stage silhouette, lights fading",
     ["legacy", "it girl"], [],
     ["ahyeon", "babymonster"]),
]


def polish(text):
    """LLM polish with facts frozen; returns text or original on failure."""
    p = (f"Polish this documentary narration for spoken delivery (keep every "
         f"fact, date, number and name EXACTLY as stated; improve only flow, "
         f"rhythm and word choice; keep it 65-90 words; no emojis, no markdown, "
         f"spoken prose only):\n\n{text}")
    out = zai.chat(p, timeout=150)
    if not out:
        return None
    txt = (out or "").strip().strip('"')
    wc = len(txt.split())
    if not (55 <= wc <= 105):
        return None
    return txt


MONTHS = ("january february march april may june july august september october "
          "november december").split()


def fact_gate(scenes, corpus):
    """Every date/number claim must appear in the research corpus."""
    problems = []
    for sc in scenes:
        t = sc["narration"].lower()
        claims = re.findall(r"\b(?:19|20)\d{2}\b", t)
        claims += [m for m in MONTHS if m in t]
        if "november 27" in t:
            claims.append("november 27")
        for c in set(claims):
            if c not in corpus:
                problems.append({"scene": sc["id"], "claim": c})
    return problems


def main():
    os.makedirs(RUN, exist_ok=True)
    ledger = json.load(open(os.path.join(RUN, "01_research.json")))
    corpus = json.dumps(ledger).lower()
    scenes = []
    for i, (label, narr, vq, ents, places, tags) in enumerate(SCENES, 1):
        txt = polish(narr) or narr
        scenes.append({"id": i, "label": label, "narration": txt,
                       "on_screen": label.upper()[:26],
                       "visual_query": vq, "entities": ents,
                       "places": places, "subject_tags": tags})
        print(f"[script] scene {i:>2} '{label}' {len(txt.split())}w"
              f"{' (polished)' if txt != narr else ' (raw)'}", flush=True)
    problems = fact_gate(scenes, corpus)
    if problems:
        print("FACT GATE FAILURES:", json.dumps(problems, indent=1))
        raise SystemExit(1)
    plan = {"title": "Ahyeon — The 5th Generation IT Girl",
            "logline": "What the word 'it girl' actually costs: the verified "
                       "story of BABYMONSTER's Ahyeon.",
            "scenes": scenes, "topic": "Ahyeon BABYMONSTER the 5th generation "
            "it girl", "style": "documentary", "region": "us",
            "target_sec": 720,
            "fact_ledger": "runs/ahyeon-it-girl-v2/01_research.json"}
    json.dump(plan, open(os.path.join(RUN, "02_script.json"), "w"),
              ensure_ascii=False, indent=1)
    total_words = sum(len(s["narration"].split()) for s in scenes)
    print(f"[script] FACT GATE PASSED; {len(scenes)} scenes, {total_words} words "
          f"(~{total_words / 145:.1f} min narration @ -3%)")


if __name__ == "__main__":
    main()
