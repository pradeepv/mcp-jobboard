from __future__ import annotations

import asyncio
import re
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Callable
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from ..crawlers.base import BaseCrawler
from ..crawlers.hackernews_jobs import HackerNewsJobsCrawler
from ..crawlers.ycombinator import YCombinatorCrawler
from ..crawlers.workatastartup import WorkAtStartupCrawler
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
        "workatastartup": WorkAtStartupCrawler,
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

<<<<<<< HEAD
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
=======
    # --------------------
    # Finite streaming (page-by-page)
    # --------------------
    async def search_jobs_stream(
        self,
        keywords: Optional[List[str]],
        sources: List[str],
        location: str,
        remote_only: bool,
        max_pages: int = 1,
        per_source_limit: int = 100,
        tags: Optional[List[str]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Yields structured events page-by-page for a finite run.
        Event schema:
          - start, source_start, page_start, job, page_complete, source_complete, complete, error
        Filtering (remote_only, location, tags) is applied before yielding jobs.
        Dedupe within a single page is implicit via source/crawler; cross-page dedupe is not applied in finite mode.
        """
        requested_sources = [s.lower().strip() for s in sources if s and s.strip()]
        req_tags_norm = self._normalize_tags(tags)

        yield {
            "type": "start",
            "sources": requested_sources,
            "max_pages": max_pages,
            "per_source_limit": per_source_limit,
        }

        total_jobs = 0
        total_pages = 0

        for src in requested_sources:
            yield {"type": "source_start", "source": src}
            source_total = 0
            pages_emitted = 0

            inst = self._get_instance(src)

            # Strategy A (preferred): if crawler supports per-page crawl, use it.
            crawl_page_fn = getattr(inst, "crawl_page", None)

            for page in range(1, max_pages + 1):
                yield {"type": "page_start", "source": src, "page": page}
                pages_emitted += 1
                total_pages += 1
                page_jobs: List[JobPosting] = []

                try:
                    if callable(crawl_page_fn):
                        # Ideal path: crawler implements crawl_page(keywords=..., page=..., per_page_limit=...)
                        try:
                            page_jobs = await crawl_page_fn(
                                keywords=keywords,
                                page=page,
                                per_page_limit=per_source_limit,
                            )
                        except TypeError:
                            # Fallback: maybe no per_page_limit arg
                            page_jobs = await crawl_page_fn(
                                keywords=keywords,
                                page=page,
                            )
                    else:
                        # Strategy B (compat): if no crawl_page, approximate by calling crawl up to 'page'
                        try:
                            all_upto_page = await inst.crawl(
                                keywords=keywords,
                                max_pages=page,
                                per_page_limit=per_source_limit,
                            )
                        except TypeError:
                            try:
                                all_upto_page = await inst.crawl(
                                    keywords=keywords,
                                    max_pages=page,
                                )
                            except TypeError:
                                all_upto_page = await inst.crawl()  # type: ignore

                        # Compute the slice for "this page".
                        if per_source_limit:
                            start_idx = (page - 1) * per_source_limit
                            end_idx = start_idx + per_source_limit
                            page_jobs = all_upto_page[start_idx:end_idx]
                        else:
                            # Conservative default page size if unknown
                            start_idx = (page - 1) * 50
                            end_idx = start_idx + 50
                            page_jobs = all_upto_page[start_idx:end_idx]

                except Exception as ex:
                    yield {"type": "error", "message": str(ex), "source": src, "page": page}
                    yield {"type": "page_complete", "source": src, "page": page, "count": 0}
                    continue

                # Apply filters and emit jobs
                emitted_count = 0
                for j in page_jobs:
                    if remote_only and not getattr(j, "remote_ok", False):
                        continue
                    if location and not self._location_match(j, location):
                        continue
                    if req_tags_norm and not self._has_required_tags(j, req_tags_norm):
                        continue

                    key = self._compute_job_key(src, j)
                    yield {
                        "type": "job",
                        "source": src,
                        "page": page,
                        "key": key,
                        "data": self._as_obj(j),
                    }
                    emitted_count += 1
                    total_jobs += 1
                    source_total += 1

                yield {"type": "page_complete", "source": src, "page": page, "count": emitted_count}

                # Early stop for this source if empty page encountered
                if emitted_count == 0:
                    break

            yield {"type": "source_complete", "source": src, "pages": pages_emitted, "total": source_total}

        yield {"type": "complete", "total_jobs": total_jobs, "sources": len(requested_sources), "pages": total_pages}

    # Helpers

    def _as_obj(self, job: JobPosting) -> Dict[str, Any]:
        if hasattr(job, "model_dump"):
            return job.model_dump()
        d = getattr(job, "__dict__", {}) or {}
        return dict(d)

    def _compute_job_key(self, source: str, job: JobPosting) -> str:
        """
        Consistent key across events.
        Preference: canonical_url + external/posting id when available.
        Fallbacks to canonical_url + source to at least group by source.
        """
        url = self._canonical_url(getattr(job, "url", None))
        jid = getattr(job, "external_id", None) or getattr(job, "posting_id", None) or ""
        if jid:
            return f"{source}:{url}::{jid}"
        return f"{source}:{url}"
>>>>>>> feature/work-at-startup-crawler

    def _normalize_tags(self, tags: Optional[List[str]]) -> List[str]:
        if not tags:
            return []
        return [t.strip().lower() for t in tags if t and t.strip()]

    def _has_required_tags(self, job: JobPosting, req_tags_norm: List[str]) -> bool:
        job_tags = [t.strip().lower() for t in (job.tags or []) if t and t.strip()]
        return all(t in job_tags for t in req_tags_norm)

    def _canonical_url(self, url: Optional[str]) -> str:
        """
        Canonicalize URLs while preserving meaningful job identifiers.
        - Removes common tracking parameters (utm_*, gh_src, ref, source, lever-source)
        - Preserves meaningful params like ashby_jid
        - Keeps proper separators and removes empty query/fragment
        """
        if not url:
            return ""
<<<<<<< HEAD
        u = url.strip()
        u = re.sub(r"[?#](utm_[^=&]+=[^&]*&?)+", "", u, flags=re.I)
        u = re.sub(r"[?#](gh_src|ref|source|lever-source|ashby_jid|ashby_src)=[^&]*&?", "?", u, flags=re.I)
        u = re.sub(r"\?&+$", "?", u)
        u = re.sub(r"[?#]$", "", u)
        return u
=======
        try:
            parsed = urlparse(url.strip())
            # Lowercase scheme and netloc for consistency
            scheme = (parsed.scheme or "").lower()
            netloc = (parsed.netloc or "").lower()
            path = parsed.path or ""

            # Parse query parameters
            params = parse_qsl(parsed.query, keep_blank_values=False)

            # Known tracking params to drop
            drop_prefixes = ("utm_",)
            drop_exact = {"gh_src", "ref", "source", "lever-source"}

            kept = []
            for k, v in params:
                kl = k.lower()
                if kl.startswith(drop_prefixes) or kl in drop_exact:
                    continue
                # Keep all others (e.g., ashby_jid)
                kept.append((k, v))

            query = urlencode(kept, doseq=True)

            # Remove fragment
            fragment = ""

            # If query becomes empty, ensure we don't end up with trailing ? or concatenation issues
            canonical = urlunparse((scheme, netloc, path, "", query, fragment))
            return canonical
        except Exception:
            # Fallback to older conservative regex cleanups if parsing fails
            u = url.strip()
            u = re.sub(r"[?#](utm_[^=&]+=[^&]*&?)+", "", u, flags=re.I)
            u = re.sub(r"[?#](gh_src|ref|source|lever-source|ashby_jid|ashby_src)=[^&]*&?", "?", u, flags=re.I)
            u = re.sub(r"\?&+$", "?", u)
            u = re.sub(r"[?#]$", "", u)
            return u
>>>>>>> feature/work-at-startup-crawler

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
            getattr(job, "location", "") or "",
            getattr(job, "title", "") or "",
            getattr(job, "company", "") or "",
        ]
        blob_parts.extend(getattr(job, "tags", []) or [])
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