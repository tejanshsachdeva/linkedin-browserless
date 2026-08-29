"""Pass A unit tests for rehydration_parser."""

from app.parsing.rehydration_parser import parse_rehydration

REHYDRATION_HTML = """
<html>
<body>
<script id="rehydrate-data">
"AsyncComponentRequest",{"newComponentId":"com.linkedin.sdui.generated.profile.dsl.impl.profileCardsExperienceOnly","requestedArguments":{"payload":{"vanityName":"jane-doe"}},"vieweeProfileId":"ACoAA123"},
"AsyncComponentRequest",{"newComponentId":"com.linkedin.sdui.generated.profile.dsl.impl.profileCardsBelowActivityPart2","requestedArguments":{}}
</script>
</body>
</html>
"""

FALLBACK_HTML = """
<html><body>
<script id="rehydrate-data">
{"newComponentId":"com.linkedin.sdui.generated.profile.dsl.impl.profileCardsExperienceOnly"}
</script>
</body></html>
"""

def _flight_escaped_html() -> str:
    inner = (
        '{"$type":"proto.sdui.actions.core.AsyncComponentRequest",'
        '"newComponentId":"com.linkedin.sdui.generated.profile.dsl.impl.profileCardsExperienceOnly",'
        '"requestedArguments":{"payload":{"vanityName":"jane-doe","vieweeProfileId":"ACoAA123"}}}'
    )
    escaped = inner.replace('"', '\\"')
    return f"""
<html><body>
<script id="rehydrate-data">window.__como_rehydration__ = [ "{escaped}" ];</script>
</body></html>
"""


def test_extracts_from_escaped_flight_blob():
    descriptors = parse_rehydration(_flight_escaped_html())
    assert len(descriptors) == 1
    assert descriptors[0].new_component_id.endswith("profileCardsExperienceOnly")
    assert descriptors[0].viewee_profile_id == "ACoAA123"


def test_extracts_async_component_descriptors():
    descriptors = parse_rehydration(REHYDRATION_HTML)
    component_ids = {d.new_component_id for d in descriptors}
    assert "com.linkedin.sdui.generated.profile.dsl.impl.profileCardsExperienceOnly" in component_ids


def test_extracts_viewee_profile_id():
    descriptors = parse_rehydration(REHYDRATION_HTML)
    exp = next(
        d
        for d in descriptors
        if d.new_component_id.endswith("profileCardsExperienceOnly")
    )
    assert exp.viewee_profile_id == "ACoAA123"


def test_fallback_scan_finds_component_ids():
    descriptors = parse_rehydration(FALLBACK_HTML)
    assert len(descriptors) >= 1
    assert any("profileCardsExperienceOnly" in d.new_component_id for d in descriptors)


def test_empty_html_returns_empty_list():
    assert parse_rehydration("<html></html>") == []
