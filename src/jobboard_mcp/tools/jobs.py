from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

from ..crawlers.base import BaseCrawler
from ..crawlers.hackernews_jobs import HackerNewsJobsCrawler
from ..crawlers.ycombinator import YCombinatorCrawler
from ..models.job import JobPosting


class JobService:
    """
    Aggregates job crawlers behind one interface with filtering and dedupe.
    """

    # Register only crawlers that exist and are confirmed working.
    SOURCE_MAP: Dict[str, type] = {
        "hackernews_jobs": HackerNewsJobsCrawler,
        "ycombinator": YCombinatorCrawler,
    }

    def __init__(self, cache_ttl_seconds: int = 600):
        # Kept for API parity; not passed into crawlers (their __init__ doesn't accept it).
        self.cache_ttl_seconds = cache_ttl_seconds
        self._instances: Dict[str, BaseCrawler] = {}

    async def __aenter__(self) -> "JobService":
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.aclose()

    async def aclose(self):
        # Cleanly close any underlying aiohttp sessions via BaseCrawler.close_session()
        for inst in self._instances.values():
            # Prefer BaseCrawler.close_session
            close = getattr(inst, "close_session", None)
            if callable(close):
                try:
                    await close()
                    continue
                except Exception:
                    pass
            # Fallback to aclose if provided by a crawler
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
            # Do not pass unsupported kwargs
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

        print(
            f"DEBUG job_service: total_kept={len(deduped)} "
            f"(sources={requested_sources}, remote_only={remote_only}, location='{location}', tags={tags})"
        )

        return deduped

    async def _run_source(
        self,
        source_key: str,
        keywords: Optional[List[str]],
        max_pages: int,
        per_source_limit: int,
    ) -> List[JobPosting]:
        inst = self._get_instance(source_key)
        # Be lenient with crawler signatures
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
        return jobs

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
        # Trim common tracking params conservatively
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
                # Merge tags, prefer True for remote_ok, and fill missing company/location
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
                        "keywords": {
                            "type": ["array", "null"],
                            "items": {"type": "string"},
                        },
                        "sources": {
                            "type": "array",
                            "items": {"type": "string", "enum": list(self.SOURCE_MAP.keys())},
                        },
                        "location": {"type": "string"},
                        "remote_only": {"type": "boolean"},
                        "max_pages": {"type": "integer", "minimum": 1, "default": 1},
                        "per_source_limit": {"type": "integer", "minimum": 1, "default": 100},
                        "tags": {
                            "type": ["array", "null"],
                            "items": {"type": "string"},
                            "description": "Require all tags to be present (case-insensitive).",
                        },
                    },
                    "required": ["sources", "location", "remote_only"],
                },
            }
        ]