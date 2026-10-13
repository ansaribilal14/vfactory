#!/usr/bin/env python3
"""R14 E2E persistence test — REAL execution, disposable asset.
Chain: persist -> verify -> manifest+git -> check -> restore+sha -> delete(owner) -> log."""
import hashlib, json, os, subprocess, sys, time, urllib.request

sys.path.insert(0, "/home/z/my-project/vfactory")
from lib import persist  # noqa: E402

BASE = "/home/z/my-project/vfactory"
PROJ = "persistence-selftest"
results = []


def step(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}", flush=True)
    return ok


# 1. disposable asset
test_path = "/tmp/r14_selftest_asset.txt"
payload = f"R14 selftest {time.time()}".encode()
open(test_path, "wb").write(payload)
step("create_test_asset", os.path.getsize(test_path) > 0)

# 2. persist (upload + verify + manifest + git)
r = persist.persist_asset(test_path, PROJ, "test", "selftest", asset_id="selftest-001")
step("persist_asset", r.get("ok"), f"state={r.get('state')} url={r.get('record', {}).get('remote_url')}")
rec = r.get("record", {})

# 3. manifest recorded with real fields
step("manifest_fields", bool(rec.get("remote_id")) and bool(rec.get("remote_url"))
     and rec.get("verification_status") == "verified"
     and rec.get("sha256") == hashlib.sha256(payload).hexdigest())

# 4. git committed + pushed
git = subprocess.run(["git", "-C", BASE, "log", "--oneline", "-1"],
                     capture_output=True, text=True).stdout.strip()
step("git_commit", "persist:" in git, git)
pushed = subprocess.run(["git", "-C", BASE, "status", "-sb"], capture_output=True,
                        text=True).stdout.split("\n")[0]
step("git_push_sync", "ahead" not in pushed and "behind" not in pushed, pushed)

# 5. availability check
c = persist.check_asset(PROJ, "selftest-001")
step("check_asset", c.get("ok"), c.get("state"))

# 6. restore + sha match (github-release record — programmatic restore path)
rr = persist.restore_asset("blackpink-gamble", "trailer-blackpink-gamble-v1",
                           "/tmp/r14_restore")
same = False
if rr.get("ok"):
    same = hashlib.sha256(open(rr["path"], "rb").read()).hexdigest() == \
        "3dc6a19540d7710838cd420ac802b4975f510325a02039504e205c200e541f80"
step("restore_github_release_sha", rr.get("ok") and same, rr.get("state"))

# 6b. storage.to restore = honest manual_restore_required (no fake download)
rr2 = persist.restore_asset(PROJ, "selftest-001", "/tmp/r14_restore")
step("storageto_restore_honest_fail", rr2.get("state") == "manual_restore_required",
     rr2.get("state"))

# 7. cleanup via owner token (documented deletion path)
tok_file = os.path.join(BASE, ".secrets", f"{PROJ}_owner_tokens.json")
deleted = False
detail = ""
if os.path.isfile(tok_file) and rec.get("remote_id"):
    tok = json.load(open(tok_file)).get("selftest-001", {}).get("owner_token")
    if tok:
        req = urllib.request.Request(
            f"https://storage.to/api/file/{rec['remote_id']}", method="DELETE",
            headers={"Authorization": f"Owner {tok}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode()[:120]
                deleted = resp.status in (200, 204)
                detail = f"http {resp.status} {body}"
        except Exception as e:
            detail = str(e)[:120]
step("owner_delete", deleted, detail)

# 8. post-delete availability = unavailable (honest check)
time.sleep(2)
c2 = persist.check_asset(PROJ, "selftest-001")
step("post_delete_unavailable", not c2.get("ok"), c2.get("state"))

# 9. record in DELETION_LOG + git
log = os.path.join(BASE, "storage", "DELETION_LOG.md")
with open(log, "a") as fh:
    fh.write(f"\n- 2026-10-13 selftest-001 ({PROJ}): deleted via owner token "
             f"after E2E test; remote_id={rec.get('remote_id')}; "
             f"post-delete check={c2.get('state')}\n")
ok, info = persist.git_commit_push([os.path.relpath(log, BASE)],
                                   "selftest: deletion log entry")
step("deletion_log_git", ok, str(info))

print("\nSUMMARY:", sum(1 for _, o, _ in results if o), "/", len(results), "passed")
sys.exit(0 if all(o for _, o, _ in results) else 1)
