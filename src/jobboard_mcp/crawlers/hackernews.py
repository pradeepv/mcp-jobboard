from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup  # type: ignore

from .base import BaseCrawler
from ..models.job import JobPosting


class HackerNewsCrawler(BaseCrawler[JobPosting]):
    """
    Hacker News 'Who’s Hiring?' crawler.

    - Discovers the latest monthly thread via Algolia; falls back to the whoishiring profile page.
    - Parses top-level comments from the HN item HTML (more reliable than comment API for full text).
    - Heuristically extracts company, title, location, remote_ok; trims description to ~600 chars.
    - Follows in-thread 'More' pagination up to max_pages.
    """

    KEY = "hackernews"

    async def crawl(
        self,
        keywords: Optional[List[str]] = None,
        max_pages: int = 1,
        thread_url: Optional[str] = None,
        per_page_limit: int = 150,
    ) -> List[JobPosting]:
        # Cache
        if self.is_cache_valid(self.KEY) and self.KEY in self.cache:
            return self._filter(self.cache[self.KEY], keywords)

        # Resolve thread URL
        if not thread_url:
            thread_url = await self._discover_latest_thread_url()
        if not thread_url:
            self.log.warning("Could not discover latest Who's Hiring thread.")
            print("DEBUG HN: discovery failed (no thread_url)")
            return []
        print(f"DEBUG HN: thread_url={thread_url}")

        jobs: List[JobPosting] = []

        next_page = thread_url
        pages = 0
        total_seen = 0

        while next_page and pages < max_pages:
            html_text = await self.get_text(next_page)
            if not html_text:
                break

            soup = BeautifulSoup(html_text, "html.parser")
            page_jobs = self._parse_top_level_comments(
                soup,
                base_url="https://news.ycombinator.com",
                per_page_limit=max(0, per_page_limit - total_seen),
            )
            jobs.extend(page_jobs)
            total_seen += len(page_jobs)
            print(f"DEBUG HN: page jobs={len(page_jobs)} total_seen={total_seen + len(page_jobs)}")
            if per_page_limit and total_seen >= per_page_limit:
                break

            # In-thread pagination
            more_a = soup.select_one("a.morelink")
            if more_a and more_a.get("href"):
                next_page = urljoin("https://news.ycombinator.com/", more_a["href"])
                pages += 1
                await self.sleep_polite(0.2)
            else:
                next_page = None

        # Cache and return
        self.cache[self.KEY] = jobs
        self.last_crawl[self.KEY] = datetime.now(timezone.utc)
        return self._filter(jobs, keywords)

    async def _discover_latest_thread_url(self) -> Optional[str]:
        """
        Prefer Algolia to find the 'Ask HN: Who is hiring? (Month YYYY)' thread.
        Fallback: parse https://news.ycombinator.com/submitted?id=whoishiring.
        """
        now = datetime.now(timezone.utc)
        search_query = f"Ask HN: Who is hiring? ({now.strftime('%B %Y')})"
        search_url = f"https://hn.algolia.com/api/v1/search?query={search_query}&tags=story"

        text = await self.get_text(search_url)
        if text:
            try:
                data = json.loads(text)
                if data.get("hits"):
                    # Most relevant hit; typically the current month
                    hit = sorted(data["hits"], key=lambda h: h.get("points", 0), reverse=True)[0]
                    object_id = hit["objectID"]
                    return f"https://news.ycombinator.com/item?id={object_id}"
            except Exception as e:
                self.log.debug("Algolia parsing failed: %r", e)

        # Fallback: whoishiring submissions page
        fallback = await self.get_text("https://news.ycombinator.com/submitted?id=whoishiring")
        if not fallback:
            return None
        try:
            soup = BeautifulSoup(fallback, "html.parser")
            link = None
            for a in soup.select("span.titleline > a"):
                if re.search(r"^Ask HN:\s*Who\s+is\s+hiring\?", a.get_text(strip=True), re.I):
                    link = a
                    break
            if link and link.get("href"):
                return link["href"] if link["href"].startswith("http") else urljoin("https://news.ycombinator.com/", link["href"])
        except Exception as e:
            self.log.debug("Fallback discovery failed: %r", e)
        return None

def _parse_top_level_comments(
    self,
    soup: BeautifulSoup,
    base_url: str,
    per_page_limit: int,
) -> List[JobPosting]:
    """
    Parse top-level comments only. HN markup varies; we:
    - Prefer tr.athing.comtr rows (canonical).
    - Verify indent width == 0 (top-level).
    - Extract text from span.commtext (with any extra classes).
    - Get permalink from the age link in the following row.
    """
    jobs: List[JobPosting] = []

    # Primary path: strict row selection
    rows = soup.select("tr.athing.comtr")
    def is_top_level(row) -> bool:
        # indent cell typically: <td class="ind"><img width="0"></td>
        ind_img = row.select_one("td.ind img")
        if ind_img and ind_img.get("width") is not None:
            try:
                return int(ind_img["width"]) == 0
            except Exception:
                return ind_img["width"] == "0"
        # Fallback: sometimes width is on td.ind as a style; treat missing as top-level
        return True

    def find_commtext(node):
        # span.commtext may have extra classes e.g., 'c00'
        el = node.select_one("span.commtext")
        if el:
            return el
        # Sometimes nested under div.comment
        return node.select_one("div.comment span.commtext")

    def next_meta_row(row):
        # The subtext/meta usually is the immediate next tr
        sib = row.find_next_sibling("tr")
        return sib

    for row in rows:
        if per_page_limit and len(jobs) >= per_page_limit:
            break
        if not is_top_level(row):
            continue

        comm_el = find_commtext(row)
        if not comm_el:
            # Try within the next row's default cell
            meta_row = next_meta_row(row)
            if meta_row:
                comm_el = find_commtext(meta_row)
        if not comm_el:
            continue

        raw_html = str(comm_el)
        desc = self._clean_description(comm_el.get_text("\n", strip=True))
        if len(desc) < 60:
            continue

        # First external link
        first_link = None
        for a in comm_el.find_all("a", href=True):
            href = a["href"]
            if "news.ycombinator.com" in href or href.startswith("item?id="):
                continue
            first_link = href
            break

        # Permalink
        meta_row = next_meta_row(row)
        permalink = None
        if meta_row:
            age_a = meta_row.select_one("span.age > a")
            if age_a and age_a.get("href"):
                permalink = urljoin(base_url, age_a["href"])

        company, title = self._guess_company_and_title(desc)
        location = self._guess_location(desc)
        remote_ok = self._is_remote(desc)

        jobs.append(
            JobPosting(
                source="Hacker News",
                url=first_link or permalink or "",
                title=title or "Software Engineer",
                company=company or "Unknown",
                location=location or "Unknown",
                description=desc[:600] + ("..." if len(desc) > 600 else ""),
                posted_date=None,
                salary=None,
                job_type=None,
                remote_ok=remote_ok,
                requirements=[],
                seniority=self._guess_seniority(desc),
                tags=self._extract_tags(desc),
                raw_html=raw_html,
            )
        )

    # Fallback path: if we somehow got zero, try scanning all default comment cells
    if not jobs:
        candidates = soup.select("td.default")
        for cell in candidates:
            if per_page_limit and len(jobs) >= per_page_limit:
                break
            # Ensure this is a top-level by looking back for indentation of zero
            parent_row = cell.find_parent("tr", class_="athing comtr")
            if parent_row and not is_top_level(parent_row):
                continue

            comm_el = cell.select_one("span.commtext") or cell.select_one("div.comment span.commtext")
            if not comm_el:
                continue
            raw_html = str(comm_el)
            desc = self._clean_description(comm_el.get_text("\n", strip=True))
            if len(desc) < 60:
                continue

            first_link = None
            for a in comm_el.find_all("a", href=True):
                href = a["href"]
                if "news.ycombinator.com" in href or href.startswith("item?id="):
                    continue
                first_link = href
                break

            permalink = None
            age_a = cell.select_one("span.age > a")
            if age_a and age_a.get("href"):
                permalink = urljoin(base_url, age_a["href"])

            company, title = self._guess_company_and_title(desc)
            location = self._guess_location(desc)
            remote_ok = self._is_remote(desc)

            jobs.append(
                JobPosting(
                    source="Hacker News",
                    url=first_link or permalink or "",
                    title=title or "Software Engineer",
                    company=company or "Unknown",
                    location=location or "Unknown",
                    description=desc[:600] + ("..." if len(desc) > 600 else ""),
                    posted_date=None,
                    salary=None,
                    job_type=None,
                    remote_ok=remote_ok,
                    requirements=[],
                    seniority=self._guess_seniority(desc),
                    tags=self._extract_tags(desc),
                    raw_html=raw_html,
                )
            )

    return jobs

    def _clean_description(self, text: str) -> str:
        t = html.unescape(text or "")
        t = re.sub(r"\s+\n", "\n", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        t = re.sub(r"[ \t]{2,}", " ", t)
        return t.strip()

    def _guess_company_and_title(self, desc: str) -> Tuple[Optional[str], Optional[str]]:
        first_line = desc.split("\n", 1)[0]

        m = re.match(r"^\s*([A-Z][\w .&+-]{1,60})\s*[—\-|:]\s*(.+)$", first_line)
        if m:
            company = re.sub(r"\s*\(YC\b.*?\)\s*$", "", m.group(1)).strip()
            title = re.sub(r"\s*[\(\[][^)\]]+[\)\]]\s*$", "", m.group(2)).strip()
            return company, title

        m = re.match(r"^\s*([A-Z][\w .&+-]{1,60})\s+(?:is\s+)?hiring\s+(.+)$", first_line, flags=re.I)
        if m:
            company = re.sub(r"\s*\(YC\b.*?\)\s*$", "", m.group(1)).strip()
            title = re.sub(r"\s*[\(\[][^)\]]+[\)\]]\s*$", "", m.group(2)).strip()
            return company, title

        m = re.search(r"\bat\s+([A-Z][\w .&+-]{1,60})\b", first_line)
        if m:
            company = re.sub(r"\s*\(YC\b.*?\)\s*$", "", m.group(1)).strip()
            before = first_line[: m.start()].strip(" -—|:")
            return company, (before or None)

        comp = None
        m = re.search(r"\b([A-Z][\w.&+-]{1,30}(?:\s+[A-Z][\w.&+-]{1,30}){0,2})\s+(?:is\s+)?hiring\b", desc, re.I)
        if m:
            comp = re.sub(r"\s*\(YC\b.*?\)\s*$", "", m.group(1)).strip()
        title = self._extract_title(desc)
        return comp, title

    def _guess_location(self, desc: str) -> Optional[str]:
        m = re.search(r"(location|locations?)\s*[:\-]\s*([^\n]+)", desc, re.I)
        if m:
            return m.group(2).strip()

        first = desc.split("\n", 1)[0]
        m2 = re.search(r"[\(\[]([^)\\\]]+)[\)\]]\s*$", first)
        if m2:
            loc = m2.group(1).strip()
            if not re.search(r"\bYC\b|\bS\d{2}\b|\bW\d{2}\b|\bF\d{2}\b", loc):
                return loc

        t = desc.lower()
        cities = ["san francisco", "sf", "new york", "nyc", "seattle", "austin", "boston", "london", "toronto", "berlin"]
        for c in cities:
            i = t.find(c)
            if i != -1:
                return desc[i : i + len(c)].strip().title()

        if "remote" in t or "anywhere" in t:
            return "Remote"

        return None

    def _is_remote(self, desc: str) -> bool:
        t = desc.lower()
        terms = ["remote", "anywhere", "distributed", "work from home", "wfh"]
        return any(term in t for term in terms)

    def _extract_title(self, desc: str) -> str:
        lines = desc.split("\n")
        candidates = lines[:3]
        role_terms = ["engineer", "developer", "manager", "scientist", "designer", "analyst", "lead", "architect"]
        for line in candidates:
            if any(w in line.lower() for w in role_terms):
                title = re.sub(r"\s*[\(\[][^)\]]+[\)\]]\s*$", "", line).strip()
                return title[:120]
        return "Software Engineer"

    def _guess_seniority(self, desc: str) -> Optional[str]:
        t = desc.lower()
        if re.search(r"\b(principal|staff)\b", t):
            return "principal" if "principal" in t else "staff"
        if re.search(r"\b(senior|sr\.)\b", t):
            return "senior"
        if re.search(r"\b(junior|jr\.)\b", t):
            return "junior"
        return None

    def _extract_tags(self, desc: str) -> List[str]:
        skills = [
            "python", "javascript", "typescript", "go", "rust", "java", "c++", "c#", "ruby",
            "react", "vue", "angular", "node", "django", "flask", "fastapi", "rails", "spring",
            "aws", "gcp", "azure", "kubernetes", "docker", "postgres", "mysql", "mongo", "redis",
            "ml", "machine learning", "nlp", "data", "analytics", "ios", "android", "devops",
        ]
        t = desc.lower()
        uniq: List[str] = []
        for s in skills:
            if s in t and s not in uniq:
                uniq.append(s)
        return uniq

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