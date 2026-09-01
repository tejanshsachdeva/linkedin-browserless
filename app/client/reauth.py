"""
Best-effort browserless re-authentication.

WHAT THIS DOES
--------------
When the stored li_at dies, attempt ONE ordinary username/password login
against LinkedIn's normal web login flow. If LinkedIn issues a session,
extract the new li_at. If LinkedIn asks for anything more — MFA, CAPTCHA,
a device checkpoint, email verification — STOP and hand off to a human.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It never attempts to satisfy, bypass, or work around a challenge. Those
controls exist to require a human, and defeating them would be both a
security-control circumvention and a fast route to losing the account.
`_classify_login_outcome` treats every challenge as a terminal
`requires_intervention` result, full stop.

REALISTIC EXPECTATIONS
----------------------
LinkedIn's login endpoint is among their most heavily defended. A scripted
login from a datacenter IP, against an account that normally signs in from
a different country, is close to the textbook profile for a challenge. In
practice expect the intervention branch to fire often. This path is worth
having because it costs one attempt to find out — it is not a solution to
credential expiry.

Because failed logins carry more account risk than failed scrapes, this
module is OFF by default (REAUTH_ENABLED=false) and is wrapped in a strict
circuit breaker (see app/services/session_recovery.py).

FRAGILITY
---------
The endpoint path and form field names below are internal to LinkedIn's
web app and are not a published API. They change without notice. They are
centralized in the constants at the top of this file so that when login
starts failing with `authentication_failed`, this is the single place to
re-inspect and patch.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# --- LinkedIn login flow constants (verify against DevTools if this breaks) ---
LOGIN_PAGE_URL = "https://www.linkedin.com/login"
LOGIN_SUBMIT_URL = "https://www.linkedin.com/checkpoint/lg/login-submit"

FIELD_USERNAME = "session_key"
FIELD_PASSWORD = "session_password"
FIELD_CSRF = "loginCsrfParam"

# Hidden CSRF input on the login page.
_CSRF_INPUT_RE = re.compile(
    r'name=["\']loginCsrfParam["\'][^>]*value=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_CSRF_INPUT_RE_ALT = re.compile(
    r'value=["\']([^"\']+)["\'][^>]*name=["\']loginCsrfParam["\']',
    re.IGNORECASE,
)

# Any of these in a redirect target or body means LinkedIn wants a human.
# Treated as terminal — never as something to solve.
_CHALLENGE_MARKERS = (
    "/checkpoint/challenge",
    "/checkpoint/lg/login-challenge",
    "/checkpoint/rm/",
    "two-step",
    "two_step",
    "verification",
    "captcha",
    "recaptcha",
    "manage-account-security",
    "add-phone",
)

# Explicit "your credentials are wrong" signals. Distinguished from a
# challenge because the operator response differs: fix the password vs.
# complete a verification.
_BAD_CREDENTIAL_MARKERS = (
    "wrong email or phone number",
    "the password you provided must have",
    "couldn't find a linkedin account",
    "please enter a valid email",
    "hmm, we don't recognize that email",
)


@dataclass
class ReauthResult:
    li_at: Optional[str]
    requires_intervention: bool
    reason: Optional[str]
    detail: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.li_at is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "requires_intervention": self.requires_intervention,
            "reason": self.reason,
            "detail": self.detail,
        }


def _extract_csrf(html: str) -> Optional[str]:
    match = _CSRF_INPUT_RE.search(html) or _CSRF_INPUT_RE_ALT.search(html)
    return match.group(1) if match else None


def _looks_like_challenge(*haystacks: str) -> Optional[str]:
    for hay in haystacks:
        if not hay:
            continue
        lowered = hay.lower()
        for marker in _CHALLENGE_MARKERS:
            if marker in lowered:
                return marker
    return None


def _looks_like_bad_credentials(body: str) -> bool:
    lowered = body.lower()
    return any(marker in lowered for marker in _BAD_CREDENTIAL_MARKERS)


class LinkedInReauthenticator:
    """
    Performs a single browserless login attempt.

    Stateless by design: it builds its own throwaway client with a clean
    cookie jar, so a failed attempt cannot corrupt the live session's
    cookies. The caller decides whether to promote the result.
    """

    def __init__(
        self,
        email: Optional[str],
        password: Optional[str],
        *,
        user_agent: Optional[str] = None,
        timeout_seconds: int = 20,
        ca_bundle_path: Optional[str] = None,
        proxy: Optional[str] = None,
    ):
        self._email = email
        self._password = password
        self._user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
        )
        self._timeout = timeout_seconds
        self._ca_bundle_path = ca_bundle_path
        self._proxy = proxy

    @property
    def is_configured(self) -> bool:
        return bool(self._email and self._password)

    def _build_client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "headers": {
                "user-agent": self._user_agent,
                "accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
                "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
            },
            "timeout": self._timeout,
            # We inspect each hop ourselves; a redirect to /checkpoint is
            # the single most important signal in this whole flow and must
            # not be silently followed.
            "follow_redirects": False,
        }
        if self._ca_bundle_path:
            kwargs["verify"] = self._ca_bundle_path
        if self._proxy:
            kwargs["proxy"] = self._proxy
        return httpx.AsyncClient(**kwargs)

    async def reauthenticate(self) -> ReauthResult:
        if not self.is_configured:
            return ReauthResult(
                li_at=None,
                requires_intervention=True,
                reason="not_configured",
                detail=(
                    "LINKEDIN_EMAIL / LINKEDIN_PASSWORD are not set, so automatic "
                    "re-authentication cannot be attempted."
                ),
            )

        client = self._build_client()
        try:
            # --- Step 1: fetch the login page for CSRF + initial cookies ---
            try:
                page = await client.get(LOGIN_PAGE_URL)
            except httpx.RequestError as exc:
                return ReauthResult(
                    li_at=None,
                    requires_intervention=True,
                    reason="network_error",
                    detail=f"Could not reach the login page: {exc}",
                )

            csrf = _extract_csrf(page.text)
            if not csrf:
                # Either LinkedIn changed the form, or we were served an
                # interstitial instead of the login page.
                challenge = _looks_like_challenge(page.text, str(page.url))
                if challenge:
                    return ReauthResult(
                        li_at=None,
                        requires_intervention=True,
                        reason="linkedin_verification_required",
                        detail=f"Login page itself presented a challenge ({challenge}).",
                    )
                return ReauthResult(
                    li_at=None,
                    requires_intervention=True,
                    reason="login_form_not_recognized",
                    detail=(
                        "Could not find the loginCsrfParam field. LinkedIn may have "
                        "changed the login form; see constants in app/client/reauth.py."
                    ),
                )

            # --- Step 2: submit credentials ---
            form = {
                FIELD_USERNAME: self._email,
                FIELD_PASSWORD: self._password,
                FIELD_CSRF: csrf,
            }
            try:
                response = await client.post(
                    LOGIN_SUBMIT_URL,
                    data=form,
                    headers={
                        "content-type": "application/x-www-form-urlencoded",
                        "origin": "https://www.linkedin.com",
                        "referer": LOGIN_PAGE_URL,
                    },
                )
            except httpx.RequestError as exc:
                return ReauthResult(
                    li_at=None,
                    requires_intervention=True,
                    reason="network_error",
                    detail=f"Login submission failed: {exc}",
                )

            return self._classify_login_outcome(client, response)
        finally:
            await client.aclose()

    def _classify_login_outcome(
        self,
        client: httpx.AsyncClient,
        response: httpx.Response,
    ) -> ReauthResult:
        location = response.headers.get("location", "")

        # Challenge detection comes FIRST and is terminal. We never attempt
        # to satisfy one — no CAPTCHA solving, no code interception, no
        # retrying past it. It goes straight to a human.
        challenge = _looks_like_challenge(location, response.text[:5000])
        if challenge:
            logger.warning(
                "LinkedIn requires human verification (%s). Stopping — "
                "automatic re-authentication will not attempt to bypass this.",
                challenge,
            )
            return ReauthResult(
                li_at=None,
                requires_intervention=True,
                reason="linkedin_verification_required",
                detail=(
                    f"LinkedIn presented a security challenge ({challenge}). "
                    "A human must complete it in a browser, then rotate the "
                    "cookie via POST /admin/session/rotate."
                ),
            )

        li_at = self._extract_li_at(client)
        if li_at:
            logger.info("Browserless re-authentication obtained a new session cookie.")
            return ReauthResult(li_at=li_at, requires_intervention=False, reason=None)

        if _looks_like_bad_credentials(response.text[:5000]):
            return ReauthResult(
                li_at=None,
                requires_intervention=True,
                reason="invalid_credentials",
                detail=(
                    "LinkedIn rejected the configured email/password. Update "
                    "LINKEDIN_EMAIL / LINKEDIN_PASSWORD."
                ),
            )

        return ReauthResult(
            li_at=None,
            requires_intervention=True,
            reason="authentication_failed",
            detail=(
                f"Login returned HTTP {response.status_code} without issuing a "
                f"session cookie and without a recognizable challenge or error."
            ),
        )

    @staticmethod
    def _extract_li_at(client: httpx.AsyncClient) -> Optional[str]:
        for cookie in client.cookies.jar:
            if cookie.name == "li_at" and cookie.value:
                return cookie.value
        return None
