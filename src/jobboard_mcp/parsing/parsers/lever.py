from __future__ import annotations

from typing import List

from bs4 import BeautifulSoup  # type: ignore

from ..models import ParsedJob, Section, CompanyProfile
from ..registry import Parser, DetectionResult
from ..utils import (
    sanitize_html,
    normalize_text,
    extract_tech_stack,
    guess_location,
    classify_section,
    extract_list_items_from_html,
    extract_company_links,
    extract_company_tagline,
    find_about_company,
)


class LeverJobParser(Parser):
    name = "lever_job"

    def detect(self, url: str, doc: BeautifulSoup) -> DetectionResult:
        score = 0
        reasons: List[str] = []
        if "jobs.lever.co" in url or "lever.co" in url:
            score += 40
            reasons.append("domain")
        if doc.select_one(".posting"):
            score += 30
            reasons.append(".posting container")
        if doc.select_one(".posting-headline"):
            score += 10
            reasons.append(".posting-headline")
        if doc.select_one(".section, .posting-description"):
            score += 10
            reasons.append("content section")
        return DetectionResult(score=score, reason=",".join(reasons) or "no-match")

    def parse(self, url: str, doc: BeautifulSoup) -> ParsedJob:
        job = ParsedJob(parser=self.name, url=url, source="Lever")

        headline = doc.select_one(".posting-headline") or doc
        # Title: h2 or h1 within headline
        h = headline.select_one("h2, h1")
        if h:
            job.title = normalize_text(h.get_text(" "))

        # Company from document title or headline text (best-effort)
        page_title = (doc.title.string or "") if doc.title else ""
        if page_title:
            parts = [p.strip() for p in page_title.split("-") if p.strip()]
            if len(parts) >= 2:
                job.company = parts[-1]

        # Container for sections
        container = (
            doc.select_one(".posting") or doc.select_one(".posting-description") or doc
        )

        sections: List[Section] = []
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
            text = (
                normalize_text(BeautifulSoup(html or "", "html.parser").get_text(" \n"))
                if html
                else None
            )
            if heading or html or text:
                sections.append(Section(heading=heading or "", html=html, text=text))

        job.sections = sections
        job.descriptionText = "\n\n".join([s.text for s in sections if s.text]) or None
        job.descriptionHtml = "\n".join([s.html for s in sections if s.html]) or None

        # Location from headline/container + salary normalization
        htxt = headline.get_text(" ") if headline else ""
        loc = guess_location(htxt) if htxt else None
        if loc:
            job.location = loc
        from ..utils import parse_salary_components, refine_location

        meta = normalize_text(htxt)[:300]
        sal = parse_salary_components(meta)
        if sal:
            mn, mx, cur, per, raw = sal
            from ..models import SalaryInfo

            job.salaryInfo = SalaryInfo(
                min=mn, max=mx, currency=cur, periodicity=per, raw=raw
            )
        job.location = refine_location(meta, job.location or "Unknown")

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

        # Company profile enrichment
        links = extract_company_links(doc)
        tagline = extract_company_tagline(doc)
        about_text, about_html = find_about_company(sections)
        job.companyProfile = CompanyProfile(
            name=job.company,
            tagline=tagline,
            aboutText=about_text,
            aboutHtml=about_html,
            links=links,
            locations=[job.location] if job.location else [],
        )

        return job
