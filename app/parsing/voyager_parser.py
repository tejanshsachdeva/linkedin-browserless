"""Parse Voyager FullProfileWithEntities normalized JSON."""

from __future__ import annotations

import html
import re
from typing import Any

from app.models.schemas import CertificationItem, EducationItem, ExperienceItem, LanguageItem

PROFILE_URN = "fsd_profile:"
POSITION_URN = "fsd_profilePosition:"
EDUCATION_URN = "fsd_profileEducation:"
SKILL_URN = "fsd_skill:"
CERTIFICATION_URN = "fsd_profileCertification:"
LANGUAGE_URN = "fsd_profileLanguage:"

_MONTH_RE = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})$")


def parse_voyager_profile(payload: dict[str, Any]) -> dict[str, Any]:
    included = payload.get("included", [])
    if not isinstance(included, list):
        included = []

    experience = parse_experience_from_voyager(included)
    return {
        "about": parse_about_from_voyager(included),
        "experience": experience,
        "education": parse_education_from_voyager(included),
        "skills": parse_skills_from_voyager(included),
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


def parse_experience_from_voyager(included: list[Any]) -> list[ExperienceItem]:
    items: list[ExperienceItem] = []
    for entry in included:
        if not isinstance(entry, dict):
            continue
        urn = entry.get("entityUrn", "")
        if POSITION_URN not in urn or not entry.get("title"):
            continue
        items.append(
            ExperienceItem(
                title=_clean_text(entry.get("title")),
                company=_clean_text(entry.get("companyName")),
                company_url=_company_url(entry),
                employment_type=_employment_type(entry),
                location=_location_text(entry.get("locationName") or entry.get("geoLocationName")),
                start_date=_format_date(entry, "start"),
                end_date=_format_date(entry, "end"),
                description=_clean_text(entry.get("description")),
            )
        )
    return _sort_experience(items)


def parse_education_from_voyager(included: list[Any]) -> list[EducationItem]:
    items: list[EducationItem] = []
    for entry in included:
        if not isinstance(entry, dict):
            continue
        urn = entry.get("entityUrn", "")
        if EDUCATION_URN not in urn:
            continue
        school = entry.get("schoolName")
        if not school:
            continue
        items.append(
            EducationItem(
                school=school,
                school_url=_school_url(entry),
                degree=entry.get("degreeName"),
                field_of_study=entry.get("fieldOfStudy"),
                start_date=_format_date(entry, "start"),
                end_date=_format_date(entry, "end"),
                description=entry.get("description"),
            )
        )
    return items


def parse_skills_from_voyager(included: list[Any]) -> list[str]:
    skills: list[str] = []
    seen: set[str] = set()
    for entry in included:
        if not isinstance(entry, dict):
            continue
        urn = entry.get("entityUrn", "")
        if SKILL_URN not in urn:
            continue
        name = entry.get("name") or entry.get("skillName")
        if isinstance(name, str) and name not in seen:
            seen.add(name)
            skills.append(name)
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
                proficiency=proficiency if isinstance(proficiency, str) else None,
            )
        )
    return items


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


def _location_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("defaultLocalizedName") or value.get("name")
    return None


def _employment_type(entry: dict[str, Any]) -> str | None:
    value = entry.get("employmentType")
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("name") or value.get("localizedName")
    return None


def _company_url(entry: dict[str, Any]) -> str | None:
    company = entry.get("company")
    if isinstance(company, dict):
        url = company.get("url")
        if isinstance(url, str):
            return url
    url = entry.get("companyUrl")
    return url if isinstance(url, str) else None


def _school_url(entry: dict[str, Any]) -> str | None:
    school = entry.get("school")
    if isinstance(school, dict):
        url = school.get("url")
        if isinstance(url, str):
            return url
    return None
