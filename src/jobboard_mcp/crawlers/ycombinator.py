from typing import List, Optional, Tuple
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from .base import BaseCrawler
from ..models.job import JobPosting
from datetime import datetime, timezone
import re


class YCombinatorCrawler(BaseCrawler[JobPosting]):
    KEY = "ycombinator"

    async def crawl(
        self,
        keywords: Optional[List[str]] = None,
        max_pages: int = 3,
    ) -> List[JobPosting]:
        # Cache
        if self.is_cache_valid(self.KEY) and self.KEY in self.cache:
            return self._filter(self.cache[self.KEY], keywords)

        base_url = "https://news.ycombinator.com/jobs"
        jobs: List[JobPosting] = []

        next_url = base_url
        pages_fetched = 0

        while next_url and pages_fetched < max_pages:
            html = await self.get_text(next_url)
            if not html:
                break

            soup = BeautifulSoup(html, "html.parser")

            # Parse job rows
            page_jobs = self._parse_jobs_from_soup(soup, base_url)
            jobs.extend(page_jobs)

            # Find 'More' pagination link
            more_a = soup.select_one("a.morelink") or soup.find("a", string=re.compile(r"^\s*More\s*$", re.I))
            if more_a and more_a.get("href"):
                next_url = urljoin(base_url, more_a["href"])
                # Be polite between pages
                await self.sleep_polite(0.15)
            else:
                next_url = None

            pages_fetched += 1

        # Cache and return filtered
        self.cache[self.KEY] = jobs
        self.last_crawl[self.KEY] = datetime.now(timezone.utc)
        return self._filter(jobs, keywords)

    def _parse_jobs_from_soup(self, soup: BeautifulSoup, base_url: str) -> List[JobPosting]:
        jobs: List[JobPosting] = []
        rows = soup.select("tr.athing")

        for row in rows:
            a = row.select_one("span.titleline > a")
            if not a:
                continue
            title = a.get_text(strip=True)
            if not title or title.lower() == "more":
                continue

            job_url = urljoin(base_url, a.get("href", ""))

            company, location = self._guess_company_location(title)
            remote_ok = self._is_remote(title)

            tags: List[str] = []
            # Extract YC batch-like tags, e.g., "YC S23", "W24", "F22"
            yc_batch = self._extract_yc_batch(title)
            if yc_batch:
                tags.append(yc_batch)
            if remote_ok:
                tags.append("Remote")
            if location:
                # Add a simple location hint as tag (e.g., "NYC")
                tags.append(location)

            jobs.append(
                JobPosting(
                    title=title,
                    company=company or "Unknown",
                    location=location or "Unknown",
                    description="",
                    url=job_url,
                    source="Y Combinator",
                    remote_ok=remote_ok,
                    tags=tags or None,
                )
            )

        return jobs

    def _guess_company_location(self, title: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Heuristics to parse company and location from titles like:
        - "Prosper AI (YC S23) Is Hiring Founding Account Executives (NYC)"
        - "Acme -- Senior Backend Engineer (Remote, US)"
        - "SuperCorp (Remote, Europe) hiring iOS Engineer"
        - "Founding Engineer (NYC or Remote) at Foobar"
        """
        t = title.strip()

        # Try to extract the trailing parenthetical as location
        # Look for the last (...) block and use it as location candidate
        loc = None
        parens = list(re.finditer(r"\(([^)]+)\)", t))
        if parens:
            loc_candidate = parens[-1].group(1).strip()
            # Avoid matching YC batch as location; if it looks like "YC S23" or "W24", ignore
            if not re.search(r"\bYC\b|\bS\d{2}\b|\bW\d{2}\b|\bF\d{2}\b", loc_candidate):
                loc = loc_candidate

        # Company often appears at the start before a dash or before 'is hiring'/'hiring' or after 'at'
        company = None

        # Pattern 1: "Company -- Role ..." or "Company - Role ..."
        m = re.match(r"^([^---:|]+?)\s*[---:|]\s*", t)
        if m:
            company = m.group(1).strip()
        else:
            # Pattern 2: "... at Company"
            m2 = re.search(r"\bat\s+([A-Z][\w .&+-]{1,60})$", t)
            if m2:
                company = m2.group(1).strip()
            else:
                # Pattern 3: "Company (YC S..)" at start
                m3 = re.match(r"^([A-Z][\w .&+-]{1,60})\s*\(YC\b.*?\)", t)
                if m3:
                    company = m3.group(1).strip()
                else:
                    # Pattern 4: leading capitalized token(s) before verbs like "is hiring" / "hiring"
                    m4 = re.match(r"^([A-Z][\w .&+-]{1,60})\s+(?:is\s+)?hiring\b", t, flags=re.I)
                    if m4:
                        company = m4.group(1).strip()

        # Basic cleanup for company
        if company:
            company = re.sub(r"\b(is\s+hiring|hiring)\b.*$", "", company, flags=re.I).strip(" ---|:.,")
            # Trim common trailing batch info
            company = re.sub(r"\s*\(YC\b.*?\)\s*$", "", company).strip()

        # Normalize location strings
        if loc:
            loc = loc.strip()
            loc = loc.strip(" .,/;:-")
            # Expand common abbreviations
            loc = loc.replace("ANYWHERE", "Anywhere").replace("anywhere", "Anywhere")
            loc = re.sub(r"\bUS\b", "United States", loc)
            loc = re.sub(r"\bUK\b", "United Kingdom", loc)

        return company if company else None, loc if loc else None

    def _extract_yc_batch(self, title: str) -> Optional[str]:
        """
        Extract YC batch-like markers and return a normalized single tag if present.
        Examples: "YC S23", "S23", "W24", "F22".
        Preference order:
          - YC <season><yy> (normalized with YC prefix if missing)
        """
        t = title
        # Match patterns like "(YC S23)" or "YC S23" or "(S23)"
        m = re.search(r"\b(?:YC\s*)?(S|W|F)\s?(\d{2})\b", t, flags=re.I)
        if not m:
            return None
        season = m.group(1).upper()
        year2 = m.group(2)
        return f"YC {season}{year2}"

    def _is_remote(self, title: str) -> bool:
        t = title.lower()
        remote_terms = [
            "remote",
            "anywhere",
            "work from home",
            "wfh",
            "distributed",
        ]
        return any(term in t for term in remote_terms)

    def _filter(self, jobs: List[JobPosting], keywords: Optional[List[str]]) -> List[JobPosting]:
        if not keywords:
            return jobs
        low = [k.lower() for k in keywords]
        out: List[JobPosting] = []
        for j in jobs:
            blob = f"{j.title} {j.description} {j.company}".lower()
            if any(k in blob for k in low):
                out.append(j)
        return out