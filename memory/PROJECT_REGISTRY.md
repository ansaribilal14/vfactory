# PROJECT REGISTRY

| project_id | type | status | deliverable | release | next action |
|---|---|---|---|---|---|
| blackpink-gamble | documentary film (51 scenes, 27+ min) | rebuild-v2-in-progress | final.mp4 (720p) + trailer | film-blackpink-gamble-that-changed-kpop (v1 BROKEN — replace) | timings → persist wavs → pool re-farm → s4 (no captions) → s5/s6 with audio gates → s7 replace |
| ahyeon-babymonster-main-vocalist-journey | proof-of-concept film (53s) | delivered 2025-10-09 (v1.0.0) | sample video | superz1402/vfactory v1.0.0 (account suspended — asset lost) | none (historical) |

## Decisions log (architecture-affecting)
- 2025-10-09: vfactory 7-stage pipeline built (s1..s7), checkpoint per stage.
- 2025-10-12: storage.to 3-step uploader proven (multipart >50MB).
- 2026-10-12: R12 film built with legacy s4 → slideshow distortion verdict.
- 2026-10-13: R13 GH-Actions YT ban — farm code removed everywhere.
- 2026-10-13: R13.5 rebuild — edge-tts Andrew voice; multi-cut real-footage s4.
- 2026-10-13: v1 of rebuild released; user verdict: stale captions + silent audio.
- 2026-10-13: R14 persistence system (git canonical + storage.to assets + immediate manifest commits).
