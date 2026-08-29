"""Tests against redacted golden fixtures captured from live LinkedIn responses."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.assembler.profile_assembler import assemble
from app.parsing.decoration_discovery import discover_decoration_version
from app.parsing.html_parser import parse_top_card
from app.parsing.rehydration_parser import parse_rehydration
from app.parsing.voyager_parser import parse_voyager_profile

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture
def golden_html() -> str:
    return (FIXTURES / "profile_golden.html").read_text(encoding="utf-8")


@pytest.fixture
def golden_voyager() -> dict:
    return json.loads((FIXTURES / "voyager_golden.json").read_text(encoding="utf-8"))


def test_golden_html_discovers_decoration_version(golden_html: str):
    assert discover_decoration_version(golden_html) == 76


def test_golden_html_parses_top_card(golden_html: str):
    data = parse_top_card(golden_html)
    assert data.name == "Jordan Rivera"
    assert data.headline == "Senior Software Engineer at Acme Corp"
    assert data.location == "San Francisco, California, United States"
    assert data.current_company == "Acme Corp"
    assert data.profile_id == "ACoAAREDAC0000000001"


def test_golden_html_has_no_live_secrets(golden_html: str):
    assert "li_at=" not in golden_html.lower()
    assert "ajax:3969811343178654321" not in golden_html
    assert "REDACTED_CSRF_TOKEN" in golden_html


def test_golden_html_parses_rehydration_descriptors(golden_html: str):
    descriptors = parse_rehydration(golden_html)
    component_ids = {d.new_component_id for d in descriptors}
    assert "com.linkedin.sdui.generated.profile.dsl.impl.profileCardsExperienceOnly" in component_ids


def test_golden_voyager_parses_sections(golden_voyager: dict):
    parsed = parse_voyager_profile(golden_voyager)
    assert parsed["about"] == "Builder of data products at & scale."
    assert len(parsed["experience"]) == 2
    assert parsed["experience"][0].title == "Senior Software Engineer"
    assert parsed["education"][0].school == "Example University"
    assert parsed["skills"] == ["Python"]


def test_golden_assembler_field_sources_and_voyager_precedence(golden_html: str, golden_voyager: dict):
    top_card = parse_top_card(golden_html)
    top_card.current_school = "Legacy School From HTML"
    parsed = parse_voyager_profile(golden_voyager)

    profile = assemble(
        top_card,
        parse_rehydration(golden_html),
        "https://www.linkedin.com/in/jordan-rivera",
        about=parsed["about"],
        experience=parsed["experience"],
        education=parsed["education"],
        skills=parsed["skills"],
        certifications=parsed["certifications"],
        languages=parsed["languages"],
    )

    assert profile.field_sources["headline"] == "html"
    assert profile.field_sources["experience"] == "voyager"
    assert profile.field_sources["current_company"] == "voyager"
    assert profile.field_sources["current_school"] == "voyager"
    assert profile.current_school == "Example University"
    assert "current_school" in profile.field_conflicts
