"""
Orchestrates automatic session recovery, with a strict circuit breaker.

WHY THE CIRCUIT BREAKER IS THE MOST IMPORTANT PART
--------------------------------------------------
A failed *scrape* costs one HTTP request. A failed *login* is a security
event on the account: repeated automated login attempts escalate toward
restriction or lockout. So the danger here is not "recovery fails" — it's
"recovery retries in a loop during an outage and locks the account."

The breaker enforces:

  * ONE attempt per expiry event, never a retry loop
  * a cooldown before any further attempt (default 1 hour)
  * a hard daily cap on attempts (default 3)
  * OPEN state after a challenge — once LinkedIn asks for human
    verification, further automated logins are pointless AND risky, so we
    stop entirely until an operator rotates manually

An in-flight lock also ensures that concurrent requests hitting an expired
session produce exactly one login attempt between them, not N.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from app.client.reauth import LinkedInReauthenticator, ReauthResult
from app.client.session import LinkedInSession

logger = logging.getLogger(__name__)


class BreakerState(str, Enum):
    CLOSED = "closed"          # attempts permitted
    COOLING_DOWN = "cooling_down"  # recent attempt; wait
    OPEN = "open"              # stopped: needs human, or cap reached


@dataclass
class RecoveryStats:
    attempts_today: int = 0
    day_started_at: float = field(default_factory=time.time)
    last_attempt_at: Optional[float] = None
    last_reason: Optional[str] = None
    last_success_at: Optional[float] = None
    opened_reason: Optional[str] = None


class SessionRecoveryService:
    def __init__(
        self,
        session: LinkedInSession,
        reauthenticator: LinkedInReauthenticator,
        *,
        enabled: bool = False,
        cooldown_seconds: int = 3600,
        max_attempts_per_day: int = 3,
        alerter=None,
    ):
        self._session = session
        self._reauth = reauthenticator
        self._enabled = enabled
        self._cooldown_seconds = cooldown_seconds
        self._max_attempts_per_day = max_attempts_per_day
        self._alerter = alerter

        self._stats = RecoveryStats()
        self._state = BreakerState.CLOSED
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Breaker logic
    # ------------------------------------------------------------------

    def _roll_day_if_needed(self) -> None:
        if time.time() - self._stats.day_started_at >= 86_400:
            self._stats.attempts_today = 0
            self._stats.day_started_at = time.time()
            if self._state is BreakerState.OPEN and self._stats.opened_reason == "daily_cap":
                self._state = BreakerState.CLOSED
                self._stats.opened_reason = None
                logger.info("Recovery daily cap reset; breaker closed.")

    def _current_state(self) -> BreakerState:
        self._roll_day_if_needed()

        if self._state is BreakerState.OPEN:
            return BreakerState.OPEN

        if self._stats.attempts_today >= self._max_attempts_per_day:
            self._state = BreakerState.OPEN
            self._stats.opened_reason = "daily_cap"
            return BreakerState.OPEN

        last = self._stats.last_attempt_at
        if last is not None and (time.time() - last) < self._cooldown_seconds:
            return BreakerState.COOLING_DOWN

        return BreakerState.CLOSED

    def _open(self, reason: str) -> None:
        self._state = BreakerState.OPEN
        self._stats.opened_reason = reason
        logger.warning("Recovery breaker OPEN (%s) — automatic login disabled.", reason)

    def reset_breaker(self) -> None:
        """Operator override, e.g. after completing a challenge manually."""
        self._state = BreakerState.CLOSED
        self._stats.opened_reason = None
        self._stats.last_attempt_at = None
        logger.info("Recovery breaker manually reset.")

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    async def attempt_recovery(self, *, force: bool = False) -> dict[str, Any]:
        """
        Try ONCE to recover the session automatically.

        Returns a dict describing what happened. Never raises: recovery is
        a best-effort side path and must not turn a clean 503 into a 500.
        """
        if not self._enabled and not force:
            return self._result(False, "disabled", "Automatic re-authentication is disabled.")

        if not self._reauth.is_configured:
            return self._result(
                False,
                "not_configured",
                "LINKEDIN_EMAIL / LINKEDIN_PASSWORD are not set.",
            )

        # Serialize: concurrent 503s must produce ONE login attempt, not N.
        if self._lock.locked():
            return self._result(
                False, "in_progress", "A recovery attempt is already running."
            )

        async with self._lock:
            state = self._current_state()

            if state is BreakerState.OPEN and not force:
                return self._result(
                    False,
                    "breaker_open",
                    (
                        f"Automatic recovery is stopped ({self._stats.opened_reason}). "
                        "Rotate manually via POST /admin/session/rotate."
                    ),
                )

            if state is BreakerState.COOLING_DOWN and not force:
                remaining = int(
                    self._cooldown_seconds - (time.time() - (self._stats.last_attempt_at or 0))
                )
                return self._result(
                    False,
                    "cooling_down",
                    f"Cooldown active; {remaining}s remaining before another attempt.",
                )

            self._stats.attempts_today += 1
            self._stats.last_attempt_at = time.time()

            logger.info(
                "Attempting browserless re-authentication (attempt %s/%s today).",
                self._stats.attempts_today,
                self._max_attempts_per_day,
            )

            try:
                result: ReauthResult = await self._reauth.reauthenticate()
            except Exception as exc:  # noqa: BLE001 - must never escape
                logger.exception("Re-authentication raised unexpectedly.")
                self._stats.last_reason = "internal_error"
                return self._result(False, "internal_error", str(exc))

            self._stats.last_reason = result.reason

            # A challenge means LinkedIn wants a human. Further automated
            # attempts are both useless and risky, so stop entirely.
            if result.reason == "linkedin_verification_required":
                self._open("verification_required")
                await self._alert(result.reason, result.detail)
                return self._result(False, result.reason, result.detail)

            if result.reason == "invalid_credentials":
                self._open("invalid_credentials")
                await self._alert(result.reason, result.detail)
                return self._result(False, result.reason, result.detail)

            if not result.ok:
                await self._alert(result.reason, result.detail)
                return self._result(False, result.reason, result.detail)

            # Validate BEFORE promoting. An unvalidated cookie would swap
            # one broken state for another while reporting success.
            previous_cookies = dict(self._session._cookies)  # noqa: SLF001
            previous_state = self._session.state

            self._session.rotate(result.li_at)
            probe = await self._session.probe()

            if not probe.get("ok"):
                self._session._cookies = previous_cookies  # noqa: SLF001
                self._session._state = previous_state  # noqa: SLF001
                self._session._revision += 1  # noqa: SLF001 - force client rebuild
                logger.warning("Re-auth produced a cookie that failed validation; rolled back.")
                await self._alert(
                    "validation_failed",
                    "Automatic login returned a cookie that did not validate.",
                )
                return self._result(
                    False,
                    "validation_failed",
                    "The recovered cookie failed validation; previous credential retained.",
                )

            self._stats.last_success_at = time.time()
            logger.info("Session recovered automatically (fp=%s).", self._session.fingerprint())
            if self._alerter is not None:
                await self._alerter.credential_recovered()
            return self._result(True, None, "Session recovered automatically.")

    async def _alert(self, reason: Optional[str], detail: Optional[str]) -> None:
        if self._alerter is None:
            return
        try:
            await self._alerter.recovery_failed(reason or "unknown", detail or "")
        except Exception as exc:  # noqa: BLE001 - alerting must never break the path
            logger.warning("Alert delivery failed: %s", exc)

    def _result(self, recovered: bool, reason: Optional[str], detail: str) -> dict[str, Any]:
        return {
            "recovered": recovered,
            "reason": reason,
            "detail": detail,
            **self.status(),
        }

    def status(self) -> dict[str, Any]:
        def iso(ts: Optional[float]) -> Optional[str]:
            if ts is None:
                return None
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))

        return {
            "auto_reauth_enabled": self._enabled,
            "credentials_configured": self._reauth.is_configured,
            "breaker_state": self._current_state().value,
            "breaker_opened_reason": self._stats.opened_reason,
            "attempts_today": self._stats.attempts_today,
            "max_attempts_per_day": self._max_attempts_per_day,
            "cooldown_seconds": self._cooldown_seconds,
            "last_attempt_at": iso(self._stats.last_attempt_at),
            "last_attempt_reason": self._stats.last_reason,
            "last_success_at": iso(self._stats.last_success_at),
        }
