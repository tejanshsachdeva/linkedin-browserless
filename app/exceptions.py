"""
Custom exception hierarchy.

Each exception maps to exactly one HTTP status in
app/middleware/error_handler.py. Raising the right exception type from
deep inside the client/parser layer is what lets the API layer respond
correctly without every function needing to know about HTTP.
"""


class ScraperError(Exception):
    """Base class for all errors raised by this service."""


class InvalidProfileUrlError(ScraperError):
    """The provided string isn't a usable LinkedIn profile URL."""


class SessionNotConfiguredError(ScraperError):
    """No LinkedIn session credentials are configured."""


class SessionExpiredError(ScraperError):
    """The LinkedIn session has expired or is no longer valid."""


# Backward-compatible alias for any external references
SessionNotAuthenticatedError = SessionExpiredError


class ProfileNotFoundError(ScraperError):
    """LinkedIn returned a 404 / "This profile isn't available" page."""


class ProfileAccessRestrictedError(ScraperError):
    """
    The profile loaded, but LinkedIn showed a limited/blurred view —
    e.g. it's outside your network and LinkedIn is gating full details,
    or the account hit a viewing limit.
    """


class RateLimitedError(ScraperError):
    """Too many concurrent scrapes or LinkedIn is throttling this session."""


class ParsingError(ScraperError):
    """
    A section of the page loaded but couldn't be parsed as expected.
    Raised per-section internally and caught by the orchestrator, which
    downgrades it to a `partial=True` response rather than failing the
    whole request — one broken section shouldn't sink everything else.
    """
