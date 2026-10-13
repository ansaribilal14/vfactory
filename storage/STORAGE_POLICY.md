# STORAGE POLICY — storage.to (anonymous tier)

Source of truth: https://storage.to/api docs (read 2026-10-13). Do not invent
endpoints or guarantees beyond this file.

## What the service actually provides
- 3-step upload: POST /api/upload/init → PUT presigned URL(s) → POST
  /api/upload/confirm. Files >50MB automatically multipart (32MB parts).
- Anonymous limits: 50 files / 24h, 100GB upload / 24h per visitor token
  (500GB per IP), max file 25GB, expiry 3 days default (up to 7 via
  expiry_days on confirm... confirm has no expiry_days param in the
  documented request — expiry is returned in the response; treat 3 days as
  the planning number unless the response says otherwise).
- NO permanence on anonymous tier. NO folders/keys — flat IDs
  (https://storage.to/{file_id}).
- **Deletion IS supported**: DELETE /api/file/{id} with owner proof.
- Ownership: every creating endpoint returns an `owner_token` (resource-
  scoped, does not expire while the resource lives). Visitor token (client-
  generated, sent as X-Visitor-Token) + creator IP are weaker proofs.

## Our rules
1. Owner tokens are stored OUTSIDE git in `.secrets/` (gitignored) — they are
   delete credentials for a PUBLIC repo. Loss of a token is acceptable:
   anonymous files expire in <=7 days anyway; record the loss honestly.
2. Every upload response (file.id, file.url, file.expires_at) is recorded in
   the project manifest as-is. NEVER fabricate URLs/IDs/expiry.
3. **VERIFICATION LIMITATION (tested 2026-10-13)**: share URLs
   (https://storage.to/{id}) are Cloudflare-bot-protected SPA pages — plain
   HTTP clients get 403 and the page exposes no direct download link without
   executing app JS. Programmatic download of anonymous files is therefore
   NOT possible, and undocumented SPA internals are off-limits by policy.
   Our "verified" = documented GET /api/file/{id}/status returns
   pending:false + size match + crc32 passed to /upload/confirm for
   server-side integrity. LOCAL sha256 in the manifest remains the
   recovery-reference truth.
4. **RESTORE LIMITATION**: storage.to records cannot be programmatically
   restored (see 3). Programmatic restore (checksum-verified) works for
   `github-release` provider records. POLICY: every final deliverable is
   BOTH released on GitHub (programmatic recovery path) AND mirrored to
   storage.to (user convenience); storage.to-only assets (intermediates)
   are recoverable by regeneration or manual browser download — stated
   plainly in the manifest, never faked.
5. Rate budgets: uploads are spread across pipeline stages; status polls
   only at verify-time and restart-recovery (documented 120/min limit).
6. storage.to is backend #1 by policy; the adapter (lib/persist.py) isolates
   provider specifics so a second backend can be added without touching the
   pipeline. Manifest schema is provider-agnostic.
7. Treat all uploaded URLs as PUBLIC — no secrets, no private data.
8. Expiry monitoring: assets are re-checked (check_asset) before reuse after
   >24h or after any restart. Expired assets are marked `expired` in the
   manifest and regenerated only if inputs survive; the loss is reported.
