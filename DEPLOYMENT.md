# Deploying AnchorAI News outside Emergent (GitHub · cPanel · VPS)

The app has two parts and needs three external services:

| Part / service | What to use when self-hosting |
|---|---|
| Frontend (React) | A static build (`frontend/build`) on any web host, including cPanel `public_html` |
| Backend (FastAPI) | cPanel "Setup Python App" (Passenger), Docker, or uvicorn on a VPS |
| Database | **MongoDB Atlas** (free tier works) — cPanel hosts don't include MongoDB |
| AI generation | Your own **fal.ai key** (`FAL_KEY`) — paid per use at fal.ai |
| Email | Your cPanel mailbox over **SMTP** |
| File storage | `STORAGE_BACKEND=local` (private folder on your server, never public) |
| Payments | Razorpay keys |

> The Emergent Universal Key (`EMERGENT_LLM_KEY`), Emergent email key and Emergent storage are tied to the
> Emergent platform. When you host elsewhere, use `FAL_KEY`, SMTP and local storage instead.

## 1. Push to GitHub
Use the platform's "Save to GitHub" button, or `git push` the `/app` folder. `.gitignore` already keeps `.env`
files, uploads (`backend/data/`) and builds out of the repository. The CI workflow
(`.github/workflows/ci.yml`) runs the backend tests (with mocked providers) and builds the frontend on every push.

## 2. Create the external accounts
1. **MongoDB Atlas** → create a free cluster → Database Access: add a user → Network Access: allow your server IP
   → copy the `mongodb+srv://...` connection string into `MONGO_URL`.
2. **fal.ai** → dashboard → API keys → create a key → `FAL_KEY`. Add billing credit there.
3. **Razorpay** → Settings → API keys → `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`. Webhooks → add
   `https://api.your-domain.com/api/v1/webhooks/payments/razorpay` for `payment.captured`, `order.paid` and
   `payment.failed`, then set the secret you chose as `RAZORPAY_WEBHOOK_SECRET`.
4. **Email (cPanel)** → Email Accounts → create `news@your-domain.com` → Connect Devices shows the SMTP host and port.

## 3. Backend `.env` (self-hosted)
Copy `.env.example` to `backend/.env` and set at least:
```
MONGO_URL="mongodb+srv://USER:PASS@cluster.xxxx.mongodb.net"
DB_NAME="anchorai"
APP_URL="https://your-domain.com"            # the frontend address (used in email links)
API_PUBLIC_URL="https://api.your-domain.com" # the backend address (used for secure file links)
CORS_ORIGINS="https://your-domain.com"
JWT_SECRET="<64 random hex characters>"
ADMIN_EMAIL="you@your-domain.com"
ADMIN_PASSWORD="<strong password>"
AI_PROVIDER_MODE="fal_direct"
FAL_KEY="<your fal.ai key>"
STORAGE_BACKEND="local"
EMAIL_BACKEND="smtp"
SMTP_HOST="mail.your-domain.com"
SMTP_PORT="465"
SMTP_SECURITY="ssl"
SMTP_USER="news@your-domain.com"
SMTP_PASSWORD="<mailbox password>"
SMTP_FROM="news@your-domain.com"
EMAIL_FROM_NAME="AnchorAI News"
RAZORPAY_KEY_ID=... RAZORPAY_KEY_SECRET=... RAZORPAY_WEBHOOK_SECRET=...
```
Generate the JWT secret with `python -c "import secrets;print(secrets.token_hex(32))"`.

## 4a. cPanel deployment
**Backend: `api.your-domain.com`**
1. Domains → create the subdomain `api.your-domain.com`. Turn on SSL with AutoSSL.
2. Upload the `backend/` folder, for example to `/home/USER/anchorai/backend`.
3. Setup Python App → Create:
   - Python version: 3.11 (3.10 or newer)
   - Application root: `anchorai/backend`
   - Application URL: `api.your-domain.com`, at the root. Don't use a sub-path such as `/api`, because the API routes already start with `/api`.
   - Startup file: `passenger_wsgi.py`
   - Entry point: `application`
4. In the app's terminal (or "Enter to the virtual environment"), run:
   `pip install -r requirements-deploy.txt`
5. Put `.env` in `anchorai/backend/`, then click **Restart**. When the app starts, it creates the database indexes and the admin account.
6. Check it: open `https://api.your-domain.com/api/health`. It should return `{"ok":true,...}`.
7. **Video worker (required).** Passenger can't run long background tasks, so add a cron job in cPanel → Cron Jobs that runs every minute:
   ```
   * * * * * cd /home/USER/anchorai/backend && /home/USER/virtualenv/anchorai/backend/3.11/bin/python run_worker.py --once >> worker.log 2>&1
   ```
   Copy the exact virtualenv path from the Python App page. A file lock stops two workers from running at once. Each run finishes every queued job and then exits.

**Frontend: `your-domain.com`**
1. On your computer, or from the CI "frontend-build" artifact, build it:
   `cd frontend && yarn install && REACT_APP_BACKEND_URL=https://api.your-domain.com yarn build`
2. Upload the contents of `frontend/build/` into `public_html/`. That includes `.htaccess`, which makes deep links such as `/app/jobs` work.

**Host requirements**
- Linux x86_64 with Python 3.10 or newer.
- About 1 GB of RAM while a video renders.
- About 500 MB of free disk space.
- Outbound HTTPS to `queue.fal.run`, `*.fal.media`, `api.razorpay.com` and your MongoDB Atlas host.

FFmpeg comes bundled with the `imageio-ffmpeg` package, so you don't need to install it on the server. Some shared hosts kill CPU-heavy processes. If renders fail with `render_failed`/timeout, use a VPS (section 4b).

## 4b. VPS or Docker (from GitHub)
```
git clone <your repo> anchorai && cd anchorai
cp .env.example backend/.env   # fill as in step 3 (MONGO_URL can stay mongodb://mongo:27017 with compose)
REACT_APP_BACKEND_URL=https://api.your-domain.com docker compose up -d --build
```
Put Nginx or Caddy in front of it with HTTPS:
- `api.your-domain.com` → port 8001
- `your-domain.com` → port 3000

Under Docker or uvicorn the worker runs inside the backend (`RUN_WORKER=1`). If you run more than one backend replica, set `RUN_WORKER=0` on them and run `python run_worker.py` as a separate service.

## 5. After deployment: checklist
1. Sign in with `ADMIN_EMAIL`, open **Admin**, and confirm every health light is green. The page lists anything that's missing.
2. Sign up with a test user and click the verification email. This confirms SMTP works, and the user gets 30 trial credits.
3. Upload a portrait, make a short Gujarati video, and watch it move through the Jobs page. This confirms fal.ai, the cron worker and FFmpeg.
4. Buy the Starter pack with a Razorpay test card. Credits are added after the webhook or server check.
5. Use **Admin → Give credits** to top up a user. Admin workspaces always have unlimited credits.

## Backups
- **Database:** run `mongodump --uri "$MONGO_URL" --db anchorai --out backups/$(date +%F)` daily, or turn on Atlas backups.
- **Files:** back up `backend/data/storage/` (portraits, audio and videos) along with the database.
