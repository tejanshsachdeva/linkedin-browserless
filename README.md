# linkedin-browserless

Browser-free LinkedIn profile API. Send a profile URL, get structured JSON — no Playwright or Chromium.

> Scraping LinkedIn violates their [User Agreement](https://www.linkedin.com/legal/user-agreement). For personal learning only. Use a secondary account.

## Quick start

```bash
git clone https://github.com/tejanshsachdeva/linkedin-browserless.git
cd linkedin-browserless
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env
```

Set `LINKEDIN_LI_AT` (and optionally `LINKEDIN_JSESSIONID`) in `.env`, or run:

```bash
python scripts/capture_session.py
```

```bash
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs

## API

```bash
curl -X POST http://127.0.0.1:8000/api/v1/profile \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.linkedin.com/in/<vanity>"}'
```

Add `?refresh=true` to bypass cache. Set `API_KEY` in `.env` to require an `X-API-Key` header.

| Endpoint | Description |
|----------|-------------|
| `POST /api/v1/profile` | Fetch profile JSON from a LinkedIn URL |
| `GET /api/v1/profile?url=...` | Same, via query param |
| `GET /health` | Liveness check |
| `GET /health/session` | LinkedIn session status (no secrets returned) |

## How it works

LinkedIn loads profiles in two tiers:

1. **HTML** — top card (name, headline, location, images) from server-rendered `/in/{vanity}`
2. **Voyager REST** — experience, education, skills, about, certifications, languages via internal API

This project replays those HTTP calls with an authenticated session (`li_at` + `JSESSIONID`). Parsers extract structured data; `section_status` and `field_sources` report what succeeded.

## Docker

```bash
docker build -t linkedin-browserless .
docker run -p 8000:8000 \
  -e LINKEDIN_LI_AT="..." \
  -e LINKEDIN_JSESSIONID="..." \
  -e API_KEY="..." \
  linkedin-browserless
```

## Test

```bash
pytest
```

## Config

See [`.env.example`](.env.example). Never commit `.env`, `.env.session`, or `session_state.json`.

## Limitations

- LinkedIn sessions expire — refresh cookies when requests fail with 401
- Connection degree is often unavailable depending on viewer relationship
- Job descriptions require a separate fetch not yet implemented
- Voyager may return a subset of skills vs what appears in the About section
- Rate limiting (HTTP 999) can block requests; keep concurrency low
