import asyncio
from contextlib import asynccontextmanager


class ScrapeThrottle:
    """
    Bounds how many profile scrape operations run concurrently against
    the same LinkedIn session.

    LinkedIn is far more likely to flag a session that fires many parallel
    HTTP requests than one that works through a queue.
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
