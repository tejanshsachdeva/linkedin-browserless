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

Add `?refresh=true` to bypass cache. When `API_KEY` is set, send header `X-API-Key: <your-key>` on every profile request (`/docs` is disabled).

```bash
curl -X POST http://127.0.0.1:8000/api/v1/profile \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret-key" \
  -d '{"url": "https://www.linkedin.com/in/<vanity>"}'
```

| Endpoint | Description |
|----------|-------------|
| `POST /api/v1/profile` | Fetch profile JSON from a LinkedIn URL |
| `GET /api/v1/profile?url=...` | Same, via query param |
| `GET /health` | Liveness check |
| `GET /health/session` | LinkedIn session status (no secrets returned) |

### Example response

Sample output from `POST /api/v1/profile` (redacted fixture data; live fields vary by profile):

<details>
<summary>JSON</summary>

```json
{
  "source_url": "https://www.linkedin.com/in/jordan-rivera",
  "profile_id": "ACoAAREDAC0000000001",
  "name": "Jordan Rivera",
  "headline": "Senior Software Engineer at Acme Corp",
  "location": "San Francisco, California, United States",
  "about": "Builder of data products at & scale.",
  "images": {
    "profile_picture": {
      "primary": "https://media.licdn.com/dms/image/v2/photo800/800_800/0/redacted-profile",
      "renditions": {
        "100": "https://media.licdn.com/dms/image/v2/photo100/100_100/0/redacted-profile",
        "800": "https://media.licdn.com/dms/image/v2/photo800/800_800/0/redacted-profile"
      }
    },
    "background_image": null
  },
  "experience": [
    {
      "title": "Senior Software Engineer",
      "company": "Acme Corp",
      "company_url": "https://www.linkedin.com/company/acme-corp/",
      "start_date": "Jul 2025",
      "end_date": null,
      "duration": "1 yr 1 mo"
    },
    {
      "title": "Software Developer",
      "company": "Legacy Industries",
      "start_date": "Jan 2023",
      "end_date": "Jun 2025",
      "duration": "2 yrs 6 mos"
    }
  ],
  "education": [
    {
      "school": "Example University",
      "degree": "B.S.",
      "field_of_study": "Computer Science"
    }
  ],
  "skills": ["Python"],
  "certifications": [
    {
      "name": "Cloud Practitioner",
      "issuing_organization": "Example Academy",
      "issue_date": "Dec 2023",
      "credential_id": "ABC123"
    }
  ],
  "languages": [
    {
      "name": "English",
      "proficiency": "Native or bilingual"
    }
  ],
  "partial": false,
  "section_status": {
    "about": "ok",
    "experience": "ok",
    "education": "ok",
    "skills": "ok",
    "certifications": "ok",
    "languages": "ok"
  },
  "scraped_at": "2026-08-29T08:00:00Z"
}
```

</details>

The response also includes `field_sources`, `data_tiers`, and `section_status` so callers can see which LinkedIn tier supplied each field.

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
