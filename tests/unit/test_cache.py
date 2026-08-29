import asyncio

import pytest

from app.cache.memory_cache import InMemoryCache


@pytest.mark.asyncio
async def test_set_and_get():
    cache = InMemoryCache()
    await cache.set("key", "value", ttl_seconds=60)
    assert await cache.get("key") == "value"


@pytest.mark.asyncio
async def test_missing_key_returns_none():
    cache = InMemoryCache()
    assert await cache.get("nope") is None


@pytest.mark.asyncio
async def test_expired_key_returns_none():
    cache = InMemoryCache()
    await cache.set("key", "value", ttl_seconds=0)
    await asyncio.sleep(0.01)
    assert await cache.get("key") is None
