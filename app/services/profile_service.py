import asyncio
import logging
import random

from app.assembler.profile_assembler import assemble
from app.cache.base import CacheBackend
from app.client.linkedin_client import LinkedInClient
from app.models.schemas import ProfileResponse, SectionStatus
from app.parsing.html_parser import parse_top_card
from app.parsing.rehydration_parser import parse_rehydration
from app.parsing.voyager_parser import parse_voyager_profile
from app.utils.rate_limiter import ScrapeThrottle
from app.utils.url_validator import extract_public_id, normalize_profile_url

logger = logging.getLogger(__name__)


class ProfileService:
    """
    The one class the API layer talks to. Everything below this
    (caching, rate limiting, HTTP client, parsing) is an implementation
    detail the endpoint doesn't need to know about.
    """

    def __init__(
        self,
        client: LinkedInClient,
        cache: CacheBackend,
        throttle: ScrapeThrottle,
        cache_ttl_seconds: int,
        include_debug: bool = False,
        *,
        section_fetch_concurrency: int = 3,
        section_fetch_delay_ms: int = 600,
    ):
        self._client = client
        self._cache = cache
        self._throttle = throttle
        self._cache_ttl_seconds = cache_ttl_seconds
        self._include_debug = include_debug
        self._section_sem = asyncio.Semaphore(section_fetch_concurrency)
        self._section_fetch_delay_ms = section_fetch_delay_ms

    async def get_profile(self, raw_url: str, force_refresh: bool = False) -> ProfileResponse:
        canonical_url = normalize_profile_url(raw_url)
        vanity = extract_public_id(canonical_url)
        cache_key = f"profile:{vanity}"

        if not force_refresh:
            cached = await self._cache.get(cache_key)
            if cached:
                logger.info("Cache hit for %s", canonical_url)
                return ProfileResponse.model_validate_json(cached)

        async with self._throttle.slot():
            logger.info("Fetching profile HTML for %s", canonical_url)
            html = await self._client.fetch_profile_html(vanity)
            top_card = parse_top_card(html)
            descriptors = parse_rehydration(html)

            sections = await self._fetch_detail_sections(vanity)

            profile = assemble(
                top_card,
                descriptors,
                canonical_url,
                include_debug=self._include_debug,
                about=sections["about"],
                experience=sections["experience"],
                education=sections["education"],
                skills=sections["skills"],
                certifications=sections["certifications"],
                languages=sections["languages"],
                section_status=sections["section_status"],
            )

        await self._cache.set(cache_key, profile.model_dump_json(), self._cache_ttl_seconds)
        return profile

    async def _fetch_detail_sections(self, vanity: str) -> dict[str, object]:
        async with self._section_sem:
            if self._section_fetch_delay_ms > 0:
                jitter = random.uniform(0.5, 1.5)
                await asyncio.sleep(self._section_fetch_delay_ms * jitter / 1000)

            section_status: dict[str, SectionStatus] = {
                "about": SectionStatus.FETCH_FAILED,
                "experience": SectionStatus.FETCH_FAILED,
                "education": SectionStatus.FETCH_FAILED,
                "skills": SectionStatus.FETCH_FAILED,
                "certifications": SectionStatus.FETCH_FAILED,
                "languages": SectionStatus.FETCH_FAILED,
            }

            try:
                payload = await self._client.fetch_voyager_profile_sections(vanity)
                parsed = parse_voyager_profile(payload)

                section_status["about"] = (
                    SectionStatus.OK if parsed["about"] else SectionStatus.NOT_PRESENT
                )
                section_status["experience"] = (
                    SectionStatus.OK if parsed["experience"] else SectionStatus.NOT_PRESENT
                )
                section_status["education"] = (
                    SectionStatus.OK if parsed["education"] else SectionStatus.NOT_PRESENT
                )
                section_status["skills"] = (
                    SectionStatus.OK if parsed["skills"] else SectionStatus.NOT_PRESENT
                )
                section_status["certifications"] = (
                    SectionStatus.OK if parsed["certifications"] else SectionStatus.NOT_PRESENT
                )
                section_status["languages"] = (
                    SectionStatus.OK if parsed["languages"] else SectionStatus.NOT_PRESENT
                )

                return {
                    "about": parsed["about"],
                    "experience": parsed["experience"],
                    "education": parsed["education"],
                    "skills": parsed["skills"],
                    "certifications": parsed["certifications"],
                    "languages": parsed["languages"],
                    "section_status": section_status,
                }
            except Exception as exc:
                logger.warning("Detail section fetch failed for %s: %s", vanity, exc)
                return {
                    "about": None,
                    "experience": [],
                    "education": [],
                    "skills": [],
                    "certifications": [],
                    "languages": [],
                    "section_status": section_status,
                }
