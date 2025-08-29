from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

@dataclass
class JobPosting:
    # Identity and provenance
    id: Optional[str] = None
    source: str = ""

    # Links
    url: str = ""

    # Core fields
    title: str = ""
    company: str = "Unknown"
    location: str = "Unknown"
    description: str = ""

    # Optional metadata
    posted_date: Optional[datetime] = None
    salary: Optional[str] = None
    job_type: Optional[str] = None
    remote_ok: bool = False
    requirements: List[str] = field(default_factory=list)
    seniority: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    # Raw content (optional)
    raw_html: Optional[str] = None