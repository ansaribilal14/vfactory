# PERSISTENCE ARCHITECTURE (R14 — permanent system)

## Principle
The runtime filesystem is DISPOSABLE. Git is the canonical state of record;
storage.to is the external asset host. Nothing important exists in only one
place after any pipeline step completes.

## Components (all in the vfactory repo)
| Path | Role |
|---|---|
| `AGENT.md` | permanent agent instructions incl. startup/shutdown protocol |
| `memory/CURRENT_STATE.md` | authoritative recovery point, updated at checkpoints |
| `memory/PROJECT_REGISTRY.md` | project IDs, status, decisions, next actions |
| `memory/SESSION_HANDOFF.md` | concise handoff: task, done, pending, next action |
| `storage/STORAGE_POLICY.md` | real storage.to capabilities + our rules |
| `storage/RECOVERY.md` | step-by-step recovery from an empty runtime |
| `storage/DELETION_LOG.md` | user-authorized cleanup history (append-only) |
| `storage/manifests/{project}.json` | per-project asset manifest (git-tracked) |
| `lib/persist.py` | the adapter: persist/verify/restore/check + git commit |
| `.secrets/` | owner tokens etc. — GITIGNORED, never committed |

## Data flow (mandatory for EVERY asset — downloaded or generated)
```
generate/download -> validate (exists, size>0)
  -> sha256 + size locally
  -> storageto.upload (init -> PUT -> confirm; multipart automatic)
  -> verify (Range-GET; full sha for small files)
  -> manifest record update (storage/manifests/{project}.json)
  -> git add/commit/push  (manifest ONLY; media never enters git)
  -> continue pipeline
```
Failure isolation: upload failure -> state upload_failed, retry later, local
copy retained. Git failure -> state manifest_pending, retry git only (never
re-upload a verified asset — dedup key is project_id + sha256).

## What is NOT persisted to storage.to
- Re-farmable SOURCE media (e.g. public MV pool) — recorded as
  `re-fetchable source` in the manifest notes with their video IDs, re-farmed
  via own-server yt-dlp/cobalt when needed (R13: no GH Actions).
- Ephemeral encode intermediates (xfade chunks, partial renders) — cheap to
  re-encode from persisted scene cuts; flagged as such in the manifest.

## Startup protocol (every fresh runtime)
1. `cd /home/z/my-project/vfactory && git fetch origin && git reset --hard origin/main`
2. Read memory/CURRENT_STATE.md, memory/SESSION_HANDOFF.md,
   memory/PROJECT_REGISTRY.md
3. Load the active project manifest; check_asset() for assets needed by the
   next stage; restore_asset() the ones missing locally.
4. Resume from the checkpoint; NEVER regenerate a verified asset.

## Shutdown protocol (every session close)
1. Update memory/*.md with real state.
2. Append to /home/z/my-project/worklog.md.
3. git commit + push (verify remote).
