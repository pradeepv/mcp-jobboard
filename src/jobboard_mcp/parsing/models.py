from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class Section:
    heading: str
    html: Optional[str] = None
    text: Optional[str] = None


@dataclass
class SalaryInfo:
    min: Optional[float] = None
    max: Optional[float] = None
    currency: Optional[str] = None
    periodicity: Optional[str] = None  # e.g., year, hour, month
    raw: Optional[str] = None


@dataclass
class CompanyProfile:
    name: Optional[str] = None
    tagline: Optional[str] = None
    aboutHtml: Optional[str] = None
    aboutText: Optional[str] = None
    links: Dict[str, Optional[str]] = field(default_factory=dict)  # careers, website, linkedin, twitter
    locations: List[str] = field(default_factory=list)


@dataclass
class ParsedJob:
    # Core
    id: Optional[str] = None
    source: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    postedDate: Optional[str] = None
    salary: Optional[str] = None
    jobType: Optional[str] = None
    remoteOk: Optional[bool] = None
    tags: List[str] = field(default_factory=list)

    # Rich content
    descriptionHtml: Optional[str] = None
    descriptionText: Optional[str] = None
    sections: List[Section] = field(default_factory=list)
    salaryInfo: Optional[SalaryInfo] = None
    requirements: List[str] = field(default_factory=list)
    responsibilities: List[str] = field(default_factory=list)
    benefits: List[str] = field(default_factory=list)
    techStack: List[str] = field(default_factory=list)
    seniority: Optional[str] = None
    companyProfile: Optional[CompanyProfile] = None

    # Provenance/meta
    parser: Optional[str] = None  # yc_job, ashby_job, lever_job, greenhouse_job, generic_html, redirect_hub
    contentScore: Optional[int] = None
    warnings: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

