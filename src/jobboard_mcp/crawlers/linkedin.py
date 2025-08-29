from typing import List, Optional
from .base import BaseCrawler
from ..models.job import JobPosting
import logging

class LinkedInCrawler(BaseCrawler[JobPosting]):
    KEY = "linkedin"
    log = logging.getLogger("LinkedInCrawler")

    async def crawl(self, keywords: Optional[List[str]] = None, location: str = "United States") -> List[JobPosting]:
        if self.is_cache_valid(self.KEY) and self.KEY in self.cache:
            return self._filter(self.cache[self.KEY], keywords)

        self.log.warning("LinkedIn scraping is limited; returning mock data. Consider official APIs.")
        jobs = [
            JobPosting(
                title="Senior Software Engineer",
                company="Tech Company",
                location="San Francisco, CA",
                description="LinkedIn job posting - authentication required for full access",
                url="https://linkedin.com/jobs/",
                source="LinkedIn (Limited Access)",
                remote_ok=True,
            )
        ]
        self.cache[self.KEY] = jobs
        from datetime import datetime
        self.last_crawl[self.KEY] = datetime.now()
        return self._filter(jobs, keywords)

    def _filter(self, jobs: List[JobPosting], keywords: Optional[List[str]]) -> List[JobPosting]:
        if not keywords:
            return jobs
        low = [k.lower() for k in keywords]
        return [j for j in jobs if any(k in f"{j.title} {j.company}".lower() for k in low)]