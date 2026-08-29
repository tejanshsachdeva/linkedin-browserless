# linkedin-browserless

Browser-free LinkedIn profile API. Send a profile URL, get structured JSON — no Playwright or Chromium.

**Live API:** Deploy via [Render](#deploy-public-https) (see below) — HTTPS is automatic on Render.

**Repository:** [github.com/tejanshsachdeva/linkedin-browserless](https://github.com/tejanshsachdeva/linkedin-browserless)

> **Disclaimer:** Scraping LinkedIn violates their [User Agreement](https://www.linkedin.com/legal/user-agreement). For personal learning and assignment use only. Use a secondary LinkedIn account for backend credentials.

---

## Approach

LinkedIn’s web app is a two-tier system — not a single HTML page with all data embedded.

1. **Tier A (HTML)** — `GET /in/{vanity}` returns server-rendered HTML with the top card: name, headline, location, connection count, profile/background images.
2. **Tier B (Voyager REST)** — The browser then calls LinkedIn’s internal Voyager API (`/voyager/api/identity/dash/profiles`) with a versioned `FullProfileWithEntities-N` decoration to fetch structured experience, education, skills, about, certifications, and languages.

This project **replays those same HTTP calls** with an authenticated session (`li_at` + `JSESSIONID` cookies). No browser, no Playwright — just `httpx` + parsers.

**Design choices:**

- **FastAPI** exposes a single `POST /api/v1/profile` endpoint accepting a LinkedIn URL.
- **Decoration auto-discovery** regexes the HTML for `FullProfileWithEntities-N` and falls back through known IDs when LinkedIn bumps versions.
- **Honest responses** — `section_status`, `field_sources`, and `partial` tell callers exactly what succeeded vs failed vs absent.
- **Session credentials** live only in environment variables on the server — never in the repo.

---

## Setup (local)

```bash
git clone https://github.com/tejanshsachdeva/linkedin-browserless.git
cd linkedin-browserless
python -m venv .venv
.venv\Scripts\activate        # Windows — use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
copy .env.example .env        # use `cp` on Unix
```

Set credentials in `.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `LINKEDIN_LI_AT` | Yes | `li_at` cookie from DevTools → Application → Cookies |
| `LINKEDIN_JSESSIONID` | Recommended | `JSESSIONID` cookie (must match same browser session as `li_at`) |
| `API_KEY` | Optional locally | If set, clients must send `X-API-Key` header |

Or run the interactive helper:

```bash
python scripts/capture_session.py
```

### Run locally

```bash
uvicorn app.main:app --reload
```

- Swagger UI: http://127.0.0.1:8000/docs  
- Session health: `GET /health/session`

---

## Deploy (public HTTPS)

### Option A — Render (recommended)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/tejanshsachdeva/linkedin-browserless)

1. Click **Deploy to Render** (or connect the GitHub repo manually).
2. In the Render dashboard → **Environment**, set:
   - `LINKEDIN_LI_AT` — your `li_at` cookie value
   - `LINKEDIN_JSESSIONID` — your `JSESSIONID` cookie value
3. Render auto-generates `API_KEY` (from `render.yaml`) — copy it for API calls.
4. After deploy, your service URL is `https://<service-name>.onrender.com` (HTTPS by default).

`render.yaml` and `Dockerfile` are included in the repo.

### Option B — Docker

```bash
docker build -t linkedin-browserless .
docker run -p 8000:8000 \
  -e LINKEDIN_LI_AT="your-li-at" \
  -e LINKEDIN_JSESSIONID="your-jsessionid" \
  -e API_KEY="your-api-key" \
  linkedin-browserless
```

Put a reverse proxy (nginx, Caddy, Traefik) in front for production HTTPS on your own VPS.

---

## API documentation

### `POST /api/v1/profile`

Fetch a LinkedIn profile by URL.

**Request**

```bash
curl -X POST "https://YOUR-SERVICE.onrender.com/api/v1/profile" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{"url": "https://www.linkedin.com/in/<vanity>"}'
```

| Parameter | Location | Description |
|-----------|----------|-------------|
| `url` | JSON body | Full LinkedIn profile URL (`/in/{vanity}`) |
| `refresh` | Query (`?refresh=true`) | Bypass cache and re-scrape |
| `X-API-Key` | Header | Required when `API_KEY` is set on the server |

**Response fields**

| Field | Source | Description |
|-------|--------|-------------|
| `name`, `headline`, `location` | HTML | Top-card identity |
| `about`, `experience`, `education`, `skills` | Voyager | Detail sections |
| `certifications`, `languages` | Voyager | When present on profile |
| `images` | HTML | Profile picture + background (multiple renditions) |
| `section_status` | — | Per-section: `ok`, `not_present`, `fetch_failed` |
| `field_sources` | — | Which tier produced each field (`html` vs `voyager`) |
| `partial` | — | `true` only if a section **fetch failed** |

### Other endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/profile?url=...` | Same as POST, for quick testing |
| `GET` | `/health` | Liveness check |
| `GET` | `/health/session` | LinkedIn cookie validity (no secrets exposed) |
| `GET` | `/docs` | Interactive OpenAPI (Swagger) |

### Sample response

```json
{
  "source_url": "https://www.linkedin.com/in/jordan-rivera",
  "name": "Jordan Rivera",
  "headline": "Senior Software Engineer at Acme Corp",
  "location": "San Francisco, California, United States",
  "current_company": "Acme Corp",
  "about": "Builder of data products at scale.",
  "experience": [{
    "title": "Senior Software Engineer",
    "company": "Acme Corp",
    "company_url": "https://www.linkedin.com/company/acme-corp/",
    "employment_type": "Full-time",
    "duration": "1 yr 8 mos"
  }],
  "education": [{ "school": "Example University", "degree": "B.S." }],
  "skills": ["Python", "FastAPI"],
  "certifications": [],
  "languages": [],
  "images": { "profile_picture": { "primary": "https://..." } },
  "partial": false,
  "section_status": { "about": "ok", "experience": "ok", "skills": "ok" },
  "field_sources": { "name": "html", "experience": "voyager" }
}
```

---

## Architecture

```
POST /api/v1/profile
        │
        ▼
  ProfileService ──cache──▶ memory / Redis
        │
        ├─ Tier A: GET /in/{vanity} ──▶ html_parser (name, headline, images, …)
        │                          └──▶ rehydration_parser (decoration ID)
        │
        └─ Tier B: GET /voyager/api/identity/dash/profiles ──▶ voyager_parser
        │
        ▼
  profile_assembler ──▶ ProfileResponse JSON
```

---

## Test

```bash
pytest
```

Golden fixtures in `tests/fixtures/` hold redacted HTML and Voyager JSON for regression tests.

---

## Configuration

See [`.env.example`](.env.example). **Never commit `.env`, `.env.session`, or `session_state.json`.**

---

## Known limitations

| Limitation | Detail |
|------------|--------|
| **LinkedIn ToS** | Scraping violates LinkedIn’s User Agreement; use a secondary account at your own risk |
| **Session expiry** | `li_at` cookies expire; refresh via `capture_session.py` or update Render env vars |
| **Rate limiting** | LinkedIn may return HTTP 999; the API maps auth failures to 401 and rate limits to 429 |
| **Connection degree** | Often unavailable (`networkDistance: -1`) depending on viewer relationship |
| **Job descriptions** | Not included in the Voyager decoration used; would require SDUI component fetch |
| **Skills count** | Voyager returns only skills listed in the profile’s skills section (often a subset of About text) |
| **Decoration versioning** | LinkedIn bumps `FullProfileWithEntities-N`; auto-discovery + fallback list mitigate this |
| **Single session** | One LinkedIn account backs all requests; not suitable for high-volume production |
| **Free-tier cold starts** | Render free plan spins down after inactivity (~50 s first request after idle) |
| **Not implemented** | Projects, honors, recommendations, activity feeds |

### Browserless vs headless browser

| Approach | Latency | Memory | Detectability |
|----------|---------|--------|---------------|
| Playwright / Puppeteer | ~3–8 s | ~200 MB+ | Lower |
| **This project (HTML + Voyager)** | **~1–2 s** | **~20 MB** | Higher |

Speed and memory are the wins; session management and LinkedIn’s anti-bot measures are the tradeoffs.

---

## Secrets checklist (before pushing)

Ensure these are **never** committed:

- `.env`, `.env.session`
- `session_state.json`
- Any file containing `li_at` or raw cookie values

`.gitignore` excludes them by default.
