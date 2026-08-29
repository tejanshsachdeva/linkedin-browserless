"""Parse Voyager FullProfileWithEntities normalized JSON."""

from __future__ import annotations

import html
import re
from typing import Any

from app.models.schemas import CertificationItem, EducationItem, ExperienceItem, LanguageItem
from app.parsing.duration import compute_duration
from app.parsing.voyager_index import build_included_index, resolve_entry_ref, resolve_ref

PROFILE_URN = "fsd_profile:"
POSITION_URN = "fsd_profilePosition:"
EDUCATION_URN = "fsd_profileEducation:"
SKILL_URN = "fsd_skill:"
CERTIFICATION_URN = "fsd_profileCertification:"
LANGUAGE_URN = "fsd_profileLanguage:"
COMPANY_URN = "fsd_company:"
SCHOOL_URN = "fsd_school:"

_USABLE_URN_MARKERS = (
    PROFILE_URN,
    POSITION_URN,
    EDUCATION_URN,
    SKILL_URN,
    CERTIFICATION_URN,
    LANGUAGE_URN,
)

_PROFICIENCY_LABELS = {
    "NATIVE_OR_BILINGUAL": "Native or bilingual",
    "FULL_PROFESSIONAL": "Full professional proficiency",
    "PROFESSIONAL_WORKING": "Professional working proficiency",
    "LIMITED_WORKING": "Limited working proficiency",
    "ELEMENTARY": "Elementary proficiency",
}

_MONTH_RE = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})$")


def voyager_payload_is_usable(payload: dict[str, Any]) -> bool:
    """True when the decoration returned recognizable profile entities."""
    included = payload.get("included", [])
    if not isinstance(included, list) or not included:
        return False
    for entry in included:
        if not isinstance(entry, dict):
            continue
        urn = entry.get("entityUrn", "")
        if any(marker in urn for marker in _USABLE_URN_MARKERS):
            return True
    return False


def parse_voyager_profile(payload: dict[str, Any]) -> dict[str, Any]:
    included = payload.get("included", [])
    if not isinstance(included, list):
        included = []

    index = build_included_index(included)
    experience = parse_experience_from_voyager(included, index)
    return {
        "about": parse_about_from_voyager(included),
        "experience": experience,
        "education": parse_education_from_voyager(included, index),
        "skills": parse_skills_from_voyager(included, index),
        "certifications": parse_certifications_from_voyager(included),
        "languages": parse_languages_from_voyager(included),
    }


def parse_about_from_voyager(included: list[Any]) -> str | None:
    best: str | None = None
    for entry in included:
        if not isinstance(entry, dict):
            continue
        urn = entry.get("entityUrn", "")
        if PROFILE_URN not in urn or urn.count(":") != 3:
            continue
        summary = entry.get("summary")
        if not isinstance(summary, str):
            continue
        cleaned = html.unescape(summary.strip())
        if cleaned and (best is None or len(cleaned) > len(best)):
            best = cleaned
    return best


def parse_experience_from_voyager(
    included: list[Any],
    index: dict[str, dict[str, Any]],
) -> list[ExperienceItem]:
    items: list[ExperienceItem] = []
    for entry in included:
        if not isinstance(entry, dict):
            continue
        urn = entry.get("entityUrn", "")
        if POSITION_URN not in urn or not entry.get("title"):
            continue
        start_date = _format_date(entry, "start")
        end_date = _format_date(entry, "end")
        items.append(
            ExperienceItem(
                title=_clean_text(entry.get("title")),
                company=_clean_text(entry.get("companyName")) or _resolved_company_name(entry, index),
                company_url=_company_url(entry, index),
                employment_type=_employment_type(entry, index),
                location=_location_text(entry, index),
                start_date=start_date,
                end_date=end_date,
                duration=compute_duration(start_date, end_date),
                description=_clean_text(entry.get("description")),
            )
        )
    return _sort_experience(items)


def parse_education_from_voyager(
    included: list[Any],
    index: dict[str, dict[str, Any]],
) -> list[EducationItem]:
    items: list[EducationItem] = []
    for entry in included:
        if not isinstance(entry, dict):
            continue
        urn = entry.get("entityUrn", "")
        if EDUCATION_URN not in urn:
            continue
        school = entry.get("schoolName") or _resolved_school_name(entry, index)
        if not school:
            continue
        items.append(
            EducationItem(
                school=school,
                school_url=_school_url(entry, index),
                degree=entry.get("degreeName"),
                field_of_study=entry.get("fieldOfStudy"),
                start_date=_format_date(entry, "start"),
                end_date=_format_date(entry, "end"),
                description=_clean_text(entry.get("description")),
            )
        )
    return items


def parse_skills_from_voyager(
    included: list[Any],
    index: dict[str, dict[str, Any]],
) -> list[str]:
    skills: list[str] = []
    seen: set[str] = set()

    def add_skill(name: Any) -> None:
        if not isinstance(name, str):
            return
        cleaned = name.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            skills.append(cleaned)

    for entry in included:
        if not isinstance(entry, dict):
            continue
        urn = entry.get("entityUrn", "")
        if SKILL_URN in urn:
            add_skill(entry.get("name") or entry.get("skillName"))
            continue
        if "collectionResponse" in urn:
            for ref in entry.get("*elements") or entry.get("elements") or []:
                skill_entry = resolve_ref(index, ref)
                if skill_entry is not None:
                    add_skill(skill_entry.get("name") or skill_entry.get("skillName"))

    return skills


def parse_certifications_from_voyager(included: list[Any]) -> list[CertificationItem]:
    items: list[CertificationItem] = []
    for entry in included:
        if not isinstance(entry, dict):
            continue
        urn = entry.get("entityUrn", "")
        if CERTIFICATION_URN not in urn:
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        items.append(
            CertificationItem(
                name=name.strip(),
                issuing_organization=_clean_text(entry.get("authority")),
                issue_date=_format_date(entry, "start"),
                credential_id=_clean_text(entry.get("licenseNumber")),
                credential_url=entry.get("url") if isinstance(entry.get("url"), str) else None,
            )
        )
    return items


def parse_languages_from_voyager(included: list[Any]) -> list[LanguageItem]:
    items: list[LanguageItem] = []
    seen: set[str] = set()
    for entry in included:
        if not isinstance(entry, dict):
            continue
        urn = entry.get("entityUrn", "")
        if LANGUAGE_URN not in urn:
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        key = name.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        proficiency = entry.get("proficiency")
        items.append(
            LanguageItem(
                name=name.strip(),
                proficiency=_proficiency_label(proficiency),
            )
        )
    return items


def _proficiency_label(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return _PROFICIENCY_LABELS.get(value, value.replace("_", " ").title())


def _resolved_company_name(entry: dict[str, Any], index: dict[str, dict[str, Any]]) -> str | None:
    company = resolve_entry_ref(index, entry, "*company")
    if company is None:
        return None
    name = company.get("name")
    return name if isinstance(name, str) else None


def _resolved_school_name(entry: dict[str, Any], index: dict[str, dict[str, Any]]) -> str | None:
    school = resolve_entry_ref(index, entry, "*school")
    if school is None:
        return None
    name = school.get("name")
    return name if isinstance(name, str) else None


def _sort_experience(items: list[ExperienceItem]) -> list[ExperienceItem]:
    return sorted(
        items,
        key=lambda item: (
            item.end_date is not None,
            -_date_sort_key(item.start_date),
            -_date_sort_key(item.end_date),
        ),
    )


def _date_sort_key(date_str: str | None) -> int:
    if not date_str:
        return 0
    match = _MONTH_RE.match(date_str.strip())
    if match:
        month = _month_name_to_int(match.group(1))
        year = int(match.group(2))
        return year * 12 + month
    if date_str.isdigit():
        return int(date_str) * 12
    return 0


def _month_name_to_int(name: str) -> int:
    names = (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    )
    try:
        return names.index(name) + 1
    except ValueError:
        return 0


def _format_date(entry: dict[str, Any], edge: str) -> str | None:
    date_range = entry.get("dateRange")
    if not isinstance(date_range, dict):
        return None
    point = date_range.get(edge)
    if not isinstance(point, dict):
        return None
    month = point.get("month")
    year = point.get("year")
    if year is None:
        return None
    if month:
        return f"{_month_name(int(month))} {year}"
    return str(year)


def _month_name(month: int) -> str:
    names = (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    )
    if 1 <= month <= 12:
        return names[month - 1]
    return str(month)


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = html.unescape(value.strip())
    return cleaned or None


def _location_text(entry: dict[str, Any], index: dict[str, dict[str, Any]]) -> str | None:
    for key in ("locationName", "geoLocationName"):
        value = entry.get(key)
        resolved = _location_text_value(value)
        if resolved:
            return resolved
    geo = resolve_entry_ref(index, entry, "*geo")
    if geo is not None:
        return _location_text_value(geo.get("defaultLocalizedName") or geo.get("name"))
    return None


def _location_text_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("defaultLocalizedName") or value.get("name")
    return None


def _employment_type(entry: dict[str, Any], index: dict[str, dict[str, Any]]) -> str | None:
    employment = resolve_entry_ref(index, entry, "*employmentType")
    if employment is not None:
        name = employment.get("name") or employment.get("localizedName")
        if isinstance(name, str):
            return name
    value = entry.get("employmentType")
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("name") or value.get("localizedName")
    return None


def _company_url(entry: dict[str, Any], index: dict[str, dict[str, Any]]) -> str | None:
    company = resolve_entry_ref(index, entry, "*company")
    if company is not None:
        url = company.get("url")
        if isinstance(url, str):
            return url
        universal = company.get("universalName")
        if isinstance(universal, str):
            return f"https://www.linkedin.com/company/{universal}/"
    company_obj = entry.get("company")
    if isinstance(company_obj, dict):
        url = company_obj.get("url")
        if isinstance(url, str):
            return url
    url = entry.get("companyUrl")
    return url if isinstance(url, str) else None


def _school_url(entry: dict[str, Any], index: dict[str, dict[str, Any]]) -> str | None:
    school = resolve_entry_ref(index, entry, "*school")
    if school is not None:
        url = school.get("url")
        if isinstance(url, str):
            return url
    school_obj = entry.get("school")
    if isinstance(school_obj, dict):
        url = school_obj.get("url")
        if isinstance(url, str):
            return url
    return None
