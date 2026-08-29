import asyncio
import time
from typing import Dict, Optional, Tuple

from app.cache.base import CacheBackend


class InMemoryCache(CacheBackend):
    """
    Process-local TTL cache. Fine for a single-instance deployment or
    local dev. If you scale to multiple API instances, swap this for
    RedisCache (app/cache/redis_cache.py) via config — the interface
    is identical, so nothing else changes.
    """

    def __init__(self):
        self._store: Dict[str, Tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[str]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        async with self._lock:
            self._store[key] = (value, time.monotonic() + ttl_seconds)
