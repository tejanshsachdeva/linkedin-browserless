"""Discover Voyager FullProfileWithEntities decoration IDs from profile HTML."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

DECORATION_PREFIX = "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities"
DECORATION_VERSION_RE = re.compile(r"FullProfileWithEntities-(\d+)")
FALLBACK_DECORATION_VERSIONS = (76, 75, 74, 73, 72)


def decoration_id(version: int) -> str:
    return f"{DECORATION_PREFIX}-{version}"


def discover_decoration_version(html: str) -> int | None:
    """Return the highest FullProfileWithEntities-N version found in HTML."""
    matches = DECORATION_VERSION_RE.findall(html)
    if not matches:
        return None
    return max(int(version) for version in matches)


def build_decoration_candidates(
    html: str | None,
    cached_version: int | None = None,
) -> list[str]:
    """
    Ordered decoration IDs to try: discovered from HTML, then cached, then fallbacks.
    """
    candidates: list[str] = []
    seen: set[str] = set()

    def add(version: int) -> None:
        candidate = decoration_id(version)
        if candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)

    discovered: int | None = None
    if html:
        discovered = discover_decoration_version(html)
        if discovered is not None:
            add(discovered)

    if cached_version is not None:
        add(cached_version)

    if discovered is None:
        logger.warning(
            "FullProfileWithEntities decoration not found in HTML; "
            "using cached/fallback decoration IDs"
        )

    for version in FALLBACK_DECORATION_VERSIONS:
        add(version)

    return candidates
