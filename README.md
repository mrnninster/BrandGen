# BrandGen — Django proof of concept

Crawl any business website, extract a brand kit (colors, fonts, logo, screenshot),
synthesize a per-site design system with GPT, then generate branded social images
with OpenAI (`gpt-image-1` / `dall-e-3` fallback) and programmatic logo overlays.

## Setup

```bash
cd ivan_demo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then set OPENAI_API_KEY
python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000/

## `.env` keys

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Required for design system + image generation |
| `OPENAI_IMAGE_MODEL` | Default `gpt-image-1` |
| `OPENAI_TEXT_MODEL` | Default `gpt-4o-mini` |
| `DEMO_MAX_SLIDES` | Max images per run when using the server key (default `1`) |
| `DJANGO_SECRET_KEY` | Django secret |
| `DJANGO_DEBUG` | `True` / `False` |

## Public demo billing (no login)

Visitors can paste their own OpenAI API key in the header bar. It is stored **only in the Django session** for that browser tab and is cleared when the browser closes (`SESSION_EXPIRE_AT_BROWSER_CLOSE`).

| Mode | Who pays | Limits |
|---|---|---|
| **Your key** | The visitor | Unlimited generations this session (up to 8 slides per carousel) |
| **Demo mode** | Your server `.env` key | **1 image per generation run**; GPT vision labeling disabled |

Keys are passed to background jobs only for the duration of that job and are never returned in API responses.

## PoC flow

1. Enter a website URL on the home page.
2. The crawler pulls homepage + a few internal pages (text, images, CSS).
3. Brand kit is saved: ranked hex colors, fonts, logo candidates, mShots screenshot.
4. GPT synthesizes a unique design system (color roles, motifs, imagery style).
5. Generate a single / carousel / quote post — OpenAI paints the scene; Pillow overlays the real logo + headline (logo is never AI-drawn).
6. Review UI shows a platform-style preview with approve / skip / regenerate / plain-language refine.

## System dependency

OCR text-quality checks need the Tesseract binary:

```bash
# Debian / Ubuntu / WSL
sudo apt-get install -y tesseract-ocr
```

## Out of scope for this demo

- Inngest / daily cron autopilot
- Ayrshare publishing
- Gemini Nano Banana Pro (proposal stack); this PoC uses OpenAI images as requested
- Full satori/resvg typography (Pillow overlay stands in)
