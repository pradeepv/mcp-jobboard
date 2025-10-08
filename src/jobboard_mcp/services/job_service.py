from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..models.job import JobPosting
from bs4 import BeautifulSoup  # type: ignore
from ..parsing import (
    ParserRegistry,
    YcJobParser,
    AshbyJobParser,
    LeverJobParser,
    GreenhouseJobParser,
    GenericHtmlParser,
)
from ..crawlers.base import BaseCrawler
from ..crawlers.ycombinator import YCombinatorCrawler
from ..crawlers.hackernews import HackerNewsCrawler
from ..crawlers.workatastartup import WorkAtStartupCrawler
from ..crawlers.yc_companies import YCCompaniesCrawler


class JobService:
    """
    Facade for aggregating jobs from multiple crawlers.
    """

    def __init__(self, cache_ttl_seconds: int = 600) -> None:
        self.yc = YCombinatorCrawler()
        self.hn = HackerNewsCrawler()
        self.waas = WorkAtStartupCrawler()
        self.yc_companies = YCCompaniesCrawler()
        self._crawlers = {
            "ycombinator": self.yc,
            "hackernews": self.hn,
            "workatastartup": self.waas,
            "yc_companies": self.yc_companies,
        }
        self.cache_ttl_seconds = cache_ttl_seconds
        self._instances: Dict[str, BaseCrawler] = {}
        self._domain_semaphores: Dict[str, asyncio.Semaphore] = {}
        self._global_sem = asyncio.Semaphore(10)

    async def close(self) -> None:
        """Close all crawler sessions."""
        await asyncio.gather(
            *(c.close_session() for c in self._crawlers.values()),
            return_exceptions=True,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

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
                    res = await self.hn.crawl(
                        keywords=keywords,
                        max_pages=max_pages,
                        per_page_limit=per_source_limit,
                    )
                elif key == "workatastartup":
                    res = await self.waas.crawl(
                        keywords=keywords,
                        max_pages=max_pages,
                        per_page_limit=per_source_limit,
                    )
                else:
                    res = await self._crawlers[key].crawl(keywords=keywords)

                out: List[JobPosting] = []
                for j in res[:per_source_limit]:
                    if remote_only and not j.remote_ok:
                        continue
                    if location and location.strip():
                        if (
                            location.lower()
                            not in f"{j.location} {j.description}".lower()
                        ):
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

    def _canonical_key(self, job: JobPosting) -> str:
        """Generate a canonical key for deduplication."""
        # Use URL as primary key if available
        if job.url:
            return job.url

        # Fallback to title + company combination
        return f"{job.title}@{job.company}"

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

    async def parse_job_url(self, url: str) -> JobPosting:
        """
        Parse a single job URL and extract job details.

        Args:
            url: The URL of the job posting to parse

        Returns:
            JobPosting with extracted details
        """
        from urllib.parse import urlparse

        # Check if this is a YC company job URL and prefer our YC parser path
        use_yc_parser = ('ycombinator.com/companies/' in url and '/jobs/' in url)

        # Create a temporary crawler instance for fetching the page
        crawler = BaseCrawler()
        await crawler._ensure_session()

        try:
            # Fetch the HTML content
            html_content = await crawler.get_text(url)
            if not html_content:
                # Create a basic job posting when content cannot be fetched
                parsed = urlparse(url)
                host = parsed.hostname or "unknown"
                job_posting = JobPosting(
                    url=url,
                    source=host,
                    title=f"Job at {host}",
                    company=host,
                    location="Location Not Specified",
                    description=f"Could not fetch content from {url}",
                    salary=None,
                    remote_ok=False,
                )
                return job_posting

            # Use the parser registry for YC and Ashby (and future parsers)
            soup = BeautifulSoup(html_content, "html.parser")
            registry = ParserRegistry()
            registry.register(YcJobParser())
            registry.register(AshbyJobParser())
            registry.register(LeverJobParser())
            registry.register(GreenhouseJobParser())
            registry.register(GenericHtmlParser())  # keep last so specific parsers win
            try:
                parser, det = registry.choose(url, soup)
                parsed = parser.parse(url, soup)
                description = parsed.descriptionText or parsed.descriptionHtml or ""
                if description and len(description) > 5000:
                    description = description[:5000] + "..."
                job_posting = JobPosting(
                    url=url,
                    source=parsed.source or ("Y Combinator" if use_yc_parser else ""),
                    title=parsed.title or "Job Posting",
                    company=parsed.company or "Unknown",
                    location=parsed.location or "Unknown",
                    description=description or "",
                    salary=None,
                    remote_ok=(parsed.location or "").lower().find("remote") >= 0,
                )
                return job_posting
            except Exception:
                # Fallback: old generic extractor
                job_posting = self._extract_job_details_from_html(html_content, url)
                return job_posting

        finally:
            await crawler.close_session()

    def _extract_job_details_from_html(self, html_content: str, url: str) -> JobPosting:
        """
        Extract job details from HTML content using BeautifulSoup.

        Args:
            html_content: The HTML content of the job posting page
            url: The URL of the job posting

        Returns:
            JobPosting with extracted details
        """
        try:
            from bs4 import BeautifulSoup
            import re
            from urllib.parse import urlparse

            soup = BeautifulSoup(html_content, "html.parser")

            # Extract domain for source
            parsed_url = urlparse(url)
            source = parsed_url.netloc

            # Remove common navigation/script elements
            for element in soup(["script", "style", "nav", "header", "footer"]):
                element.decompose()

            # Try to extract title (look for common title selectors)
            title = None
            title_selectors = [
                "h1",
                '[data-testid="job-title"]',
                ".job-title",
                '[class*="title"]',
                "title",
            ]

            for selector in title_selectors:
                element = soup.select_one(selector)
                if element and element.get_text(strip=True):
                    title = element.get_text(strip=True)
                    break

            # If no title found, try meta tags
            if not title:
                title_meta = soup.find("meta", attrs={"name": "title"}) or soup.find(
                    "meta", attrs={"property": "og:title"}
                )
                if title_meta:
                    title = title_meta.get("content", "")

            # Try to extract company name
            company = None
            company_selectors = [
                '[data-testid="company-name"]',
                ".company-name",
                '[class*="company"]',
                "[data-company]",
            ]

            for selector in company_selectors:
                element = soup.select_one(selector)
                if element and element.get_text(strip=True):
                    company = element.get_text(strip=True)
                    break

            # Try to extract location
            location = None
            location_selectors = [
                '[data-testid="job-location"]',
                ".job-location",
                '[class*="location"]',
                "[data-location]",
            ]

            for selector in location_selectors:
                element = soup.select_one(selector)
                if element and element.get_text(strip=True):
                    location = element.get_text(strip=True)
                    break

            # Try to extract salary
            salary = None
            salary_selectors = [
                '[data-testid="job-salary"]',
                ".job-salary",
                '[class*="salary"]',
                "[data-salary]",
            ]

            for selector in salary_selectors:
                element = soup.select_one(selector)
                if element and element.get_text(strip=True):
                    salary = element.get_text(strip=True)
                    break

            # Extract description (main content)
            description = ""
            # Look for common job description containers
            description_selectors = [
                '[data-testid="job-description"]',
                ".job-description",
                '[class*="description"]',
                '[class*="job-posting"]',
                "main",
                "article",
                ".content",
            ]

            for selector in description_selectors:
                element = soup.select_one(selector)
                if element:
                    # Get text content and clean it up
                    desc_text = element.get_text(separator=" ", strip=True)
                    if len(desc_text) > len(description):
                        description = desc_text

            # If still no description, get body text
            if not description:
                body = soup.find("body")
                if body:
                    description = body.get_text(separator=" ", strip=True)

            # Limit description length to prevent oversized responses
            if len(description) > 5000:
                description = description[:5000] + "..."

            # Create job posting object
            job_posting = JobPosting(
                url=url,
                source=source,
                title=title or "Job Posting",
                company=company or "Unknown Company",
                location=location or "Location Not Specified",
                description=description or "No description available",
                salary=salary,
                remote_ok="remote" in (description + " " + (title or "")).lower(),
            )

            print(
                f"[DEBUG] _extract_job_details_from_html returning: {type(job_posting)}",
                file=sys.stderr,
            )
            return job_posting

        except Exception as e:
            # If parsing fails, create a basic job posting with URL info
            from urllib.parse import urlparse

            parsed = urlparse(url)
            host = parsed.hostname or "unknown"

            job_posting = JobPosting(
                url=url,
                source=host,
                title=f"Job at {host}",
                company=host,
                location="Location Not Specified",
                description=f"Could not parse job details from {url}. Error: {str(e)}",
                salary=None,
                remote_ok=False,
            )

            print(
                f"[DEBUG] _extract_job_details_from_html returning fallback: {type(job_posting)}",
                file=sys.stderr,
            )
            return job_posting
