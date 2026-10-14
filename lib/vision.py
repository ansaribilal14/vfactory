#!/usr/bin/env python3
"""lib/vision.py — z-ai vision wrapper for frame-level editorial verification.
Deterministic retries, JSON-extraction, no keys in logs."""
import json, os, re, subprocess, time

ZAI = "z-ai"


def _extract_json(text):
    if not text:
        return None
    i = min([x for x in (text.find("["), text.find("{")) if x != -1], default=-1)
    if i == -1:
        return None
    j = max(text.rfind("]"), text.rfind("}"))
    if j <= i:
        return None
    try:
        return json.loads(text[i:j + 1])
    except json.JSONDecodeError:
        return None


def ask(prompt, images, timeout=240, retries=3):
    """Vision query on 1..N local image paths. Returns assistant text or None.
    R15: real backoff — the vision endpoint rate-limits hard (HTTP 429)."""
    delays = (0, 20, 60, 150)          # hard rate limits need long waits
    for attempt in range(retries + 1):
        cmd = ["z-ai", "vision", "-p", prompt]
        for p in images:
            cmd += ["-i", p]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout, start_new_session=True)
            out = (r.stdout or "").strip()
            combined = (out + "\n" + (r.stderr or ""))
            # 429 can surface on either stream, with or without a failing exit
            if "429" in combined or "Too many requests" in combined:
                time.sleep(delays[min(attempt + 1, len(delays) - 1)])
                continue
            if out:
                # unwrap the API envelope: choices[0].message.content
                try:
                    env = json.loads(out[out.find("{"):out.rfind("}") + 1])
                    content = env["choices"][0]["message"]["content"]
                    if content and content.strip():
                        return content.strip()
                except Exception:
                    pass
                lines = [ln for ln in out.splitlines()
                         if not ln.startswith(("🚀", "==", "Z-AI", "Usage:"))]
                txt = "\n".join(lines).strip()
                if txt and not txt.startswith("{"):
                    return txt          # plain-text reply (no envelope)
        except Exception:
            pass
        time.sleep(delays[min(attempt, len(delays) - 1)])
    return None


def ask_json(prompt, images, timeout=240, retries=2):
    """Vision query that must return JSON (object or list)."""
    txt = ask(prompt + "\nReturn ONLY valid JSON, no commentary.", images,
              timeout=timeout, retries=retries)
    if not txt:
        return None
    txt = re.sub(r"```(?:json)?", "", txt)
    return _extract_json(txt)
