from typing import Optional

from app.cache.base import CacheBackend


class RedisCache(CacheBackend):
    """
    Redis-backed cache for when the API runs as multiple instances
    behind a load balancer and needs a shared cache. Only imported/used
    if CACHE_BACKEND=redis, so `redis` isn't a hard dependency for
    people running the simple single-instance setup.
    """

    def __init__(self, redis_url: str):
        import redis.asyncio as redis  # local import: optional dependency

        self._client = redis.from_url(redis_url, decode_responses=True)

    async def get(self, key: str) -> Optional[str]:
        return await self._client.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self._client.set(key, value, ex=ttl_seconds)
