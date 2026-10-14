# CURRENT STATE — authoritative recovery point (updated at every checkpoint)

Last updated: 2026-10-14 (Ahyeon delivery session)
Head commit at last write: see `git log -1`

## Active projects

### ahyeon-the-fifth-generation-it-girl (DELIVERED 2026-10-14)
- **Status**: v1 RELEASED — release `film-ahyeon-the-fifth-generation-it-girl` on
  ansaribilal14/vfactory (448MB 720p30, 393.2s, 14 scenes) + storage.to mirror
  https://storage.to/dImPev8W0 (3-day default expiry). TG pending .tg_token.
- **Pipeline upgrades shipped this run**: s5 = opuscar composed-score engine
  (chord prog / harmonic bass / KS plucks / round-robin / -23dBFS headroom mix);
  s6 = clip-proof master (voice acompressor, no gain slam, alimiter -1dB,
  two-pass LINEAR loudnorm; peak -1.5dB verified, distortion fixed);
  s2 = narrative-arc prompt + per-scene expansion (395->820 words);
  s3 = project-scoped length floor; s7 = per-project manifest identity.
- **Pending**: user download confirmation -> delete release assets (R13).
  .tg_token still missing (user must re-provide).

### blackpink-gamble (documentary film, 51 scenes)
- **Status**: v2 DELIVERED 2026-10-13 — awaiting user download confirm before
  release-asset deletion.
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
