from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Auth (required) ---
    linkedin_li_at: Optional[str] = Field(default=None, alias="LINKEDIN_LI_AT")
    linkedin_jsessionid: Optional[str] = Field(default=None, alias="LINKEDIN_JSESSIONID")
    session_state_path: str = Field(default="session_state.json", alias="SESSION_STATE_PATH")

    # --- HTTP ---
    request_timeout_seconds: int = Field(default=20, alias="REQUEST_TIMEOUT_SECONDS")
    max_concurrent_scrapes: int = Field(default=2, alias="MAX_CONCURRENT_SCRAPES")
    section_fetch_concurrency: int = Field(default=3, alias="SECTION_FETCH_CONCURRENCY")
    section_fetch_delay_ms: int = Field(default=600, alias="SECTION_FETCH_DELAY_MS")
    user_agent: Optional[str] = Field(default=None, alias="USER_AGENT")

    # --- Cache ---
    cache_backend: str = Field(default="memory", alias="CACHE_BACKEND")
    cache_ttl_seconds: int = Field(default=3600, alias="CACHE_TTL_SECONDS")
    redis_url: Optional[str] = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # --- Corporate network (optional) ---
    # A TLS-inspecting proxy re-signs HTTPS with an internal root CA that
    # Python's default trust store doesn't recognise. Point CA_BUNDLE_PATH
    # at the exported corporate root to make httpx trust it.
    ca_bundle_path: Optional[str] = Field(default=None, alias="CA_BUNDLE_PATH")
    http_proxy: Optional[str] = Field(default=None, alias="HTTP_PROXY")
    https_proxy: Optional[str] = Field(default=None, alias="HTTPS_PROXY")

    # --- API ---
    api_key: Optional[str] = Field(default=None, alias="API_KEY")
    # Separate from api_key: rotation installs a password-equivalent
    # secret and changes service behaviour, so it gets its own credential.
    # If unset, /admin/session/* refuses to serve (fails closed).
    admin_api_key: Optional[str] = Field(default=None, alias="ADMIN_API_KEY")
    enable_docs: bool = Field(default=False, alias="ENABLE_DOCS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    include_debug: bool = Field(default=False, alias="INCLUDE_DEBUG")

    @field_validator(
        "api_key",
        "admin_api_key",
        "linkedin_li_at",
        "linkedin_jsessionid",
        "ca_bundle_path",
        "http_proxy",
        "https_proxy",
        mode="before",
    )
    @classmethod
    def empty_str_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
