# AnchorAI News API (v1)
All endpoints are under `/api/v1`, JSON, `Authorization: Bearer <session token>` unless marked public.
Every resource is scoped to the caller's current workspace; foreign IDs return 404.

| Method | Path | Notes |
|---|---|---|
| POST | /auth/register | public; creates user + workspace, sends verification email |
| POST | /auth/login · /auth/logout · /auth/logout-all | brute-force lockout (5 fails / 15 min) |
| GET | /auth/me | |
| POST | /auth/verify-email · /auth/resend-verification | trial credits granted on verify |
| POST | /auth/forgot-password · /auth/reset-password | 1-hour single-use token; revokes sessions |
| POST/GET | /workspaces · /workspaces/current · /workspaces/{id}/switch | |
| GET | /account · POST /account/delete · POST /account/data-deletion | |
| GET | /consent/text | current consent version + bases |
| POST | /anchors/upload-url | upload instructions (no presigned uploads on this storage) |
| POST | /anchors | multipart: file, display_name, description, authorized_by, consent_basis, consent_confirmed, consent_version |
| GET | /anchors · /anchors/{id} | signed image URLs |
| DELETE | /anchors/{id} · POST /anchors/{id}/revoke-consent | |
| CRUD | /channels · POST /channels/{id}/logo | brand presets |
| GET | /voices · /voices/{voice}/preview | real Gujarati preview audio (cached) |
| POST | /scripts/analyze | counts, estimate, validation |
| POST/GET/PATCH/DELETE | /projects · /projects/{id} | |
| POST | /projects/{id}/generate | header `Idempotency-Key` (16–64 chars); body `{consent_confirmed:true}`; 402 if credits short; 503 if provider unconfigured |
| GET | /jobs · /jobs/{id} | |
| POST | /jobs/{id}/cancel · /jobs/{id}/retry | retry reuses finished narration/anchor stages |
| GET | /videos · /projects/{id}/videos | |
| POST | /videos/{id}/download-url | `?inline=true` for preview (30 min) else attachment (5 min) |
| GET | /videos/{id}/subtitles.srt · .vtt | |
| DELETE | /videos/{id} | |
| POST | /compose/preview-frame | JPEG static composition from the real renderer |
| GET | /dashboard | |
| GET | /billing/balance · /billing/ledger · /billing/payments · /billing/packs | |
| POST | /billing/checkout · /billing/verify | Razorpay order + server verification |
| POST | /webhooks/payments/razorpay | public; HMAC `X-Razorpay-Signature`; dedup by event id |
| POST | /webhooks/avatar/{provider} | rejects (status is polled) |
| GET | /files/signed?t= | public; short-lived signed token; Range supported |
| GET/POST | /admin/health · /admin/workspaces · /admin/credits/adjust · /admin/audit · /admin/reconcile | admin only |
