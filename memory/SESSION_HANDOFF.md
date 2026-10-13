# SESSION HANDOFF — read me first after any restart

**Active project**: blackpink-gamble (vfactory run `runs/blackpink-gamble`)

**Current task**: v2 rebuild — remove stale captions, FIX silent audio,
re-deliver. Sandbox reset on 2026-10-13 wiped local media; script + 51
narration WAVs survived via git.

**Completed (verified)**:
- R13 purge (GH-Actions farm removed; ansaribilal14/ytagent-1 + CCE pushed)
- 51 Andrew @ -15% WAVs on disk, volume-verified (mean ≈ -21dB, max -3dB)
- WAV↔scene mapping resolved (see memory/CURRENT_STATE.md)
- v1 film released (broken) — release tag film-blackpink-gamble-that-changed-kpop

**Pending**:
- 03_timings.json rebuild from canonical WAVs
- storage.to persistence of all rebuild assets (R14 core just implemented)
- MV pool re-farm (23 videos) + s4 cuts without captions
- s5 bed rebalanced for phone-speaker audibility
- s6 with audio volume gates at: post-mix, post-mux
- s7 release asset replacement (delete v1 assets, upload v2)

**Blockers**: .tg_token missing (user must re-provide); 2-core CPU →
encodes must fit 10-min tool windows (use veryfast + chunk resume)

**Exact next action**: run `python3 scripts/build_timings.py` then start s4
pool re-farm.

**Key commit**: see `git log -1` (R14 persistence core + rebuild fixes)
