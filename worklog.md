# worklog — vfactory session log (append-only)

---
Task ID: R15-startup
Agent: main (Super Z)
Task: MISSION: REPAIR VFACTORY AND REBUILD THE AHYEON DOCUMENTARY — startup state capture + root-cause diagnosis

Work Log:
- Read AGENT.md, all stage implementations (s2-s7), vfactory.py, lib/*, git state.
- Repo: ansaribilal14/vfactory @ main 9ae956f8, clean tree, canonical remote verified (push perms admin=true).
- Located old run: runs/ahyeon-5th-gen-it-girl/ (git-tracked narration + script + timings + timeline + pool manifest; heavy render artifacts wiped by sandbox reset).
- Recovered the FAILED release film from GitHub release asset (448MB, sha256 22e2193a0cefd3863ba8c74c9fe4ae1fa854d17fe76f24e3a1ef54b288827a28 — matches storage manifest) into runs/ahyeon-5th-gen-it-girl/recovered/.
- AUDIO DIAGNOSIS (objective, not log-trust):
  * Narration files: 14/14 healthy (peak ≈ -3dB, mean ≈ -20dB, speech band ≈ -24dB).
  * Shipped film audio: uniform spectral profile, LRA=1.60, no voice-band modulation.
  * DECISIVE: normalized cross-correlation of all 14 narration tracks vs film audio
    at expected timeline offsets => 14/14 ABSENT (peak corr 0.071-0.149, noise level).
  * CONCLUSION: released film is MUSIC-ONLY. Narration never reached the shipped mix.
- ROOT CAUSES (code-level, stages/s6_render.py @ 9ae956f8):
  1. pass_c reuses mix.wav whenever mix.wav+mix.ok exist — no dependency check on
     narration files, timings, bed, or starts mapping. A music-only or stale mix persists.
  2. final.mp4 reuse is duration-only (ffprobe > total-3.0) — audio changes do not
     invalidate the shipped file.
  3. The "HARD AUDIO GATE" is volumedetect mean/max only — a loud music-only mix
     passes (measured max -1.4dB). It cannot detect missing speech.
  4. s4 scene cuts: keyword-overlap ranking (pool keys/aliases) + rotated
     pseudo-random range offsets = arbitrary clip lineup, no shot-level intent.
  5. s5 composer: kick/hats/8th-bass/16th-pluck groove = upbeat pop energy
     (user: documentary-inappropriate).
  6. s3: tongtong fallback can silently substitute the banned voice.
  7. Script (old run): factual defects (Produce 48 claim false; unverified stats)
     and generic AI-essay tone; no verified fact ledger.
- Environment verified: z-ai vision CLI available (frame verification possible),
  character-clip-extractor cloned at agent-tools/, ytagent downloads dir live,
  storage.to + ghrelease libs working.
- DECISION: rebuild documentary in NEW run dir runs/ahyeon-it-girl-v2; preserve
  old run + old release untouched; fix pipeline stages + add regression tests;
  proof render before full render; new versioned release after gates pass.

Stage Summary:
- Root causes recorded with measured evidence. Implementation begins: narration
  gates + fingerprint invalidation (s6/s3), cinematic score (s5), editorial EDL
  + shot indexing + vision verification (s4), imgagent contextual imagery,
  verified-story script (s1/s2), regression tests, proof render, full render.
