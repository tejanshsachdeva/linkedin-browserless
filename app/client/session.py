"""LinkedIn session management: cookies, CSRF token, httpx client factory.

Session credential lifecycle
----------------------------
The `li_at` cookie is a password-equivalent secret with a finite life. It
expires on LinkedIn's schedule, and can be invalidated early by a logout,
a password change, or LinkedIn's own anomaly detection (e.g. the same
token used from a residential IP and a datacenter IP).

Because expiry is an expected recurring condition rather than an
exceptional one, this class tracks credential *state* explicitly:

  UNKNOWN  - not yet probed (fresh boot, or just rotated)
  VALID    - an authenticated request succeeded
  INVALID  - we observed a login/checkpoint redirect; stop trying

`is_usable` gates outbound requests. Once INVALID, the client
short-circuits to a clean 503 rather than making doomed requests that
redirect to /login — which is both faster for the caller and avoids
exhibiting a request pattern worth not exhibiting.

`rotate()` swaps in a fresh cookie at runtime and bumps `revision`, which
is how the client knows to rebuild its httpx connection pool. That is
what makes credential replacement possible without a redeploy.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import httpx

from app.client.headers import build_html_get_headers
from app.core.config import Settings
from app.exceptions import SessionNotConfiguredError

logger = logging.getLogger(__name__)

_SESSION_INSTRUCTIONS = """
LinkedIn session is not configured.

To authenticate:
1. Log into LinkedIn in your browser.
2. Open DevTools → Application → Cookies → https://www.linkedin.com
3. Copy the value of the "li_at" cookie.
4. Set LINKEDIN_LI_AT in your .env file, or run:
     python scripts/capture_session.py

On a running deployment you can instead POST the new value to
/admin/session/rotate with the X-Admin-Key header — no redeploy needed.

Optionally set LINKEDIN_JSESSIONID; if omitted, one will be auto-generated.
""".strip()


class CredentialState(str, Enum):
    UNKNOWN = "unknown"
    VALID = "valid"
    INVALID = "invalid"


def generate_jsessionid() -> str:
    return f"ajax:{random.randint(10**18, 10**19 - 1)}"


class LinkedInSession:
    """
    Holds cookies + derives the csrf-token header.

    Auth precedence:
      1. session_state.json on disk (cookie jar persisted from a prior run
         or from a runtime rotation — this is what lets a rotated cookie
         survive a process restart instead of silently reverting to a
         stale env var)
      2. LINKEDIN_LI_AT + LINKEDIN_JSESSIONID env vars
      3. raise SessionNotConfiguredError with actionable instructions
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._session_path = Path(settings.session_state_path)
        self._cookies: dict[str, str] = {}

        # Credential health, tracked explicitly — see module docstring.
        self._state: CredentialState = CredentialState.UNKNOWN
        self._last_validated_at: Optional[float] = None
        self._last_failure_at: Optional[float] = None
        self._last_failure_reason: Optional[str] = None
        self._rotated_at: Optional[float] = None
        self._source: str = "env"

        # Incremented on every rotation. LinkedInClient compares this
        # against its own snapshot to decide whether its cached
        # httpx.AsyncClient (which owns a copy of the cookie jar) is
        # stale and must be rebuilt.
        self._revision: int = 0

        self._load_session()

    # ------------------------------------------------------------------
    # Basic accessors
    # ------------------------------------------------------------------

    @property
    def csrf_token(self) -> str:
        return self._cookies.get("JSESSIONID", generate_jsessionid())

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def state(self) -> CredentialState:
        return self._state

    @property
    def is_usable(self) -> bool:
        """
        Whether it's worth attempting a LinkedIn request.

        UNKNOWN counts as usable: on a fresh boot we haven't probed yet
        and the right move is to try, not to refuse. Only an *observed*
        failure stops us.
        """
        return bool(self._cookies.get("li_at")) and self._state is not CredentialState.INVALID

    def get_cookie(self, name: str) -> Optional[str]:
        return self._cookies.get(name)

    def fingerprint(self) -> Optional[str]:
        """
        Short non-reversible id for logs, so you can tell which credential
        is in play without ever logging the credential itself.
        """
        li_at = self._cookies.get("li_at")
        if not li_at:
            return None
        return hashlib.sha256(li_at.encode()).hexdigest()[:12]

    # ------------------------------------------------------------------
    # Loading / persistence
    # ------------------------------------------------------------------

    def _load_session(self) -> None:
        if self._session_path.exists():
            try:
                data = json.loads(self._session_path.read_text(encoding="utf-8"))
                cookies = data.get("cookies", {})
                if isinstance(cookies, dict):
                    loaded = {str(k): str(v) for k, v in cookies.items()}
                    if loaded.get("li_at"):
                        self._cookies = loaded
                        self._source = "session_state"
                        self._rotated_at = data.get("rotated_at")
                        logger.info(
                            "Loaded session from %s (fp=%s).",
                            self._session_path,
                            self.fingerprint(),
                        )
                        return
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not read %s: %s", self._session_path, exc)

        li_at = self._settings.linkedin_li_at
        if not li_at:
            raise SessionNotConfiguredError(_SESSION_INSTRUCTIONS)

        jsessionid = self._settings.linkedin_jsessionid or generate_jsessionid()
        self._cookies = {"li_at": li_at, "JSESSIONID": jsessionid}
        self._source = "env"
        logger.info("Loaded session from environment (fp=%s).", self.fingerprint())

    def persist(self) -> None:
        payload: dict[str, Any] = {"cookies": self._cookies}
        if self._rotated_at is not None:
            payload["rotated_at"] = self._rotated_at
        try:
            self._session_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            try:
                # Owner-only: this file holds a password-equivalent secret.
                self._session_path.chmod(0o600)
            except OSError:
                pass  # best effort; some filesystems (e.g. Windows) ignore this
        except OSError as exc:
            logger.warning("Could not persist session state: %s", exc)

    def update_cookies_from_response(self, response: httpx.Response) -> None:
        for cookie in response.cookies.jar:
            self._cookies[cookie.name] = cookie.value

    @staticmethod
    def should_persist_response(response: httpx.Response) -> bool:
        if response.status_code in (401, 403, 429, 999):
            return False
        if response.status_code >= 400:
            return False
        body_lower = response.text.lower()
        if "authwall" in body_lower and len(response.text) < 20_000:
            return False
        return True

    def apply_response_cookies(self, response: httpx.Response) -> None:
        """Update cookies from a response and persist only on success."""
        self.update_cookies_from_response(response)
        if self.should_persist_response(response):
            self.persist()

    # ------------------------------------------------------------------
    # Credential state transitions
    # ------------------------------------------------------------------

    def mark_valid(self) -> None:
        was_invalid = self._state is CredentialState.INVALID
        self._state = CredentialState.VALID
        self._last_validated_at = time.time()
        if was_invalid:
            logger.info("Session credential recovered (fp=%s).", self.fingerprint())

    def mark_invalid(self, reason: str) -> bool:
        """
        Returns True only on the *transition* into INVALID, so callers can
        alert exactly once instead of on every subsequent failed request.
        """
        is_transition = self._state is not CredentialState.INVALID
        self._state = CredentialState.INVALID
        self._last_failure_at = time.time()
        self._last_failure_reason = reason
        if is_transition:
            logger.error(
                "Session credential marked INVALID (fp=%s): %s", self.fingerprint(), reason
            )
        return is_transition

    def rotate(self, li_at: str, jsessionid: str | None = None) -> None:
        """
        Install a fresh credential at runtime.

        State resets to UNKNOWN rather than optimistically VALID — the
        caller is expected to probe immediately, and we don't claim health
        on faith. `revision` is bumped so LinkedInClient rebuilds its
        connection pool with the new cookie jar on the next request.
        """
        cleaned = li_at.strip().strip('"')
        if not cleaned:
            raise ValueError("li_at value is empty.")

        self._cookies = {
            "li_at": cleaned,
            "JSESSIONID": (jsessionid or self._cookies.get("JSESSIONID") or generate_jsessionid()),
        }
        self._state = CredentialState.UNKNOWN
        self._last_failure_at = None
        self._last_failure_reason = None
        self._rotated_at = time.time()
        self._source = "admin_rotation"
        self._revision += 1
        self.persist()
        logger.info("Session credential rotated (fp=%s, rev=%s).", self.fingerprint(), self._revision)

    def snapshot(self) -> dict[str, Any]:
        """Operator-facing state. Never includes the cookie value."""

        def iso(ts: Optional[float]) -> Optional[str]:
            if ts is None:
                return None
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))

        return {
            "state": self._state.value,
            "usable": self.is_usable,
            "has_li_at": bool(self._cookies.get("li_at")),
            "fingerprint": self.fingerprint(),
            "source": self._source,
            "revision": self._revision,
            "last_validated_at": iso(self._last_validated_at),
            "last_failure_at": iso(self._last_failure_at),
            "last_failure_reason": self._last_failure_reason,
            "rotated_at": iso(self._rotated_at),
        }

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def build_client(self) -> httpx.AsyncClient:
        """
        Build an authenticated client.

        follow_redirects is deliberately FALSE. With it enabled, an expired
        li_at produces /in/<vanity>/ -> /login -> /in/<vanity>/ -> ... and
        httpx raises TooManyRedirects *inside* .get(), before any of our
        classification logic can run — which surfaced as an opaque HTTP 500
        in production. Handling redirects ourselves lets us inspect the
        first hop and raise SessionExpiredError instead.
        """
        headers = build_html_get_headers(user_agent=self._settings.user_agent)

        kwargs: dict[str, Any] = {
            "base_url": "https://www.linkedin.com",
            "headers": headers,
            "cookies": self._cookies,
            "timeout": self._settings.request_timeout_seconds,
            "follow_redirects": False,
        }

        # Corporate TLS-inspecting proxies re-sign HTTPS with an internal
        # root CA that Python's default trust store doesn't know about.
        if getattr(self._settings, "ca_bundle_path", None):
            kwargs["verify"] = self._settings.ca_bundle_path

        proxy = getattr(self._settings, "https_proxy", None) or getattr(
            self._settings, "http_proxy", None
        )
        if proxy:
            kwargs["proxy"] = proxy

        return httpx.AsyncClient(**kwargs)

    async def probe(self) -> dict[str, Any]:
        """
        Lightweight authenticated check against the feed.

        Updates credential state as a side effect, so this doubles as the
        validator for a freshly rotated cookie.
        """
        async with self.build_client() as client:
            try:
                response = await client.get("/feed/")
            except httpx.RequestError as exc:
                # A network failure is NOT evidence the cookie is bad.
                # Marking INVALID here would cause a self-inflicted outage
                # and a false alert on every transient DNS/TLS hiccup.
                logger.warning("Probe network error (state unchanged): %s", exc)
                return {"ok": False, "status_code": None, "error": str(exc), **self.snapshot()}

            if 300 <= response.status_code < 400:
                location = response.headers.get("location", "")
                # An authenticated /feed/ always returns 200. ANY redirect
                # therefore means we are not authenticated — including a
                # redirect back to /feed/ itself, which is LinkedIn's loop
                # signature for a dead cookie and was the original cause of
                # the TooManyRedirects 500. Only matching known auth paths
                # here was too narrow: it left the credential sitting in
                # UNKNOWN instead of INVALID, which suppressed alerting.
                if _is_auth_redirect(location):
                    detail = f"Probe redirected to an authentication page ({location})."
                elif _is_self_redirect(location, "/feed/"):
                    detail = (
                        "Probe redirected /feed/ back to itself — LinkedIn's "
                        "redirect-loop signature for an expired session."
                    )
                else:
                    detail = f"Probe redirected to {location or 'an unknown location'}."

                self.mark_invalid(detail)
                return {"ok": False, "status_code": response.status_code, **self.snapshot()}

            body_lower = response.text.lower()
            ok = (
                response.status_code == 200
                and "authwall" not in body_lower
                and "login-form" not in body_lower
            )

            if ok:
                self.mark_valid()
            elif response.status_code in (401, 403) or "authwall" in body_lower:
                self.mark_invalid(f"Probe returned HTTP {response.status_code} / auth wall.")
            # 429 / 999 / 5xx: throttling or upstream trouble, not proof of
            # a dead cookie. Leave state untouched.

            return {"ok": ok, "status_code": response.status_code, **self.snapshot()}

    def to_debug_dict(self) -> dict[str, Any]:
        return {
            "has_li_at": bool(self._cookies.get("li_at")),
            "jsessionid_prefix": (self._cookies.get("JSESSIONID") or "")[:12],
        }


_AUTH_PATH_MARKERS = ("/login", "/checkpoint", "/uas/login", "/authwall", "/signup")


def _is_auth_redirect(location: str) -> bool:
    if not location:
        return False
    return any(marker in location.lower() for marker in _AUTH_PATH_MARKERS)


def _is_self_redirect(location: str, path: str) -> bool:
    """
    True when a redirect points back at the path we just requested.

    LinkedIn does this with an expired cookie rather than redirecting to
    /login, which is why an auth-path-only check missed it.
    """
    if not location:
        return False
    lowered = location.lower().rstrip("/")
    target = path.lower().rstrip("/")
    return lowered.endswith(target)
