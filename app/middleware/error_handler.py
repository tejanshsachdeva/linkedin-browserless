import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.exceptions import (
    InvalidProfileUrlError,
    ProfileAccessRestrictedError,
    ProfileNotFoundError,
    RateLimitedError,
    ScraperError,
    SessionExpiredError,
    SessionNotConfiguredError,
)

logger = logging.getLogger(__name__)

_STATUS_MAP = {
    InvalidProfileUrlError: 400,
    SessionNotConfiguredError: 401,
    SessionExpiredError: 401,
    ProfileAccessRestrictedError: 403,
    ProfileNotFoundError: 404,
    RateLimitedError: 429,
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ScraperError)
    async def handle_scraper_error(request: Request, exc: ScraperError):
        status_code = _STATUS_MAP.get(type(exc), 500)
        if status_code == 500:
            logger.exception("Unhandled scraper error")
        return JSONResponse(
            status_code=status_code,
            content={"error": type(exc).__name__, "detail": str(exc)},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        logger.exception("Unhandled exception")
        return JSONResponse(
            status_code=500,
            content={"error": "InternalServerError", "detail": "An unexpected error occurred."},
        )
