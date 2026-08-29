"""Authenticated HTTP client for LinkedIn profile pages."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from app.client.headers import build_voyager_get_headers
from app.client.session import LinkedInSession
from app.exceptions import (
    ProfileAccessRestrictedError,
    ProfileNotFoundError,
    RateLimitedError,
    SessionExpiredError,
)
from app.parsing.sdui_contracts import voyager_profile_url

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
    def __init__(self, session: LinkedInSession):
        self._session = session
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self._client is None:
            self._client = self._session.build_client()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch_profile_html(self, vanity: str) -> str:
        if self._client is None:
            await self.start()

        assert self._client is not None
        response = await self._client.get(f"/in/{vanity}/")
        self._session.update_cookies_from_response(response)
        self._session.persist()

        self._check_auth_redirect(response)
        self._check_status_and_body(response)
        return response.text

    def _check_auth_redirect(self, response: httpx.Response) -> None:
        final_url = str(response.url).lower()
        if any(marker in final_url for marker in _LOGIN_PATHS):
            raise SessionExpiredError(
                "LinkedIn redirected to login/checkpoint — session expired or invalid."
            )
        body_lower = response.text.lower()
        if "login-form" in body_lower or "sign in to linkedin" in body_lower:
            raise SessionExpiredError(
                "LinkedIn redirected to login/checkpoint — session expired or invalid."
            )
        if "checkpoint" in body_lower and "challenge" in body_lower:
            raise SessionExpiredError(
                "LinkedIn redirected to login/checkpoint — session expired or invalid."
            )

    def _check_status_and_body(self, response: httpx.Response) -> None:
        body_lower = response.text.lower()

        if response.status_code == 999:
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

    async def fetch_voyager_profile_sections(self, vanity: str) -> dict[str, Any]:
        """Fetch experience/education/skills via Voyager FullProfileWithEntities."""
        if self._client is None:
            await self.start()

        assert self._client is not None
        headers = build_voyager_get_headers(
            vanity=vanity,
            csrf_token=self._session.csrf_token,
        )
        response = await self._client.get(voyager_profile_url(vanity), headers=headers)
        self._session.update_cookies_from_response(response)
        self._session.persist()
        self._check_auth_redirect(response)

        if response.status_code in (401, 403):
            raise SessionExpiredError("LinkedIn rejected Voyager profile request (auth).")
        if response.status_code == 429:
            raise RateLimitedError("LinkedIn returned HTTP 429 on Voyager fetch.")
        if response.status_code == 404:
            raise ProfileNotFoundError("Voyager profile not found.")
        if response.status_code >= 400:
            response.raise_for_status()
        return response.json()
