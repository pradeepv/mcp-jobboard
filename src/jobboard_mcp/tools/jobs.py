from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple, Callable
from urllib.parse import urlparse

from ..crawlers.base import BaseCrawler
from ..crawlers.hackernews_jobs import HackerNewsJobsCrawler
from ..crawlers.ycombinator import YCombinatorCrawler
from ..models.job import JobPosting

# --------------------
# ATS handler registry
# --------------------

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
    # collapse excessive blank lines, normalize bullets lightly
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # also collapse excessive spaces before newlines
    text = re.sub(r"[ \t]+\n", "\n", text)
    return text.strip()

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None  # type: ignore

@register_ats("jobs.ashbyhq.com")
@register_ats("www.ashbyhq.com")
def parse_ashby(job: JobPosting, html: str) -> JobPosting:
    if not BeautifulSoup:
        return job

    soup = BeautifulSoup(html, "html.parser")

    # Remove obvious chrome to avoid picking massive non-description areas
    for sel in ["header", "nav", "footer", "[role='navigation']", "[role='banner']", "[role='contentinfo']"]:
        for el in soup.select(sel):
            el.decompose()

    # Common Ashby containers (cover multiple tenant themes)
    selectors = [
        '[data-testid="job-posting__description"]',
        '[data-test="job-posting__description"]',
        '[data-testid="job-description"]',
        ".job-posting__description",
        ".JobPosting__Description",
        ".Posting__Description",
        ".posting-description",
        ".prose",                 # tailwind prose
        ".ProseMirror",           # editor output
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

    # Heuristic fallback: choose the largest text block inside <main> or whole page
    def biggest_text_block(root):
        candidates = []
        for el in root.find_all(["div", "section", "article"]):
            # Skip elements that are likely layout-only
            classes = " ".join(el.get("class", [])).lower()
            if any(c in classes for c in ["header", "nav", "footer", "sidebar", "apply", "application"]):
                continue
            text = el.get_text(" ", strip=True)
            if text and len(text) > 400:  # avoid trivial blocks
                candidates.append((len(text), el))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    if not node:
        root = soup.select_one("main") or soup  # prefer main region
        node = biggest_text_block(root) or biggest_text_block(soup)

    if node:
        # Clean out script/style/noscript
        for bad in node.find_all(["script", "style", "noscript"]):
            bad.decompose()
        text = node.get_text("\n", strip=True)
        if text:
            job.description = text_collapse(text)

    # Salary and remote hints
    blob = soup.get_text(" ", strip=True)
    m = re.search(r"(Salary|Compensation|Pay|Base)\s*[:\-]\s*([^\n]+)", blob, re.I)
    if m and not job.salary:
        job.salary = m.group(2).strip()
    job.remote_ok = job.remote_ok or ("remote" in blob.lower())

    return job

@register_ats("boards.greenhouse.io")
def parse_greenhouse(job: JobPosting, html: str) -> JobPosting:
    if not BeautifulSoup:
        return job
    soup = BeautifulSoup(html, "html.parser")
    # Greenhouse has fairly consistent containers but varies per company theme
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

@register_ats("jobs.lever.co")
def parse_lever(job: JobPosting, html: str) -> JobPosting:
    if not BeautifulSoup:
        return job
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one(".description, .section.page, .content, .content-container, .posting") or soup.find(id="job")
    if node:
        job.description = text_collapse(node.get_text("\n", strip=True))
    blob = soup.get_text(" ", strip=True)
    m = re.search(r"(Salary|Compensation|Pay)\s*[:\-]\s*([^\n]+)", blob, re.I)
    if m and not job.salary:
        job.salary = m.group(2).strip()
    job.remote_ok = job.remote_ok or ("remote" in blob.lower())
    return job

@register_ats("www.workatastartup.com")
def parse_workatastartup(job: JobPosting, html: str) -> JobPosting:
    if not BeautifulSoup:
        return job
    soup = BeautifulSoup(html, "html.parser")
    node = (
        soup.select_one(".job-detail, .job, main, article, #__next main")
        or soup.find("main")
        or soup.find("article")
    )
    if node:
        job.description = text_collapse(node.get_text("\n", strip=True))
    if "remote" in soup.get_text(" ", strip=True).lower():
        job.remote_ok = True
    return job

@register_ats("deepnote.com")
def parse_deepnote(job: JobPosting, html: str) -> JobPosting:
    if not BeautifulSoup:
        return job
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one("main, article, [data-page], .careers, .jobs")
    if node:
        job.description = text_collapse(node.get_text("\n", strip=True))
    if "remote" in soup.get_text(" ", strip=True).lower():
        job.remote_ok = True
    return job

class JobService:
    """
    Aggregates job crawlers behind one interface with filtering, dedupe, and enrichment.
    """

    SOURCE_MAP: Dict[str, type] = {
        "hackernews_jobs": HackerNewsJobsCrawler,
        "ycombinator": YCombinatorCrawler,
    }

    def __init__(self, cache_ttl_seconds: int = 600):
        self.cache_ttl_seconds = cache_ttl_seconds
        self._instances: Dict[str, BaseCrawler] = {}
        # Per-domain concurrency and global cap
        self._domain_semaphores: Dict[str, asyncio.Semaphore] = {}
        self._global_sem = asyncio.Semaphore(10)

    async def __aenter__(self) -> "JobService":
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.aclose()

    async def aclose(self):
        for inst in self._instances.values():
            close = getattr(inst, "close_session", None)
            if callable(close):
                try:
                    await close()
                    continue
                except Exception:
                    pass
            aclose = getattr(inst, "aclose", None)
            if callable(aclose):
                try:
                    await aclose()
                except Exception:
                    pass

    def _get_instance(self, key: str) -> BaseCrawler:
        key_l = key.lower()
        if key_l not in self.SOURCE_MAP:
            raise ValueError(f"Unknown source: {key}")
        if key_l not in self._instances:
            cls = self.SOURCE_MAP[key_l]
            self._instances[key_l] = cls()  # type: ignore[call-arg]
        return self._instances[key_l]

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

        tasks = [self._run_source(src, keywords, max_pages, per_source_limit) for src in requested_sources]
        results_lists = await asyncio.gather(*tasks, return_exceptions=True)

        jobs: List[JobPosting] = []
        for src, res in zip(requested_sources, results_lists):
            if isinstance(res, Exception):
                print(f"[WARN] source {src} failed: {res}")
                continue

            kept = []
            for j in res:
                if remote_only and not getattr(j, "remote_ok", False):
                    continue
                if location and not self._location_match(j, location):
                    continue
                if req_tags_norm and not self._has_required_tags(j, req_tags_norm):
                    continue
                kept.append(j)
            jobs.extend(kept)

        deduped = self._dedupe_jobs_merge_tags(jobs)

        if enrich and deduped:
            limit = enrich_limit if enrich_limit is not None else 50
            subset = deduped[:limit]
            try:
                enriched_subset = await self.enrich_details(subset)
                deduped[:len(enriched_subset)] = enriched_subset
            except Exception as e:
                print(f"[WARN] enrich failed: {e}")

        return deduped

    async def _run_source(
        self,
        source_key: str,
        keywords: Optional[List[str]],
        max_pages: int,
        per_source_limit: int,
    ) -> List[JobPosting]:
        inst = self._get_instance(source_key)
        try:
            jobs = await inst.crawl(
                keywords=keywords,
                max_pages=max_pages,
                per_page_limit=per_source_limit,
            )
        except TypeError:
            try:
                jobs = await inst.crawl(
                    keywords=keywords,
                    max_pages=max_pages,
                )
            except TypeError:
                jobs = await inst.crawl()  # type: ignore

        if per_source_limit and len(jobs) > per_source_limit:
            jobs = jobs[:per_source_limit]
        # ensure source_key is set if crawler forgot
        for j in jobs:
            if not getattr(j, "source_key", None):
                j.source_key = source_key
        return jobs

    # ------------- Enrichment -------------

    def _get_domain_sem(self, domain: str) -> asyncio.Semaphore:
        dom = domain.lower()
        if dom not in self._domain_semaphores:
            # Default to 4 concurrent per domain
            self._domain_semaphores[dom] = asyncio.Semaphore(4)
        return self._domain_semaphores[dom]

    async def enrich_details(self, jobs: List[JobPosting]) -> List[JobPosting]:
            seen_debug = {"count": 0}  # closure state for light debug

            async def enrich_one(job: JobPosting) -> JobPosting:
                if not job.url or (job.description and job.description.strip()):
                    return job

                parsed = urlparse(job.url)
                domain = parsed.netloc.lower()

                handler = ATS_HANDLER.get(domain)
                if not handler:
                    # debug for first items
                    if seen_debug["count"] < 15:
                        print(f"[enrich] skip: no handler for domain={domain} url={job.url}")
                        seen_debug["count"] += 1
                    return job

                # Choose a session: reuse the crawler session if possible
                crawler = None
                if job.source_key:
                    crawler = self._instances.get(job.source_key)

                async def fetch_html() -> Optional[str]:
                    try:
                        if crawler:
                            return await crawler.get_text(job.url, timeout=20)
                        if self._instances:
                            any_crawler = next(iter(self._instances.values()))
                            return await any_crawler.get_text(job.url, timeout=20)
                    except Exception as e:
                        if seen_debug["count"] < 15:
                            print(f"[enrich] fetch error for {domain}: {e}")
                            seen_debug["count"] += 1
                        return None
                    return None

                # Respect concurrency limits
                dom_sem = self._get_domain_sem(domain)
                async with self._global_sem, dom_sem:
                    html = await fetch_html()
                    if seen_debug["count"] < 15:
                        print(f"[enrich] domain={domain} handler=YES html_len={len(html) if html else 0} url={job.url}")
                        seen_debug["count"] += 1
                    if not html:
                        return job
                    try:
                        enriched = handler(job, html)
                        # If still empty, log once
                        if seen_debug["count"] < 15 and not (enriched.description or "").strip():
                            print(f"[enrich] handler produced empty description for domain={domain}")
                            seen_debug["count"] += 1
                        return enriched
                    except Exception as e:
                        if seen_debug["count"] < 15:
                            print(f"[enrich] handler error for {domain}: {e}")
                            seen_debug["count"] += 1
                        return job

            return await asyncio.gather(*(enrich_one(j) for j in jobs))    # ------------- Filters & Dedupe -------------

    def _normalize_tags(self, tags: Optional[List[str]]) -> List[str]:
        if not tags:
            return []
        return [t.strip().lower() for t in tags if t and t.strip()]

    def _has_required_tags(self, job: JobPosting, req_tags_norm: List[str]) -> bool:
        job_tags = [t.strip().lower() for t in (job.tags or []) if t and t.strip()]
        return all(t in job_tags for t in req_tags_norm)

    def _canonical_url(self, url: Optional[str]) -> str:
        if not url:
            return ""
        u = url.strip()
        u = re.sub(r"[?#](utm_[^=&]+=[^&]*&?)+", "", u, flags=re.I)
        u = re.sub(r"[?#](gh_src|ref|source|lever-source|ashby_jid|ashby_src)=[^&]*&?", "?", u, flags=re.I)
        u = re.sub(r"\?&+$", "?", u)
        u = re.sub(r"[?#]$", "", u)
        return u

    def _dedupe_jobs_merge_tags(self, jobs: List[JobPosting]) -> List[JobPosting]:
        seen: Dict[Tuple[str, str], int] = {}
        out: List[JobPosting] = []
        for j in jobs:
            key = (j.source or "", self._canonical_url(j.url))
            if key in seen:
                idx = seen[key]
                keep = out[idx]
                keep.tags = sorted(set((keep.tags or []) + (j.tags or [])))
                keep.remote_ok = bool(getattr(keep, "remote_ok", False) or getattr(j, "remote_ok", False))
                if (keep.location in (None, "", "Unknown")) and j.location and j.location != "Unknown":
                    keep.location = j.location
                if (keep.company in (None, "", "Unknown")) and j.company and j.company != "Unknown":
                    keep.company = j.company
                continue
            seen[key] = len(out)
            out.append(j)
        return out

    def _location_match(self, job: JobPosting, want: str) -> bool:
        if not want:
            return True
        want_norm = want.strip().lower()
        if not want_norm:
            return True

        aliases = {
            "united states": {"united states", "us", "usa", "u.s.", "u.s.a", "us-based", "us remote", "remote-us", "anywhere in the us"},
            "united kingdom": {"united kingdom", "uk", "u.k.", "britain", "england", "scotland", "wales"},
            "europe": {"europe", "eu", "e.u.", "european"},
            "canada": {"canada", "ca", "canadian"},
            "remote": {"remote", "anywhere", "distributed", "work from home", "wfh"},
            "san francisco": {"san francisco", "sf", "bay area"},
            "new york": {"new york", "ny", "nyc"},
        }

        want_set = {want_norm}
        for k, vals in aliases.items():
            if want_norm == k or want_norm in vals:
                want_set |= vals
                want_set.add(k)

        blob_parts = [
            job.location or "",
            job.title or "",
            job.company or "",
        ]
        blob_parts.extend(job.tags or [])
        blob = " ".join(blob_parts).lower()

        return any(alias in blob for alias in want_set)

    def list_job_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "search_jobs",
                "description": "Search aggregated jobs from multiple sources with filters.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keywords": {"type": ["array", "null"], "items": {"type": "string"}},
                        "sources": {"type": "array", "items": {"type": "string", "enum": list(self.SOURCE_MAP.keys())}},
                        "location": {"type": "string"},
                        "remote_only": {"type": "boolean"},
                        "max_pages": {"type": "integer", "minimum": 1, "default": 1},
                        "per_source_limit": {"type": "integer", "minimum": 1, "default": 100},
                        "tags": {"type": ["array", "null"], "items": {"type": "string"}},
                        "enrich": {"type": "boolean", "default": True},
                        "enrich_limit": {"type": ["integer", "null"], "default": 50},
                    },
                    "required": ["sources", "location", "remote_only"],
                },
            }
        ]