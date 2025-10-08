from __future__ import annotations

from typing import List

from bs4 import BeautifulSoup  # type: ignore

from ..models import ParsedJob, Section
from ..registry import Parser, DetectionResult
from ..utils import sanitize_html, normalize_text, extract_tech_stack, guess_location


class YcJobParser(Parser):
    name = "yc_job"

    def detect(self, url: str, doc: BeautifulSoup) -> DetectionResult:
        score = 0
        reason = []
        if "ycombinator.com/companies/" in url and "/jobs/" in url:
            score += 60
            reason.append("url-match")
        # DOM signatures
        if doc.select_one("h1.ycdc-section-title.mb-2"):
            score += 25
            reason.append("h1.ycdc-section-title")
        if doc.select_one("div.prose.max-w-full"):
            score += 15
            reason.append("div.prose.max-w-full")
        return DetectionResult(score=score, reason=",".join(reason) or "no-match")

    def parse(self, url: str, doc: BeautifulSoup) -> ParsedJob:
        job = ParsedJob(parser=self.name, url=url, source="Y Combinator")

        # Company name and tagline
        comp_blk = doc.select_one("div.space-y-1")
        if comp_blk:
            # First strong/text node as name; next text as tagline (best-effort)
            job.company = normalize_text(comp_blk.get_text(separator=" ") or "").split(" · ")[0].strip() or None

        # Title
        h1 = doc.select_one("h1.ycdc-section-title.mb-2")
        if h1:
            job.title = normalize_text(h1.get_text(" "))

        # Try to guess location from nearby text blocks
        header_blk = h1.parent if h1 else None
        if header_blk:
            header_text = normalize_text(header_blk.get_text(" "))
            loc = guess_location(header_text)
            if loc:
                job.location = loc

        # Sections: collect h2.ycdc-section-title and following content until next h2
        sections: List[Section] = []
        for h2 in doc.select("h2.ycdc-section-title"):
            heading = normalize_text(h2.get_text(" "))
            html_parts: List[str] = []
            for sib in h2.find_all_next():
                # stop when encountering the next h2 at the same level
                if sib == h2:
                    continue
                if sib.name == "h2" and "ycdc-section-title" in (sib.get("class") or []):
                    break
                # capture prose blocks only
                if sib.name in ("div", "p", "ul", "ol", "li"):
                    html_parts.append(str(sib))
            html = sanitize_html("\n".join(html_parts)) if html_parts else None
            text = normalize_text(BeautifulSoup(html or "", "html.parser").get_text(" \n")) if html else None
            if heading or html or text:
                sections.append(Section(heading=heading or "", html=html, text=text))

        job.sections = sections
        # Description text as concatenation of section texts
        job.descriptionText = "\n\n".join([s.text for s in sections if s.text]) or None
        job.descriptionHtml = "\n".join([s.html for s in sections if s.html]) or None

        # Derive tech stack from description
        if job.descriptionText:
            job.techStack = extract_tech_stack(job.descriptionText)

        # TODO: salary/location normalization from metadata lines
        # TODO: requirements/responsibilities/benefits from ULs within relevant sections

        # Basic content score
        score = 0
        if job.title:
            score += 25
        if job.company:
            score += 15
        if job.descriptionText and len(job.descriptionText) > 120:
            score += 40
        if sections:
            score += 20
        job.contentScore = min(100, score)

        return job

