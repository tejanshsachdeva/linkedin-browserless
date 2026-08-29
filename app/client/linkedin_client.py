"""Authenticated HTTP client for LinkedIn profile pages."""

from __future__ import annotations

import asyncio
import logging
import random
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
        self._cached_decoration_version: int | None = None

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
        self._session.apply_response_cookies(response)

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
            if "authwall" in body_lower:
                raise SessionExpiredError(
                    "LinkedIn returned HTTP 999 with auth wall — session expired or invalid."
                )
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
        if self._client is None:
            await self.start()

        assert self._client is not None
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
            self._session.apply_response_cookies(response)
            self._check_auth_redirect(response)

            if response.status_code in (401, 403):
                raise SessionExpiredError("LinkedIn rejected Voyager profile request (auth).")

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
        assert self._client is not None
        headers = build_voyager_get_headers(
            vanity=vanity,
            csrf_token=self._session.csrf_token,
        )
        return await self._client.get(
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
