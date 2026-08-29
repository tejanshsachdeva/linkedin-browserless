"""Unit tests for LinkedInClient HTTP error mapping."""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import Response

from app.client.linkedin_client import LinkedInClient
from app.client.session import LinkedInSession
from app.core.config import Settings
from app.exceptions import (
    ProfileAccessRestrictedError,
    ProfileNotFoundError,
    RateLimitedError,
    SessionExpiredError,
)


@pytest.fixture
def client() -> LinkedInClient:
    settings = Settings(
        LINKEDIN_LI_AT="test-li-at-token",
        LINKEDIN_JSESSIONID="ajax:1234567890123456789",
    )
    session = LinkedInSession(settings)
    return LinkedInClient(session)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_profile_html_success(client: LinkedInClient):
    respx.get("https://www.linkedin.com/in/jane-doe/").mock(
        return_value=Response(200, text="<html><h1>Jane Doe</h1></html>")
    )
    html = await client.fetch_profile_html("jane-doe")
    assert "Jane Doe" in html


@pytest.mark.asyncio
@respx.mock
async def test_redirect_to_login_raises_session_expired(client: LinkedInClient):
    respx.get("https://www.linkedin.com/in/jane-doe/").mock(
        return_value=Response(200, text="<html><form class='login-form'>Sign in to LinkedIn</form></html>")
    )
    with pytest.raises(SessionExpiredError):
        await client.fetch_profile_html("jane-doe")


@pytest.mark.asyncio
@respx.mock
async def test_checkpoint_url_raises_session_expired(client: LinkedInClient):
    respx.get("https://www.linkedin.com/in/jane-doe/").mock(
        return_value=Response(200, text="<html><div>checkpoint challenge</div></html>")
    )
    with pytest.raises(SessionExpiredError):
        await client.fetch_profile_html("jane-doe")


@pytest.mark.asyncio
@respx.mock
async def test_404_raises_profile_not_found(client: LinkedInClient):
    respx.get("https://www.linkedin.com/in/missing/").mock(
        return_value=Response(404, text="Not found")
    )
    with pytest.raises(ProfileNotFoundError):
        await client.fetch_profile_html("missing")


@pytest.mark.asyncio
@respx.mock
async def test_999_raises_rate_limited(client: LinkedInClient):
    respx.get("https://www.linkedin.com/in/jane-doe/").mock(
        return_value=Response(999, text="Blocked")
    )
    with pytest.raises(RateLimitedError, match="999"):
        await client.fetch_profile_html("jane-doe")


@pytest.mark.asyncio
@respx.mock
async def test_429_raises_rate_limited(client: LinkedInClient):
    respx.get("https://www.linkedin.com/in/jane-doe/").mock(
        return_value=Response(429, text="Too Many Requests")
    )
    with pytest.raises(RateLimitedError, match="429"):
        await client.fetch_profile_html("jane-doe")


@pytest.mark.asyncio
@respx.mock
async def test_auth_wall_raises_access_restricted(client: LinkedInClient):
    respx.get("https://www.linkedin.com/in/jane-doe/").mock(
        return_value=Response(
            200,
            text="<html><h1>Join LinkedIn</h1><p>Sign in to view this profile</p></html>",
        )
    )
    with pytest.raises(ProfileAccessRestrictedError):
        await client.fetch_profile_html("jane-doe")


@pytest.mark.asyncio
@respx.mock
async def test_embedded_try_again_later_on_profile_not_rate_limited(client: LinkedInClient):
    """SDUI embeds 'try again later' in real profile pages — must not false-positive."""
    body = (
        "<html><head><title>Jane Doe | LinkedIn</title></head><body>"
        + ("x" * 25_000)
        + 'Please try again later.'
        + 'id="rehydrate-data"'
        + "ACoAAFAKE0000000001"
        + "</body></html>"
    )
    respx.get("https://www.linkedin.com/in/jane-doe/").mock(
        return_value=Response(200, text=body)
    )
    html = await client.fetch_profile_html("jane-doe")
    assert "try again later" in html


@pytest.mark.asyncio
@respx.mock
async def test_unavailable_profile_body_raises_not_found(client: LinkedInClient):
    respx.get("https://www.linkedin.com/in/gone/").mock(
        return_value=Response(200, text="<html>This profile isn't available</html>")
    )
    with pytest.raises(ProfileNotFoundError):
        await client.fetch_profile_html("gone")
