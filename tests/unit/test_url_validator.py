import pytest

from app.exceptions import InvalidProfileUrlError
from app.utils.url_validator import extract_public_id, normalize_profile_url


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://www.linkedin.com/in/jane-doe", "https://www.linkedin.com/in/jane-doe"),
        ("http://linkedin.com/in/jane-doe/", "https://www.linkedin.com/in/jane-doe"),
        ("linkedin.com/in/jane-doe", "https://www.linkedin.com/in/jane-doe"),
        (
            "https://www.linkedin.com/in/jane-doe?trk=nav_profile",
            "https://www.linkedin.com/in/jane-doe",
        ),
    ],
)
def test_normalize_valid_urls(raw, expected):
    assert normalize_profile_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "https://example.com/in/jane-doe",
        "https://www.linkedin.com/company/acme",
        "https://www.linkedin.com/jobs/view/12345",
        "not a url at all",
    ],
)
def test_normalize_invalid_urls_raise(raw):
    with pytest.raises(InvalidProfileUrlError):
        normalize_profile_url(raw)


def test_extract_public_id():
    assert extract_public_id("https://www.linkedin.com/in/jane-doe") == "jane-doe"
