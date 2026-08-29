"""Unit tests for Voyager decoration auto-discovery."""

from app.parsing.decoration_discovery import (
    build_decoration_candidates,
    decoration_id,
    discover_decoration_version,
)


def test_discover_decoration_version_from_html():
    html = 'config:"com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-76"'
    assert discover_decoration_version(html) == 76


def test_discover_decoration_version_picks_highest():
    html = "FullProfileWithEntities-74 and FullProfileWithEntities-76"
    assert discover_decoration_version(html) == 76


def test_discover_decoration_version_returns_none_when_absent():
    assert discover_decoration_version("<html><body>no decoration</body></html>") is None


def test_build_candidates_prefers_discovered_then_cached_then_fallbacks():
    html = "FullProfileWithEntities-77"
    candidates = build_decoration_candidates(html, cached_version=76)
    assert candidates[0] == decoration_id(77)
    assert decoration_id(76) in candidates
    assert decoration_id(75) in candidates


def test_build_candidates_uses_fallbacks_when_html_has_no_decoration():
    candidates = build_decoration_candidates(None, cached_version=76)
    assert candidates[0] == decoration_id(76)
    assert decoration_id(75) in candidates
