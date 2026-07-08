# Deploying BrandGen on Vercel

Vercel now supports Django with **zero-config** (detects `manage.py` + `WSGI_APPLICATION`). This repo includes `vercel.json` and production settings, but **this PoC has important limits** on serverless.

## Quick answer: what to prepare

| Step | Required? | Notes |
|---|---|---|
| Push repo to GitHub | Yes | Vercel deploys from git |
| Set env vars in Vercel dashboard | Yes | See below |
| **Postgres database** | **Yes** | SQLite does not persist on Vercel |
| `collectstatic` + `migrate` on build | Yes | Configured in `vercel.json` `buildCommand` |
| Pro plan (recommended) | Strongly recommended | 300s function timeout; Hobby max is 10–60s |
| External media storage (S3 / Vercel Blob) | Recommended | `/tmp` media is ephemeral |
| No bundler (webpack/vite) | — | Django templates + static CSS only |

There is **no JS bundling step**. Python deps come from `requirements.txt`.

## Deploy steps

1. **Create a Postgres database** (Vercel Postgres, Neon, or Supabase) and copy `DATABASE_URL`.

2. **Connect repo** at [vercel.com/new](https://vercel.com/new) — root directory: `ivan_demo` if the repo root is the parent folder.

3. **Environment variables** (Vercel → Project → Settings → Environment Variables):

   | Variable | Value |
   |---|---|
   | `VERCEL` | `1` |
   | `DJANGO_SECRET_KEY` | Random string (`python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`) |
   | `DJANGO_DEBUG` | `False` |
   | `OPENAI_API_KEY` | Your server demo key |
   | `DATABASE_URL` | Postgres connection string |
   | `CSRF_TRUSTED_ORIGINS` | `https://your-project.vercel.app` |
   | `ANALYTICS_DASHBOARD_TOKEN` | Random secret for `/usage/?token=…` |
   | `DEMO_MAX_SLIDES` | `1` |

   Vercel sets `VERCEL=1` automatically in many cases; setting it explicitly is fine.

4. **Deploy**
   ```bash
   npm i -g vercel
   cd ivan_demo
   vercel --prod
   ```

5. **Usage dashboard** after deploy:
   ```
   https://your-project.vercel.app/usage/?token=YOUR_ANALYTICS_DASHBOARD_TOKEN
   ```

## What we already configured in this repo

- `vercel.json` — build runs `collectstatic` + `migrate`, WSGI `maxDuration: 300`
- `config/settings.py` — Postgres via `DATABASE_URL`, WhiteNoise static files, Vercel host/CSRF handling
- `brandgen/services/jobs.py` — on Vercel, jobs run **inline** (no background threads)
- `.vercelignore` — excludes `.venv`, `media/`, `.env`

## Important limitations on Vercel

### 1. Background threads don't work
Serverless functions freeze after the response. Local dev uses threads; **Vercel runs crawl/generate synchronously** before redirecting to the progress page. A full crawl + 5-slide carousel may **hit the function timeout**.

**Mitigation:** Demo mode (1 image), Pro plan 300s timeout, or move long jobs to Railway/Render + Inngest.

### 2. SQLite won't work in production
The filesystem is read-only/ephemeral. **You must set `DATABASE_URL`** to Postgres.

### 3. Uploaded/generated media is ephemeral
Images save to `/tmp` on Vercel and disappear between invocations/deploys. For a public demo, add **S3**, **Cloudflare R2**, or **Vercel Blob** storage later.

### 4. System dependencies
- **cairosvg** (SVG → PNG) may fail if Cairo isn't on the runtime — logo conversion might degrade.
- **pytesseract** / Tesseract OCR likely **won't be available** — OCR overlay logic falls back gracefully.

### 5. Cold starts
First request after idle can be slow (Django + heavy deps).

## Better alternatives for this app

If you need reliable long-running image pipelines, background jobs, and persistent media **without major refactors**, consider:

- **[Railway](https://railway.app)** — long-running Django + Postgres + volumes
- **[Render](https://render.com)** — web service + managed Postgres
- **[Fly.io](https://fly.io)** — Docker, persistent volumes

Vercel fits best if you treat this as a **demo with 1-image runs** and accept ephemeral media.

## Local production smoke test

Before deploying, simulate production settings:

```bash
export DATABASE_URL=postgres://...
export VERCEL=1
export DJANGO_DEBUG=False
python manage.py collectstatic --noinput
python manage.py migrate
python manage.py runserver
```

## Optional: custom domain

Add your domain in Vercel, then set:

```
CSRF_TRUSTED_ORIGINS=https://yourdomain.com
DJANGO_ALLOWED_HOSTS=yourdomain.com,.vercel.app
```
