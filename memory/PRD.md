# AnchorAI News — PRD

## Original problem statement
A multi-tenant SaaS that turns an authorized anchor portrait and a Gujarati news script into a real AI-generated, lip-synced 16:9 1080p "Breaking News" MP4. The MP4 has branding, Gujarati subtitles, a ticker and an AI disclosure label. The product also includes consent controls, a credit ledger, payments, jobs, a video library, and admin tools. Nothing is mocked.

Later requests:
1. Admins can give credits to users, and admins have unlimited credits.
2. The app can be hosted easily from GitHub or cPanel, and every feature keeps working there.

## Architecture
- **Stack:** FastAPI + MongoDB + React (CRA) + Tailwind/shadcn.
- **Background worker:** asyncio with Mongo leases, so jobs resume after a crash. On cPanel it runs from cron instead (`run_worker.py --once`).
- **AI:**
  - Narration: fal.ai ElevenLabs v3 (language set to Gujarati, returns character timestamps).
  - Talking anchor: Kling AI Avatar v2 Standard.
  - Credential modes: the Universal Key, or the owner's own `FAL_KEY` (`AI_PROVIDER_MODE`).
- **Rendering:** graphics drawn with Pillow (raqm, for correct Gujarati letter shaping) and composed with FFmpeg (bundled by `imageio-ffmpeg`).
- **Storage:** Emergent private storage, or local disk (`STORAGE_BACKEND`). Files are served only through short-lived signed links.
- **Email:** Emergent managed email, or SMTP (`EMAIL_BACKEND`).
- **Payments:** Razorpay orders with signature checks, a direct server-side payment check, and HMAC-verified webhooks.

## Implemented (2026-10-10)
- Email/password auth: verification, password reset, sessions that can be revoked, lockout after repeated failed logins. Workspaces with memberships.
- Anchor library: checks the file's real contents, records versioned consent, supports revoking consent and deletion.
- Channels (brand presets) and a 7-step creator with a live static preview and an exact-frame render.
- Full live pipeline, verified end to end: real Gujarati narration → lip-synced anchor → 1920×1080 H.264/AAC MP4 with subtitles, ticker, intro and disclosure.
- Jobs page with cancel and retry. Video library with MP4, SRT and VTT downloads.
- Append-only credit ledger with reserve, capture and release entries. Retries and repeated events can't charge twice. 30 trial credits after email verification.
- Admin:
  - health checks for every service
  - "Give credits" with quick presets
  - audit log and ledger reconciliation
  - admin workspaces have **unlimited credits**: no charges, and ledger entries are recorded at 0
- Self-hosting kit: `passenger_wsgi.py`, `run_worker.py`, `bootstrap.py`, `requirements-deploy.txt`, `.htaccess`, Dockerfiles and compose, GitHub CI, and the `DEPLOYMENT.md` and `.env.example` files.
- Tests: 13 mocked unit/integration tests in `test_anchorai.py`. The testing agent ran 43 tests in total (iteration 3), all passing.

## Backlog
- **P0:** Razorpay keys from the owner (purchases are switched off until they're added).
- **P1:**
  - workspace invitations and roles
  - Kling Avatar Pro "HD" option
  - narration longer than 60 seconds, split into segments
  - a pronunciation dictionary for each workspace
- **P2:**
  - 9:16 Shorts
  - more templates
  - YouTube publishing
  - GST invoices
  - C2PA content credentials
  - Gujarati interface
