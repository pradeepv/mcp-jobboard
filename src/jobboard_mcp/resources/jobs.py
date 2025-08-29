from typing import List
from mcp.types import Resource

def list_job_resources() -> List[Resource]:
    return [
        Resource(uri="jobs://ycombinator", name="Y Combinator Jobs", description="YC job listings", mimeType="application/json"),
        Resource(uri="jobs://hackernews", name="Hacker News Who is Hiring", description="Monthly HN hiring threads", mimeType="application/json"),
        Resource(uri="jobs://techcrunch", name="TechCrunch Job Articles", description="Job-related articles", mimeType="application/json"),
        Resource(uri="jobs://linkedin", name="LinkedIn Jobs (Limited)", description="LinkedIn (mock/demo)", mimeType="application/json"),
    ]
    