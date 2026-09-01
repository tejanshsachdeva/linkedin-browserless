from fastapi import APIRouter, Depends, Response, status

from app.client.session import CredentialState, LinkedInSession
from app.dependencies import get_linkedin_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Liveness. Is the process up? Deliberately does not touch LinkedIn."""
    return {"status": "ok"}


@router.get("/health/session")
async def session_health(
    response: Response,
    session: LinkedInSession = Depends(get_linkedin_session),
):
    """
    Readiness: can this service actually do its job right now?

    Unauthenticated but leaks nothing — no cookie, no fingerprint, no
    internal failure detail. That way anyone hitting a 503 from the
    profile endpoint can self-diagnose the cause without needing the
    admin key.

    Uses cached state when the credential is already known INVALID rather
    than probing on every call; a dead cookie doesn't need re-confirming,
    and probing in a loop is exactly the pattern worth avoiding.
    """
    if session.state is CredentialState.INVALID:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "degraded",
            "session": "invalid",
            "operational": False,
            "message": (
                "The upstream LinkedIn session has expired. The service operator "
                "must supply a fresh credential. Profile requests return 503 "
                "until then."
            ),
        }

    probe = await session.probe()

    if not probe.get("ok"):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "degraded",
            "session": probe.get("state", "unknown"),
            "operational": False,
            "message": "Could not confirm an authenticated LinkedIn session.",
        }

    return {
        "status": "ok",
        "session": "valid",
        "operational": True,
        "last_validated_at": probe.get("last_validated_at"),
    }
