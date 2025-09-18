from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup  # type: ignore

from .base import BaseCrawler
from ..models.job import JobPosting


class WorkAtStartupCrawler(BaseCrawler[JobPosting]):
    """
    Crawler for Work at a Startup (https://www.workatastartup.com/jobs).
    Parses YC portfolio company job listings from the Work at a Startup platform.
    """

    KEY = "workatastartup"
    BASE_URL = "https://www.workatastartup.com"
    START_URL = f"{BASE_URL}/jobs"
    SOURCE_NAME = "Work at a Startup"

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
        current_url = self.START_URL
        pages_crawled = 0

        while current_url and pages_crawled < max_pages:
            html = await self.get_text(current_url)
            if not html:
                break

            soup = BeautifulSoup(html, "html.parser")

            # Parse jobs from current page
            page_jobs = self._parse_job_listings(
                soup, 
                current_url,
                max(0, per_page_limit - len(jobs)) if per_page_limit else 0
            )
            jobs.extend(page_jobs)

            # Check if we've hit the limit
            if per_page_limit and len(jobs) >= per_page_limit:
                break

            # Look for pagination (this site might use infinite scroll/load more)
            # For now, we'll just do one page as the site seems to load everything dynamically
            current_url = None
            pages_crawled += 1
            
            if current_url:
                await self.sleep_polite(0.3)  # Be respectful

        # Cache and return
        self.cache[self.KEY] = jobs
        self.last_crawl[self.KEY] = datetime.now(timezone.utc)
        return self._filter(jobs, keywords)

    def _parse_job_listings(
        self, 
        soup: BeautifulSoup, 
        page_url: str, 
        limit: int
    ) -> List[JobPosting]:
        """Parse job listings from the page"""
        jobs: List[JobPosting] = []

        # Find all job listing containers
        # Based on the HTML structure, jobs are in divs with specific classes
        job_containers = soup.select("div.company-jobs div.jobs-list > div")
        
        for container in job_containers:
            if limit and len(jobs) >= limit:
                break
                
            job_divs = container.select("div.w-full.bg-beige-lighter")
            for job_div in job_divs:
                if limit and len(jobs) >= limit:
                    break
                
                try:
                    job = self._parse_single_job(job_div)
                    if job:
                        jobs.append(job)
                except Exception as e:
                    self.log.debug(f"Error parsing job: {e}")
                    continue

        return jobs

    def _parse_single_job(self, job_element) -> Optional[JobPosting]:
        """Parse a single job posting from its HTML element"""
        try:
            # Extract company information
            company_link = job_element.select_one("a[target='company']")
            if not company_link:
                return None

            company_details = job_element.select_one(".company-details")
            if not company_details:
                return None

            # Extract company name and YC batch
            company_text = company_details.get_text(strip=True)
            company, yc_batch = self._parse_company_and_batch(company_text)

            # Extract company description
            description_el = company_details.select_one(".text-gray-600")
            company_description = description_el.get_text(strip=True) if description_el else ""

            # Extract job title and URL
            job_link = job_element.select_one("a[target='job']")
            if not job_link:
                return None

            job_title = job_link.get_text(strip=True)
            job_url = job_link.get("href", "")
            if job_url and not job_url.startswith("http"):
                job_url = urljoin(self.BASE_URL, job_url)

            # Extract job details (type, location, category)
            job_details = job_element.select_one(".job-details")
            location, job_type, job_category = self._parse_job_details(job_details)

            # Extract job ID from data attributes
            job_id_attr = job_link.get("data-jobid")
            
            # Determine if remote
            remote_ok = self._is_remote_job(location, job_title, company_description)

            # Create tags
            tags = []
            if yc_batch:
                tags.append(yc_batch)
            if job_category:
                tags.append(job_category)
            if remote_ok:
                tags.append("Remote")

            # Create the job posting
            job = JobPosting(
                id=job_id_attr,
                source=self.SOURCE_NAME,
                url=job_url,
                title=job_title,
                company=company or "Unknown",
                location=location or "Unknown",
                description=company_description[:600] + ("..." if len(company_description) > 600 else ""),
                remote_ok=remote_ok,
                tags=tags,
                job_type=job_type,
                raw_html=str(job_element)
            )

            return job

        except Exception as e:
            self.log.debug(f"Error parsing single job: {e}")
            return None

    def _parse_company_and_batch(self, company_text: str) -> tuple[Optional[str], Optional[str]]:
        """Extract company name and YC batch from company text"""
        # Pattern: "Company (YC Batch) • Description"
        company_match = re.match(r"^([^(]+?)(?:\s*\(([^)]+)\))?\s*(?:•|$)", company_text)
        
        if company_match:
            company = company_match.group(1).strip()
            batch_info = company_match.group(2)
            
            # Extract YC batch if present
            yc_batch = None
            if batch_info and "YC" in batch_info:
                yc_batch = batch_info.strip()
            elif batch_info:
                # Sometimes it's just the batch without YC prefix
                batch_match = re.search(r"[SWF]\d{2}", batch_info)
                if batch_match:
                    yc_batch = f"YC {batch_match.group(0)}"
                    
            return company, yc_batch
        
        return company_text, None

    def _parse_job_details(self, details_element) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Parse job details to extract location, type, and category"""
        if not details_element:
            return None, None, None

        # Try to find structured spans first
        spans = details_element.select('span')
        details_parts = []
        
        for span in spans:
            text = span.get_text(strip=True)
            if text and text not in details_parts:
                details_parts.append(text)
        
        # Fallback to text parsing if no spans found
        if not details_parts:
            details_text = details_element.get_text(strip=True)
            # Split by bullet points or other separators
            parts = [part.strip() for part in re.split(r'[•|]', details_text) if part.strip()]
            details_parts = parts
        
        job_type = None
        location = None
        category = None
        
        for part in details_parts:
            part_lower = part.lower()
            
            # Identify job type
            if any(jt in part_lower for jt in ["fulltime", "full-time", "part-time", "parttime", "contract", "internship"]):
                job_type = part
            # Identify job category/tech area
            elif any(cat_word in part_lower for cat_word in ["backend", "frontend", "full stack", "fullstack", "devops", "ml", "ios", "android", "embedded", "hardware"]):
                category = part
            # Identify location (anything with geographic indicators or 'remote')
            elif any(loc_word in part_lower for loc_word in ["remote", "san francisco", "new york", "palo alto", "ca", "ny", "us", "united states", "hybrid", "santa clara", "philadelphia", "austin", "anywhere"]) or ", " in part:
                location = part
        
        return location, job_type, category

    def _is_remote_job(self, location: Optional[str], title: str, description: str) -> bool:
        """Check if job is remote-friendly"""
        searchable_text = f"{location or ''} {title} {description}".lower()
        remote_terms = [
            "remote", "anywhere", "work from home", "wfh", "distributed",
            "us remote", "remote (us)", "remote/", "hybrid"
        ]
        return any(term in searchable_text for term in remote_terms)

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