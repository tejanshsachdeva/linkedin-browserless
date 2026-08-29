from fastapi import APIRouter, Depends, Query

from app.dependencies import get_profile_service
from app.models.schemas import ProfileRequest, ProfileResponse
from app.security import require_api_key
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/api/v1", tags=["profile"], dependencies=[Depends(require_api_key)])


@router.post("/profile", response_model=ProfileResponse)
async def get_profile(
    body: ProfileRequest,
    refresh: bool = Query(default=False, description="Bypass cache and re-scrape."),
    service: ProfileService = Depends(get_profile_service),
) -> ProfileResponse:
    """
    Accepts a LinkedIn profile URL and returns structured profile data.

    Example request body:
        {"url": "https://www.linkedin.com/in/some-person"}
    """
    return await service.get_profile(body.url, force_refresh=refresh)


@router.get("/profile", response_model=ProfileResponse)
async def get_profile_via_query(
    url: str = Query(..., description="LinkedIn profile URL"),
    refresh: bool = Query(default=False),
    service: ProfileService = Depends(get_profile_service),
) -> ProfileResponse:
    """GET variant for quick manual testing via browser / curl without a JSON body."""
    return await service.get_profile(url, force_refresh=refresh)
