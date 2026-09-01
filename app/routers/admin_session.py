"""
Operator endpoints for inspecting and rotating the LinkedIn credential.

Why this exists
---------------
Before this router, replacing an expired li_at meant editing an
environment variable in the hosting dashboard and waiting for a full
redeploy — several minutes, with no confirmation that the new value
actually worked until traffic arrived.

Now: POST the cookie, it is validated against LinkedIn *before* being
committed, and you get an immediate yes/no. Seconds, no redeploy.

SECURITY
--------
Rotation accepts a password-equivalent secret and changes service
behaviour, so it requires ADMIN_API_KEY — deliberately separate from the
public API_KEY. If ADMIN_API_KEY is unset the endpoints return 503 rather
than being open: an unauthenticated credential-rotation endpoint would be
strictly worse than having none at all.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.client.session import LinkedInSession
from app.core.config import get_settings
from app.dependencies import get_linkedin_session, get_recovery_service
from app.services.session_recovery import SessionRecoveryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/session", tags=["admin"])


class RotateRequest(BaseModel):
    li_at: str = Field(
        ...,
        min_length=20,
        description="Fresh li_at cookie value copied from an authenticated browser.",
    )
    jsessionid: str | None = Field(
        default=None,
        description="Optional. Auto-generated if omitted.",
    )


class RotateResponse(BaseModel):
    ok: bool
    validated: bool
    message: str
    fingerprint: str | None = None


async def require_admin_key(x_admin_key: str | None = Header(default=None)) -> None:
    configured = get_settings().admin_api_key

    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Admin endpoints are disabled because ADMIN_API_KEY is not "
                "configured on this deployment."
            ),
        )

    # Constant-time compare so response timing doesn't leak the key.
    if not x_admin_key or not hmac.compare_digest(x_admin_key, configured):
        logger.warning("Rejected admin request with missing/invalid X-Admin-Key.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-Admin-Key header.",
        )


@router.get("", dependencies=[Depends(require_admin_key)])
async def session_status(
    session: LinkedInSession = Depends(get_linkedin_session),
    recovery: SessionRecoveryService = Depends(get_recovery_service),
):
    """Full credential + recovery state. Never returns the cookie value."""
    return {**session.snapshot(), "recovery": recovery.status()}


@router.post("/recover", dependencies=[Depends(require_admin_key)])
async def trigger_recovery(
    force: bool = False,
    recovery: SessionRecoveryService = Depends(get_recovery_service),
):
    """
    Manually trigger one automatic re-authentication attempt.

    `force=true` bypasses the cooldown and daily cap — use sparingly, and
    never in a loop: repeated automated logins are what put the account at
    risk of lockout. It does NOT bypass a challenge; if LinkedIn wants
    human verification, the attempt still stops there.
    """
    return await recovery.attempt_recovery(force=force)


@router.post("/breaker/reset", dependencies=[Depends(require_admin_key)])
async def reset_breaker(recovery: SessionRecoveryService = Depends(get_recovery_service)):
    """
    Close the recovery circuit breaker.

    Use after completing a LinkedIn challenge manually in a browser, so
    the service is allowed to attempt automatic recovery again later.
    """
    recovery.reset_breaker()
    return recovery.status()


@router.post("/probe", dependencies=[Depends(require_admin_key)])
async def force_probe(session: LinkedInSession = Depends(get_linkedin_session)):
    """Trigger an immediate validity check rather than waiting for traffic."""
    return await session.probe()


@router.post(
    "/rotate",
    response_model=RotateResponse,
    dependencies=[Depends(require_admin_key)],
)
async def rotate_credential(
    body: RotateRequest,
    session: LinkedInSession = Depends(get_linkedin_session),
) -> RotateResponse:
    """
    Install a new li_at.

    The submitted cookie is validated against LinkedIn BEFORE being kept.
    On failure we restore the previous credential and return 400 —
    installing an unverified cookie would swap one broken state for
    another while reporting success, and a mistyped paste shouldn't be
    able to make the service worse off than it already was.
    """
    previous_cookies = dict(session._cookies)  # noqa: SLF001 - deliberate rollback snapshot
    previous_state = session.state

    try:
        session.rotate(body.li_at, body.jsessionid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    probe = await session.probe()

    if not probe.get("ok"):
        session._cookies = previous_cookies  # noqa: SLF001
        session._state = previous_state  # noqa: SLF001
        session._revision += 1  # noqa: SLF001 - force client rebuild back to old jar
        logger.warning("Rotation rejected: submitted cookie failed validation.")
        raise HTTPException(
            status_code=400,
            detail=(
                "The submitted li_at was rejected by LinkedIn. It may be expired, "
                "truncated, or copied from a session that has since been signed "
                "out. The previous credential has been retained."
            ),
        )

    logger.info("Credential rotated and validated (fp=%s).", session.fingerprint())
    return RotateResponse(
        ok=True,
        validated=True,
        message="Credential installed and validated. Service is operational.",
        fingerprint=session.fingerprint(),
    )
