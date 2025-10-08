from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any

@dataclass
class JobPosting:
    # Identity and provenance
    id: Optional[str] = None
    source: str = ""                 # Human-friendly source label, e.g., "Y Combinator"

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

    # New: internal routing key for JobService/crawlers (e.g., "ycombinator", "hackernews_jobs")
    source_key: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to standardized dictionary format."""
        from ..utils.fallback import assess_data_quality, to_standardized_dict
        return to_standardized_dict(self)

    def __post_init__(self):
        """Post-initialization validation and cleanup."""
        # Ensure critical fields have sensible values
        if not self.title:
            self.title = "Job Posting"
        if not self.company:
            self.company = "Unknown Company"
        if not self.source:
            self.source = "Unknown"

        # Ensure ID is set
        if not self.id:
            from ..utils.fallback import generate_fallback_id
            self.id = generate_fallback_id(self.__dict__)