"""
Composition root: builds singleton objects once at startup and hands
them out via FastAPI dependency injection.
"""
from app.cache.base import CacheBackend
from app.cache.memory_cache import InMemoryCache
from app.client.linkedin_client import LinkedInClient
from app.client.session import LinkedInSession
from app.core.config import Settings, get_settings
from app.services.profile_service import ProfileService
from app.utils.rate_limiter import ScrapeThrottle

_linkedin_session: LinkedInSession | None = None
_linkedin_client: LinkedInClient | None = None
_profile_service: ProfileService | None = None


def build_cache(settings: Settings) -> CacheBackend:
    if settings.cache_backend == "redis":
        from app.cache.redis_cache import RedisCache

        return RedisCache(settings.redis_url)
    return InMemoryCache()


def get_linkedin_session() -> LinkedInSession:
    global _linkedin_session
    if _linkedin_session is None:
        _linkedin_session = LinkedInSession(get_settings())
    return _linkedin_session


async def get_linkedin_client() -> LinkedInClient:
    global _linkedin_client
    if _linkedin_client is None:
        _linkedin_client = LinkedInClient(get_linkedin_session())
        await _linkedin_client.start()
    return _linkedin_client


async def get_profile_service() -> ProfileService:
    global _profile_service
    if _profile_service is None:
        settings = get_settings()
        client = await get_linkedin_client()
        cache = build_cache(settings)
        throttle = ScrapeThrottle(settings.max_concurrent_scrapes)
        _profile_service = ProfileService(
            client=client,
            cache=cache,
            throttle=throttle,
            cache_ttl_seconds=settings.cache_ttl_seconds,
            include_debug=settings.include_debug,
            section_fetch_concurrency=settings.section_fetch_concurrency,
            section_fetch_delay_ms=settings.section_fetch_delay_ms,
        )
    return _profile_service


async def shutdown_clients() -> None:
    global _linkedin_client, _profile_service, _linkedin_session
    if _linkedin_client is not None:
        await _linkedin_client.close()
        _linkedin_client = None
    _profile_service = None
    _linkedin_session = None
