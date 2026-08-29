from fastapi import APIRouter, Depends

from app.dependencies import get_linkedin_session
from app.client.session import LinkedInSession

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    return {"status": "ok"}


@router.get("/health/session")
async def session_health(session: LinkedInSession = Depends(get_linkedin_session)):
    """
    Checks whether the configured LinkedIn session can reach an authenticated page.
    Does not expose cookie values.
    """
    probe = await session.probe()
    return {"status": "ok" if probe["ok"] else "degraded", **probe}
