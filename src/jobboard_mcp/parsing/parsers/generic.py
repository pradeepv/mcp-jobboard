from __future__ import annotations

from typing import List, Optional

from bs4 import BeautifulSoup  # type: ignore

from ..models import ParsedJob, Section
from ..registry import Parser, DetectionResult
from ..utils import sanitize_html, normalize_text, extract_tech_stack


class GenericHtmlParser(Parser):
    name = "generic_html"

    def detect(self, url: str, doc: BeautifulSoup) -> DetectionResult:
        # Conservative default: low score so specific parsers win.
        text_len = len((doc.body.get_text(" ") if doc.body else doc.get_text(" ")) or "")
        score = 10 if text_len > 200 else 0
        return DetectionResult(score=score, reason=f"text_len={text_len}")

    def parse(self, url: str, doc: BeautifulSoup) -> ParsedJob:
        job = ParsedJob(parser=self.name, url=url)

        # Title heuristic: first h1 or h2 near top; fallback to document title
        h = doc.select_one("h1, h2")
        if h:
            job.title = normalize_text(h.get_text(" "))
        elif doc.title and doc.title.string:
            job.title = normalize_text(doc.title.string)

        # Find a likely main content container: the largest block of text depth-wise
        container = self._largest_text_container(doc)

        # Split into sections using h2/h3 headings if present
        sections: List[Section] = []
        if container:
            headings = container.select("h2, h3")
            if headings:
                for heading_tag in headings:
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
            else:
                # No headings: take paragraphs and lists as one section
                blocks = container.select("p, ul, ol, li")
                html = sanitize_html("\n".join(str(b) for b in blocks)) if blocks else None
                text = normalize_text(BeautifulSoup(html or "", "html.parser").get_text(" \n")) if html else None
                if html or text:
                    sections.append(Section(heading=job.title or "Description", html=html, text=text))

        job.sections = sections
        job.descriptionText = "\n\n".join([s.text for s in sections if s.text]) or None
        job.descriptionHtml = "\n".join([s.html for s in sections if s.html]) or None

        if job.descriptionText:
            job.techStack = extract_tech_stack(job.descriptionText)

        # Scoring: based on description length and sections availability
        score = 0
        if job.title:
            score += 15
        if job.descriptionText and len(job.descriptionText) > 200:
            score += 60
        if sections:
            score += 25
        job.contentScore = min(100, score)

        return job

    def _largest_text_container(self, doc: BeautifulSoup) -> Optional[BeautifulSoup]:
        best = None
        best_len = 0
        for el in doc.find_all(["article", "main", "section", "div"]):
            # Skip nav/footer/header by class hints
            cls = " ".join(el.get("class") or [])
            if any(x in cls for x in ["nav", "footer", "header", "menu", "cookie"]):
                continue
            txt = el.get_text(" ") or ""
            l = len(txt)
            if l > best_len:
                best = el
                best_len = l
        return best or doc.body or doc

