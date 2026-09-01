"""
Exercises the real FastAPI app with the profile service swapped out for a stub.
"""
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.assembler.profile_assembler import assemble
from app.cache.memory_cache import InMemoryCache
from app.dependencies import get_profile_service
from app.exceptions import ProfileNotFoundError, SessionExpiredError
from app.main import app
from app.models.schemas import ImageRenditions, SectionStatus
from app.parsing.html_parser import TopCardData
from app.utils.rate_limiter import ScrapeThrottle
from app.utils.url_validator import extract_public_id, normalize_profile_url


class StubProfileService:
    """Mirrors ProfileService caching behavior without network or parsing."""

    def __init__(self, response_factory):
        self._response_factory = response_factory
        self._cache = InMemoryCache()
        self._throttle = ScrapeThrottle(max_concurrent=2)
        self._cache_ttl_seconds = 60
        self.calls = 0
        self._exc: Exception | None = None

    def raise_on_fetch(self, exc: Exception) -> None:
        self._exc = exc

    async def get_profile(self, raw_url: str, force_refresh: bool = False):
        from app.models.schemas import ProfileResponse

        if self._exc:
            raise self._exc

        canonical_url = normalize_profile_url(raw_url)
        cache_key = f"profile:{extract_public_id(canonical_url)}"

        if not force_refresh:
            cached = await self._cache.get(cache_key)
            if cached:
                return ProfileResponse.model_validate_json(cached)

        async with self._throttle.slot():
            self.calls += 1
            profile = self._response_factory(canonical_url)

        await self._cache.set(cache_key, profile.model_dump_json(), self._cache_ttl_seconds)
        return profile


def make_sample_response(url: str):
    top_card = TopCardData(
        name="Jordan Rivera",
        headline="Senior Software Engineer at Acme Corp",
        location="San Francisco, California, United States",
        profile_picture=ImageRenditions(
            primary="https://media.licdn.com/example/800.jpg",
            renditions={"800": "https://media.licdn.com/example/800.jpg"},
        ),
    )
    return assemble(top_card, [], url, include_debug=False)


@pytest.fixture
async def client_and_stub():
    stub_service = StubProfileService(make_sample_response)
    app.dependency_overrides[get_profile_service] = lambda: stub_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, stub_service

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_check():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_get_profile_success(client_and_stub):
    client, stub_service = client_and_stub
    resp = await client.post(
        "/api/v1/profile", json={"url": "https://www.linkedin.com/in/jane-doe"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Jordan Rivera"
    assert body["partial"] is True
    assert body["data_tiers"]["detail_sections"] == "not_implemented"
    assert body["section_status"]["experience"] == SectionStatus.NOT_IMPLEMENTED.value
    assert stub_service.calls == 1


@pytest.mark.asyncio
async def test_second_request_hits_cache(client_and_stub):
    client, stub_service = client_and_stub
    url = "https://www.linkedin.com/in/jane-doe"
    await client.post("/api/v1/profile", json={"url": url})
    await client.post("/api/v1/profile", json={"url": url})
    assert stub_service.calls == 1


@pytest.mark.asyncio
async def test_refresh_flag_bypasses_cache(client_and_stub):
    client, stub_service = client_and_stub
    url = "https://www.linkedin.com/in/jane-doe"
    await client.post("/api/v1/profile", json={"url": url})
    await client.post("/api/v1/profile?refresh=true", json={"url": url})
    assert stub_service.calls == 2


@pytest.mark.asyncio
async def test_invalid_url_returns_400(client_and_stub):
    client, _ = client_and_stub
    resp = await client.post("/api/v1/profile", json={"url": "https://example.com/not-linkedin"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "InvalidProfileUrlError"


@pytest.mark.asyncio
async def test_get_variant_via_query_param(client_and_stub):
    client, _ = client_and_stub
    resp = await client.get(
        "/api/v1/profile", params={"url": "https://www.linkedin.com/in/jane-doe"}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Jordan Rivera"


@pytest.mark.asyncio
async def test_session_expired_returns_503():
    stub_service = StubProfileService(make_sample_response)
    stub_service.raise_on_fetch(SessionExpiredError("expired"))
    app.dependency_overrides[get_profile_service] = lambda: stub_service
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/profile",
            json={"url": "https://www.linkedin.com/in/jane-doe"},
        )
    app.dependency_overrides.clear()
    # 503, not 401: the caller's request was valid — it's the service's own
    # upstream credential that expired, and only an operator can fix it.
    # A 401 would wrongly imply the caller needs to authenticate.
    assert resp.status_code == 503
    assert resp.headers.get("Retry-After")
    assert resp.json()["operator_action_required"] is True
    assert resp.json()["error"] == "SessionExpiredError"


@pytest.mark.asyncio
async def test_profile_not_found_returns_404():
    stub_service = StubProfileService(make_sample_response)
    stub_service.raise_on_fetch(ProfileNotFoundError("not found"))
    app.dependency_overrides[get_profile_service] = lambda: stub_service
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/profile",
            json={"url": "https://www.linkedin.com/in/missing"},
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 404
    assert resp.json()["error"] == "ProfileNotFoundError"
