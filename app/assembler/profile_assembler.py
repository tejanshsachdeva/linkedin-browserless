"""Merge Tier A + Tier B parsed data into ProfileResponse."""

from __future__ import annotations

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

    missing_sections: list[str] = []
    for section in DETAIL_SECTIONS:
        if status.get(section) not in (SectionStatus.OK, SectionStatus.NOT_PRESENT):
            missing_sections.append(section)
        elif status.get(section) == SectionStatus.NOT_PRESENT and section in (
            "experience",
            "education",
            "skills",
            "about",
            "certifications",
            "languages",
        ):
            missing_sections.append(section)

    detail_tier = "not_implemented"
    if about or experience or education or skills or certifications or languages:
        detail_tier = "partial" if missing_sections else "ok"

    if education and not top_card.current_school and education[0].school:
        top_card.current_school = education[0].school

    partial = bool(missing_sections) or detail_tier != "ok"

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
        current_company=top_card.current_company,
        current_school=top_card.current_school,
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
        sdui_descriptors=descriptors if include_debug else None,
    )
