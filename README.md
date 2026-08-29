# linkedin-browserless

Browser-free LinkedIn profile API. Send a profile URL, get structured JSON — no Playwright or Chromium.

> **Disclaimer:** Scraping LinkedIn violates their [User Agreement](https://www.linkedin.com/legal/user-agreement). For personal learning only. Use a secondary account.

**Repo:** [github.com/tejanshsachdeva/linkedin-browserless](https://github.com/tejanshsachdeva/linkedin-browserless)

## Architecture

Two-tier pipeline: server-rendered HTML for the top card, Voyager REST for detail sections.

```
POST /api/v1/profile
        │
        ▼
  ProfileService ──cache──▶ memory / Redis
        │
        ├─ Tier A: GET /in/{vanity} ──▶ html_parser (name, headline, images, …)
        │                          └──▶ rehydration_parser (SDUI descriptors, decoration ID)
        │
        └─ Tier B: GET /voyager/api/identity/dash/profiles ──▶ voyager_parser
                   (auto-discovered FullProfileWithEntities-N decoration)
        │
        ▼
  profile_assembler ──▶ ProfileResponse JSON
```

**Tier A** — Top card from SSR HTML (fast, always fetched).

**Tier B** — Experience, education, skills, about, certifications, languages via LinkedIn’s internal Voyager API. The `FullProfileWithEntities-N` decoration ID is discovered from the HTML when present, cached per session, and falls back through a list of known-good versions.

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

Session health: `GET /health/session` — checks whether your LinkedIn cookies still work (no secrets returned).

## API

```bash
curl -X POST http://127.0.0.1:8000/api/v1/profile \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.linkedin.com/in/<vanity>"}'
```

Add `?refresh=true` to bypass cache.

Optional: set `API_KEY` in `.env` and send `X-API-Key` header.

### Sample response

```json
{
  "source_url": "https://www.linkedin.com/in/jordan-rivera",
  "name": "Jordan Rivera",
  "headline": "Senior Software Engineer at Acme Corp",
  "location": "San Francisco, California, United States",
  "current_company": "Acme Corp",
  "about": "Builder of data products at scale.",
  "experience": [{ "title": "Senior Software Engineer", "company": "Acme Corp" }],
  "partial": false,
  "missing_sections": [],
  "section_status": {
    "about": "ok",
    "experience": "ok",
    "education": "ok",
    "skills": "ok",
    "certifications": "not_present",
    "languages": "ok"
  },
  "data_tiers": {
    "top_card": "ok",
    "detail_sections": "ok"
  },
  "field_sources": {
    "name": "html",
    "headline": "html",
    "experience": "voyager",
    "current_company": "voyager"
  },
  "field_conflicts": []
}
```

When HTML and Voyager disagree on overlapping fields (e.g. `current_company`), Voyager wins and the field name appears in `field_conflicts`.

`partial` is `true` only when a section **fetch failed** or was **not implemented** — empty sections on the profile (`not_present`) do not count.

## Test

```bash
pytest
```

Golden fixtures in `tests/fixtures/` hold redacted HTML and Voyager JSON for regression tests against real LinkedIn response shapes.

## Config

See [`.env.example`](.env.example).

## Limitations

| Area | Verified live | Fixture-only |
|------|---------------|--------------|
| Top-card HTML parsing (name, headline, location, images) | Yes | Golden HTML in `tests/fixtures/profile_golden.html` |
| Voyager section parsing (experience, education, skills, …) | Yes | Golden JSON in `tests/fixtures/voyager_golden.json` |
| Decoration auto-discovery (`FullProfileWithEntities-N` in HTML) | Structure verified in golden fixture; re-verify when LinkedIn changes bundles | Fallback list covers missing discovery |
| SDUI async component fetch | Parsed for debug metadata only; not used as a data source yet | — |
| Projects, honors, recommendations, activity | Not implemented | — |

## Browserless vs headless browser

| Approach | Latency | Memory | Detectability | Maintenance |
|----------|---------|--------|---------------|-------------|
| Playwright / Puppeteer | ~3–8 s | ~200 MB+ | Lower (real browser fingerprint) | Breaks on UI/DOM changes |
| **This project (HTML + Voyager HTTP)** | **~1–2 s** | **~20 MB** | **Higher** (session cookie + API pattern) | Breaks when Voyager contracts change |

Speed and memory are the real wins. A headless browser is harder for LinkedIn to distinguish from normal use; raw HTTP with a stolen `li_at` cookie is easier to fingerprint and throttle. The tradeoff is intentional: faster and lighter, but you must manage session health, rate limits, and decoration versioning yourself.
