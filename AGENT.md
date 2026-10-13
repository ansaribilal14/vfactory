# AGENT.md — vfactory operating contract (MANDATORY READING)

This file is the accumulated institutional memory of this project. Every agent
session MUST read this file + `worklog.md` before doing anything. It exists so
that quality regressions seen in real user feedback (R1–R12) never happen twice.

**Repo: `ansaribilal14/vfactory`** (rehosted 2026-10-13 after the superz1402
account suspension; all Rule 9 releases publish here now).

## Mission

Autonomous documentary factory: topic → research → script → narration → real
footage → score → render → **GitHub Release + Telegram** → find users →
observe → learn → improve → charge. Current flagship project: **BLACKPINK
documentary, 27 minutes or more** (R12).

## Hard rules distilled from user feedback (NEVER violate)

- R1–R2: No image slideshows. No random clips. No odd/drip-MV audio. No
  on-screen paragraph text. Research-first; pace slow and deliberate.
- R3: Footage must be SUBJECT-SPECIFIC (the actual artist), never generic.
  Methodology: `ansaribilal14/character-clip-extractor`.
- R4: Priority order: **footage retrieval > accurate research > pacing >
  sound design > coherent editing**. Reference docs: `xDx0SiYUw_o`,
  `ryj6jhR4mCU`, `SEIPw295qrg`, `U7SogEXOdBY`, `YtuVWTvR3S4`.
  Repo references: OpenMontage (`calesthio/OpenMontage`, first choice),
  ai-video-factory, ContentMachine, Narrate-AI.
- R5: Get the final video. No IP excuses. Use ytdl-agent to source real assets.
- R6: Scene visuals must semantically match the narration at that timestamp.
  Script drives subject-faithful sourcing.
- R7: Background music quality matters. Full-length delivery (20+ min) matters.
- R9: Full-length film ALWAYS delivered (never trailer-only). Trailers are an
  ADDITION. GitHub Pages landing page exists and stays good.
- R10: Real footage runs only — never regress to images+music+voiceover.
- R11: **Rule 9 below** — main video always published as a git release.
- R12: BLACKPINK topic, 27+ minutes, competitor transcript research allowed.

## YouTube sourcing rule (user directive, 2026-10-13 — PERMANENT)

**NEVER use GitHub Actions to download YouTube videos. Not one workflow, not
one step, not "just for tests".** All YT fetching happens locally on our own
server/environment via ytdl-agent / yt-dlp. All GitHub-Actions YT-downloader
workflows were purged from every local clone on 2026-10-13 (re-purge is part
of tools/restore_env.sh). Non-negotiable.

**Release asset lifecycle (user directive, 2026-10-13):** after the user
confirms they have downloaded a release's assets, DELETE those assets from
the release on request. Releases are a delivery vehicle, not permanent
storage, when the user says so.

## Rule 9 — Release delivery (mechanical, not optional)

1. s7 ALWAYS calls `publish_release()`: tag `film-<slug>` on
   `ansaribilal14/vfactory`, assets `<slug>_full_1080p.mp4`,
   `<slug>_full_720p.mp4`, `<slug>_trailer.mp4` (when present).
2. The release link is ALWAYS pushed to Telegram (chat_id 1263089875,
   bot @Submittermebot, token in `/home/z/my-project/.tg_token`, chmod 600).
3. **Telegram copies or storage.to mirrors alone are NOT a complete delivery.**
4. `delivery.json.release.ok == true` gates the `delivered` flag. Operator
   MUST verify this field before declaring any run complete.

## Pipeline contract

| Stage | Responsibility | Checkpoint |
|-------|----------------|------------|
| s1 research | multi-angle search → source brief + FACT bank | `01_research.json` |
| s2 script   | segmented documentary script (27 min ≈ 4000+ narration words), FACT discipline | `02_script.json` |
| s3 voice    | per-segment TTS + word-level timestamps | `03_voice/`, `03_timings.json` |
| s4 media    | REAL footage only (ytdl-agent pool + farm + clip selection); subject-specific; semantic match to script | `04_media/`, `04_media.json` |
| s5 music    | synthesized bed, ducked under VO, loudnorm | `05_music/bed.wav` |
| s6 render   | segmented render + concat, 1080p30 | `06_final/`, `final.mp4` |
| s7 deliver  | Rule 9 release + TG + mirror | `delivery.json` |

Orchestrator: `vfactory.py` with `.done_<stage>` checkpoints. Runs must be
foreground (sandbox reaps detached background processes); every stage writes
its checkpoint before exit. Resume with `--run-dir`.

⚠️ NOTE (2026-10-13): the R10 real-footage rebuild of s4 was lost in a sandbox
reset (this disk holds the legacy image-search s4). REBUILD s4 real-footage
before the BLACKPINK run. The ytdl-agent + farm methodology is proven — see
worklog Task 29-era runs.

## Closing protocol (§23–28) — every deliverable, every time

1. Update docs (README/AGENT.md/worklog).
2. Security scan: `rg -n "ghp_|github_pat_|sk-|Bearer [A-Za-z0-9]" .` — no
   secrets in tracked files, ever.
3. `git add -A && git commit`.
4. `git push` — local commit is NOT done; "updated locally" ≠ done.
5. Remote verify: `git ls-remote origin <branch>` shows the new sha.
6. For runs: verify `delivery.json.release.ok == true` + anonymous asset
   download (expect HTTP 206 on a Range request) + TG link sent.
7. Append the run to `/home/z/my-project/worklog.md` (template inside).

## Credentials map (chmod 600, NEVER in git, never in archives)

- GitHub: `/home/z/my-project/.gh_token` → **ansaribilal14** (superz1402 is
  SUSPENDED since 2026-10-13 — do not use, do not push there)
- storage.to visitor: auto-managed by `lib/storageto.py`
- Telegram: `/home/z/my-project/.tg_token` (@Submittermebot) — re-provide
  after sandbox resets; chat_id 1263089875
- git auth: `/home/z/my-project/.git-credentials` (credential.helper store)

## Discipline

- Label claims FACT / HYPOTHESIS / UNVERIFIED. Quality is proven against
  reference documentaries and user acceptance, not vibes.
- Never clobber parallel sessions' git work (push to your own branch lane).
- Read `worklog.md` first; append your Task ID entry after finishing.
- Anonymous storage.to files expire ≤7 days; GitHub Releases are the
  permanent home; local sandbox can RESET WITHOUT WARNING — push early,
  push often.

## R14 — PERMANENT PERSISTENCE PROTOCOL (mandatory, repository-level)

The runtime filesystem is disposable. Git = canonical state; storage.to =
asset host. Enforced by `lib/persist.py` + `docs/PERSISTENCE_ARCHITECTURE.md`.

1. **Session start (before ANY substantive work)**: fetch + hard-reset to
   origin/main; read memory/CURRENT_STATE.md, memory/SESSION_HANDOFF.md,
   memory/PROJECT_REGISTRY.md; load the active project manifest; restore
   needed assets via persist.restore_asset(); resume from checkpoint. NEVER
   regenerate a verified asset.
2. **Asset completion (downloaded OR generated)**: immediately
   persist_asset() → upload → verify → manifest → git commit+push. No
   batching until session end. Media NEVER enters git; JSONs/timings DO
   (commit run-state jsons at each stage).
3. **Session close**: update memory/*.md, append worklog, commit+push,
   verify remote sha.
4. **Releases are per-project and immediate** — a completed project ships
   without waiting for others. Release ≠ permission to delete.
5. **Cleanup requires explicit user authorization**; storage.to deletion
   only via owner token (kept in gitignored .secrets/); every cleanup is
   recorded in storage/DELETION_LOG.md. If the owner token is lost, say so —
   anonymous files expire <=7 days regardless.
6. **Never fabricate** URLs, IDs, checksums, expiries, or test results.
   If an asset is lost/expired, mark it and report the loss plainly.
