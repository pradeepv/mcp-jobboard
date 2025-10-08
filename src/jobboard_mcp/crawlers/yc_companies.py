"""
YC Companies Job Crawler - Handles individual job postings from YC company pages.
"""
import re
from typing import Optional, Dict, Any
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from .base import BaseCrawler
from ..models.job import JobPosting
from datetime import datetime, timezone


class YCCompaniesCrawler(BaseCrawler[JobPosting]):
    """
    Crawler for individual YC company job posting pages.
    Handles URLs like: https://www.ycombinator.com/companies/company-name/jobs/job-id
    """

    KEY = "yc_companies"

    async def parse_job_url(self, url: str) -> Optional[JobPosting]:
        """Parse a specific YC company job posting URL."""
        try:
            html = await self.get_text(url)
            if not html:
                self.log.warning("Failed to fetch HTML from URL: %s", url)
                return None

            soup = BeautifulSoup(html, 'html.parser')
            return self._parse_job_from_soup(soup, url)

        except Exception as e:
            self.log.error("Error parsing YC job URL %s: %s", url, e)
            return None

    def _parse_job_from_soup(self, soup: BeautifulSoup, url: str) -> Optional[JobPosting]:
        """Parse job information from YC company job page."""
        try:
            # Extract job title
            title = self._extract_title(soup)

            # Extract company name
            company = self._extract_company(soup)

            # Extract location
            location = self._extract_location(soup)

            # Extract description
            description = self._extract_description(soup)

            # Extract salary information
            salary = self._extract_salary(soup)

            # Extract job type and remote status
            job_type, remote_ok = self._extract_job_details(soup)

            # Generate job ID from URL
            job_id = self._generate_job_id(url)

            # Create job posting
            job = JobPosting(
                id=job_id,
                title=title or "Job Posting",
                company=company or "Unknown Company",
                location=location or "Unknown",
                description=description or "",
                url=url,
                source="Y Combinator",
                source_key=self.KEY,
                posted_date=datetime.now(timezone.utc),
                salary=salary,
                job_type=job_type,
                remote_ok=remote_ok,
                tags=self._extract_tags(soup, remote_ok, job_type)
            )

            return job

        except Exception as e:
            self.log.error("Error parsing job from soup: %s", e)
            return None

    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract job title from various possible locations."""
        title_selectors = [
            'h1',
            '.job-title',
            '.position-title',
            '[data-testid="job-title"]',
            'title'
        ]

        for selector in title_selectors:
            element = soup.select_one(selector)
            if element:
                title = element.get_text().strip()
                if title and len(title) > 3:
                    return title

        # Fallback: try to extract from page title
        title_tag = soup.find('title')
        if title_tag:
            title_text = title_tag.get_text()
            # Extract from "Job Title at Company | Y Combinator"
            match = re.match(r'(.+?)\s+at\s+.+?\s*\|\s*Y Combinator', title_text)
            if match:
                return match.group(1).strip()

        return None

    def _extract_company(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract company name."""
        company_selectors = [
            '.company-name',
            '.company',
            '[data-testid="company-name"]',
            'meta[property="og:site_name"]'
        ]

        for selector in company_selectors:
            element = soup.select_one(selector)
            if element:
                if element.name == 'meta':
                    company = element.get('content', '').strip()
                else:
                    company = element.get_text().strip()
                if company:
                    return company

        # Fallback: try to extract from page title
        title_tag = soup.find('title')
        if title_tag:
            title_text = title_tag.get_text()
            # Extract from "Job Title at Company | Y Combinator"
            match = re.match(r'.+?\s+at\s+(.+?)\s*\|\s*Y Combinator', title_text)
            if match:
                return match.group(1).strip()

        return None

    def _extract_location(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract job location."""
        location_selectors = [
            '.location',
            '.job-location',
            '[data-testid="location"]',
            'span:contains("Remote")',
            'span:contains("San Francisco")',
            'span:contains("New York")'
        ]

        for selector in location_selectors:
            element = soup.select_one(selector)
            if element:
                location = element.get_text().strip()
                if location and len(location) > 2:
                    return location

        # Look for location in description
        desc_element = soup.select_one('.description, .job-description')
        if desc_element:
            desc_text = desc_element.get_text()
            # Look for common location patterns
            location_patterns = [
                r'(San Francisco|New York|Remote|London|Berlin|Toronto|Vancouver)\b',
                r'(CA|NY|TX|FL|WA)\s+(?:USA|US)?',
                r'(United States|Canada|UK|Germany)',
            ]
            for pattern in location_patterns:
                match = re.search(pattern, desc_text, re.IGNORECASE)
                if match:
                    return match.group(1).strip()

        return None

    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract job description."""
        desc_selectors = [
            '.description',
            '.job-description',
            '.job-details',
            '[data-testid="job-description"]'
        ]

        for selector in desc_selectors:
            element = soup.select_one(selector)
            if element:
                desc = element.get_text().strip()
                if len(desc) > 50:  # Ensure it's a substantial description
                    return desc

        # Fallback: try to extract the main content area
        main_content = soup.select_one('main, .main, #main')
        if main_content:
            # Remove nav, header, footer elements
            for unwanted in main_content.select('nav, header, footer, .navigation, .menu'):
                unwanted.decompose()

            desc = main_content.get_text().strip()
            if len(desc) > 100:
                return desc

        return None

    def _extract_salary(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract salary information."""
        salary_selectors = [
            '.salary',
            '.compensation',
            '[data-testid="salary"]'
        ]

        for selector in salary_selectors:
            element = soup.select_one(selector)
            if element:
                salary = element.get_text().strip()
                if salary and ('$' in salary or 'USD' in salary or 'per year' in salary.lower()):
                    return salary

        # Look for salary patterns in description
        desc_element = soup.select_one('.description, .job-description')
        if desc_element:
            desc_text = desc_element.get_text()
            salary_patterns = [
                r'\$(\d{2,3},?\d{3})(?:\s*-\s*\$(\d{2,3},?\d{3}))?\s*(?:k|K)?\s*(?:per\s*year|/year|annual)',
                r'(\d{2,3},?\d{3})\s*-\s*(\d{2,3},?\d{3})\s*USD',
            ]
            for pattern in salary_patterns:
                match = re.search(pattern, desc_text)
                if match:
                    return match.group(0).strip()

        return None

    def _extract_job_details(self, soup: BeautifulSoup) -> tuple[Optional[str], bool]:
        """Extract job type and remote status."""
        remote_ok = False
        job_type = None

        # Check for remote indicators
        remote_selectors = [
            '.remote',
            '[data-testid="remote"]',
            'span:contains("Remote")',
            'div:contains("Remote")'
        ]

        for selector in remote_selectors:
            elements = soup.select(selector)
            for element in elements:
                text = element.get_text().lower()
                if 'remote' in text:
                    remote_ok = True
                    break

        # Check in description as well
        desc_element = soup.select_one('.description, .job-description')
        if desc_element:
            desc_text = desc_element.get_text().lower()
            remote_indicators = ['remote', 'fully remote', 'work from home', 'wfh']
            if any(indicator in desc_text for indicator in remote_indicators):
                remote_ok = True

        # Extract job type
        job_type_selectors = [
            '.job-type',
            '.employment-type',
            '[data-testid="job-type"]'
        ]

        for selector in job_type_selectors:
            element = soup.select_one(selector)
            if element:
                job_type_text = element.get_text().strip().lower()
                if job_type_text in ['full-time', 'part-time', 'contract', 'internship']:
                    job_type = job_type_text
                    break

        return job_type, remote_ok

    def _extract_tags(self, soup: BeautifulSoup, remote_ok: bool, job_type: Optional[str]) -> list[str]:
        """Extract relevant tags."""
        tags = []

        # Add remote tag if applicable
        if remote_ok:
            tags.append('Remote')

        # Add job type tag
        if job_type:
            tags.append(job_type.title())

        # Look for skill tags in description
        desc_element = soup.select_one('.description, .job-description')
        if desc_element:
            desc_text = desc_element.get_text().lower()

            skill_keywords = [
                'python', 'java', 'javascript', 'react', 'node', 'aws', 'docker',
                'kubernetes', 'sql', 'postgresql', 'mongodb', 'machine learning',
                'ai', 'golang', 'rust', 'typescript', 'vue', 'angular', 'django',
                'flask', 'spring', 'ruby', 'rails', 'php', 'laravel', '.net',
                'c++', 'c#', 'swift', 'kotlin', 'scala', 'elixir', 'haskell'
            ]

            for skill in skill_keywords:
                if skill in desc_text:
                    tags.append(skill.title())

        return tags[:10]  # Limit to 10 tags

    def _generate_job_id(self, url: str) -> str:
        """Generate a stable job ID from URL."""
        # Extract job ID from URL pattern: /companies/company-name/jobs/job-id
        match = re.search(r'/jobs/([^/?]+)', url)
        if match:
            return f"yc_job_{match.group(1)}"

        # Fallback: use URL hash
        return f"yc_job_{abs(hash(url))}"