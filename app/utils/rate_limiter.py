import asyncio
from contextlib import asynccontextmanager


class ScrapeThrottle:
    """
    Bounds how many browser scrape operations run concurrently against
    the *same* LinkedIn session.

    This exists for two reasons:
      1. LinkedIn is far more likely to flag a session that fires many
         parallel requests than one that works through a queue.
      2. A single Playwright browser instance can only sanely drive a
         handful of concurrent pages before memory/CPU on a small host
         becomes the bottleneck anyway.
    """

    def __init__(self, max_concurrent: int):
        self._semaphore = asyncio.Semaphore(max_concurrent)

    @asynccontextmanager
    async def slot(self):
        acquired = await self._try_acquire()
        try:
            yield
        finally:
            if acquired:
                self._semaphore.release()

    async def _try_acquire(self) -> bool:
        await self._semaphore.acquire()
        return True
