"""LinkedIn session management: cookies, CSRF token, httpx client factory."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Optional

import httpx

from app.client.headers import DEFAULT_USER_AGENT, build_html_get_headers
from app.core.config import Settings
from app.exceptions import SessionNotConfiguredError

_SESSION_INSTRUCTIONS = """
LinkedIn session is not configured.

To authenticate:
1. Log into LinkedIn in your browser.
2. Open DevTools → Application → Cookies → https://www.linkedin.com
3. Copy the value of the "li_at" cookie.
4. Set LINKEDIN_LI_AT in your .env file, or run:
     python scripts/capture_session.py

Optionally set LINKEDIN_JSESSIONID; if omitted, one will be auto-generated.
""".strip()


def generate_jsessionid() -> str:
    return f"ajax:{random.randint(10**18, 10**19 - 1)}"


class LinkedInSession:
    """
    Holds cookies + derives the csrf-token header.

    Auth precedence:
      1. session_state.json on disk (cookie jar persisted from a prior run)
      2. LINKEDIN_LI_AT + LINKEDIN_JSESSIONID env vars
      3. raise SessionNotConfiguredError with actionable instructions
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._session_path = Path(settings.session_state_path)
        self._cookies: dict[str, str] = {}
        self._load_session()

    @property
    def csrf_token(self) -> str:
        return self._cookies.get("JSESSIONID", generate_jsessionid())

    def _load_session(self) -> None:
        if self._session_path.exists():
            try:
                data = json.loads(self._session_path.read_text(encoding="utf-8"))
                cookies = data.get("cookies", {})
                if isinstance(cookies, dict):
                    self._cookies = {str(k): str(v) for k, v in cookies.items()}
                    if self._cookies.get("li_at"):
                        return
            except (json.JSONDecodeError, OSError):
                pass

        li_at = self._settings.linkedin_li_at
        if not li_at:
            raise SessionNotConfiguredError(_SESSION_INSTRUCTIONS)

        jsessionid = self._settings.linkedin_jsessionid or generate_jsessionid()
        self._cookies = {
            "li_at": li_at,
            "JSESSIONID": jsessionid,
        }

    def persist(self) -> None:
        payload = {"cookies": self._cookies}
        self._session_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

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
        """Update cookies from a response and persist only on successful responses."""
        self.update_cookies_from_response(response)
        if self.should_persist_response(response):
            self.persist()

    def build_client(self) -> httpx.AsyncClient:
        headers = build_html_get_headers(user_agent=self._settings.user_agent)

        return httpx.AsyncClient(
            base_url="https://www.linkedin.com",
            headers=headers,
            cookies=self._cookies,
            timeout=self._settings.request_timeout_seconds,
            follow_redirects=True,
        )

    async def probe(self) -> dict[str, Any]:
        """Lightweight auth check against LinkedIn feed."""
        async with self.build_client() as client:
            response = await client.get("/feed/")
            body_lower = response.text.lower()
            ok = (
                response.status_code == 200
                and "authwall" not in body_lower
                and "login-form" not in body_lower
            )
            return {
                "ok": ok,
                "status_code": response.status_code,
                **self.to_debug_dict(),
            }

    def get_cookie(self, name: str) -> Optional[str]:
        return self._cookies.get(name)

    def to_debug_dict(self) -> dict[str, Any]:
        return {
            "has_li_at": bool(self._cookies.get("li_at")),
            "jsessionid_prefix": (self._cookies.get("JSESSIONID") or "")[:12],
        }
