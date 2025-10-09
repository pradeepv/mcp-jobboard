from __future__ import annotations

from typing import List

from bs4 import BeautifulSoup  # type: ignore

from ..models import ParsedJob, Section, CompanyProfile
from ..registry import Parser, DetectionResult
from ..utils import sanitize_html, normalize_text, extract_tech_stack, guess_location, classify_section, extract_list_items_from_html, extract_company_links, extract_company_tagline, find_about_company


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

        # Strip obvious non-description UI chrome to reduce noise
        for el in doc.select("nav, header, footer, form, aside, [role='dialog'], .overlay, .modal, .application, .apply, .field, .input, .select"):
            try:
                el.decompose()
            except Exception:
                pass

        # Prefer a more specific description container to avoid grabbing the entire app chrome
        container = (
            doc.select_one(".content .body")
            or doc.select_one(".content .section")
            or doc.select_one(".application .content")
            or doc.select_one(".opening .content")
            or doc.select_one(".job .content")
            or doc.select_one("#content")
            or doc.select_one(".job-posting")
            or doc.select_one("article .content")
            or doc.select_one(".content")
            or doc
        )

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

        # If no headings found, attempt heuristic pseudo-sections by keyword anchors within container
        if not sections:
            keywords = [
                ("Responsibilities", "responsibilities"),
                ("Qualifications", "requirements"),
                ("Requirements", "requirements"),
                ("Benefits", "benefits"),
                ("Perks", "benefits"),
            ]
            text_blocks = container.find_all(["strong", "b", "h4", "h5", "p"])
            for tb in text_blocks:
                t = normalize_text(tb.get_text(" "))
                for kw, _kind in keywords:
                    if kw.lower() in t.lower():
                        # collect following siblings until next strong/heading
                        html_parts: List[str] = []
                        for sib in tb.find_all_next():
                            if sib == tb:
                                continue
                            if sib.name in ("strong", "b", "h2", "h3", "h4", "h5", "hr"):
                                break
                            if sib.name in ("div", "p", "ul", "ol", "li"):
                                html_parts.append(str(sib))
                        html = sanitize_html("\n".join(html_parts)) if html_parts else None
                        text = normalize_text(BeautifulSoup(html or "", "html.parser").get_text(" \n")) if html else None
                        if html or text:
                            sections.append(Section(heading=kw, html=html, text=text))
                        break

        # If still no sections, create a section per large list to surface bullets
        if not sections:
            lists = container.select("ul, ol")
            for i, lst in enumerate(lists[:3]):  # limit to first few lists
                html = sanitize_html(str(lst))
                text = normalize_text(BeautifulSoup(html, "html.parser").get_text(" \n"))
                if text and len(text) > 60:
                    sections.append(Section(heading=f"List {i+1}", html=html, text=text))

        job.sections = sections
        job.descriptionText = "\n\n".join([s.text for s in sections if s.text]) or None
        job.descriptionHtml = "\n".join([s.html for s in sections if s.html]) or None

        ctxt = container.get_text(" ") if container else ""
        loc = guess_location(ctxt) if ctxt else None
        if loc:
            job.location = loc
        from ..utils import parse_salary_components, refine_location
        meta = normalize_text(ctxt)[:300]
        sal = parse_salary_components(meta)
        if sal:
            mn, mx, cur, per, raw = sal
            from ..models import SalaryInfo
            job.salaryInfo = SalaryInfo(min=mn, max=mx, currency=cur, periodicity=per, raw=raw)
        job.location = refine_location(meta, job.location or "Unknown")

        # Company inference from meta/site_name or page title if missing
        if not job.company and doc.title and doc.title.string:
            pt = doc.title.string
            parts = [p.strip() for p in pt.split("-") if p.strip()]
            if len(parts) >= 2:
                job.company = parts[-1]
        if not job.company:
            ogsn = doc.find("meta", attrs={"property": "og:site_name"})
            if ogsn and ogsn.get("content"):
                job.company = normalize_text(ogsn["content"]) or job.company

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
