"""
SDUI component IDs and Voyager profile fetch contracts.

AsyncComponentRequest descriptors are parsed from `script#rehydrate-data` for
debug metadata. Structured section data (experience, education, skills) is
fetched via Voyager REST with the FullProfileWithEntities decoration.
"""

from __future__ import annotations

# Voyager decoration that includes positions, education, skills in `included[]`.
VOYAGER_FULL_PROFILE_DECORATION = (
    "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-76"
)

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


def voyager_profile_url(vanity: str) -> str:
    return (
        f"{VOYAGER_PROFILE_PATH}"
        f"?q=memberIdentity&memberIdentity={vanity}"
        f"&decorationId={VOYAGER_FULL_PROFILE_DECORATION}"
    )
