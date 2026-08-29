"""Unit tests for session cookie persistence rules."""

from httpx import Response

from app.client.session import LinkedInSession
from app.core.config import Settings


def test_should_not_persist_error_responses():
    session = LinkedInSession(
        Settings(LINKEDIN_LI_AT="test-token", LINKEDIN_JSESSIONID="ajax:1234567890123456789")
    )
    assert session.should_persist_response(Response(999, text="authwall")) is False
    assert session.should_persist_response(Response(429, text="rate limited")) is False
    assert session.should_persist_response(Response(200, text="x" * 25_000)) is True
