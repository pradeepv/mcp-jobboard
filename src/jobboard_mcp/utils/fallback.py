"""
Fallback utilities for handling incomplete or messy job data.
Provides robust data sanitization and career page detection.
"""
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup

from ..models.job import JobPosting


def generate_fallback_id(job_data: Dict[str, Any]) -> str:
    """Generate a stable ID from available job data."""
    # Try to use URL-based ID, fall back to title+company hash
    if job_data.get('url'):
        return f"job_{abs(hash(job_data['url']))}"
    elif job_data.get('title') and job_data.get('company'):
        combined = f"{job_data['title']}_{job_data['company']}"
        return f"job_{abs(hash(combined))}"
    else:
        return f"job_{abs(hash(str(job_data)))}_{datetime.now().timestamp()}"


def extract_company_from_url(url: str) -> str:
    """Extract company name from URL domain."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Remove www. and extract main domain part
        domain = domain.replace('www.', '')
        parts = domain.split('.')
        if len(parts) >= 2:
            return parts[-2].title()
        return domain.title()
    except:
        return "Unknown"


def detect_career_page(url: str, html_content: str = "") -> bool:
    """Detect if URL points to careers page rather than specific job."""
    url_lower = url.lower()
    content_lower = html_content.lower()[:2000]  # Check first 2k chars

    # Enhanced URL patterns indicating career pages
    career_url_patterns = [
        r'/careers?', r'/jobs?', r'/positions?', r'/opportunities?',
        r'/join-?us', r'/work-?with-?us', r'/hiring',
        # Specific patterns for the URLs provided
        r'careers\.[^/]+$',  # careers.activeloop.ai
        r'/job-?board',       # General job board patterns
        r'/open-?roles'        # Open roles pages
    ]

    # Specific domain patterns that are career pages
    career_domains = [
        'careers.activeloop.ai',
        'jobs.lever.co', 'boards.greenhouse.io',
        'jobs.ashbyhq.com', 'apply.workable.com'
    ]

    # Content patterns indicating career pages
    career_content_patterns = [
        r'we are hiring', r'join our team', r'open positions',
        r'current openings', r'career opportunities', r'work at',
        r'all positions', r'browse jobs', r'job listings',
        # Additional patterns
        r'multiple positions', r'see all jobs', r'view all openings',
        r'explore opportunities', r'current job openings'
    ]

    # Check if URL matches career domains
    parsed_url = urlparse(url)
    if parsed_url.netloc.lower() in career_domains:
        return True

    # Check URL patterns
    for pattern in career_url_patterns:
        if re.search(pattern, url_lower):
            return True

    # Check content patterns
    for pattern in career_content_patterns:
        if re.search(pattern, content_lower):
            return True

    # Specific check for YC company pages - these are individual jobs, not career pages
    if 'ycombinator.com/companies/' in url_lower and '/jobs/' in url_lower:
        return False

    # Specific check for Notion pages - they're usually career boards
    if 'notion.site' in url_lower or 'notion.so' in url_lower:
        return True

    return False


def extract_job_links_from_career_page(html_content: str, base_url: str) -> List[str]:
    """Extract individual job posting URLs from career pages."""
    if not html_content:
        return []

    soup = BeautifulSoup(html_content, 'html.parser')
    job_links = []

    # Platform-specific selectors
    platform_selectors = {
        'activeloop.ai': [
            'a[href*="/jobs/"]',
            'a[href*="/positions/"]',
            '.job-card a',
            '.position-link a',
            '[data-job-id]'
        ],
        'notion.site': [
            'a[href*="/job"]',
            'a[href*="/position"]',
            'a[href*="/role"]',
            '.notion-link',
            '[data-block-id]'
        ],
        'default': [
            'a[href*="/job"]',
            'a[href*="/position"]',
            'a[href*="/role"]',
            'a[href*="/opening"]',
            '.job-listing a',
            '.position a',
            '.opening a',
            '[data-job-id]',
            '[data-position]'
        ]
    }

    # Determine platform from base URL
    platform = 'default'
    if 'activeloop.ai' in base_url.lower():
        platform = 'activeloop.ai'
    elif 'notion.site' in base_url.lower() or 'notion.so' in base_url.lower():
        platform = 'notion'

    seen_urls = set()

    # Use platform-specific selectors first
    selectors = platform_selectors.get(platform, platform_selectors['default'])

    # Add common selectors for fallback
    common_selectors = [
        'a[href*="/jobs/"]',
        'a[href*="/careers/"]',
        'a[href*="/apply"]',
        'a[href*="/join"]'
    ]
    selectors.extend(common_selectors)

    for selector in selectors:
        try:
            links = soup.select(selector)
            for link in links:
                href = link.get('href')
                if href and not href.startswith('#') and not href.startswith('mailto:'):
                    full_url = urljoin(base_url, href)

                    # Filter out non-job URLs
                    if is_job_url(full_url):
                        if full_url not in seen_urls:
                            job_links.append(full_url)
                            seen_urls.add(full_url)
        except Exception as e:
            # Continue with other selectors if one fails
            continue

    # If no job links found, try text-based extraction for specific platforms
    if not job_links and platform == 'notion':
        job_links.extend(extract_notion_job_links(soup, base_url))

    return list(job_links)[:10]  # Limit to first 10 jobs


def is_job_url(url: str) -> bool:
    """Check if a URL appears to be a job posting URL."""
    url_lower = url.lower()

    # Non-job URL patterns to exclude
    exclude_patterns = [
        '/about', '/contact', '/team', '/culture', '/benefits',
        '/privacy', '/terms', '/blog', '/news', '/press',
        '/login', '/register', '/signup', '/apply/general'
    ]

    for pattern in exclude_patterns:
        if pattern in url_lower:
            return False

    # Job URL patterns to include
    job_patterns = [
        '/job', '/position', '/role', '/opening', '/opportunity',
        '/careers', '/jobs', '/apply', '/join', '/work'
    ]

    return any(pattern in url_lower for pattern in job_patterns)


def extract_notion_job_links(soup: BeautifulSoup, base_url: str) -> List[str]:
    """Extract job links from Notion pages using text analysis."""
    job_links = []

    # Look for links that contain job-related text
    links = soup.find_all('a', href=True)
    for link in links:
        text = link.get_text().strip().lower()
        href = link.get('href')

        # Check if link text suggests it's a job posting
        job_keywords = [
            'engineer', 'developer', 'manager', 'director', 'analyst',
            'designer', 'product', 'marketing', 'sales', 'support',
            'senior', 'junior', 'lead', 'principal', 'staff'
        ]

        if any(keyword in text for keyword in job_keywords) and href:
            full_url = urljoin(base_url, href)
            if is_job_url(full_url):
                job_links.append(full_url)

    return job_links


def sanitize_job_title(title: str) -> str:
    """Clean and normalize job title."""
    if not title:
        return "Job Posting"

    # Remove common prefixes/suffixes
    cleaned = re.sub(r'^(job|position|role):\s*', '', title.strip(), flags=re.IGNORECASE)

    # Capitalize properly
    cleaned = ' '.join(word.capitalize() for word in cleaned.split())

    return cleaned if cleaned else "Job Posting"


def assess_data_quality(job_data: Dict[str, Any]) -> str:
    """Assess the quality/completeness of job data."""
    critical_fields = ['title']
    important_fields = ['company', 'url', 'source']
    optional_fields = ['location', 'description', 'salary']

    has_critical = all(job_data.get(field) for field in critical_fields)
    has_important = any(job_data.get(field) for field in important_fields)
    has_optional = any(job_data.get(field) for field in optional_fields)

    if has_critical and has_important and has_optional:
        return 'complete'
    elif has_critical and has_important:
        return 'partial'
    elif has_critical:
        return 'minimal'
    else:
        return 'invalid'


def create_fallback_job_posting(raw_data: Dict[str, Any]) -> JobPosting:
    """Create a JobPosting with intelligent fallbacks for missing data."""
    # Generate stable ID
    job_id = raw_data.get('id') or generate_fallback_id(raw_data)

    # Title with fallback
    title = sanitize_job_title(raw_data.get('title', ''))

    # Company with extraction fallback
    company = (raw_data.get('company') or
               extract_company_from_url(raw_data.get('url', '')) or
               "Unknown Company")

    # Source fallback
    source = raw_data.get('source') or raw_data.get('source_key', 'Unknown')

    # Other fields with sensible defaults
    location = raw_data.get('location') or "Unknown"
    description = raw_data.get('description') or ""
    snippet = raw_data.get('snippet') or raw_data.get('description', '')[:200]

    # Parse dates safely
    posted_date = None
    if raw_data.get('posted_at'):
        try:
            posted_date = datetime.fromisoformat(raw_data['posted_at'].replace('Z', '+00:00'))
        except:
            pass

    return JobPosting(
        id=job_id,
        title=title,
        company=company,
        location=location,
        description=description,
        url=raw_data.get('url', ''),
        source=source,
        posted_date=posted_date,
        salary=raw_data.get('salary'),
        job_type=raw_data.get('job_type'),
        remote_ok=raw_data.get('remote_ok', False),
        requirements=raw_data.get('requirements', []),
        seniority=raw_data.get('seniority'),
        tags=raw_data.get('tags', []),
        source_key=raw_data.get('source_key'),
        raw_html=raw_data.get('raw_html')
    )


def to_standardized_dict(job_posting: JobPosting) -> Dict[str, Any]:
    """Convert JobPosting to standardized dictionary format."""
    return {
        "id": job_posting.id,
        "title": job_posting.title,
        "company": job_posting.company,
        "location": job_posting.location,
        "url": job_posting.url,
        "source": job_posting.source,
        "description": job_posting.description,
        "snippet": job_posting.description[:200] if job_posting.description else None,
        "salary": job_posting.salary,
        "remote_ok": job_posting.remote_ok,
        "job_type": job_posting.job_type,
        "posted_at": job_posting.posted_date.isoformat() if job_posting.posted_date else None,
        "tags": job_posting.tags,
        "requirements": job_posting.requirements,
        "seniority": job_posting.seniority,
        "data_quality": assess_data_quality(job_posting.__dict__)
    }