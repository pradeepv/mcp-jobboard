# Job Board Crawlers Refactoring Guide

## 1. Analysis of Current Issues

### URL and Source Overlap
- **`hackernews_jobs.py`** and **`ycombinator.py`** both target `https://news.ycombinator.com/jobs`
- Both crawlers parse the same structured job listings but with different source names ("Hacker News Jobs" vs "Y Combinator")
- This creates functional redundancy and potential duplicate job postings
- **`hackernews.py`** correctly targets monthly "Who's Hiring" threads (distinct functionality)

### Current URL Mappings (Problematic)
```
hackernews_jobs.py → https://news.ycombinator.com/jobs
ycombinator.py     → https://news.ycombinator.com/jobs  [DUPLICATE]
hackernews.py      → Monthly "Who's Hiring" threads     [OK - Unique]
```

### Pain Points
- Duplicate job entries in aggregated results
- Inconsistent parsing logic for the same data source
- Maintenance overhead from parallel implementations
- Confusing source attribution ("HN Jobs" vs "YC" for same posts)

## 2. Proposed URL Assignments & Responsibilities

| Crawler | Proposed Target | Responsibility | Rationale |
|---------|----------------|----------------|-----------|
| `hackernews_jobs.py` | `https://news.ycombinator.com/jobs` | Official HN job board postings | Keep existing, well-tested HN jobs logic |
| `ycombinator.py` | **TODO: YC Company Directory URLs** | YC portfolio company jobs | Target actual YC-affiliated company job pages |
| `hackernews.py` | Monthly "Who's Hiring" threads | Community hiring posts in HN threads | Keep existing, already distinct |

### Suggested YC URLs (To be confirmed/modified by maintainer)
```
# Primary YC company directory
https://news.ycombinator.com/jobs

# YC job board (if exists)
https://www.ycombinator.com/jobs

# Alternative: Work at a Startup
https://www.workatastartup.com/jobs
```

**TODO: Replace with actual target URLs for YC crawler**

## 3. Detailed Template Structure

### Base Crawler Template
```python
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from .base import BaseCrawler
from ..models.job import JobPosting

class BaseJobCrawler(BaseCrawler[JobPosting]):
    """
    Base template for job board crawlers.
    Provides common patterns for pagination, parsing, and JobPosting creation.
    """
    
    # Subclasses must define these
    KEY: str = "override_me"
    BASE_URL: str = "https://example.com"
    START_URLS: List[str] = []
    SOURCE_NAME: str = "Override Me"
    
    async def crawl(
        self,
        keywords: Optional[List[str]] = None,
        max_pages: int = 3,
        per_page_limit: int = 100,
    ) -> List[JobPosting]:
        """Main crawling entry point"""
        # Cache check
        if self.is_cache_valid(self.KEY) and self.KEY in self.cache:
            return self._filter(self.cache[self.KEY], keywords)
        
        jobs: List[JobPosting] = []
        
        for start_url in self.START_URLS:
            page_jobs = await self._crawl_source(start_url, max_pages, per_page_limit)
            jobs.extend(page_jobs)
        
        # Cache and return
        self.cache[self.KEY] = jobs
        self.last_crawl[self.KEY] = datetime.now(timezone.utc)
        return self._filter(jobs, keywords)
    
    async def _crawl_source(
        self, 
        start_url: str, 
        max_pages: int, 
        per_page_limit: int
    ) -> List[JobPosting]:
        """Crawl a single source with pagination"""
        jobs: List[JobPosting] = []
        current_url = start_url
        pages_crawled = 0
        
        while current_url and pages_crawled < max_pages:
            html = await self.get_text(current_url)
            if not html:
                break
                
            soup = BeautifulSoup(html, "html.parser")
            
            # Parse jobs from current page
            page_jobs = await self.parse_job_listings(
                soup, 
                current_url, 
                max(0, per_page_limit - len(jobs))
            )
            jobs.extend(page_jobs)
            
            # Check if we've hit the limit
            if per_page_limit and len(jobs) >= per_page_limit:
                break
            
            # Find next page
            current_url = await self.get_next_page_url(soup, current_url)
            if current_url:
                pages_crawled += 1
                await self.sleep_polite(0.2)  # Be respectful
        
        return jobs
    
    async def parse_job_listings(
        self, 
        soup: BeautifulSoup, 
        page_url: str, 
        limit: int
    ) -> List[JobPosting]:
        """
        Parse job listings from a page.
        Override this method in subclasses.
        """
        raise NotImplementedError("Subclasses must implement parse_job_listings")
    
    async def get_next_page_url(
        self, 
        soup: BeautifulSoup, 
        current_url: str
    ) -> Optional[str]:
        """
        Find the next page URL from pagination links.
        Override this method in subclasses if needed.
        """
        # Common pagination patterns
        next_link = soup.select_one("a.morelink, a[rel='next'], .pagination .next")
        if next_link and next_link.get("href"):
            return urljoin(self.BASE_URL, next_link["href"])
        return None
    
    def create_job_posting(
        self,
        title: str,
        company: str,
        url: str,
        **kwargs
    ) -> JobPosting:
        """Helper to create JobPosting with consistent defaults"""
        return JobPosting(
            title=title or "Unknown Position",
            company=company or "Unknown",
            url=url,
            source=self.SOURCE_NAME,
            location=kwargs.get("location", "Unknown"),
            description=kwargs.get("description", ""),
            remote_ok=kwargs.get("remote_ok", False),
            tags=kwargs.get("tags", []),
            posted_date=kwargs.get("posted_date"),
            salary=kwargs.get("salary"),
            job_type=kwargs.get("job_type"),
            seniority=kwargs.get("seniority"),
            requirements=kwargs.get("requirements", []),
            raw_html=kwargs.get("raw_html"),
            id=kwargs.get("id")
        )
    
    def _filter(self, jobs: List[JobPosting], keywords: Optional[List[str]]) -> List[JobPosting]:
        """Standard keyword filtering"""
        if not keywords:
            return jobs
        
        low_keywords = [k.lower() for k in keywords]
        filtered = []
        
        for job in jobs:
            searchable_text = f"{job.title} {job.company} {job.description}".lower()
            if any(keyword in searchable_text for keyword in low_keywords):
                filtered.append(job)
        
        return filtered

class TemplateJobCrawler(BaseJobCrawler):
    """
    Template implementation - copy and modify for new crawlers
    """
    KEY = "template"
    BASE_URL = "https://example-jobboard.com"
    START_URLS = [
        "https://example-jobboard.com/jobs",
        # Add more starting URLs as needed
    ]
    SOURCE_NAME = "Example Job Board"
    
    async def parse_job_listings(
        self, 
        soup: BeautifulSoup, 
        page_url: str, 
        limit: int
    ) -> List[JobPosting]:
        """Parse job listings from the page"""
        jobs = []
        
        # TODO: Update selectors for your target site
        job_elements = soup.select(".job-listing")  # Adjust selector
        
        for element in job_elements[:limit] if limit else job_elements:
            # TODO: Extract job details using site-specific selectors
            title = element.select_one(".title")?.get_text(strip=True) or ""
            company = element.select_one(".company")?.get_text(strip=True) or ""
            job_url = element.select_one("a")?.get("href") or ""
            
            if job_url and not job_url.startswith("http"):
                job_url = urljoin(self.BASE_URL, job_url)
            
            # TODO: Add more field extraction as needed
            location = self._extract_location(element)
            remote_ok = self._is_remote_job(element)
            tags = self._extract_tags(element)
            
            if title and company:  # Basic validation
                job = self.create_job_posting(
                    title=title,
                    company=company,
                    url=job_url,
                    location=location,
                    remote_ok=remote_ok,
                    tags=tags,
                    raw_html=str(element)
                )
                jobs.append(job)
        
        return jobs
    
    def _extract_location(self, element) -> str:
        """Extract location from job element"""
        # TODO: Implement site-specific location extraction
        location_el = element.select_one(".location")
        return location_el.get_text(strip=True) if location_el else "Unknown"
    
    def _is_remote_job(self, element) -> bool:
        """Check if job is remote-friendly"""
        # TODO: Implement site-specific remote detection
        text = element.get_text().lower()
        return any(term in text for term in ["remote", "anywhere", "work from home"])
    
    def _extract_tags(self, element) -> List[str]:
        """Extract tags/skills from job element"""
        # TODO: Implement site-specific tag extraction
        tags = []
        tag_elements = element.select(".tag, .skill, .technology")
        for tag_el in tag_elements:
            tag = tag_el.get_text(strip=True)
            if tag:
                tags.append(tag)
        return tags
```

## 4. JobPosting Compatibility Guidelines

### Required Fields
- **`title`**: Job title (string, non-empty)
- **`company`**: Company name (string, defaults to "Unknown")
- **`url`**: Job posting URL (string, should be absolute URL)
- **`source`**: Source name (string, e.g., "Hacker News Jobs")

### Optional Fields with Standards
- **`location`**: Location string or "Remote" or "Unknown"
- **`posted_date`**: `datetime` object in UTC timezone
- **`description`**: Plain text description (trim to ~600 chars for consistency)
- **`remote_ok`**: Boolean indicating remote-friendly position
- **`tags`**: List of strings (skills, technologies, YC batch, etc.)
- **`salary`**: Salary string (preserve original format)
- **`seniority`**: "junior", "senior", "staff", "principal", etc.
- **`requirements`**: List of requirement strings

### URL Validation
```python
def validate_job_url(url: str, base_url: str) -> str:
    """Ensure job URL is absolute and valid"""
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return urljoin(base_url, url)
```

## 5. Implementation Plan by Crawler

### 5.1 hackernews_jobs.py (Keep as-is, minor cleanup)
```python
# BEFORE: Already working well
class HackerNewsJobsCrawler(BaseCrawler[JobPosting]):
    KEY = "hackernews_jobs"
    BASE = "https://news.ycombinator.com"
    START_URL = f"{BASE}/jobs"

# AFTER: Minor refactor to match template
class HackerNewsJobsCrawler(BaseJobCrawler):
    KEY = "hackernews_jobs"
    BASE_URL = "https://news.ycombinator.com"
    START_URLS = ["https://news.ycombinator.com/jobs"]
    SOURCE_NAME = "Hacker News Jobs"
    
    # Keep existing parsing logic, just adapt to template methods
```

### 5.2 ycombinator.py (Major refactor)
```python
# BEFORE: Conflicted with hackernews_jobs.py
class YCombinatorCrawler(BaseCrawler[JobPosting]):
    # Targeted same URL as hackernews_jobs.py

# AFTER: Target actual YC sources
class YCombinatorCrawler(BaseJobCrawler):
    KEY = "ycombinator"
    BASE_URL = "https://www.ycombinator.com"  # TODO: Update with real URLs
    START_URLS = [
        # TODO: Add actual YC job board URLs
        "https://www.ycombinator.com/companies?batch=all&jobs=true",
        "https://www.workatastartup.com/companies",  # If applicable
    ]
    SOURCE_NAME = "Y Combinator"
    
    async def parse_job_listings(self, soup, page_url, limit):
        # TODO: Implement YC-specific parsing logic
        # Focus on YC portfolio companies and their job listings
        pass
```

### 5.3 hackernews.py (Minor adjustments)
```python
# BEFORE: Already distinct, targeting "Who's Hiring" threads
class HackerNewsCrawler(BaseCrawler[JobPosting]):
    # This is already correctly differentiated

# AFTER: Adapt to template but keep core logic
class HackerNewsCrawler(BaseJobCrawler):
    KEY = "hackernews"
    BASE_URL = "https://news.ycombinator.com"
    START_URLS = []  # Dynamically discovered via Algolia
    SOURCE_NAME = "Hacker News"
    
    # Keep existing thread discovery and comment parsing logic
```

## 6. Testing and Validation Strategy

### Unit Tests
- Use VCR.py cassettes to record HTTP responses for deterministic testing
- Test each crawler independently with known URLs
- Validate JobPosting field population and format

```python
import vcr
import pytest
from crawlers.hackernews_jobs import HackerNewsJobsCrawler

@vcr.use_cassette('fixtures/hn_jobs_page.yml')
async def test_hackernews_jobs_parsing():
    crawler = HackerNewsJobsCrawler()
    jobs = await crawler.crawl(max_pages=1)
    
    assert len(jobs) > 0
    for job in jobs:
        assert job.title
        assert job.company
        assert job.url
        assert job.source == "Hacker News Jobs"
```

### Duplication Detection
- Implement job URL uniqueness checks
- Cross-crawler duplicate detection in aggregation layer
- Alert on unexpectedly high duplicate rates

### Integration Tests
- Run all crawlers and verify no URL conflicts
- Test aggregated job feed for quality
- Performance benchmarks (jobs per minute, memory usage)

### Manual QA Checklist for New Crawlers
- [ ] Crawler targets unique URLs (no overlap with existing)
- [ ] All JobPosting required fields populated
- [ ] Source name is descriptive and consistent
- [ ] Pagination works correctly
- [ ] Rate limiting is respectful (delays between requests)
- [ ] Error handling gracefully manages failed requests
- [ ] Cache invalidation works properly

## 7. Migration Steps

1. **Phase 1**: Create new `ycombinator.py` targeting actual YC sources
2. **Phase 2**: Test new YC crawler independently
3. **Phase 3**: Update existing crawlers to use template structure
4. **Phase 4**: Add comprehensive tests for all crawlers
5. **Phase 5**: Deploy and monitor for duplicates
6. **Phase 6**: Archive old conflicting implementations

## 8. Future Crawler Additions

### Template for New Job Boards
When adding new crawlers, copy `TemplateJobCrawler` and:

1. Update `KEY`, `BASE_URL`, `START_URLS`, and `SOURCE_NAME`
2. Implement `parse_job_listings()` with site-specific selectors
3. Add helper methods for location, tags, remote detection
4. Write unit tests with VCR cassettes
5. Verify no URL conflicts with existing crawlers

### Suggested Additional Sources
- AngelList/Wellfound
- LinkedIn Jobs (with proper API integration)
- GitHub Jobs (if available)
- Stack Overflow Jobs
- Remote-specific boards (Remote.co, We Work Remotely)

## 9. Maintenance Guidelines

- Review crawler health monthly (success rates, job counts)
- Update selectors when target sites change layouts  
- Monitor for new duplicate sources
- Keep JobPosting model compatibility during updates
- Document any site-specific parsing quirks in crawler docstrings

---

**TODO for Maintainer**: 
- Replace placeholder YC URLs with actual target URLs
- Test proposed URL assignments
- Validate that suggested YC sources have accessible job data
- Add any additional job board URLs for future implementation