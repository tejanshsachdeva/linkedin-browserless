from fastapi import Header, HTTPException, status

from app.core.config import get_settings


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """
    If API_KEY is set in the environment, every request must include a
    matching X-API-Key header. If API_KEY is unset (e.g. local dev),
    this is a no-op — the endpoint is open.
    """
    settings = get_settings()
    if settings.api_key is None:
        return
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid API key."
        )
