from __future__ import annotations

from typing import List

from bs4 import BeautifulSoup  # type: ignore

from ..models import ParsedJob, Section
from ..registry import Parser, DetectionResult
from ..utils import sanitize_html, normalize_text, extract_tech_stack, guess_location, classify_section, extract_list_items_from_html


class GreenhouseJobParser(Parser):
    name = "greenhouse_job"

    def detect(self, url: str, doc: BeautifulSoup) -> DetectionResult:
        score = 0
        reasons: List[str] = []
        if "greenhouse.io" in url or "boards.greenhouse" in url:
            score += 40
            reasons.append("domain")
        # Common GH containers
        if doc.select_one("#app, .app, .content, .application, .opening, .job"):
            score += 30
            reasons.append("app/content container")
        if doc.select_one("h1, h2"):
            score += 10
            reasons.append("has heading")
        return DetectionResult(score=score, reason=",".join(reasons) or "no-match")

    def parse(self, url: str, doc: BeautifulSoup) -> ParsedJob:
        job = ParsedJob(parser=self.name, url=url, source="Greenhouse")

        # Title heuristics
        h = doc.select_one("h1, h2")
        if h:
            job.title = normalize_text(h.get_text(" "))

        # Company name best-effort from title tag
        page_title = (doc.title.string or "") if doc.title else ""
        if page_title:
            parts = [p.strip() for p in page_title.split("-") if p.strip()]
            if len(parts) >= 2:
                job.company = parts[-1]

        container = doc.select_one("#app, .app, .content, .application, .opening, .job") or doc

        sections: List[Section] = []
        # Many GH pages use h2/h3 to segment content
        for heading_tag in container.select("h2, h3"):
            heading = normalize_text(heading_tag.get_text(" "))
            html_parts: List[str] = []
            for sib in heading_tag.find_all_next():
                if sib == heading_tag:
                    continue
                if sib.name in ("h2", "h3"):
                    break
                if sib.name in ("div", "p", "ul", "ol", "li"):
                    html_parts.append(str(sib))
            html = sanitize_html("\n".join(html_parts)) if html_parts else None
            text = normalize_text(BeautifulSoup(html or "", "html.parser").get_text(" \n")) if html else None
            if heading or html or text:
                sections.append(Section(heading=heading or "", html=html, text=text))

        job.sections = sections
        job.descriptionText = "\n\n".join([s.text for s in sections if s.text]) or None
        job.descriptionHtml = "\n".join([s.html for s in sections if s.html]) or None

        loc = guess_location(container.get_text(" ")) if container else None
        if loc:
            job.location = loc

        if job.descriptionText:
            job.techStack = extract_tech_stack(job.descriptionText)

        # Extract lists by section heading classification
        for s in sections:
            kind = classify_section(s.heading)
            if not kind or not s.html:
                continue
            items = extract_list_items_from_html(s.html)
            if not items:
                continue
            if kind == "requirements":
                job.requirements.extend(items)
            elif kind == "responsibilities":
                job.responsibilities.extend(items)
            elif kind == "benefits":
                job.benefits.extend(items)

        # Basic scoring
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
