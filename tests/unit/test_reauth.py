"""
Tests for browserless re-authentication and the recovery circuit breaker.

The most important tests here are the ones asserting that a challenge is
TERMINAL: LinkedIn's MFA/CAPTCHA/checkpoint controls exist to require a
human, and this code must stop at them rather than attempt to satisfy
them. test_challenge_opens_breaker_permanently is the guard against a
future change quietly turning this into a retry loop against a security
control.
"""

import httpx
import pytest
import respx

from app.client.reauth import LinkedInReauthenticator
from app.client.session import CredentialState, LinkedInSession
from app.core.config import Settings
from app.services.session_recovery import BreakerState, SessionRecoveryService

LOGIN_PAGE = "https://www.linkedin.com/login"
LOGIN_SUBMIT = "https://www.linkedin.com/checkpoint/lg/login-submit"

LOGIN_HTML = (
    '<html><form><input name="loginCsrfParam" value="csrf-token-abc123"/></form></html>'
)
LI_AT = "AQEDAT" + "x" * 60


def make_reauth(**kw):
    return LinkedInReauthenticator(email="a@b.com", password="pw", **kw)


# ------------------------------------------------------- challenge = STOP


@pytest.mark.asyncio
@respx.mock
async def test_checkpoint_redirect_requires_intervention():
    respx.get(LOGIN_PAGE).mock(return_value=httpx.Response(200, text=LOGIN_HTML))
    respx.post(LOGIN_SUBMIT).mock(
        return_value=httpx.Response(
            302,
            headers={"location": "https://www.linkedin.com/checkpoint/challenge/AgH..."},
        )
    )
    result = await make_reauth().reauthenticate()
    assert result.li_at is None
    assert result.requires_intervention
    assert result.reason == "linkedin_verification_required"


@pytest.mark.asyncio
@respx.mock
async def test_captcha_in_body_requires_intervention():
    respx.get(LOGIN_PAGE).mock(return_value=httpx.Response(200, text=LOGIN_HTML))
    respx.post(LOGIN_SUBMIT).mock(
        return_value=httpx.Response(200, text="<html>please complete the captcha</html>")
    )
    result = await make_reauth().reauthenticate()
    assert result.reason == "linkedin_verification_required"


@pytest.mark.asyncio
@respx.mock
async def test_two_step_verification_requires_intervention():
    respx.get(LOGIN_PAGE).mock(return_value=httpx.Response(200, text=LOGIN_HTML))
    respx.post(LOGIN_SUBMIT).mock(
        return_value=httpx.Response(200, text="<html>two-step verification required</html>")
    )
    result = await make_reauth().reauthenticate()
    assert result.reason == "linkedin_verification_required"


# ------------------------------------------------------------ happy path


@pytest.mark.asyncio
@respx.mock
async def test_successful_login_returns_li_at():
    respx.get(LOGIN_PAGE).mock(return_value=httpx.Response(200, text=LOGIN_HTML))
    respx.post(LOGIN_SUBMIT).mock(
        return_value=httpx.Response(
            302,
            headers={
                "location": "https://www.linkedin.com/feed/",
                "set-cookie": f"li_at={LI_AT}; Domain=.linkedin.com; Path=/",
            },
        )
    )
    result = await make_reauth().reauthenticate()
    assert result.li_at == LI_AT
    assert not result.requires_intervention


# ------------------------------------------------------------- failures


@pytest.mark.asyncio
@respx.mock
async def test_bad_credentials_reported_distinctly():
    respx.get(LOGIN_PAGE).mock(return_value=httpx.Response(200, text=LOGIN_HTML))
    respx.post(LOGIN_SUBMIT).mock(
        return_value=httpx.Response(200, text="<html>Wrong email or phone number</html>")
    )
    result = await make_reauth().reauthenticate()
    assert result.reason == "invalid_credentials"


@pytest.mark.asyncio
@respx.mock
async def test_missing_csrf_field_is_reported():
    respx.get(LOGIN_PAGE).mock(return_value=httpx.Response(200, text="<html>nope</html>"))
    result = await make_reauth().reauthenticate()
    assert result.reason == "login_form_not_recognized"


@pytest.mark.asyncio
async def test_unconfigured_credentials_short_circuit():
    r = LinkedInReauthenticator(email=None, password=None)
    result = await r.reauthenticate()
    assert result.reason == "not_configured"
    assert not r.is_configured


@pytest.mark.asyncio
@respx.mock
async def test_network_error_does_not_crash():
    respx.get(LOGIN_PAGE).mock(side_effect=httpx.ConnectError("boom"))
    result = await make_reauth().reauthenticate()
    assert result.reason == "network_error"


# ------------------------------------------------------ circuit breaker


@pytest.fixture
def session(tmp_path):
    return LinkedInSession(
        Settings(
            LINKEDIN_LI_AT=LI_AT,
            SESSION_STATE_PATH=str(tmp_path / "s.json"),
        )
    )


def make_recovery(session, **kw):
    kw.setdefault("enabled", True)
    return SessionRecoveryService(session, make_reauth(), **kw)


@pytest.mark.asyncio
async def test_disabled_by_default(session):
    svc = SessionRecoveryService(session, make_reauth(), enabled=False)
    out = await svc.attempt_recovery()
    assert out["recovered"] is False
    assert out["reason"] == "disabled"


@pytest.mark.asyncio
@respx.mock
async def test_challenge_opens_breaker_permanently(session):
    """
    A challenge must stop automated login entirely — not back off and
    retry. Retrying against a security control is both useless and the
    fastest way to get the account restricted.
    """
    respx.get(LOGIN_PAGE).mock(return_value=httpx.Response(200, text=LOGIN_HTML))
    respx.post(LOGIN_SUBMIT).mock(
        return_value=httpx.Response(
            302, headers={"location": "https://www.linkedin.com/checkpoint/challenge/x"}
        )
    )
    svc = make_recovery(session)

    first = await svc.attempt_recovery()
    assert first["reason"] == "linkedin_verification_required"
    assert svc.status()["breaker_state"] == BreakerState.OPEN.value

    second = await svc.attempt_recovery()
    assert second["reason"] == "breaker_open"


@pytest.mark.asyncio
@respx.mock
async def test_cooldown_blocks_immediate_retry(session):
    respx.get(LOGIN_PAGE).mock(return_value=httpx.Response(200, text=LOGIN_HTML))
    respx.post(LOGIN_SUBMIT).mock(return_value=httpx.Response(200, text="<html>?</html>"))
    svc = make_recovery(session, cooldown_seconds=3600)

    await svc.attempt_recovery()
    second = await svc.attempt_recovery()
    assert second["reason"] == "cooling_down"


@pytest.mark.asyncio
@respx.mock
async def test_daily_cap_opens_breaker(session):
    respx.get(LOGIN_PAGE).mock(return_value=httpx.Response(200, text=LOGIN_HTML))
    respx.post(LOGIN_SUBMIT).mock(return_value=httpx.Response(200, text="<html>?</html>"))
    svc = make_recovery(session, cooldown_seconds=0, max_attempts_per_day=2)

    await svc.attempt_recovery()
    await svc.attempt_recovery()
    third = await svc.attempt_recovery()
    assert third["reason"] == "breaker_open"
    assert svc.status()["breaker_opened_reason"] == "daily_cap"


@pytest.mark.asyncio
@respx.mock
async def test_recovered_cookie_is_validated_before_promotion(session):
    """An unvalidated cookie must not be promoted; roll back instead."""
    respx.get(LOGIN_PAGE).mock(return_value=httpx.Response(200, text=LOGIN_HTML))
    new_cookie = "AQEDNEW" + "y" * 60
    respx.post(LOGIN_SUBMIT).mock(
        return_value=httpx.Response(
            302,
            headers={
                "location": "https://www.linkedin.com/feed/",
                "set-cookie": f"li_at={new_cookie}; Domain=.linkedin.com; Path=/",
            },
        )
    )
    # Validation probe fails -> must roll back to the original cookie.
    respx.get("https://www.linkedin.com/feed/").mock(
        return_value=httpx.Response(302, headers={"location": "https://www.linkedin.com/login"})
    )

    svc = make_recovery(session)
    out = await svc.attempt_recovery()

    assert out["recovered"] is False
    assert out["reason"] == "validation_failed"
    assert session.get_cookie("li_at") == LI_AT  # rolled back


@pytest.mark.asyncio
@respx.mock
async def test_successful_recovery_promotes_and_validates(session):
    respx.get(LOGIN_PAGE).mock(return_value=httpx.Response(200, text=LOGIN_HTML))
    new_cookie = "AQEDNEW" + "y" * 60
    respx.post(LOGIN_SUBMIT).mock(
        return_value=httpx.Response(
            302,
            headers={
                "location": "https://www.linkedin.com/feed/",
                "set-cookie": f"li_at={new_cookie}; Domain=.linkedin.com; Path=/",
            },
        )
    )
    respx.get("https://www.linkedin.com/feed/").mock(
        return_value=httpx.Response(200, text="<html>feed content</html>")
    )

    session.mark_invalid("expired")
    svc = make_recovery(session)
    out = await svc.attempt_recovery()

    assert out["recovered"] is True
    assert session.get_cookie("li_at") == new_cookie
    assert session.state is CredentialState.VALID


@pytest.mark.asyncio
async def test_status_never_leaks_password(session):
    import json

    svc = make_recovery(session)
    assert "pw" not in json.dumps(svc.status())
