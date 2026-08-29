"""Merge Tier A + Tier B parsed data into ProfileResponse."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.models.schemas import (
    AsyncSectionDescriptor,
    CertificationItem,
    EducationItem,
    ExperienceItem,
    LanguageItem,
    ProfileImages,
    ProfileResponse,
    SectionStatus,
)
from app.parsing.html_parser import TopCardData

logger = logging.getLogger(__name__)

DETAIL_SECTIONS = (
    "about",
    "experience",
    "education",
    "skills",
    "certifications",
    "languages",
)


def assemble(
    top_card: TopCardData,
    descriptors: list[AsyncSectionDescriptor],
    source_url: str,
    include_debug: bool = False,
    *,
    about: Optional[str] = None,
    experience: Optional[list[ExperienceItem]] = None,
    education: Optional[list[EducationItem]] = None,
    skills: Optional[list[str]] = None,
    certifications: Optional[list[CertificationItem]] = None,
    languages: Optional[list[LanguageItem]] = None,
    section_status: Optional[dict[str, SectionStatus]] = None,
) -> ProfileResponse:
    experience = experience or []
    education = education or []
    skills = skills or []
    certifications = certifications or []
    languages = languages or []

    status: dict[str, SectionStatus] = {
        section: SectionStatus.NOT_IMPLEMENTED for section in DETAIL_SECTIONS
    }
    if section_status:
        status.update(section_status)

    if experience and status.get("experience") == SectionStatus.NOT_IMPLEMENTED:
        status["experience"] = SectionStatus.OK
    if education and status.get("education") == SectionStatus.NOT_IMPLEMENTED:
        status["education"] = SectionStatus.OK
    if skills and status.get("skills") == SectionStatus.NOT_IMPLEMENTED:
        status["skills"] = SectionStatus.OK
    if about and status.get("about") == SectionStatus.NOT_IMPLEMENTED:
        status["about"] = SectionStatus.OK
    if certifications and status.get("certifications") == SectionStatus.NOT_IMPLEMENTED:
        status["certifications"] = SectionStatus.OK
    if languages and status.get("languages") == SectionStatus.NOT_IMPLEMENTED:
        status["languages"] = SectionStatus.OK

    field_sources, field_conflicts, current_company, current_school = _resolve_field_provenance(
        top_card,
        about=about,
        experience=experience,
        education=education,
        skills=skills,
        certifications=certifications,
        languages=languages,
    )

    missing_sections: list[str] = []
    for section in DETAIL_SECTIONS:
        section_state = status.get(section)
        if section_state in (SectionStatus.FETCH_FAILED, SectionStatus.NOT_IMPLEMENTED):
            missing_sections.append(section)

    has_detail_data = bool(about or experience or education or skills or certifications or languages)
    any_fetch_failed = any(status.get(s) == SectionStatus.FETCH_FAILED for s in DETAIL_SECTIONS)
    any_not_implemented = any(
        status.get(s) == SectionStatus.NOT_IMPLEMENTED for s in DETAIL_SECTIONS
    )

    if not has_detail_data and any_not_implemented and not section_status:
        detail_tier = "not_implemented"
    elif any_fetch_failed or (any_not_implemented and section_status):
        detail_tier = "partial"
    elif has_detail_data or section_status:
        detail_tier = "ok"
    else:
        detail_tier = "not_implemented"

    partial = bool(missing_sections)

    images = ProfileImages(
        profile_picture=top_card.profile_picture,
        background_image=top_card.background_image,
    )

    return ProfileResponse(
        source_url=source_url,
        profile_id=top_card.profile_id,
        member_urn=top_card.member_urn,
        name=top_card.name,
        headline=top_card.headline,
        location=top_card.location,
        pronouns=top_card.pronouns,
        connection_degree=top_card.connection_degree,
        connections_count=top_card.connections_count,
        current_company=current_company,
        current_school=current_school,
        open_to_work=top_card.open_to_work,
        about=about,
        images=images,
        experience=experience,
        education=education,
        skills=skills,
        certifications=certifications,
        languages=languages,
        scraped_at=datetime.now(timezone.utc),
        partial=partial,
        missing_sections=missing_sections,
        section_status=status,
        data_tiers={"top_card": "ok", "detail_sections": detail_tier},
        field_sources=field_sources,
        field_conflicts=field_conflicts,
        sdui_descriptors=descriptors if include_debug else None,
    )


def _resolve_field_provenance(
    top_card: TopCardData,
    *,
    about: Optional[str],
    experience: list[ExperienceItem],
    education: list[EducationItem],
    skills: list[str],
    certifications: list[CertificationItem],
    languages: list[LanguageItem],
) -> tuple[dict[str, str], list[str], Optional[str], Optional[str]]:
    """
    Build field_sources and resolve overlapping HTML vs Voyager values.
    Voyager wins on conflict; conflicts are logged and returned in field_conflicts.
    """
    sources: dict[str, str] = {}
    conflicts: list[str] = []

    html_fields = {
        "name": top_card.name,
        "headline": top_card.headline,
        "location": top_card.location,
        "pronouns": top_card.pronouns,
        "connection_degree": top_card.connection_degree,
        "connections_count": top_card.connections_count,
        "open_to_work": top_card.open_to_work,
        "profile_id": top_card.profile_id,
        "member_urn": top_card.member_urn,
    }
    for field, value in html_fields.items():
        if value is not None and value != "" and value != []:
            sources[field] = "html"

    if top_card.profile_picture or top_card.background_image:
        sources["images"] = "html"

    if about:
        sources["about"] = "voyager"
    if experience:
        sources["experience"] = "voyager"
    if education:
        sources["education"] = "voyager"
    if skills:
        sources["skills"] = "voyager"
    if certifications:
        sources["certifications"] = "voyager"
    if languages:
        sources["languages"] = "voyager"

    html_company = top_card.current_company
    voyager_company = experience[0].company if experience else None
    current_company = _pick_with_precedence(
        field="current_company",
        html_value=html_company,
        voyager_value=voyager_company,
        sources=sources,
        conflicts=conflicts,
    )

    html_school = top_card.current_school
    voyager_school = education[0].school if education else None
    current_school = _pick_with_precedence(
        field="current_school",
        html_value=html_school,
        voyager_value=voyager_school,
        sources=sources,
        conflicts=conflicts,
    )

    return sources, conflicts, current_company, current_school


def _pick_with_precedence(
    *,
    field: str,
    html_value: Optional[str],
    voyager_value: Optional[str],
    sources: dict[str, str],
    conflicts: list[str],
) -> Optional[str]:
    if voyager_value and html_value and voyager_value != html_value:
        conflicts.append(field)
        logger.warning(
            "Field conflict for %s: html=%r voyager=%r; using voyager",
            field,
            html_value,
            voyager_value,
        )
    if voyager_value:
        sources[field] = "voyager"
        return voyager_value
    if html_value:
        sources[field] = "html"
        return html_value
    return None
