# CURRENT STATE — authoritative recovery point (updated at every checkpoint)

Last updated: 2026-10-13 (R14 session)
Head commit at last write: see `git log -1`

## Active projects

### blackpink-gamble (documentary film, 51 scenes, 27+ min requirement)
- **Status**: REBUILD-IN-PROGRESS (user verdict on 2026-10-13 release: stale
  captions + NO audible audio → full audio/caption rebuild)
- **Recovered after sandbox wipe**: 02_script.json + 51 canonical narration
  WAVs (edge-tts en-US-AndrewNeural @ -15%, verified mean -21dB) are
  git-tracked under `runs/blackpink-gamble/` — do NOT re-synthesize.
- **WAV→scene mapping**: cold_open_s0X→1-2, ch1..ch7 s03..s49, outro_s50/s51→50-51.
  Strays (do NOT use): ch4_s18.wav, ch7_s50.wav, outro_s52.wav
- **Released assets (v1, BROKEN audio/captions)**: GitHub release
  `film-blackpink-gamble-that-changed-kpop` on ansaribilal14/vfactory —
  to be REPLACED with v2 assets after rebuild. storage.to mirror
  https://storage.to/x5y24ajjT (expires 2026-10-16).
- **Next action**: build 03_timings.json from canonical WAVs → persist WAVs →
  re-farm MV pool (23 videos via ytagent cobalt) → s4 cuts (NO captions) →
  s5 bed (audible on phone speakers) → s6 render with AUDIO GATES →
  s7 release replace.

## Standing user rules (enforced)
1. NO image slideshows / zoompan / static frames (R1-R2, R13.5)
2. NO GitHub Actions for YT downloads — own-server yt-dlp/cobalt only (R13)
3. Voice = en-US-AndrewNeural (tongtong BANNED for English narration)
4. Main film MUST be a git release (Rule 9) + link to user
5. Release assets DELETED after user downloads (R13 lifecycle)
6. 27+ minutes hard floor for the BLACKPINK film (R12)
7. Worklog appended at EVERY session close
8. R14: every asset persisted to storage.to immediately + manifest
   committed (see docs/PERSISTENCE_ARCHITECTURE.md)
