# RECOVERY — from a completely empty runtime

Scenario: sandbox reset. Local filesystem empty except /home/z/my-project skeleton
and credentials in ~/.gh_token etc.

## Steps
1. Restore repos:
   ```
   cd /home/z/my-project/vfactory
   git remote set-url origin https://ansaribilal14:$(cat /home/z/my-project/.gh_token)@github.com/ansaribilal14/vfactory.git
   git fetch origin && git reset --hard origin/main
   ```
   (Other agent repos: agent-tools/* re-clone from ansaribilal14 forks if needed.)
2. Read memory/CURRENT_STATE.md + memory/SESSION_HANDOFF.md — they name the
   active project, completed stages, and the exact next action.
3. Open storage/manifests/{project}.json. For each asset the next stage needs:
   - availability check (lib/persist.py check_asset)
   - restore into runs/{project}/... (lib/persist.py restore_asset)
   - sha256 is verified automatically on restore; a mismatch = report, never fake.
4. Assets marked expired/unavailable: re-check once; if really gone, mark in
   manifest, regenerate ONLY the missing asset from its dependencies (the
   record lists generation_stage + dependencies).
5. Re-farmable sources (public MV pool etc.) are noted per-asset in the
   manifest notes with video IDs — re-farm on this server via
   agent-tools/ytagent (cobalt method). Never via GitHub Actions (R13).
6. Resume the pipeline from the recorded stage. Checkpoint markers
   (.done_*) and resumable stage code make each stage skip completed work.
7. After recovery, commit a state note:
   `git commit -m "recovery: runtime restored, resumed at <stage>"` + push.

## What CANNOT be recovered from git alone
- Large media not yet persisted (by policy everything important is persisted
  immediately — a gap here = a bug; fix the pipeline stage that skipped it).
- .secrets/ (owner tokens) — if lost, remote files remain until expiry;
  deletion of those specific files is then impossible (documented limitation).
