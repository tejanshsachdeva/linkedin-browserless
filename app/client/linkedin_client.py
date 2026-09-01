"""Authenticated HTTP client for LinkedIn profile pages."""

from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any

import httpx

from app.client.headers import build_voyager_get_headers
from app.client.session import LinkedInSession, _is_auth_redirect
from app.exceptions import (
    ProfileAccessRestrictedError,
    ProfileNotFoundError,
    RateLimitedError,
    SessionExpiredError,
)
from app.parsing.decoration_discovery import (
    DECORATION_VERSION_RE,
    build_decoration_candidates,
)
from app.parsing.sdui_contracts import voyager_profile_url
from app.parsing.voyager_parser import voyager_payload_is_usable

logger = logging.getLogger(__name__)

_LOGIN_PATHS = ("/login", "/checkpoint")
_NOT_FOUND_MARKERS = (
    "page not found",
    "profile isn't available",
    "this page doesn't exist",
)
_LOGGED_OUT_MARKERS = (
    "join linkedin",
    "sign in to linkedin",
    "sign in to view",
    "authwall",
)

# Shown on tiny interstitial/error pages — not embedded SDUI copy on real profiles.
_STANDALONE_RATE_LIMIT_MARKERS = (
    "too many requests",
    "rate limit exceeded",
)

VOYAGER_MAX_ATTEMPTS = 3

# We follow redirects manually (see LinkedInSession.build_client), so we
# need our own bound. Legitimate LinkedIn redirects are 1-2 hops (trailing
# slash, vanity canonicalisation); anything beyond this is a loop.
MAX_REDIRECT_HOPS = 5


def _looks_like_profile_page(response: httpx.Response) -> bool:
    """True when the response is a full authenticated profile document."""
    if response.status_code != 200:
        return False
    text = response.text
    if len(text) < 20_000:
        return False
    lower = text.lower()
    if 'id="rehydrate-data"' in lower or "window.__como_rehydration__" in lower:
        return True
    if re.search(r"<title>[^<]+\|\s*linkedin</title>", lower):
        return True
    if re.search(r"ACoAA[A-Za-z0-9_-]{10,}", text):
        return True
    return False


class LinkedInClient:
    def __init__(self, session: LinkedInSession, alerter=None, recovery=None):
        self._session = session
        self._alerter = alerter
        self._recovery = recovery
        self._client: httpx.AsyncClient | None = None
        self._client_revision: int = -1
        self._cached_decoration_version: int | None = None

    async def start(self) -> None:
        await self._ensure_client()

    async def _ensure_client(self) -> httpx.AsyncClient:
        """
        Return a client whose cookie jar matches the session's CURRENT
        credential.

        httpx.AsyncClient copies cookies at construction time, so a client
        built before a rotation would keep sending the dead cookie until
        the process restarted — defeating the whole point of hot rotation.
        Comparing the session's revision counter against ours makes
        replacement automatic and costs one integer compare per request.
        """
        if self._client is None or self._client_revision != self._session.revision:
            if self._client is not None:
                logger.info(
                    "Session revision changed (%s -> %s); rebuilding HTTP client.",
                    self._client_revision,
                    self._session.revision,
                )
                await self._client.aclose()
            self._client = self._session.build_client()
            self._client_revision = self._session.revision
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._client_revision = -1

    def _fail_session(self, reason: str) -> None:
        """
        Mark the credential dead and raise.

        Records whether this was the *transition* into INVALID so the
        caller can alert exactly once rather than on every failed request.
        """
        became_invalid = self._session.mark_invalid(reason)
        self._pending_alert = reason if became_invalid else None
        raise SessionExpiredError(reason)

    async def _flush_alert(self) -> None:
        reason = getattr(self, "_pending_alert", None)
        if reason and self._alerter is not None:
            self._pending_alert = None
            try:
                await self._alerter.credential_invalid(reason)
            except Exception as exc:  # noqa: BLE001 - alerting must not break the path
                logger.warning("Alert delivery failed: %s", exc)

    def _guard_usable(self) -> None:
        """
        Short-circuit when we already know the credential is dead.

        Besides answering the caller faster, this stops us repeatedly
        hitting LinkedIn with requests that we know will bounce to /login.
        """
        if not self._session.is_usable:
            raise SessionExpiredError(
                "The LinkedIn session credential is known to be invalid. "
                "An operator must rotate it (POST /admin/session/rotate) "
                "before profile requests can succeed."
            )

    async def _get_following_redirects(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """
        Issue a GET, following only *benign* redirects.

        This is the fix for the production 500. Previously the client ran
        with follow_redirects=True, so an expired cookie caused
        /in/<vanity>/ -> /login -> /in/<vanity>/ -> ... and httpx raised
        TooManyRedirects inside .get(), before _check_auth_redirect could
        classify anything. Inspecting each hop's Location header lets us
        detect the auth bounce on the very first redirect.
        """
        client = await self._ensure_client()
        current = url

        for _ in range(MAX_REDIRECT_HOPS):
            response = await client.get(current, headers=headers)
            self._session.apply_response_cookies(response)

            if not (300 <= response.status_code < 400):
                return response

            location = response.headers.get("location", "")
            if _is_auth_redirect(location):
                self._fail_session(
                    f"LinkedIn redirected to an authentication page "
                    f"({location or 'unknown location'}) — session expired or invalid."
                )

            if not location:
                return response

            current = str(httpx.URL(str(response.url)).join(location))
            logger.debug("Following benign redirect to %s", current)

        # Every hop was non-auth yet we never landed. Treat as expiry:
        # a redirect loop is overwhelmingly a dead-session symptom, and
        # this is the safety net that keeps it from becoming a 500.
        self._fail_session("LinkedIn redirected repeatedly — session expired or invalid.")
        raise AssertionError("unreachable")  # pragma: no cover

    async def fetch_profile_html(self, vanity: str) -> str:
        try:
            return await self._fetch_profile_html_once(vanity)
        except SessionExpiredError:
            await self._flush_alert()

            # Best-effort automatic recovery: exactly ONE attempt, gated by
            # the circuit breaker in SessionRecoveryService. If LinkedIn
            # demands verification, recovery stops there and we surface the
            # 503 — we never try to satisfy a challenge.
            if self._recovery is None:
                raise

            outcome = await self._recovery.attempt_recovery()
            if not outcome.get("recovered"):
                raise

            logger.info("Session auto-recovered; retrying %s once.", vanity)
            return await self._fetch_profile_html_once(vanity)

    async def _fetch_profile_html_once(self, vanity: str) -> str:
        self._guard_usable()

        response = await self._get_following_redirects(f"/in/{vanity}/")

        self._check_auth_redirect(response)
        self._check_status_and_body(response)

        # A successful authenticated fetch is the strongest evidence the
        # credential is healthy — record it so a recovered session flips
        # back out of INVALID without waiting for a separate probe.
        self._session.mark_valid()
        return response.text

    def _check_auth_redirect(self, response: httpx.Response) -> None:
        final_url = str(response.url).lower()
        if any(marker in final_url for marker in _LOGIN_PATHS):
            self._fail_session(
                "LinkedIn served a login/checkpoint page — session expired or invalid."
            )
        body_lower = response.text.lower()
        if "login-form" in body_lower or "sign in to linkedin" in body_lower:
            self._fail_session(
                "LinkedIn served a login form — session expired or invalid."
            )
        if "checkpoint" in body_lower and "challenge" in body_lower:
            self._fail_session(
                "LinkedIn served a security checkpoint — session requires re-authentication."
            )

    def _check_status_and_body(self, response: httpx.Response) -> None:
        body_lower = response.text.lower()

        if response.status_code == 999:
            if "authwall" in body_lower:
                self._fail_session(
                    "LinkedIn returned HTTP 999 with auth wall — session expired or invalid."
                )
            # Bare 999 is throttling, not proof of a dead cookie — do not
            # mark the credential invalid here.
            raise RateLimitedError("LinkedIn returned HTTP 999 (anti-bot / rate limit).")

        if response.status_code == 429:
            raise RateLimitedError("LinkedIn returned HTTP 429 (rate limited).")

        if response.status_code == 404:
            raise ProfileNotFoundError(f"Profile not found (HTTP 404).")

        if response.status_code >= 400:
            if any(marker in body_lower for marker in _NOT_FOUND_MARKERS):
                raise ProfileNotFoundError("Profile not found or unavailable.")
            response.raise_for_status()

        if any(marker in body_lower for marker in _LOGGED_OUT_MARKERS):
            raise ProfileAccessRestrictedError(
                "LinkedIn returned a logged-out or auth-walled page."
            )

        if any(marker in body_lower for marker in _NOT_FOUND_MARKERS):
            raise ProfileNotFoundError("Profile not found or unavailable.")

        if _looks_like_profile_page(response):
            return

        if any(marker in body_lower for marker in _STANDALONE_RATE_LIMIT_MARKERS):
            raise RateLimitedError("LinkedIn indicates rate limiting in response body.")

        if response.status_code == 200 and len(response.text) < 5000:
            if "try again later" in body_lower or "rate limit" in body_lower:
                raise RateLimitedError("LinkedIn indicates rate limiting in response body.")

    async def fetch_voyager_profile_sections(
        self,
        vanity: str,
        *,
        html: str | None = None,
    ) -> dict[str, Any]:
        """Fetch experience/education/skills via Voyager FullProfileWithEntities."""
        self._guard_usable()

        candidates = build_decoration_candidates(html, self._cached_decoration_version)
        last_ok_payload: dict[str, Any] | None = None
        auth_failed = False

        for decoration in candidates:
            try:
                payload = await self._fetch_voyager_with_retry(vanity, decoration)
            except SessionExpiredError:
                auth_failed = True
                raise
            except ProfileNotFoundError:
                continue

            if payload is None:
                continue

            last_ok_payload = payload
            if voyager_payload_is_usable(payload):
                self._cache_decoration_version(decoration)
                return payload

            logger.warning(
                "Voyager decoration %s returned 200 but no recognizable entities for %s",
                decoration,
                vanity,
            )

        if last_ok_payload is not None:
            logger.warning(
                "All Voyager decorations returned sparse payloads for %s; using last 200 response",
                vanity,
            )
            return last_ok_payload

        if auth_failed:
            raise SessionExpiredError("LinkedIn rejected Voyager profile request (auth).")

        raise ProfileNotFoundError("Voyager profile not found for any decoration candidate.")

    async def _fetch_voyager_with_retry(
        self,
        vanity: str,
        decoration: str,
    ) -> dict[str, Any] | None:
        last_response: httpx.Response | None = None
        for attempt in range(1, VOYAGER_MAX_ATTEMPTS + 1):
            response = await self._request_voyager_profile(vanity, decoration)
            last_response = response
            self._check_auth_redirect(response)

            if response.status_code in (401, 403):
                self._fail_session("LinkedIn rejected Voyager profile request (auth).")

            if response.status_code == 404:
                raise ProfileNotFoundError("Voyager profile not found.")

            if response.status_code == 400:
                logger.warning("Voyager decoration rejected (400): %s", decoration)
                return None

            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= VOYAGER_MAX_ATTEMPTS:
                    if response.status_code == 429:
                        raise RateLimitedError("LinkedIn returned HTTP 429 on Voyager fetch.")
                    response.raise_for_status()
                delay = self._retry_delay(attempt, response)
                logger.warning(
                    "Voyager %s for %s (attempt %s/%s); retrying in %.1fs",
                    response.status_code,
                    decoration,
                    attempt,
                    VOYAGER_MAX_ATTEMPTS,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            if response.status_code >= 400:
                response.raise_for_status()

            return response.json()

        if last_response is not None and last_response.status_code == 429:
            raise RateLimitedError("LinkedIn returned HTTP 429 on Voyager fetch.")
        if last_response is not None and last_response.status_code >= 500:
            last_response.raise_for_status()
        return None

    async def _request_voyager_profile(
        self,
        vanity: str,
        decoration: str,
    ) -> httpx.Response:
        headers = build_voyager_get_headers(
            vanity=vanity,
            csrf_token=self._session.csrf_token,
        )
        return await self._get_following_redirects(
            voyager_profile_url(vanity, profile_decoration=decoration),
            headers=headers,
        )

    @staticmethod
    def _retry_delay(attempt: int, response: httpx.Response) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after) + random.uniform(0, 0.5)
            except ValueError:
                pass
        base = 1.0 * (2 ** (attempt - 1))
        return base + random.uniform(0, 0.5)

    def _cache_decoration_version(self, decoration: str) -> None:
        match = DECORATION_VERSION_RE.search(decoration)
        if match:
            self._cached_decoration_version = int(match.group(1))
