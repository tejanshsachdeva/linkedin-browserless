import logging

import httpx
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

# How long to tell clients to wait before retrying a session failure.
# Recovery is a manual operator action, so this is a "check back shortly"
# hint rather than a real estimate.
SESSION_RETRY_AFTER_SECONDS = 300

# Session problems are 503, not 401.
#
# The caller's request was perfectly valid — it's the SERVICE's upstream
# credential that has expired. A 401 would tell them THEY need to
# authenticate, which is misleading and unactionable. 503 + Retry-After is
# the honest signal, and it also means uptime monitors treat a dead
# credential as an outage instead of a healthy response.
_STATUS_MAP = {
    InvalidProfileUrlError: 400,
    SessionNotConfiguredError: 503,
    SessionExpiredError: 503,
    ProfileAccessRestrictedError: 403,
    ProfileNotFoundError: 404,
    RateLimitedError: 429,
}

_SESSION_ERRORS = (SessionExpiredError, SessionNotConfiguredError)


def _session_error_body(detail: str) -> dict:
    return {
        "error": "SessionExpired",
        "detail": detail,
        "operator_action_required": True,
        "check_status_at": "/health/session",
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ScraperError)
    async def handle_scraper_error(request: Request, exc: ScraperError):
        status_code = _STATUS_MAP.get(type(exc), 500)
        if status_code == 500:
            logger.exception("Unhandled scraper error")

        headers = {}
        content = {"error": type(exc).__name__, "detail": str(exc)}

        if isinstance(exc, _SESSION_ERRORS):
            headers["Retry-After"] = str(SESSION_RETRY_AFTER_SECONDS)
            content = {
                **_session_error_body(str(exc)),
                "error": type(exc).__name__,
            }
        elif isinstance(exc, RateLimitedError):
            headers["Retry-After"] = "60"

        return JSONResponse(status_code=status_code, content=content, headers=headers)

    @app.exception_handler(httpx.TooManyRedirects)
    async def handle_redirect_loop(request: Request, exc: httpx.TooManyRedirects):
        """
        Safety net.

        With follow_redirects=False and per-hop inspection in
        LinkedInClient, this should no longer fire. It stays because this
        exact exception was the original production 500: if LinkedIn ever
        introduces a redirect shape we don't classify, the caller should
        still get an actionable 503 rather than an opaque server error.
        """
        logger.error(
            "Redirect loop escaped classification — treating as session expiry. "
            "This suggests LinkedIn changed a redirect pattern: %s",
            exc,
        )
        return JSONResponse(
            status_code=503,
            headers={"Retry-After": str(SESSION_RETRY_AFTER_SECONDS)},
            content=_session_error_body(
                "LinkedIn redirected repeatedly, which indicates the upstream "
                "session is no longer valid."
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        logger.exception("Unhandled exception")
        return JSONResponse(
            status_code=500,
            content={"error": "InternalServerError", "detail": "An unexpected error occurred."},
        )
