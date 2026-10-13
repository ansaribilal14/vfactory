#!/usr/bin/env python3
"""GitHub Releases publisher — Rule 9 engine.
Recreated 2026-10-13 after superz1402 suspension (rehosted on ansaribilal14).

publish(tag, title, named_files, body) -> (html_url, {name: url}, all_ok)
- ensure_release is idempotent (reuse existing tag's release)
- upload_asset skips identical uploads (same name+size+state), replaces
  different-size ones (delete + re-upload), verifies state=uploaded + size.
"""
import os
import requests

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
DEFAULT_REPO = "ansaribilal14/vfactory"  # rehosted after superz1402 suspension


def _token():
    env = os.environ.get("GH_TOKEN")
    if env and env.strip():
        return env.strip()
    for cand in (os.path.expanduser("~/.gh_token"),
                 "/home/z/my-project/.gh_token"):
        if cand and os.path.isfile(cand):
            body = open(cand).read().strip()
            if body:
                return body
    raise RuntimeError(
        "no GitHub token found (GH_TOKEN / ~/.gh_token / /home/z/my-project/.gh_token)")


def _hdr():
    return {"Authorization": f"Bearer {_token()}",
            "Accept": "application/vnd.github+json"}


def _repo():
    return os.environ.get("VF_REPO", DEFAULT_REPO)


def ensure_release(tag, title, body=""):
    """Get or create the release for `tag`. Idempotent."""
    r = requests.get(f"{API}/repos/{_repo()}/releases/tags/{tag}",
                     headers=_hdr(), timeout=30)
    if r.status_code == 200:
        return r.json()
    r = requests.post(f"{API}/repos/{_repo()}/releases", headers=_hdr(),
                      timeout=30,
                      json={"tag_name": tag, "name": title, "body": body,
                            "draft": False, "prerelease": False})
    if r.status_code not in (200, 201):
        raise RuntimeError(f"release create failed: {r.status_code} {r.text[:300]}")
    return r.json()


def upload_asset(rel_id, path, name, size):
    """Upload one asset. Idempotent: identical (name+size+uploaded) -> skip.
    Different size under same name -> delete then re-upload. Verifies result."""
    r = requests.get(f"{API}/repos/{_repo()}/releases/{rel_id}/assets?per_page=100",
                     headers=_hdr(), timeout=30)
    for a in (r.json() if r.status_code == 200 else []):
        if a.get("name") == name:
            if a.get("size") == size and a.get("state") == "uploaded":
                return True, a
            requests.delete(f"{API}/repos/{_repo()}/releases/assets/{a['id']}",
                            headers=_hdr(), timeout=30)
            break
    with open(path, "rb") as fh:
        up = requests.post(
            f"{UPLOADS}/repos/{_repo()}/releases/{rel_id}/assets?name={name}",
            headers={"Authorization": f"Bearer {_token()}",
                     "Content-Type": "application/octet-stream"},
            data=fh, timeout=3600)
    if up.status_code != 201:
        return False, {"error": f"{up.status_code} {up.text[:200]}"}
    a = up.json()
    ok = (a.get("state") == "uploaded" and a.get("size") == size)
    return ok, a


def publish(tag, title, named_files, body=""):
    """named_files: [(local_path, asset_name), ...] -> (html_url, urls, all_ok)
    Replace semantics: identical assets are skipped, different-size assets are
    re-uploaded, and any asset NOT in named_files is deleted (stale-version
    cleanup) so the release always reflects the current build."""
    rel = ensure_release(tag, title, body)
    requests.patch(f"{API}/repos/{_repo()}/releases/{rel['id']}",
                   headers=_hdr(), timeout=30,
                   json={"name": title, "body": body})
    urls, ok_all = {}, True
    names = set()
    for path, name in named_files:
        names.add(name)
        if not (path and os.path.isfile(path)):
            urls[name] = None
            ok_all = False
            continue
        ok, asset = upload_asset(rel["id"], path, name, os.path.getsize(path))
        urls[name] = asset.get("browser_download_url") if ok else None
        ok_all = ok_all and ok
    r = requests.get(f"{API}/repos/{_repo()}/releases/{rel['id']}/assets?per_page=100",
                     headers=_hdr(), timeout=30)
    for a in (r.json() if r.status_code == 200 else []):
        if a.get("name") not in names:
            requests.delete(f"{API}/repos/{_repo()}/releases/assets/{a['id']}",
                            headers=_hdr(), timeout=30)
    return rel.get("html_url"), urls, ok_all


if __name__ == "__main__":
    import sys, json
    print(json.dumps(ensure_release("smoke-test", "smoke test", "delete me"),
                     indent=1)[:400])
