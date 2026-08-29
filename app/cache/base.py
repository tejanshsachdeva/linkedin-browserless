from abc import ABC, abstractmethod
from typing import Optional


class CacheBackend(ABC):
    """
    Minimal cache interface. The service layer only ever talks to this,
    never to a concrete backend — so swapping in-memory for Redis in
    production is a one-line change in the dependency wiring, not a
    rewrite.
    """

    @abstractmethod
    async def get(self, key: str) -> Optional[str]:
        ...

    @abstractmethod
    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        ...
