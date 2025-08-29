import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Generic, List, Optional, TypeVar
import aiohttp
import logging

T = TypeVar("T")

class BaseCrawler(Generic[T]):
    def __init__(self, cache_ttl: timedelta = timedelta(hours=1)):
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache: Dict[str, List[T]] = {}
        self.last_crawl: Dict[str, datetime] = {}
        self.cache_ttl = cache_ttl
        self.log = logging.getLogger(self.__class__.__name__)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        return self.session

    # Backwards-compatible: keep create_session but delegate
    async def create_session(self):
        await self._ensure_session()

    async def close_session(self):
        if self.session and not self.session.closed:
            try:
                await self.session.close()
            except Exception as e:
                self.log.debug("Error closing session: %r", e)
        self.session = None  # clear reference

    def is_cache_valid(self, key: str) -> bool:
        ts = self.last_crawl.get(key)
        return bool(ts and (datetime.now(timezone.utc) - ts) < self.cache_ttl)

    async def get_text(self, url: str, **kwargs) -> Optional[str]:
        session = await self._ensure_session()
        try:
            async with session.get(url, **kwargs) as resp:
                if resp.status != 200:
                    self.log.warning("GET %s -> %s", url, resp.status)
                    return None
                return await resp.text()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.log.warning("GET %s failed: %r", url, e)
            return None

    async def sleep_polite(self, seconds: float = 0.1):
        await asyncio.sleep(seconds)

    # Optional convenience to use crawlers with "async with"
    async def __aenter__(self):
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close_session()