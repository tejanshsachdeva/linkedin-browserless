import re
from urllib.parse import urlparse, urlunparse

from app.exceptions import InvalidProfileUrlError

_PROFILE_PATH_RE = re.compile(r"^/in/[A-Za-z0-9\-_%]+/?$")


def normalize_profile_url(raw_url: str) -> str:
    """
    Validates that `raw_url` looks like a LinkedIn public profile URL
    (linkedin.com/in/<vanity-or-id>) and returns a canonical HTTPS form
    with tracking query params stripped.

    Raises InvalidProfileUrlError otherwise.
    """
    if not raw_url or not raw_url.strip():
        raise InvalidProfileUrlError("URL is empty.")

    candidate = raw_url.strip()
    if not candidate.startswith(("http://", "https://")):
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)

    host = parsed.netloc.lower().removeprefix("www.")
    if host not in {"linkedin.com"} and not host.endswith(".linkedin.com"):
        raise InvalidProfileUrlError(f"Not a linkedin.com URL: {raw_url!r}")

    if not _PROFILE_PATH_RE.match(parsed.path):
        raise InvalidProfileUrlError(
            f"Not a recognizable profile path (expected /in/<handle>): {parsed.path!r}"
        )

    canonical = urlunparse(("https", "www.linkedin.com", parsed.path.rstrip("/"), "", "", ""))
    return canonical


def extract_public_id(profile_url: str) -> str:
    """Pulls the vanity handle out of a normalized profile URL, used as a cache key."""
    path = urlparse(profile_url).path
    return path.rstrip("/").split("/")[-1]
