# Deploying BrandGen on Render

Render runs Django as a **long-lived web service** — background threads, Postgres, and a persistent disk for uploads work out of the box. There is **no JS bundling step**; Python deps come from `requirements.txt`.

## What to prepare

| Step | Required? | Notes |
|---|---|---|
| Push repo to GitHub / GitLab | Yes | Render deploys from git |
| Set `OPENAI_API_KEY` in Render | Yes | Server demo key |
| Postgres | Yes | Created automatically by `render.yaml` |
| `collectstatic` + `migrate` on build | Yes | `build.sh` |
| Persistent disk for media | Recommended | 1 GB mount in `render.yaml` |
| Apt packages (Tesseract, Cairo) | Optional | `Aptfile` for OCR + SVG logos |

## Option A — Blueprint (recommended)

1. Push this repo and open [Render Dashboard → New → Blueprint](https://dashboard.render.com/blueprints).
2. Connect the repository.
3. If the repo root is the **parent** of this app, set **Root Directory** to `ivan_demo`.
4. Render reads `render.yaml` and creates:
   - **Postgres** (`brandgen-db`)
   - **Web service** (`brandgen`) with a 1 GB disk at `/var/data/media`
5. When prompted, set **`OPENAI_API_KEY`** (marked `sync: false` in the blueprint).
6. Deploy. After the first successful build, open:
   ```
   https://<your-service>.onrender.com/usage/?token=<ANALYTICS_DASHBOARD_TOKEN>
   ```
   Copy `ANALYTICS_DASHBOARD_TOKEN` from the service’s Environment tab (auto-generated).

## Option B — Manual web service

1. **New → PostgreSQL** — copy the internal `DATABASE_URL`.
2. **New → Web Service** — connect repo, runtime **Python 3**.
3. Settings:

   | Field | Value |
   |---|---|
   | Root Directory | `ivan_demo` (if needed) |
   | Build Command | `./build.sh` |
   | Start Command | `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --worker-class gthread --workers 1 --threads 4 --timeout 300 --access-logfile - --error-logfile - --log-level info` |

4. **Environment variables**:

   | Variable | Value |
   |---|---|
   | `DJANGO_SECRET_KEY` | Random string |
   | `DJANGO_DEBUG` | `False` |
   | `OPENAI_API_KEY` | Your server key |
   | `DATABASE_URL` | From Render Postgres |
   | `ANALYTICS_DASHBOARD_TOKEN` | Random secret |
   | `DEMO_MAX_SLIDES` | `1` |
   | `MEDIA_ROOT` | `/var/data/media` |
   | `LOG_LEVEL` | `INFO` (use `DEBUG` temporarily when troubleshooting) |

5. **Disks** → Add disk, mount path `/var/data/media`, 1 GB (for logos and generated images).

6. Deploy.

## Logs and debugging

**Important:** The Postgres service logs (connection received / disconnection) are **not your app logs**. They only show database health checks every few seconds — that is normal.

Application logs live on the **Web Service**:

1. Render Dashboard → **BrandGen** (web service, not Postgres)
2. **Logs** tab
3. Filter for lines like:
   - `INFO brandgen.startup` — app boot, media path, DB engine
   - `INFO brandgen.request` — every HTTP request
   - `INFO brandgen.services.jobs` — job start / complete / failure
   - `INFO brandgen.services.progress` — each pipeline step
   - `ERROR` — failures with full stack traces

Set `LOG_LEVEL=DEBUG` in Environment Variables for more detail, then redeploy.

When a job appears stuck, look for:

| Log pattern | Meaning |
|---|---|
| `Queueing background thread` then `Job … step begin: crawl` | Job started OK |
| Last step is `design_system` or `slide_0` with no follow-up | Likely OpenAI timeout or API key issue |
| `Cannot create media root` | Disk not mounted — add `/var/data/media` disk |
| No job logs at all after crawl submit | Thread never started — check web service logs, not Postgres |

Also check **Admin → Pipeline jobs** for `error_message` on failed jobs.

## Already configured in this repo

- `render.yaml` — Postgres + web service + disk + env defaults
- `build.sh` — install deps, `collectstatic`, `migrate`
- `Aptfile` — Tesseract (OCR) and Cairo (SVG → PNG)
- `config/settings.py` — Postgres via `DATABASE_URL`, WhiteNoise, Render host/CSRF, disk media path
- `requirements.txt` — includes `gunicorn`, `whitenoise`, `psycopg2-binary`

## Custom domain

After adding a domain in Render, set:

```
CSRF_TRUSTED_ORIGINS=https://yourdomain.com
DJANGO_ALLOWED_HOSTS=yourdomain.com
```

Render also sets `RENDER_EXTERNAL_URL` and `RENDER_EXTERNAL_HOSTNAME` automatically; those are appended in settings if not already listed.

## Local production smoke test

```bash
export DATABASE_URL=postgres://...
export DJANGO_DEBUG=False
export MEDIA_ROOT=/tmp/brandgen-media
mkdir -p "$MEDIA_ROOT"
python manage.py collectstatic --noinput
python manage.py migrate
gunicorn config.wsgi:application --bind 127.0.0.1:8000 --timeout 300
```

## Render free tier notes

- Web services **spin down after ~15 minutes** of idle traffic; first request after sleep can take 30–60s.
- Free Postgres expires after 90 days (upgrade or export data before then).
- Long image-generation runs are supported via Gunicorn’s **300s timeout** (unlike Vercel serverless limits).

## Usage dashboard

```
https://<your-service>.onrender.com/usage/?token=YOUR_ANALYTICS_DASHBOARD_TOKEN
```

Events are also visible in Django admin (`/admin/`) after creating a superuser:

```bash
python manage.py createsuperuser
```

Run via Render Shell or locally against the production `DATABASE_URL`.
