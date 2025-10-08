from __future__ import annotations

import asyncio
import re
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterator,
    Dict,
    List,
    Optional,
    Tuple,
    Callable,
)
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from ..crawlers.base import BaseCrawler
from ..crawlers.hackernews_jobs import HackerNewsJobsCrawler
from ..crawlers.ycombinator import YCombinatorCrawler
from ..crawlers.workatastartup import WorkAtStartupCrawler
from ..models.job import JobPosting

# --------------------
# ATS handler registry
# --------------------

ATS_HANDLER: Dict[str, Callable[[JobPosting, str], JobPosting]] = {}


def register_ats(domain: str):
    def deco(fn: Callable[[JobPosting, str], JobPosting]):
        ATS_HANDLER[domain.lower()] = fn
        return fn

    return deco


def text_collapse(text: str) -> str:
    # Collapse excessive blank lines and normalize bullets lightly
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return text.strip()


try:
    from bs4 import BeautifulSoup
except ImportError:
    raise ImportError(
        "BeautifulSoup is required but not installed. Please install it using `pip install beautifulsoup4`."
    )

# --------------------
# ATS Parsing Functions
# --------------------


@register_ats("jobs.ashbyhq.com")
@register_ats("www.ashbyhq.com")
def parse_ashby(job: JobPosting, html: str) -> JobPosting:
    soup = BeautifulSoup(html, "html.parser")

    # Remove irrelevant elements
    for sel in [
        "header",
        "nav",
        "footer",
        "[role='navigation']",
        "[role='banner']",
        "[role='contentinfo']",
    ]:
        for el in soup.select(sel):
            el.decompose()

    selectors = [
        '[data-testid="job-posting__description"]',
        '[data-test="job-posting__description"]',
        '[data-testid="job-description"]',
        ".job-posting__description",
        ".JobPosting__Description",
        ".Posting__Description",
        ".posting-description",
        ".prose",
        ".ProseMirror",
        "article",
        "main",
        ".content",
        "section",
    ]

    node = None
    for sel in selectors:
        cand = soup.select_one(sel)
        if cand and cand.get_text(strip=True):
            node = cand
            break

    def biggest_text_block(root):
        candidates = []
        for el in root.find_all(["div", "section", "article"]):
            classes = " ".join(el.get("class", [])).lower()
            if any(
                c in classes
                for c in ["header", "nav", "footer", "sidebar", "apply", "application"]
            ):
                continue
            text = el.get_text(" ", strip=True)
            if text and len(text) > 400:
                candidates.append((len(text), el))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    if not node:
        root = soup.select_one("main") or soup
        node = biggest_text_block(root) or biggest_text_block(soup)

    if node:
        for bad in node.find_all(["script", "style", "noscript"]):
            bad.decompose()
        text = node.get_text("\n", strip=True)
        if text:
            job.description = text_collapse(text)

    blob = soup.get_text(" ", strip=True)
    m = re.search(r"(Salary|Compensation|Pay|Base)\s*[:\-]\s*([^\n]+)", blob, re.I)
    if m and not job.salary:
        job.salary = m.group(2).strip()
    job.remote_ok = job.remote_ok or ("remote" in blob.lower())

    return job


@register_ats("boards.greenhouse.io")
def parse_greenhouse(job: JobPosting, html: str) -> JobPosting:
    soup = BeautifulSoup(html, "html.parser")
    node = (
        soup.select_one("#content")
        or soup.select_one(".content")
        or soup.select_one(".opening .content")
        or soup.select_one(".app-content")
        or soup.find("article")
        or soup.find("main")
    )
    if node:
        job.description = text_collapse(node.get_text("\n", strip=True))
    blob = soup.get_text(" ", strip=True)
    job.remote_ok = job.remote_ok or ("remote" in blob.lower())
    m = re.search(r"(Salary|Compensation|Pay|Base)\s*[:\-]\s*([^\n]+)", blob, re.I)
    if m and not job.salary:
        job.salary = m.group(2).strip()
    return job


@register_ats("www.ycombinator.com")
def parse_ycombinator(job: JobPosting, html: str) -> JobPosting:
    """
    Parse Y Combinator job posting pages.
    """
    import sys

    soup = BeautifulSoup(html, "html.parser")

    # Remove irrelevant elements
    for sel in [
        "header",
        "nav",
        "footer",
        "[role='navigation']",
        "[role='banner']",
        "[role='contentinfo']",
    ]:
        for el in soup.select(sel):
            el.decompose()

    # Extract job title (usually in an h1)
    title_element = soup.select_one("h1")
    if title_element:
        job.title = title_element.get_text(strip=True)

    # Extract company name (usually in a heading or div with company info)
    company_elements = soup.select(
        "[data-testid='company-name'], .company-name, h2, .company"
    )
    for el in company_elements:
        if el and el.get_text(strip=True):
            job.company = el.get_text(strip=True)
            break

    # Extract location
    location_elements = soup.select(
        "[data-testid='job-location'], .job-location, [class*='location']"
    )
    for el in location_elements:
        if el and el.get_text(strip=True):
            job.location = el.get_text(strip=True)
            break

    # Extract salary
    salary_elements = soup.select(
        "[data-testid='job-salary'], .job-salary, [class*='salary']"
    )
    for el in salary_elements:
        if el and el.get_text(strip=True):
            job.salary = el.get_text(strip=True)
            break

    # Extract job description (main content)
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
            if len(desc_text) > len(job.description or ""):
                job.description = desc_text

    # If still no description, get body text
    if not job.description:
        body = soup.find("body")
        if body:
            job.description = body.get_text(separator=" ", strip=True)

    # Limit description length to prevent oversized responses
    if job.description and len(job.description) > 5000:
        job.description = job.description[:5000] + "..."

    # Check for remote opportunities
    job.remote_ok = job.remote_ok or (
        "remote" in (job.description + " " + (job.title or "")).lower()
    )

    return job


# Additional ATS parsers (e.g., Lever, WorkAtStartup, etc.) can be added here...

# --------------------
# Job Service Class
# --------------------


class JobService:
    SOURCE_MAP: Dict[str, type] = {
        "hackernews_jobs": HackerNewsJobsCrawler,
        "ycombinator": YCombinatorCrawler,
        "workatastartup": WorkAtStartupCrawler,
    }

    def __init__(self, cache_ttl_seconds: int = 600):
        self.cache_ttl_seconds = cache_ttl_seconds
        self._instances: Dict[str, BaseCrawler] = {}
        self._domain_semaphores: Dict[str, asyncio.Semaphore] = {}
        self._global_sem = asyncio.Semaphore(10)

    async def search_jobs_stream(
        self,
        keywords: Optional[List[str]],
        sources: List[str],
        location: str,
        remote_only: bool,
        max_pages: int = 1,
        per_source_limit: int = 100,
        tags: Optional[List[str]] = None,
        enrich: bool = True,
        enrich_limit: Optional[int] = 50,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream job search results as events."""
        if not sources:
            return

        requested_sources = [s.lower().strip() for s in sources]
        req_tags_norm = self._normalize_tags(tags)

        # Emit start event
        yield {
            "type": "start",
            "sources": requested_sources,
            "max_pages": max_pages,
            "per_source_limit": per_source_limit,
            "remote_only": remote_only,
            "location": location,
        }

        total_jobs = 0
        total_pages = 0

        for src in requested_sources:
            # Emit source start event
            yield {"type": "source_start", "source": src}

            source_jobs = []
            source_pages = 0

            try:
                # Run the source and get all jobs
                jobs = await self._run_source(
                    src, keywords, max_pages, per_source_limit
                )

                # Filter jobs based on criteria
                filtered_jobs = [
                    j
                    for j in jobs
                    if (not remote_only or getattr(j, "remote_ok", False))
                    and (not location or self._location_match(j, location))
                    and (not req_tags_norm or self._has_required_tags(j, req_tags_norm))
                ]

                # Emit page start event (simplified - treating all as one page for streaming)
                yield {"type": "page_start", "source": src, "page": 1}

                # Emit job events
                for job in filtered_jobs:
                    yield {
                        "type": "job",
                        "source": src,
                        "page": 1,
                        "key": f"{src}:{job.url}",
                        "data": {
                            "id": job.id,
                            "source": job.source,
                            "url": job.url,
                            "title": job.title,
                            "company": job.company,
                            "location": job.location,
                            "description": job.description,
                            "posted_date": job.posted_date,
                            "salary": job.salary,
                            "job_type": job.job_type,
                            "remote_ok": job.remote_ok,
                            "requirements": job.requirements,
                            "seniority": job.seniority,
                            "tags": job.tags,
                            "raw_html": job.raw_html,
                            "source_key": job.source_key,
                        },
                    }
                    source_jobs.append(job)

                # Emit page complete event
                yield {
                    "type": "page_complete",
                    "source": src,
                    "page": 1,
                    "count": len(source_jobs),
                }

                source_pages = 1
                total_jobs += len(source_jobs)
                total_pages += source_pages

                # Emit source complete event
                yield {
                    "type": "source_complete",
                    "source": src,
                    "pages": source_pages,
                    "total": len(source_jobs),
                }

            except Exception as e:
                # Emit error event
                yield {"type": "error", "source": src, "page": 1, "message": str(e)}

        # Emit complete event
        yield {
            "type": "complete",
            "total_jobs": total_jobs,
            "sources": len(requested_sources),
            "pages": total_pages,
        }

    async def search_jobs(
        self,
        keywords: Optional[List[str]],
        sources: List[str],
        location: str,
        remote_only: bool,
        max_pages: int = 1,
        per_source_limit: int = 100,
        tags: Optional[List[str]] = None,
        enrich: bool = True,
        enrich_limit: Optional[int] = 50,
    ) -> List[JobPosting]:
        if not sources:
            return []

        requested_sources = [s.lower().strip() for s in sources]
        req_tags_norm = self._normalize_tags(tags)

        tasks = [
            self._run_source(src, keywords, max_pages, per_source_limit)
            for src in requested_sources
        ]
        results_lists = await asyncio.gather(*tasks, return_exceptions=True)

        jobs: List[JobPosting] = []
        for src, res in zip(requested_sources, results_lists):
            if isinstance(res, Exception):
                print(f"[WARN] source {src} failed: {res}")
                continue

            filtered = [
                j
                for j in res
                if (not remote_only or getattr(j, "remote_ok", False))
                and (not location or self._location_match(j, location))
                and (not req_tags_norm or self._has_required_tags(j, req_tags_norm))
            ]
            jobs.extend(filtered)

        deduped = self._dedupe_jobs_merge_tags(jobs)

        if enrich:
            subset = deduped[:enrich_limit]
            try:
                enriched_subset = await self.enrich_details(subset)
                deduped[: len(enriched_subset)] = enriched_subset
            except Exception as e:
                print(f"[WARN] enrich failed: {e}")

        return deduped

    def _normalize_tags(self, tags: Optional[List[str]]) -> List[str]:
        if not tags:
            return []
        return [t.strip().lower() for t in tags if t.strip()]

    def _location_match(self, job: JobPosting, want: str) -> bool:
        """
        Check if the desired location is mentioned in the job's location,
        title, or description.
        """
        want_norm = want.strip().lower()
        blob = " ".join(
            [
                getattr(job, "location", ""),
                getattr(job, "title", ""),
                getattr(job, "description", ""),
            ]
        ).lower()
        return want_norm in blob

    def _has_required_tags(self, job: JobPosting, required_tags: List[str]) -> bool:
        """Check if job has all required tags"""
        job_tags = getattr(job, "tags", [])
        if not job_tags:
            return False
        job_tags = [t.strip().lower() for t in job_tags]
        return all(tag in job_tags for tag in required_tags)

    def _dedupe_jobs_merge_tags(self, jobs: List[JobPosting]) -> List[JobPosting]:
        """Remove duplicate jobs and merge tags"""
        seen = {}
        for job in jobs:
            # Use URL as primary key for deduplication
            key = job.url
            if key in seen:
                # Merge tags
                existing_tags = seen[key].tags or []
                new_tags = job.tags or []
                seen[key].tags = list(set(existing_tags + new_tags))
            else:
                seen[key] = job
        return list(seen.values())

    async def _run_source(
        self,
        source: str,
        keywords: Optional[List[str]],
        max_pages: int,
        per_source_limit: int,
    ) -> List[JobPosting]:
        """Run a specific source crawler and return job listings"""
        if source not in self.SOURCE_MAP:
            raise ValueError(f"Unknown source: {source}")

        if source not in self._instances:
            self._instances[source] = self.SOURCE_MAP[source]()

        crawler = self._instances[source]

        # Initialize crawler if needed
        if hasattr(crawler, "initialize"):
            await crawler.initialize()

        # Get job listings
        jobs = []
        try:
            job_list = []
            if source == "ycombinator":
                # YC crawler doesn't take per_page_limit
                job_list = await crawler.crawl(keywords=keywords, max_pages=max_pages)
            else:
                # Other crawlers take per_page_limit
                job_list = await crawler.crawl(
                    keywords=keywords,
                    max_pages=max_pages,
                    per_page_limit=per_source_limit,
                )
            jobs.extend(job_list)
        except Exception as e:
            print(f"[ERROR] Failed to fetch jobs from {source}: {e}")
            raise

        return jobs

    async def enrich_details(self, jobs: List[JobPosting]) -> List[JobPosting]:
        """Enrich job details by fetching and parsing job URLs"""
        enriched_jobs = []

        for job in jobs:
            try:
                # Skip if already has detailed description
                if job.description and len(job.description) > 200:
                    enriched_jobs.append(job)
                    continue

                # Fetch and parse job URL
                parsed_job = await self.parse_job_url(job.url)

                # Update original job with parsed details
                if parsed_job.description:
                    job.description = parsed_job.description
                if parsed_job.salary:
                    job.salary = parsed_job.salary
                if parsed_job.location:
                    job.location = parsed_job.location
                if parsed_job.remote_ok is not None:
                    job.remote_ok = parsed_job.remote_ok

                enriched_jobs.append(job)
            except Exception as e:
                print(f"[WARN] Failed to enrich job {job.url}: {e}")
                enriched_jobs.append(job)  # Add original job if enrichment fails

        return enriched_jobs

    async def parse_job_url(self, url: str) -> JobPosting:
        """
        Parse a single job URL and extract job details.

        Args:
            url: The URL of the job posting to parse

        Returns:
            JobPosting with extracted details
        """
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

            # Extract domain for ATS handler lookup
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.lower()

            # Use registered ATS handler if available
            if domain in ATS_HANDLER:
                # Create a minimal job posting to pass to the ATS handler
                job_posting = JobPosting(url=url, source=domain)
                return ATS_HANDLER[domain](job_posting, html_content)

            # Otherwise, use generic HTML parsing
            return self._extract_job_details_from_html(html_content, url)

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

            return job_posting

        except Exception as e:
            # If parsing fails, create a basic job posting with URL info
            parsed = urlparse(url)
            host = parsed.hostname or "unknown"

            return JobPosting(
                url=url,
                source=host,
                title=f"Job at {host}",
                company=host,
                location="Location Not Specified",
                description=f"Could not parse job details from {url}. Error: {str(e)}",
                salary=None,
                remote_ok=False,
            )

    async def close(self) -> None:
        """Close all crawler sessions."""
        _ = await asyncio.gather(
            *(c.close_session() for c in self._instances.values()),
            return_exceptions=True,
        )

    # Async context manager methods
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False


# --------------------
# Additional Helpers
# --------------------

# Other utility methods and classes can be added here...
