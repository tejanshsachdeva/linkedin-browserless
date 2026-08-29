"""
SDUI component IDs and Voyager profile fetch contracts.

AsyncComponentRequest descriptors are parsed from `script#rehydrate-data` for
debug metadata. Structured section data (experience, education, skills) is
fetched via Voyager REST with the FullProfileWithEntities decoration.
"""

from __future__ import annotations

from app.parsing.decoration_discovery import decoration_id

# Default when discovery and fallbacks are unavailable (tests, legacy callers).
VOYAGER_FULL_PROFILE_DECORATION = decoration_id(76)

VOYAGER_PROFILE_PATH = "/voyager/api/identity/dash/profiles"

# Map component suffix → logical section (debug / future use)
COMPONENT_SECTION_MAP: dict[str, str] = {
    "profileCardsExperienceOnly": "experience",
    "profileCardsBelowActivityPart1WithoutExp": "about",
    "profileCardsBelowActivityPart2": "education",
    "profileCardsBelowActivityPart3": "skills",
    "profileCardsBelowActivityPart4": "certifications",
    "profileCardsBelowActivityPart5": "languages",
    "profileCardsBelowActivityPart6": "projects",
    "profileCardsBelowActivityPart7": "honors",
}


def component_section(component_id: str) -> str | None:
    suffix = component_id.rsplit(".", 1)[-1]
    return COMPONENT_SECTION_MAP.get(suffix)


def voyager_profile_url(vanity: str, *, profile_decoration: str | None = None) -> str:
    decoration = profile_decoration or VOYAGER_FULL_PROFILE_DECORATION
    return (
        f"{VOYAGER_PROFILE_PATH}"
        f"?q=memberIdentity&memberIdentity={vanity}"
        f"&decorationId={decoration}"
    )
