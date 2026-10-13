#!/usr/bin/env python3
"""persist.py — universal asset persistence (R14 permanent system).

Git = canonical state of record; storage.to = external asset host; the local
runtime is disposable. Every downloaded/generated asset is uploaded
immediately, verified, recorded in the git-tracked manifest, and committed.

States: generated -> uploaded_unverified -> verified -> persisted
        upload_failed / manifest_pending / unavailable / expired / restored

Owner tokens are RESOURCE credentials (they allow deletion) and are therefore
kept OUT of the public repo in .secrets/ (gitignored). Losing them only means
waiting for natural 3-7 day expiry — documented in STORAGE_POLICY.md.
"""
import hashlib, json, os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import storageto  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_DIR = os.path.join(BASE, "storage", "manifests")
SECRETS_DIR = os.path.join(BASE, ".secrets")
GIT_BRANCH = None  # current branch


def _sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def _git(args, timeout=60):
    return subprocess.run(["git", "-C", BASE] + args, capture_output=True,
                          text=True, timeout=timeout)


def git_commit_push(files, message, retries=3):
    """Commit + push manifest/state updates. Pull --rebase first to avoid
    clobbering newer remote state. Returns (ok, sha_or_error)."""
    for attempt in range(retries):
        try:
            add = _git(["add"] + files)
            if add.returncode != 0:
                return False, f"add failed: {add.stderr[-200:]}"
            dirty = _git(["diff", "--cached", "--quiet"])
            if dirty.returncode == 0:
                return True, "no-changes"
            c = _git(["commit", "-q", "-m", message])
            if c.returncode != 0:
                return False, f"commit failed: {c.stderr[-200:]}"
            sha = _git(["rev-parse", "--short", "HEAD"]).stdout.strip()
            pull = _git(["pull", "--rebase", "-q"], timeout=90)
            if pull.returncode != 0:
                _git(["rebase", "--abort"])
            push = _git(["push", "-q", "origin", "HEAD"], timeout=120)
            if push.returncode == 0:
                return True, sha
            # remote moved — rebase and retry
            time.sleep(2 + attempt * 3)
        except subprocess.TimeoutExpired:
            time.sleep(3)
    return False, "push retries exhausted"


def _manifest_path(project_id):
    return os.path.join(MANIFEST_DIR, f"{project_id}.json")


def load_manifest(project_id):
    p = _manifest_path(project_id)
    if os.path.isfile(p):
        return json.load(open(p))
    return {"schema_version": 1, "project_id": project_id, "status": "active",
            "assets": []}


def save_manifest(project_id, manifest):
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    p = _manifest_path(project_id)
    json.dump(manifest, open(p, "w"), indent=1, sort_keys=False)
    return p


def find_asset(project_id, asset_id):
    m = load_manifest(project_id)
    for a in m["assets"]:
        if a["asset_id"] == asset_id:
            return a
    return None


def persist_asset(path, project_id, asset_type, generation_stage,
                  version="v1", asset_id=None, notes=None, verify_full=False):
    """Upload one completed asset to storage.to, verify it, record it in the
    git-tracked manifest, commit+push. Idempotent by content hash: re-calling
    with the same file content does NOT re-upload."""
    path = os.path.abspath(path)
    if not (os.path.isfile(path) and os.path.getsize(path) > 0):
        return {"ok": False, "state": "generated_invalid",
                "error": f"missing/empty file: {path}"}

    sha = _sha256(path)
    size = os.path.getsize(path)
    fname = os.path.basename(path)

    # idempotency: same project+content already verified -> skip upload
    existing = find_asset(project_id, asset_id or fname)
    if existing and existing.get("sha256") == sha and \
            existing.get("verification_status") == "verified":
        return {"ok": True, "state": "persisted", "dedup": True,
                "record": existing}

    rec = {"asset_id": asset_id or fname, "project_id": project_id,
           "asset_type": asset_type, "filename": fname,
           "mime_type": _mime(fname), "size_bytes": size, "sha256": sha,
           "provider": "storage.to", "remote_id": None, "remote_url": None,
           "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "uploaded_at": None, "last_verified_at": None,
           "verification_status": "generated",
           "availability_status": "local_only",
           "retention_policy": "anonymous: 3 days default, <=7 via expiry_days",
           "expiration_at": None, "generation_stage": generation_stage,
           "version": version, "dependencies": [], "retry_status": None,
           "notes": notes or ""}

    # 1) upload (storage.to 3-step flow; multipart handled by lib)
    try:
        up = storageto.upload(path)
        f = up.get("file") or up  # lib returns flat {id,url,...}; API docs nest under file
        rec["remote_id"] = f.get("id")
        rec["remote_url"] = f.get("url")
        rec["uploaded_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        rec["expiration_at"] = f.get("expires_at")
        rec["verification_status"] = "uploaded_unverified"
        rec["availability_status"] = "remote_pending_verify"
        if up.get("owner_token"):
            _save_owner_token(project_id, rec["asset_id"], up["owner_token"])
    except Exception as e:
        rec["verification_status"] = "upload_failed"
        rec["retry_status"] = f"upload error: {str(e)[:200]}"
        _write_manifest_record(project_id, rec)
        return {"ok": False, "state": "upload_failed", "record": rec}

    # 2) verify retrievability
    ok, how = verify_remote(rec, full=verify_full)
    rec["last_verified_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    rec["verification_status"] = "verified" if ok else "uploaded_unverified"
    rec["availability_status"] = "available" if ok else "verify_failed"
    if not ok:
        rec["retry_status"] = f"verify: {how}"

    # 3) manifest + git (retry git only — never re-upload on git failure)
    _write_manifest_record(project_id, rec)
    if rec["verification_status"] != "verified":
        return {"ok": False, "state": rec["verification_status"], "record": rec}
    return {"ok": True, "state": "persisted", "record": rec}


def _write_manifest_record(project_id, rec):
    m = load_manifest(project_id)
    m["assets"] = [a for a in m["assets"] if a["asset_id"] != rec["asset_id"]]
    m["assets"].append(rec)
    m["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    p = save_manifest(project_id, m)
    ok, info = git_commit_push([os.path.relpath(p, BASE)],
                               f"persist: {project_id}/{rec['asset_id']} "
                               f"({rec['verification_status']})")
    rec["manifest_pending"] = not ok
    if not ok:
        rec["retry_status"] = f"git: {info}"


def _save_owner_token(project_id, asset_id, token):
    os.makedirs(SECRETS_DIR, exist_ok=True)
    p = os.path.join(SECRETS_DIR, f"{project_id}_owner_tokens.json")
    d = json.load(open(p)) if os.path.isfile(p) else {}
    d[asset_id] = {"owner_token": token, "remote_id": None,
                   "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    json.dump(d, open(p, "w"), indent=1)


def verify_remote(rec, full=False):
    """Availability probe via the DOCUMENTED status endpoint.

    storage.to share URLs are Cloudflare-bot-protected SPA pages: anonymous
    programmatic download is not available and undocumented internals are
    off-limits by policy. "verified" therefore means: file exists (not
    pending), size matches, crc32 was validated server-side at confirm time.
    Local sha256 stays the recovery-reference truth in the manifest.
    Programmatic restore works for github-release provider records; for
    storage.to records it requires manual browser download (documented
    limitation).
    """
    import urllib.request
    if rec.get("provider") == "github-release" and rec.get("remote_url"):
        try:
            req = urllib.request.Request(rec["remote_url"],
                                         headers={"Range": "bytes=0-1023"})
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status not in (200, 206):
                    return False, f"http {r.status}"
                r.read(1024)
            return True, "release-range-probe"
        except Exception as e:
            return False, str(e)[:150]
    if not rec.get("remote_id"):
        return False, "no remote_id"
    try:
        req = urllib.request.Request(
            f"https://storage.to/api/file/{rec['remote_id']}/status")
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode())
        if d.get("pending") is False:
            return True, "status-endpoint"
        return False, f"status={d}"
    except Exception as e:
        return False, str(e)[:150]


def check_asset(project_id, asset_id):
    rec = find_asset(project_id, asset_id)
    if not rec:
        return {"ok": False, "state": "unknown_asset"}
    ok, how = verify_remote(rec)
    rec["last_verified_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    rec["availability_status"] = "available" if ok else "unavailable"
    rec["verification_status"] = "verified" if ok else "uploaded_unverified"
    if not ok:
        rec["retry_status"] = f"check: {how}"
    _write_manifest_record(project_id, rec)
    return {"ok": ok, "state": rec["availability_status"], "record": rec}


def restore_asset(project_id, asset_id, dest_dir):
    """Download a manifest asset into dest_dir, verify sha256, mark restored.

    github-release records: fully programmatic. storage.to records: NOT
    programmatically restorable (Cloudflare-protected SPA; undocumented
    internals are off-limits) — fails fast with an explicit state instead
    of downloading an HTML page and faking success."""
    rec = find_asset(project_id, asset_id)
    if not rec or not rec.get("remote_url"):
        return {"ok": False, "state": "no_remote_location"}
    if rec.get("provider") == "storage.to":
        rec["availability_status"] = "manual_restore_required"
        rec["retry_status"] = ("storage.to anonymous download is "
                               "bot-protected; restore via browser manually")
        _write_manifest_record(project_id, rec)
        return {"ok": False, "state": "manual_restore_required",
                "url": rec["remote_url"]}
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, rec["filename"])
    try:
        import urllib.request
        urllib.request.urlretrieve(rec["remote_url"], dest)
    except Exception as e:
        rec["availability_status"] = "restore_failed"
        rec["retry_status"] = str(e)[:150]
        _write_manifest_record(project_id, rec)
        return {"ok": False, "state": "restore_failed", "error": str(e)[:150]}
    good = _sha256(dest) == rec["sha256"]
    rec["last_verified_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    if good:
        rec["availability_status"] = "restored"
        rec["verification_status"] = "verified"
    else:
        rec["retry_status"] = "sha mismatch on restore"
    _write_manifest_record(project_id, rec)
    return {"ok": good, "state": "restored" if good else "sha_mismatch",
            "path": dest}


def _mime(fname):
    ext = fname.rsplit(".", 1)[-1].lower()
    return {".mp4": "video/mp4", ".wav": "audio/wav", ".mp3": "audio/mpeg",
            ".png": "image/png", ".jpg": "image/jpeg", ".srt": "text/plain",
            ".json": "application/json", ".txt": "text/plain"}.get(
        "." + ext, "application/octet-stream")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "persist":
        print(json.dumps(persist_asset(a[1], a[2], a[3], a[4]), indent=1))
    elif a[0] == "check":
        print(json.dumps(check_asset(a[2], a[1]), indent=1))
    elif a[0] == "restore":
        print(json.dumps(restore_asset(a[1], a[2], a[3]), indent=1))
