#!/usr/bin/env python3
"""vfactory — topic -> full video -> Telegram/storage.to delivery.
One command:
  python3 vfactory.py "TOPIC TEXT" [--style documentary] [--scenes 7]
      [--aspect 16:9|9:16] [--region us|kr|jp|cn] [--ai-broll]
      [--tts-speed 1.0] [--no-deliver] [--run-dir DIR] [--rebuild]
Each stage checkpoints into runs/<slug>/ so failed runs resume.
"""
import argparse, json, os, re, sys, time, traceback

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from stages import s1_research, s2_script, s3_voice, s4_media, s5_music, s6_render, s7_deliver  # noqa: E402


def slugify(text, maxlen=48):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:maxlen].rstrip("-") or "video") + "-" + time.strftime("%m%d-%H%M%S")


def log(run_dir, msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(os.path.join(run_dir, "run.log"), "a") as fh:
        fh.write(line + "\n")


def main():
    ap = argparse.ArgumentParser(description="topic -> full video")
    ap.add_argument("topic")
    ap.add_argument("--style", default="documentary",
                    help="documentary|cinematic|hype|explainer")
    ap.add_argument("--scenes", type=int, default=7)
    ap.add_argument("--aspect", default="16:9", choices=["16:9", "9:16"])
    ap.add_argument("--region", default="us", help="image search region")
    ap.add_argument("--tts-speed", type=float, default=1.0)
    ap.add_argument("--ai-broll", action="store_true",
                    help="generate scene-1 b-roll with AI video (slow)")
    ap.add_argument("--no-deliver", action="store_true")
    ap.add_argument("--chat-id", default=None)
    ap.add_argument("--run-dir", default=None, help="resume existing run")
    ap.add_argument("--rebuild", action="store_true", help="ignore checkpoints")
    args = ap.parse_args()

    run_dir = args.run_dir or os.path.join(BASE, "runs", slugify(args.topic))
    os.makedirs(run_dir, exist_ok=True)
    topic_json = os.path.join(run_dir, "00_topic.json")
    if not os.path.exists(topic_json) or args.rebuild:
        json.dump({"topic": args.topic, "style": args.style, "scenes": args.scenes,
                   "aspect": args.aspect, "region": args.region,
                   "tts_speed": args.tts_speed, "ai_broll": args.ai_broll,
                   "chat_id": args.chat_id, "created": time.strftime("%Y-%m-%d %H:%M:%S")},
                  open(topic_json, "w"), ensure_ascii=False, indent=1)
    topic = json.load(open(topic_json))

    log(run_dir, f"RUN START: {topic['topic']}")
    steps = [
        ("research", lambda: s1_research.run(run_dir, topic["topic"], topic.get("region", "us"))),
        ("script", lambda: s2_script.run(run_dir, topic["topic"], topic.get("style", "documentary"),
                                         topic.get("scenes", 7), topic.get("region", "us"))),
        ("voice", lambda: s3_voice.run(run_dir)),
        ("media", lambda: s4_media.run(run_dir)),
    ]
    for name, fn in steps:
        marker = os.path.join(run_dir, f".done_{name}")
        if os.path.exists(marker) and not args.rebuild:
            log(run_dir, f"skip {name} (checkpoint)")
            continue
        t0 = time.time()
        log(run_dir, f"stage {name} ...")
        fn()
        open(marker, "w").write("1")
        log(run_dir, f"stage {name} done in {time.time()-t0:.0f}s")

    # timeline estimate -> music bed at exact length -> render
    items, _plan = s6_render.build_timeline(run_dir)
    total_est = round(sum(i["dur"] for i in items), 3)
    log(run_dir, f"timeline estimated ({total_est:.0f}s incl. cards)")
    t0 = time.time()
    s5_music.run(run_dir, total_est)
    log(run_dir, f"stage music done in {time.time()-t0:.0f}s")
    t0 = time.time()
    info = s6_render.run(run_dir)
    log(run_dir, f"stage render done in {time.time()-t0:.0f}s "
                 f"({info['total']:.0f}s video)")

    size_mb = os.path.getsize(os.path.join(run_dir, "final.mp4")) / 1048576
    log(run_dir, f"final.mp4 ready: {size_mb:.1f} MB")

    if not args.no_deliver:
        res = s7_deliver.run(run_dir, deliver=True, chat_id=args.chat_id)
        log(run_dir, f"delivery: {res.get('method')} ok={res.get('ok')} "
                     f"url={res.get('url')}")
    log(run_dir, "RUN COMPLETE")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
