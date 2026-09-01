"""
Tests for credential expiry detection and hot rotation.

The headline case is test_expired_session_returns_503_not_500, which is a
regression test for the exact production failure: an expired li_at caused
httpx.TooManyRedirects to escape as an opaque HTTP 500.
"""

import httpx
import pytest
import respx

from app.client.linkedin_client import LinkedInClient
from app.client.session import CredentialState, LinkedInSession
from app.core.config import Settings
from app.exceptions import RateLimitedError, SessionExpiredError

LI_AT = "AQEDAT" + "x" * 60
NEW_LI_AT = "AQEDNEW" + "y" * 60


def make_settings(tmp_path) -> Settings:
    return Settings(
        LINKEDIN_LI_AT=LI_AT,
        LINKEDIN_JSESSIONID="ajax:1234567890123456789",
        SESSION_STATE_PATH=str(tmp_path / "session_state.json"),
    )


@pytest.fixture
def session(tmp_path):
    return LinkedInSession(make_settings(tmp_path))


# --------------------------------------------------------------- the bug


@pytest.mark.asyncio
@respx.mock
async def test_expired_session_returns_session_error_not_redirect_loop(session):
    """
    REGRESSION: expired li_at must raise SessionExpiredError, not
    httpx.TooManyRedirects.

    Previously build_client() used follow_redirects=True, so this loop was
    consumed inside .get() and surfaced as HTTP 500.
    """
    respx.get("https://www.linkedin.com/in/someone/").mock(
        return_value=httpx.Response(302, headers={"location": "https://www.linkedin.com/login"})
    )
    respx.get("https://www.linkedin.com/login").mock(
        return_value=httpx.Response(
            302, headers={"location": "https://www.linkedin.com/in/someone/"}
        )
    )

    client = LinkedInClient(session)
    with pytest.raises(SessionExpiredError):
        await client.fetch_profile_html("someone")

    assert session.state is CredentialState.INVALID
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_checkpoint_redirect_detected(session):
    respx.get("https://www.linkedin.com/in/someone/").mock(
        return_value=httpx.Response(302, headers={"location": "/checkpoint/challenge/"})
    )
    client = LinkedInClient(session)
    with pytest.raises(SessionExpiredError):
        await client.fetch_profile_html("someone")
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_benign_redirect_is_followed_not_treated_as_expiry(session):
    """Trailing-slash canonicalisation must not kill the session."""
    respx.get("https://www.linkedin.com/in/someone").mock(
        return_value=httpx.Response(
            301, headers={"location": "https://www.linkedin.com/in/someone/"}
        )
    )
    body = '<html><div id="rehydrate-data">urn:li:member:1</div>' + "x" * 25_000 + "</html>"
    respx.get("https://www.linkedin.com/in/someone/").mock(
        return_value=httpx.Response(200, text=body)
    )

    client = LinkedInClient(session)
    html = await client.fetch_profile_html("someone")
    assert "rehydrate-data" in html
    assert session.state is CredentialState.VALID
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_bare_999_is_rate_limit_not_expiry(session):
    """Throttling must not mark the credential dead."""
    respx.get("https://www.linkedin.com/in/someone/").mock(
        return_value=httpx.Response(999, text="Request denied")
    )
    client = LinkedInClient(session)
    with pytest.raises(RateLimitedError):
        await client.fetch_profile_html("someone")
    assert session.state is not CredentialState.INVALID
    await client.close()


@pytest.mark.asyncio
async def test_known_dead_session_short_circuits(session):
    """Once INVALID we must not issue further doomed requests."""
    session.mark_invalid("test")
    client = LinkedInClient(session)
    with pytest.raises(SessionExpiredError, match="known to be invalid"):
        await client.fetch_profile_html("someone")
    await client.close()


# ------------------------------------------------------------- rotation


def test_rotate_bumps_revision_and_resets_state(session):
    session.mark_invalid("dead")
    before = session.revision

    session.rotate(NEW_LI_AT)

    assert session.revision == before + 1
    assert session.state is CredentialState.UNKNOWN  # not optimistically VALID
    assert session.get_cookie("li_at") == NEW_LI_AT


def test_rotate_strips_quotes_and_whitespace(session):
    session.rotate(f'  "{NEW_LI_AT}"  ')
    assert session.get_cookie("li_at") == NEW_LI_AT


def test_rotate_rejects_empty(session):
    with pytest.raises(ValueError):
        session.rotate("   ")


def test_rotated_credential_survives_restart(tmp_path):
    """
    Persisted rotation must win over a stale env var on reload.

    Otherwise a cold start silently reverts to the old cookie — which
    works briefly and then breaks with no obvious cause.
    """
    settings = make_settings(tmp_path)
    s1 = LinkedInSession(settings)
    s1.rotate(NEW_LI_AT)

    s2 = LinkedInSession(settings)  # env still holds the ORIGINAL LI_AT
    assert s2.get_cookie("li_at") == NEW_LI_AT


@pytest.mark.asyncio
@respx.mock
async def test_client_rebuilds_pool_after_rotation(session):
    """
    httpx copies cookies at construction, so a rotation must invalidate
    the cached client or it keeps sending the dead cookie.
    """
    body = '<html><div id="rehydrate-data">x</div>' + "y" * 25_000 + "</html>"
    respx.get("https://www.linkedin.com/in/someone/").mock(
        return_value=httpx.Response(200, text=body)
    )

    client = LinkedInClient(session)
    await client.fetch_profile_html("someone")
    first_pool = client._client

    session.rotate(NEW_LI_AT)
    await client.fetch_profile_html("someone")

    assert client._client is not first_pool
    assert client._client.cookies.get("li_at") == NEW_LI_AT
    await client.close()


# ----------------------------------------------------------- state mgmt


def test_mark_invalid_reports_transition_only_once(session):
    """Alerting must fire once, not on every failed request."""
    assert session.mark_invalid("first") is True
    assert session.mark_invalid("second") is False


def test_snapshot_never_leaks_cookie(session):
    import json

    assert LI_AT not in json.dumps(session.snapshot())


def test_fingerprint_is_short_and_not_reversible(session):
    fp = session.fingerprint()
    assert fp and len(fp) == 12 and LI_AT not in fp


def test_unknown_state_is_still_usable(session):
    """At boot we haven't probed; the right move is to try, not refuse."""
    assert session.state is CredentialState.UNKNOWN
    assert session.is_usable


@pytest.mark.asyncio
@respx.mock
async def test_probe_network_error_does_not_mark_invalid(session):
    """A DNS blip is not an expired cookie."""
    respx.get("https://www.linkedin.com/feed/").mock(
        side_effect=httpx.ConnectError("dns failure")
    )
    result = await session.probe()
    assert result["ok"] is False
    assert session.state is not CredentialState.INVALID


# ------------------------------------------------- probe redirect handling


@pytest.mark.asyncio
@respx.mock
async def test_probe_self_redirect_marks_invalid(session):
    """
    REGRESSION: LinkedIn redirects /feed/ back to /feed/ when the cookie is
    dead, rather than redirecting to /login. An auth-path-only check missed
    this and left the credential in UNKNOWN, which suppressed alerting.
    """
    respx.get("https://www.linkedin.com/feed/").mock(
        return_value=httpx.Response(
            302, headers={"location": "https://www.linkedin.com/feed/"}
        )
    )
    result = await session.probe()
    assert result["ok"] is False
    assert session.state is CredentialState.INVALID


@pytest.mark.asyncio
@respx.mock
async def test_probe_any_redirect_marks_invalid(session):
    """An authenticated /feed/ returns 200, so ANY redirect means dead."""
    respx.get("https://www.linkedin.com/feed/").mock(
        return_value=httpx.Response(302, headers={"location": "https://www.linkedin.com/"})
    )
    await session.probe()
    assert session.state is CredentialState.INVALID


@pytest.mark.asyncio
@respx.mock
async def test_probe_200_marks_valid(session):
    respx.get("https://www.linkedin.com/feed/").mock(
        return_value=httpx.Response(200, text="<html>feed content here</html>")
    )
    result = await session.probe()
    assert result["ok"] is True
    assert session.state is CredentialState.VALID
