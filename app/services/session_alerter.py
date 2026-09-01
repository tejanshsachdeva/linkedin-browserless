"""
Notifies the operator when the session dies or recovery fails.

This closes the "Alert you automatically" step. Without it, the only
signal is a log line you'd have to be watching for — which is how the
last outage was discovered by someone else first.

Fires on TRANSITIONS only. LinkedInSession.mark_invalid() returns True
only when state actually changes, so a dead cookie during a busy period
produces one alert, not hundreds.

Transport is any URL accepting a JSON POST — Slack and Discord incoming
webhooks work as-is. A structured log line is always emitted regardless,
so log-drain-based alerting works even with no webhook configured.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class SessionAlerter:
    def __init__(
        self,
        webhook_url: Optional[str] = None,
        service_name: str = "linkedin-profile-api",
        rotation_hint_url: Optional[str] = None,
        timeout_seconds: int = 10,
    ):
        self._webhook_url = webhook_url
        self._service_name = service_name
        self._rotation_hint_url = rotation_hint_url
        self._timeout = timeout_seconds

    async def _emit(self, event: str, text: str, **extra) -> None:
        logger.error(json.dumps({"event": event, "service": self._service_name, **extra}))

        if not self._webhook_url:
            return
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                await client.post(
                    self._webhook_url,
                    json={
                        "text": text,
                        "event": event,
                        "service": self._service_name,
                        **extra,
                    },
                )
        except Exception as exc:  # noqa: BLE001 - never break the request path
            logger.warning("Failed to deliver alert (%s): %s", event, exc)

    async def credential_invalid(self, reason: str) -> None:
        text = (
            f"*{self._service_name}*: LinkedIn session credential is no longer valid.\n"
            f"Reason: {reason}\n"
            f"Profile requests return 503 until a fresh li_at is supplied."
        )
        if self._rotation_hint_url:
            text += f"\nRotate at: {self._rotation_hint_url}"
        await self._emit("session_credential_invalid", text, reason=reason)

    async def recovery_failed(self, reason: str, detail: str) -> None:
        if reason == "linkedin_verification_required":
            text = (
                f"*{self._service_name}*: automatic re-authentication STOPPED — "
                f"LinkedIn requires human verification.\n{detail}\n"
                f"Complete the challenge in a browser, then rotate the cookie manually."
            )
        else:
            text = (
                f"*{self._service_name}*: automatic re-authentication failed "
                f"({reason}).\n{detail}\nManual rotation required."
            )
        if self._rotation_hint_url:
            text += f"\nRotate at: {self._rotation_hint_url}"
        await self._emit("session_recovery_failed", text, reason=reason, detail=detail)

    async def credential_recovered(self) -> None:
        await self._emit(
            "session_credential_recovered",
            f"*{self._service_name}*: session recovered automatically. Service operational.",
        )

    async def credential_rotated(self) -> None:
        await self._emit(
            "session_credential_rotated",
            f"*{self._service_name}*: session credential rotated manually and validated.",
        )
