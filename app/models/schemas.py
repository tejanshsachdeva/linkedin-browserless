"""
Data contract for the API.

Keeping this in one place means the parsers, the service layer, and the
API layer all agree on shape. If LinkedIn adds/removes a field on their
profile page, this is the one file that defines what we promise callers.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ImageRenditions(BaseModel):
    primary: Optional[str] = None
    renditions: Dict[str, str] = Field(default_factory=dict)


class ProfileImages(BaseModel):
    profile_picture: Optional[ImageRenditions] = None
    background_image: Optional[ImageRenditions] = None


class ExperienceItem(BaseModel):
    title: Optional[str] = None
    company: Optional[str] = None
    company_url: Optional[str] = None
    employment_type: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    duration: Optional[str] = None
    description: Optional[str] = None


class EducationItem(BaseModel):
    school: Optional[str] = None
    school_url: Optional[str] = None
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = None


class CertificationItem(BaseModel):
    name: Optional[str] = None
    issuing_organization: Optional[str] = None
    issue_date: Optional[str] = None
    credential_id: Optional[str] = None
    credential_url: Optional[str] = None


class LanguageItem(BaseModel):
    name: Optional[str] = None
    proficiency: Optional[str] = None


class OpenToWork(BaseModel):
    headline: Optional[str] = None
    detail: Optional[str] = None


class SectionStatus(str, Enum):
    OK = "ok"
    NOT_PRESENT = "not_present"
    FETCH_FAILED = "fetch_failed"
    NOT_IMPLEMENTED = "not_implemented"


class AsyncSectionDescriptor(BaseModel):
    """SDUI async component request extracted from initial HTML (Phase 2 bridge)."""

    new_component_id: str
    requested_arguments: Dict[str, Any] = Field(default_factory=dict)
    viewee_profile_id: Optional[str] = None
    profile_component_state: Optional[Dict[str, Any]] = None


class ProfileResponse(BaseModel):
    source_url: str
    profile_id: Optional[str] = None
    member_urn: Optional[str] = None
    name: Optional[str] = None
    headline: Optional[str] = None
    location: Optional[str] = None
    pronouns: Optional[str] = None
    connection_degree: Optional[str] = None
    connections_count: Optional[str] = None
    current_company: Optional[str] = None
    current_school: Optional[str] = None
    open_to_work: Optional[OpenToWork] = None
    about: Optional[str] = None
    images: ProfileImages = Field(default_factory=ProfileImages)
    experience: List[ExperienceItem] = Field(default_factory=list)
    education: List[EducationItem] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    certifications: List[CertificationItem] = Field(default_factory=list)
    languages: List[LanguageItem] = Field(default_factory=list)
    scraped_at: datetime
    partial: bool = False  # True only when a section fetch failed or was not implemented
    missing_sections: List[str] = Field(
        default_factory=list,
        description="Sections with fetch_failed or not_implemented status (excludes not_present).",
    )
    section_status: Dict[str, SectionStatus] = Field(default_factory=dict)
    data_tiers: Dict[str, str] = Field(default_factory=dict)
    field_sources: Dict[str, str] = Field(default_factory=dict)
    field_conflicts: List[str] = Field(default_factory=list)
    sdui_descriptors: Optional[List[AsyncSectionDescriptor]] = None


class ProfileRequest(BaseModel):
    url: str = Field(..., description="Full LinkedIn profile URL")


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
