from typing import List, Optional
from bs4 import BeautifulSoup
from .base import BaseCrawler
from ..models.job import JobPosting

class TechCrunchCrawler(BaseCrawler[JobPosting]):
    KEY = "techcrunch"

    async def crawl(self, keywords: Optional[List[str]] = None) -> List[JobPosting]:
        if self.is_cache_valid(self.KEY) and self.KEY in self.cache:
            return self._filter(self.cache[self.KEY], keywords)

        jobs: List[JobPosting] = []
        url = "https://techcrunch.com/category/startups/"
        html = await self.get_text(url)
        if html:
            soup = BeautifulSoup(html, "html.parser")
            for h2 in soup.select("h2.post-block__title")[:10]:
                a = h2.find("a")
                if not a:
                    continue
                title = a.get_text(strip=True)
                if any(k in title.lower() for k in ["hiring", "jobs", "careers", "talent", "recruit"]):
                    jobs.append(
                        JobPosting(
                            title=title,
                            company="Various",
                            location="Various",
                            description="TechCrunch article about job opportunities",
                            url=a.get("href") or url,
                            source="TechCrunch",
                        )
                    )
        self.cache[self.KEY] = jobs
        from datetime import datetime
        self.last_crawl[self.KEY] = datetime.now()
        return self._filter(jobs, keywords)

    def _filter(self, jobs: List[JobPosting], keywords: Optional[List[str]]) -> List[JobPosting]:
        if not keywords:
            return jobs
        low = [k.lower() for k in keywords]
        return [j for j in jobs if any(k in j.title.lower() for k in low)]