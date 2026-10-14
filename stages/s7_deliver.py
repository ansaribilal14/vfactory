#!/usr/bin/env python3
"""Stage 7: delivery.

Rule 9 (mandatory): the main film is ALWAYS published as a GitHub Release
(1080p master + 720p + trailer when present) on ansaribilal14/vfactory and
the release link is pushed to Telegram. Telegram copies and storage.to
mirrors are courtesy extras — release.ok gates the `delivered` flag.
"""
import json, os, re, subprocess, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import storageto, telegram, ghrelease  # noqa: E402


def _slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60] or "film"


def publish_release(run_dir, title, topic, chat_id):
    """Rule 9: tag film-<slug>, upload every version, TG the release link.
    R13 lifecycle: assets are TEMPORARY distribution — deleted after the user
    has downloaded them. Asset names reflect the REAL render resolution."""
    slug = topic.get("slug") or _slug(title)
    tag = f"film-{slug}"
    # honest resolution label from the actual file
    h = 0
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=height", "-of", "csv=p=0",
                            os.path.join(run_dir, "final.mp4")],
                           capture_output=True, text=True)
        h = int(r.stdout.strip() or 0)
    except Exception:
        pass
    main_name = f"{slug}_full_{h}p.mp4" if h else f"{slug}_full.mp4"
    named = [(os.path.join(run_dir, "final.mp4"), main_name)]
    for src, dst in (("final_720p.mp4", f"{slug}_full_720p.mp4"),
                     ("trailer.mp4", f"{slug}_trailer.mp4")):
        p = os.path.join(run_dir, src)
        if os.path.isfile(p) and src != "final_720p.mp4":
            named.append((p, dst))
    info = {"tag": tag, "repo": ghrelease._repo(), "assets": {}}
    try:
        html_url, urls, ok_all = ghrelease.publish(
            tag, title, named,
            body=f"{title}\n\nDelivered by vfactory (autonomous documentary pipeline).\n"
                 f"Master: {h or '?'}p real-footage render, multi-cut editing, "
                 f"narration + score (loudnorm -14).\n"
                 f"v3: full directorial rebuild per user review — every cut "
                 f"vision-verified against an AHYEON reference frame (dense "
                 f"presence map + per-cut head/mid/tail checks + human review); "
                 f"dedicated vocal-performance spine; era-true absence footage.\n"
                 f"Asset lifecycle: files are removed from this release after "
                 f"the requester has downloaded them (temporary distribution).")
        info.update({"ok": bool(ok_all), "html_url": html_url, "urls": urls})
        link_msg = (f"🎬 <b>{title}</b> — official release\n"
                    f"⬇️ {html_url}\n"
                    + "\n".join(f"• <a href=\"{u}\">{n}</a>"
                                for n, u in urls.items() if u))
        try:
            sent = telegram.send_message(link_msg, chat_id=chat_id)
            info["tg_message_id"] = sent.get("result", {}).get("message_id")
            info["tg_ok"] = True
        except Exception as te:
            info["tg_ok"] = False
            info["tg_error"] = str(te)[:200]
    except Exception as e:
        info.update({"ok": False, "error": str(e)[:300]})
    return info


def run(run_dir, deliver=True, chat_id=None):
    final = os.path.join(run_dir, "final.mp4")
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    tl = json.load(open(os.path.join(run_dir, "06_timeline.json")))
    size = os.path.getsize(final)
    mb = size / 1024 / 1024
    title = plan.get("title", topic["topic"])
    slug = topic.get("slug") or _slug(title)   # single project identity (R14)
    caption = (f"<b>{title}</b>\n{topic['topic']}\n"
               f"{tl['total']:.0f}s • {tl.get('scenes') or len(plan['scenes'])} scenes • {mb:.1f} MB\n"
               f"built by vfactory")
    chat_id = chat_id or topic.get("chat_id") or telegram.DEFAULT_CHAT
    result = {"file": final, "size_mb": round(mb, 1), "chat_id": chat_id}

    if not deliver:
        result["delivered"] = False
        json.dump(result, open(os.path.join(run_dir, "delivery.json"), "w"), indent=1)
        return result

    # 1) Rule 9 — GitHub release ALWAYS for the main film
    result["release"] = publish_release(run_dir, title, topic, chat_id)
    result["release"]["slug"] = slug

    # 1b) R14 — persist final deliverable immediately (storage.to + manifest)
    try:
        from lib import persist
        rel = result.get("release") or {}
        slug = topic.get("slug") or _slug(title)
        if rel.get("ok"):
            url_main = next((u for u in (rel.get("urls") or {}).values() if u), None)
            m = persist.load_manifest(slug)
            m["assets"] = [a for a in m["assets"]
                           if not a["asset_id"].startswith("film-")]
            m["assets"].append({
                "asset_id": f"film-{slug}-v1-720p", "asset_type": "video_final",
                "filename": f"{slug}_full_720p.mp4", "provider": "github-release",
                "remote_id": rel.get("tag"), "remote_url": url_main,
                "size_bytes": size, "sha256": None,
                "verification_status": "uploaded_unverified",
                "availability_status": "available",
                "retention_policy": "release asset (deleted after user download)",
                "expiration_at": None, "generation_stage": "s6_render",
                "version": "v1", "dependencies": ["narration-wavs", "mv-pool"],
                "retry_status": "sha pending (computable from local final.mp4)",
                "notes": "v1: opuscar composed score, clip-proof master chain"})
            m["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            persist.save_manifest(m["project_id"], m)
            persist.git_commit_push(
                [os.path.relpath(persist._manifest_path(m["project_id"]),
                                 persist.BASE)],
                f"persist: {m['project_id']}/film-{slug}-v1-720p (release)")
        up = persist.persist_asset(final, slug,
                                   "video_final", "s6_render", version="v1",
                                   asset_id=f"{slug}-v1-storage-mirror",
                                   notes="storage.to mirror of v1 final")
        result["persist"] = {"ok": up.get("ok"), "state": up.get("state"),
                             "url": (up.get("record") or {}).get("remote_url")}
    except Exception as pe:
        result["persist_error"] = str(pe)[:200]

    # 2) courtesy copy: <=48 MB direct sendVideo; bigger -> storage.to mirror
    try:
        if size <= telegram.TG_DIRECT_LIMIT:
            ok, resp = telegram.send_video(final, caption=caption, chat_id=chat_id)
            result.update({"method": "telegram_direct", "ok": ok,
                           "message_id": resp.get("result", {}).get("message_id")})
            if not ok:
                result["error"] = resp.get("description", "sendVideo failed")
        else:
            mirror = (result.get("persist") or {}).get("url")
            if mirror:                    # R14: reuse persisted mirror — no 2nd upload
                up = {"url": mirror, "id": None, "expires_at": None}
            else:
                up = storageto.upload(final)
            result.update({"method": "storageto", "ok": True,
                           **{k: up.get(k) for k in ("url", "id", "expires_at")}})
            msg = (f"<b>{title}</b> — {tl['total']:.0f}s, {mb:.1f} MB\n"
                   f"⬇️ <a href=\"{up['url']}\">{up['url']}</a>\n"
                   f"(storage.to mirror • valid until {up.get('expires_at') or 'expiry'})")
            try:
                sent = telegram.send_message(msg, chat_id=chat_id)
                result["message_id"] = sent.get("result", {}).get("message_id")
            except Exception as te:
                result["tg_error"] = str(te)[:200]
    except Exception as e:
        result["mirror_error"] = str(e)[:200]

    # 3) release.ok gates delivery
    result["delivered"] = bool(result.get("release", {}).get("ok"))
    json.dump(result, open(os.path.join(run_dir, "delivery.json"), "w"),
              ensure_ascii=False, indent=1)
    return result


if __name__ == "__main__":
    print(json.dumps(run(os.path.dirname(sys.argv[1])), indent=2))
