"""Unit tests for field provenance in profile_assembler."""

from app.assembler.profile_assembler import assemble
from app.models.schemas import EducationItem, ExperienceItem, SectionStatus
from app.parsing.html_parser import TopCardData


def test_voyager_wins_current_company_conflict():
    top_card = TopCardData(
        name="Jane Doe",
        headline="Engineer at Old Co",
        current_company="Old Co",
    )
    experience = [
        ExperienceItem(title="Engineer", company="New Co"),
    ]

    profile = assemble(
        top_card,
        [],
        "https://www.linkedin.com/in/jane-doe",
        experience=experience,
    )

    assert profile.current_company == "New Co"
    assert profile.field_sources["current_company"] == "voyager"
    assert "current_company" in profile.field_conflicts


def test_html_used_when_voyager_absent():
    top_card = TopCardData(name="Jane Doe", current_company="Acme Corp")
    profile = assemble(top_card, [], "https://www.linkedin.com/in/jane-doe")
    assert profile.current_company == "Acme Corp"
    assert profile.field_sources["current_company"] == "html"
    assert profile.field_conflicts == []


def test_voyager_school_wins_over_html():
    top_card = TopCardData(name="Jane Doe", current_school="HTML School")
    education = [EducationItem(school="Voyager University")]
    profile = assemble(
        top_card,
        [],
        "https://www.linkedin.com/in/jane-doe",
        education=education,
    )
    assert profile.current_school == "Voyager University"
    assert profile.field_sources["current_school"] == "voyager"
    assert "current_school" in profile.field_conflicts


def test_not_present_sections_do_not_mark_partial():
    top_card = TopCardData(name="Jane Doe", headline="Engineer")
    profile = assemble(
        top_card,
        [],
        "https://www.linkedin.com/in/jane-doe",
        about="About text",
        experience=[ExperienceItem(title="Engineer", company="Acme")],
        section_status={
            "about": SectionStatus.OK,
            "experience": SectionStatus.OK,
            "education": SectionStatus.NOT_PRESENT,
            "skills": SectionStatus.OK,
            "certifications": SectionStatus.NOT_PRESENT,
            "languages": SectionStatus.NOT_PRESENT,
        },
    )
    assert profile.partial is False
    assert profile.missing_sections == []
    assert profile.data_tiers["detail_sections"] == "ok"
