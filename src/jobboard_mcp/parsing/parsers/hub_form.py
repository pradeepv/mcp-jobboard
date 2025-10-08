from __future__ import annotations

from typing import List

from bs4 import BeautifulSoup  # type: ignore

from ..models import ParsedJob, Section, CompanyProfile
from ..registry import Parser, DetectionResult
from ..utils import normalize_text


class HubOrFormParser(Parser):
    name = "redirect_hub"

    def detect(self, url: str, doc: BeautifulSoup) -> DetectionResult:
        score = 0
        reasons: List[str] = []
        # Heuristics: lots of links to job cards, or presence of significant forms without description content
        job_card_selectors = [
            ".job-card", ".jobs-list", "[data-job]", "[data-job-card]",
            ".careers-list", ".openings", ".positions",
        ]
        has_cards = any(doc.select(sel) for sel in job_card_selectors)
        if has_cards:
            score += 30
            reasons.append("job-cards")
        # Form-heavy page without much copy
        forms = doc.select("form")
        body_text = normalize_text(doc.body.get_text(" ") if doc.body else doc.get_text(" "))
        if forms and len(body_text) < 600:
            score += 25
            reasons.append("form-gated")
        return DetectionResult(score=score, reason=",".join(reasons) or "no-match")

    def parse(self, url: str, doc: BeautifulSoup) -> ParsedJob:
        job = ParsedJob(parser=self.name, url=url)

        # Company profile guesses from title and meta
        company = None
        if doc.title and doc.title.string:
            t = doc.title.string
            parts = [p.strip() for p in t.split("-") if p.strip()]
            if parts:
                company = parts[0]
        job.companyProfile = CompanyProfile(name=company, links={})

        # Guidance message as descriptionText
        msg = (
            "This page appears to list multiple jobs or requires a form/application "
            "before viewing a detailed job description. Please select a specific job "
            "posting link to retrieve a full description."
        )
        job.descriptionText = msg
        job.sections = [Section(heading="Overview", text=msg, html=None)]
        job.contentScore = 20
        job.warnings.append("hub_or_form_detected")

        return job

