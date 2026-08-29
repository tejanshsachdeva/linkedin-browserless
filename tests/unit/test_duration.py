"""Unit tests for duration computation."""

from app.parsing.duration import compute_duration


def test_compute_duration_current_role():
    assert compute_duration("Jan 2025", None) is not None
    assert "mo" in compute_duration("Jan 2025", None) or "yr" in compute_duration("Jan 2025", None)


def test_compute_duration_completed_role():
    assert compute_duration("Jan 2023", "Jun 2025") == "2 yrs 6 mos"


def test_compute_duration_year_only():
    assert compute_duration("2020", "2024") == "4 yrs"
