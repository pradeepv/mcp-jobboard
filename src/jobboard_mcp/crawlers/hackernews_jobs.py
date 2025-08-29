from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup  # type: ignore

from .base import BaseCrawler
from ..models.job import JobPosting


class HackerNewsJobsCrawler(BaseCrawler[JobPosting]):
    """
    Crawler for https://news.ycombinator.com/jobs (HN Jobs board).
    Parses the jobs listing page (and optional pagination) and extracts each job story.
    """

    KEY = "hackernews_jobs"

    BASE = "https://news.ycombinator.com"
    START_URL = f"{BASE}/jobs"

    async def crawl(
        self,
        keywords: Optional[List[str]] = None,
        max_pages: int = 1,
        per_page_limit: int = 100,
    ) -> List[JobPosting]:
        if self.is_cache_valid(self.KEY) and self.KEY in self.cache:
            return self._filter(self.cache[self.KEY], keywords)

        jobs: List[JobPosting] = []
        next_url: Optional[str] = self.START_URL
        pages = 0

        while next_url and pages < max_pages:
            html_text = await self.get_text(next_url)
            if not html_text:
                break

            soup = BeautifulSoup(html_text, "html.parser")

            page_jobs = self._parse_jobs_page(soup, per_page_limit=max(0, per_page_limit - len(jobs)))
            jobs.extend(page_jobs)

            if per_page_limit and len(jobs) >= per_page_limit:
                break

            more = soup.select_one("a.morelink")
            if more and more.get("href"):
                next_url = urljoin(self.BASE + "/", more["href"])
                pages += 1
                await self.sleep_polite(0.2)
            else:
                next_url = None

        self.cache[self.KEY] = jobs
        self.last_crawl[self.KEY] = datetime.now(timezone.utc)
        return self._filter(jobs, keywords)

    def _parse_jobs_page(self, soup: BeautifulSoup, per_page_limit: int) -> List[JobPosting]:
        jobs: List[JobPosting] = []

        rows = soup.select("tr.athing")
        for row in rows:
            if per_page_limit and len(jobs) >= per_page_limit:
                break

            titleline = row.select_one("span.titleline")
            if not titleline:
                continue

            title_a = titleline.select_one("a")
            if not title_a:
                continue

            title_text = title_a.get_text(strip=True)
            story_url = title_a.get("href") or ""
            item_id = (row.get("id") or "").strip()

            company, title, location = self._guess_fields_from_title(title_text)

            sitebit = titleline.select_one(".sitestr")
            site_str = sitebit.get_text(strip=True) if sitebit else ""

            tags: List[str] = []
            if company:
                m = re.search(r"\((YC\s+[SW]\d{2})\)", company, flags=re.I)
                if m:
                    tags.append(m.group(1).upper())
                    company = re.sub(r"\s*\((YC\s+[SW]\d{2})\)\s*", "", company, flags=re.I).strip()

            title_low = title_text.lower()
            remote_ok = any(
                k in title_low
                for k in ["remote", "remotely", "anywhere", "distributed", "work from home", "wfh", "us-remote", "remote-us"]
            )

            hn_link = f"{self.BASE}/item?id={item_id}" if item_id else ""

            jobs.append(
                JobPosting(
                    id=item_id or None,
                    source="Hacker News Jobs",
                    url=story_url if story_url and not story_url.startswith("item?id=") else hn_link,
                    title=title or title_text,
                    company=company or "Unknown",
                    location=location or "Unknown",
                    description="",
                    posted_date=None,
                    salary=None,
                    job_type=None,
                    remote_ok=remote_ok,
                    requirements=[],
                    seniority=None,
                    tags=tags,
                    raw_html=str(row),
                    source_key=self.KEY,
                )
            )

        return jobs

    def _guess_fields_from_title(self, text: str):
        t = (text or "").strip()
        if not t:
            return None, "", None

        company: Optional[str] = None
        title: str = t
        location: Optional[str] = None

        parens = re.findall(r"\(([^)]+)\)", t)

        loc_tokens = {
            "remote", "us", "usa", "united states", "uk", "london", "nyc", "sf", "san francisco",
            "berlin", "europe", "eu", "canada", "toronto", "vancouver", "australia", "singapore",
            "boston", "seattle", "la", "los angeles", "austin", "dublin", "paris", "amsterdam"
        }

        def looks_like_location(s: str) -> bool:
            s_low = s.strip().lower()
            if not s_low:
                return False
            if s_low.startswith("yc "):
                return False
            if any(tok in s_low for tok in loc_tokens):
                return True
            if len(s_low) <= 6 and s_low.replace("/", "").replace("-", "").isalpha():
                return True
            return False

        last_loc = None
        for grp in reversed(parens):
            if looks_like_location(grp):
                last_loc = grp.strip()
                break

        m = re.match(r"^\s*(.+?)\s+is\s+hiring\s+(.+?)\s*$", t, re.I)
        if m:
            company = m.group(1).strip()
            title = m.group(2).strip()
            if last_loc:
                location = last_loc
            return company, title, location

        m = re.match(r"^\s*(.+?)\s+at\s+(.+?)\s*$", t, re.I)
        if m:
            title = m.group(1).strip()
            company = m.group(2).strip()
            if last_loc:
                location = last_loc
            return company, title, location

        m = re.match(r"^\s*(.+?)\s+hiring\s+(.+?)\s*$", t, re.I)
        if m:
            company = m.group(1).strip()
            title = m.group(2).strip()
            if last_loc:
                location = last_loc
            return company, title, location

        if last_loc:
            location = last_loc

        return company, title, location

    def _filter(self, jobs: List[JobPosting], keywords: Optional[List[str]]) -> List[JobPosting]:
        if not keywords:
            return jobs
        low = [k.lower() for k in keywords]
        out: List[JobPosting] = []
        for j in jobs:
            blob = f"{j.title} {j.company}".lower()
            if any(k in blob for k in low):
                out.append(j)
        return out