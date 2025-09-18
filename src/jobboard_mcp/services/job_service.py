from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..models.job import JobPosting
from ..crawlers.ycombinator import YCombinatorCrawler
from ..crawlers.hackernews import HackerNewsCrawler
from ..crawlers.workatastartup import WorkAtStartupCrawler


class JobService:
    """
    Facade for aggregating jobs from multiple crawlers.
    """

    def __init__(self) -> None:
        self.yc = YCombinatorCrawler()
        self.hn = HackerNewsCrawler()
        self.waas = WorkAtStartupCrawler()
        self._crawlers = {
            "ycombinator": self.yc,
            "hackernews": self.hn,
            "workatastartup": self.waas,
        }

    async def close(self) -> None:
        await asyncio.gather(*(c.close_session() for c in self._crawlers.values()), return_exceptions=True)

    async def search_jobs(
        self,
        sources: List[str],
        keywords: Optional[List[str]] = None,
        remote_only: bool = False,
        location: Optional[str] = None,
        max_pages: int = 2,
        per_source_limit: int = 100,
    ) -> Dict[str, object]:
        started_at = datetime.now(timezone.utc)
        jobs: List[JobPosting] = []
        errors: Dict[str, str] = {}
        counts: Dict[str, int] = {}

        run_sources = [s for s in sources if s in self._crawlers]
        for s in sources:
            if s not in self._crawlers:
                errors[s] = "unknown source"

        async def run_source(key: str) -> List[JobPosting]:
            try:
                if key == "ycombinator":
                    res = await self.yc.crawl(keywords=keywords, max_pages=max_pages)
                elif key == "hackernews":
                    res = await self.hn.crawl(keywords=keywords, max_pages=max_pages, per_page_limit=per_source_limit)
                elif key == "workatastartup":
                    res = await self.waas.crawl(keywords=keywords, max_pages=max_pages, per_page_limit=per_source_limit)
                else:
                    res = await self._crawlers[key].crawl(keywords=keywords)

                out: List[JobPosting] = []
                for j in res[:per_source_limit]:
                    if remote_only and not j.remote_ok:
                        continue
                    if location and location.strip():
                        if location.lower() not in f"{j.location} {j.description}".lower():
                            continue
                    out.append(j)
                counts[key] = len(out)
                return out
            except Exception as e:
                errors[key] = f"{type(e).__name__}: {e}"
                return []

        results = await asyncio.gather(*(run_source(s) for s in run_sources))
        for batch in results:
            jobs.extend(batch)

        jobs = self._dedupe_jobs(jobs)

        completed_at = datetime.now(timezone.utc)
        metadata = {
            "countsPerSource": counts,
            "errors": errors or None,
            "startedAt": started_at.isoformat(),
            "completedAt": completed_at.isoformat(),
            "total": len(jobs),
        }
        return {"jobs": jobs, "metadata": metadata}

    def _dedupe_jobs(self, jobs: List[JobPosting]) -> List[JobPosting]:
        seen = set()
        out: List[JobPosting] = []
        for j in jobs:
            key = self._canonical_key(j)
            if key in seen:
                continue
            seen.add(key)
            out.append(j)
        return out

    def _canonical_key(self, j: JobPosting) -> str:
        url = (j.url or "").split("#", 1)[0].strip().lower()
        return f"{j.source.lower()}|{url}"