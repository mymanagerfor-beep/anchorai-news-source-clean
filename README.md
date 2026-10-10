# AnchorAI News

Multi-tenant SaaS that turns an **authorized anchor portrait + Gujarati news script** into a branded
**16:9 1920×1080 Breaking News MP4**. The MP4 has a lip-synced AI presenter, Gujarati subtitles, a scrolling
ticker and a permanent AI-generated disclosure label.

## Architecture & data flow
```
React (CRA + Tailwind + shadcn) ──HTTPS/JSON (Bearer session JWT)──▶ FastAPI /api/v1
MongoDB: users, workspaces, workspace_memberships, sessions, anchors, consents, channels, projects,
         jobs, media_assets, credit_ledger, payments, webhook_events, audit_events
Emergent private object storage: portraits, narration audio, raw anchor video, final MP4
Background worker (asyncio + Mongo leases, crash-resumable):
  validating → generating (ElevenLabs v3 TTS, language_code=gu, char timestamps;
               Kling AI Avatar v2 Standard image+audio lip-sync) → retrieving (download, probe, decode check)
  → rendering (Pillow + HarfBuzz/raqm Gujarati graphics, FFmpeg compose; verify 1920×1080 H.264/AAC,
               duration, decode; store; read-back verify) → completed (capture credits, email)
```
Provider calls go through **fal.ai queue inference** using the Emergent Universal Key proxy.
The adapter lives in `backend/providers.py` (`FalQueueAdapter`). Its methods are:
`validate_configuration`, `validate_request`, `estimate_cost_usd`, `create`, `get_status`, `cancel_job`,
`retrieve_output` and `verify_webhook`. Each submission is saved before polling starts. After a crash, the
worker goes back to polling the saved submission. It never sends the request again.

### Changes from the brief (platform limits)
| Brief | Implemented | Reason |
|---|---|---|
| PostgreSQL + migrations | MongoDB with unique indexes created on startup (`server.py: ensure_indexes`) | Platform-managed DB |
| Redis + worker | In-process asyncio worker with Mongo leases (`worker.py`) | No Redis available |
| S3 presigned URLs | Private storage. The backend streams files through short-lived signed links (`/api/v1/files/signed`, 5–30 min, supports byte ranges) | Storage has no presigned URLs |
| Vite + TypeScript | CRA (craco) + JavaScript | Platform template |
| Avatar webhooks | Authenticated status polling | The Universal-Key proxy sends no app webhooks |

## Local development
```
cd backend && pip install -r requirements.txt && cp ../.env.example .env   # fill values
uvicorn server:app --reload --port 8001
cd frontend && yarn install && REACT_APP_BACKEND_URL=http://localhost:8001 yarn start
```
- **FFmpeg:** bundled with the `imageio-ffmpeg` wheel (static 7.x build).
- **Gujarati font:** `backend/fonts/NotoSansGujarati.ttf` (OFL licence).
- **Database setup:** indexes and constraints are created on every startup and are safe to re-run.

## Tests
`cd backend && python -m pytest tests -q -n0`. Tests use the `anchorai_test` database with the worker turned off.

**Every provider response in the automated tests is MOCKED.** Passing tests do not prove live generation.

The tests cover:
- Accounts: registration and workspace creation, unverified email blocked from generating.
- Scripts: Gujarati validation and the length limit.
- Portraits: valid upload, plus rejection of malformed, oversized and too-small images.
- Generation checks: missing consent, insufficient credits, missing provider credentials, and the same idempotency key returning the same job.
- Credits: cancelling a job releases all reserved credits. A successful job charges once, and a repeated charge does nothing. A provider timeout releases all credits.
- Access control: other workspaces get 404, forged download links are rejected, and deleted portraits can't be accessed.
- Payments: the Razorpay webhook signature is checked and duplicate deliveries are ignored.
- Rendering: subtitle timing, SRT and VTT export, a valid MP4 render, and FFmpeg failure handling.

Manual live acceptance test (spends real provider credit): `tests/manual/live_e2e.sh`.

## Provider setup and Gujarati check
- Set `EMERGENT_LLM_KEY`. Usage is charged to the Universal Key balance.
- Gujarati was tested live. `fal-ai/elevenlabs/tts/eleven-v3` with `language_code="gu"` returned correct Gujarati speech and per-character timestamps (about 13 characters per second).
- Voices: Sarah, Laura, George and Brian.
- The Admin page shows whether the provider, storage, FFmpeg, font, payments and email are working. It gives a clear setup error for anything that isn't.

## Payments (Razorpay)
Set `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET`. In the Razorpay dashboard, add a
webhook to `https://<APP_URL>/api/v1/webhooks/payments/razorpay` for `payment.captured`, `order.paid` and
`payment.failed`.

Credits are added only after one of these checks passes:
- a webhook with a valid HMAC signature, or
- a valid checkout signature, plus a server-side `GET /payments/{id}` showing the payment as `captured`.

Each order can add credits only once (ledger key `payment:{order_id}`). Until the keys are set, the buy
buttons are turned off and a notice explains why.

## Credit policy
- 1 credit = 1 second of finished narration, minimum 10 per video.
- At submit, the estimate × 1.15 is reserved in a single atomic database update.
- On completion, the reservation is released and the actual seconds are charged.
- On any failure or cancellation, the full reservation is released.
- Every ledger entry has a unique key (`job:{id}:a{attempt}:{reserve|release|capture}`), so retries and repeated events can't charge twice.
- The Admin reconcile check compares each workspace balance with the sum of its ledger entries.

## Estimated provider costs (fal.ai list prices)
- Narration: US$0.10 per 1,000 characters
- Talking anchor: US$0.0562 per second
- Total: about US$0.06–0.07 per second of video

## Deployment, backup and restore
- **Deploy:** put the backend (port 8001) and frontend behind HTTPS. Set `APP_URL` and `CORS_ORIGINS` to the public address. `docker-compose.yml` and Dockerfiles are included for self-hosting.
- **Back up:** `mongodump --uri "$MONGO_URL" --db "$DB_NAME" --out backup/$(date +%F)`
- **Restore:** `mongorestore --uri "$MONGO_URL" --db "$DB_NAME" backup/<date>/<db>`, then run Admin → reconcile.

## Retention
Deleting a portrait, video or account takes effect immediately: signed links stop working and the files are
marked `pending_purge`. The storage API has no delete call, so removing the files from storage has to be done
separately. Revoking consent blocks future use and fails any queued jobs. Copies that were already
downloaded can't be recalled.

## Troubleshooting
| Error | Meaning and fix |
|---|---|
| `provider_balance` | The Universal Key balance is empty. Top it up, then retry the job. |
| `provider_rejected` | The provider refused the portrait. Use a clear, front-facing photo. |
| `render_failed` | Rendering failed. Check the `anchorai.worker` backend logs. |

## Known limitations
- Subtitles are timed per phrase from character timestamps, not word by word.
- Narration is limited to 60 seconds per video, and speaking speed can't be adjusted.
- The anchor is generated at the provider's resolution (about 784×1168) and then placed on the 1080p frame.
- Each workspace has a single owner.
- No C2PA content credentials yet.

**Self-hosting on GitHub / cPanel / VPS: see `DEPLOYMENT.md`.**

API reference: `docs/API.md` and OpenAPI at `/api/docs`.
