"""HTTP header builders for LinkedIn requests."""

from __future__ import annotations

from typing import Optional

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)


def build_html_get_headers(*, user_agent: Optional[str] = None) -> dict[str, str]:
    """Headers mirroring a real browser navigation to a profile page."""
    ua = user_agent or DEFAULT_USER_AGENT
    return {
        "accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
        "user-agent": ua,
        "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
    }


def build_voyager_get_headers(
    *,
    vanity: str,
    csrf_token: str,
    user_agent: Optional[str] = None,
) -> dict[str, str]:
    """Headers for Voyager REST profile section requests."""
    ua = user_agent or DEFAULT_USER_AGENT
    return {
        "accept": "application/vnd.linkedin.normalized+json+2.1",
        "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
        "csrf-token": csrf_token,
        "referer": f"https://www.linkedin.com/in/{vanity}/",
        "user-agent": ua,
        "x-li-lang": "en_US",
        "x-restli-protocol-version": "2.0.0",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }
