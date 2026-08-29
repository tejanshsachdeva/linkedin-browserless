"""Unit tests for voyager_parser."""

from app.parsing.voyager_parser import parse_voyager_profile, voyager_payload_is_usable

MINIMAL_VOYAGER_PAYLOAD = {
    "included": [
        {
            "entityUrn": "urn:li:fsd_profile:ACoAA123",
            "summary": "Builder of data products at &amp; scale.",
        },
        {
            "entityUrn": "urn:li:fsd_profilePosition:1",
            "title": "Senior Engineer",
            "companyName": "Acme Corp",
            "*company": "urn:li:fsd_company:1",
            "*employmentType": "urn:li:fsd_employmentType:1",
            "dateRange": {
                "start": {"month": 7, "year": 2025},
            },
        },
        {
            "entityUrn": "urn:li:fsd_company:1",
            "name": "Acme Corp",
            "url": "https://www.linkedin.com/company/acme-corp/",
            "universalName": "acme-corp",
        },
        {
            "entityUrn": "urn:li:fsd_employmentType:1",
            "name": "Full-time",
        },
        {
            "entityUrn": "urn:li:fsd_profilePosition:2",
            "title": "Software Developer",
            "companyName": "Example Industries",
            "dateRange": {
                "start": {"month": 1, "year": 2023},
                "end": {"month": 6, "year": 2025},
            },
        },
        {
            "entityUrn": "urn:li:fsd_profileEducation:1",
            "schoolName": "Example University",
            "degreeName": "B.S.",
            "fieldOfStudy": "Computer Science",
        },
        {
            "entityUrn": "urn:li:fsd_skill:1",
            "name": "Python",
        },
        {
            "entityUrn": "urn:li:fsd_profileCertification:(ACoAA123,1)",
            "name": "Cloud Practitioner",
            "authority": "Example Academy",
            "dateRange": {"start": {"month": 12, "year": 2023}},
            "licenseNumber": "ABC123",
            "url": "https://example.org/credentials/abc123",
        },
        {
            "entityUrn": "urn:li:fsd_profileLanguage:(ACoAA123,1)",
            "name": "English",
            "proficiency": "NATIVE_OR_BILINGUAL",
        },
    ]
}


def test_parse_full_voyager_profile():
    parsed = parse_voyager_profile(MINIMAL_VOYAGER_PAYLOAD)

    assert parsed["about"] == "Builder of data products at & scale."
    assert len(parsed["experience"]) == 2
    assert parsed["experience"][0].title == "Senior Engineer"
    assert parsed["experience"][0].end_date is None
    assert parsed["experience"][0].company_url == "https://www.linkedin.com/company/acme-corp/"
    assert parsed["experience"][0].employment_type == "Full-time"
    assert parsed["experience"][0].duration is not None
    assert len(parsed["education"]) == 1
    assert parsed["skills"] == ["Python"]
    assert len(parsed["certifications"]) == 1
    assert parsed["certifications"][0].name == "Cloud Practitioner"
    assert parsed["certifications"][0].issuing_organization == "Example Academy"
    assert parsed["certifications"][0].issue_date == "Dec 2023"
    assert parsed["certifications"][0].credential_id == "ABC123"
    assert len(parsed["languages"]) == 1
    assert parsed["languages"][0].name == "English"


def test_experience_sorted_with_current_role_first():
    parsed = parse_voyager_profile(MINIMAL_VOYAGER_PAYLOAD)
    assert parsed["experience"][0].company == "Acme Corp"
    assert parsed["experience"][1].end_date == "Jun 2025"


def test_voyager_payload_is_usable():
    assert voyager_payload_is_usable(MINIMAL_VOYAGER_PAYLOAD) is True
    assert voyager_payload_is_usable({"included": []}) is False
    assert voyager_payload_is_usable({"included": [{"entityUrn": "urn:li:other:1"}]}) is False
