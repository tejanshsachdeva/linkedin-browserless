# linkedin-browserless

Browser-free LinkedIn profile API. Send a profile URL, get structured JSON — no Playwright or Chromium.

> **Disclaimer:** Scraping LinkedIn violates their [User Agreement](https://www.linkedin.com/legal/user-agreement). For personal learning only. Use a secondary account.

**Repo:** [github.com/tejanshsachdeva/linkedin-browserless](https://github.com/tejanshsachdeva/linkedin-browserless)

## Setup

```bash
git clone https://github.com/tejanshsachdeva/linkedin-browserless.git
cd linkedin-browserless
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env
```

Set `LINKEDIN_LI_AT` in `.env` (from DevTools → Application → Cookies → `li_at`), or run:

```bash
python scripts/capture_session.py
```

## Run

```bash
uvicorn app.main:app --reload
```

Docs: http://127.0.0.1:8000/docs

## API

```bash
curl -X POST http://127.0.0.1:8000/api/v1/profile \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.linkedin.com/in/<vanity>"}'
```

Add `?refresh=true` to bypass cache.

Returns top-card fields (name, headline, location, images) plus experience, education, skills, about, certifications, and languages via Voyager REST.

Optional: set `API_KEY` in `.env` and send `X-API-Key` header.

## Test

```bash
pytest
```

## Config

See [`.env.example`](.env.example).
