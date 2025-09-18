# JobBoard MCP Server - Context Documentation

## Overview

The JobBoard MCP (Model Context Protocol) server is a modular system designed to crawl and aggregate job postings from multiple sources. It provides both a command-line interface and an MCP server interface for accessing job data. The system is built with extensibility in mind, supporting feature flags and a plugin architecture for different job sources.

## Architecture

### Core Components

1. **MCP Server** (`src/jobboard_mcp/server.py`)
   - Implements the Model Context Protocol interface
   - Provides resources and tools for job searching
   - Supports feature flags for enabling/disabling functionality
   - Handles both resource listing and tool execution

2. **Job Service** (`src/jobboard_mcp/services/job_service.py` & `src/jobboard_mcp/tools/jobs.py`)
   - Central service for aggregating jobs from multiple crawlers
   - Implements filtering, deduplication, and streaming capabilities
   - Manages crawler instances and coordinates job collection
   - Provides both batch and streaming interfaces

3. **Crawlers** (`src/jobboard_mcp/crawlers/`)
   - Base crawler class with common functionality
   - Individual crawlers for different job sources
   - Implements caching, rate limiting, and error handling

4. **Data Models** (`src/jobboard_mcp/models/`)
   - Job posting data structure
   - Base model with timestamping capabilities

5. **CLI Interface** (`main.py`)
   - Dual-mode operation: search and parse
   - Search mode: Crawls multiple sources for job listings
   - Parse mode: Analyzes individual job URLs for metadata extraction
   - Supports both human-readable and JSON output formats

## Supported Job Sources

### 1. Y Combinator Jobs (`ycombinator.py`)
- **Source**: https://news.ycombinator.com/jobs
- **Features**:
  - Parses job listings from HN jobs page
  - Extracts company, title, and location from job titles
  - Detects YC batch information (e.g., "YC S23")
  - Identifies remote-friendly positions
  - Supports pagination through "More" links

### 2. Hacker News Jobs (`hackernews_jobs.py`)
- **Source**: https://news.ycombinator.com/jobs
- **Features**:
  - Parses job story listings
  - Extracts company, title, and location from titles
  - Handles YC batch tags
  - Detects remote work opportunities
  - Supports pagination

### 3. Hacker News "Who's Hiring" (`hackernews.py`)
- **Source**: Monthly "Ask HN: Who is hiring?" threads
- **Features**:
  - Discovers latest monthly thread via Algolia API
  - Parses top-level comments for job postings
  - Extracts detailed job information from comment text
  - Heuristic parsing for company, title, location, and requirements
  - Supports pagination within threads

### 4. TechCrunch (`techcrunch.py`)
- **Source**: https://techcrunch.com/category/startups/
- **Features**:
  - Scans for job-related articles
  - Basic filtering for hiring-related content
  - Limited implementation (returns mock data)

### 5. LinkedIn (`linkedin.py`)
- **Source**: LinkedIn Jobs (limited access)
- **Features**:
  - Returns mock data due to authentication requirements
  - Placeholder for future LinkedIn API integration

## Data Model

### JobPosting Structure
```python
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
```

## Key Features

### 1. Filtering and Search
- **Keywords**: Filter jobs by keywords in title, company, or description
- **Location**: Filter by location with intelligent matching and aliases
- **Remote Only**: Filter for remote-friendly positions
- **Tags**: Filter by required tags (case-insensitive)

### 2. Deduplication
- **URL-based**: Deduplicates jobs with identical canonical URLs
- **Tag Merging**: Merges tags from duplicate jobs
- **Data Enhancement**: Fills missing company/location data from duplicates

### 3. Streaming Support
- **Page-by-page**: Streams jobs as they're discovered
- **Event-driven**: Emits structured events (start, page_start, job, complete, error)
- **Progress tracking**: Provides real-time progress updates

### 4. Caching
- **TTL-based**: Configurable cache time-to-live
- **Per-source**: Individual cache per crawler
- **Session management**: Proper cleanup of HTTP sessions

### 5. Per-URL Parse Mode
- **Dual Operation Modes**: Supports both search and parse modes via `--mode` argument
- **URL Analysis**: Extracts metadata from individual job posting URLs
- **Heuristic Parsing**: Uses URL structure to infer job details
- **Error Handling**: Structured error responses with proper exit codes
- **Automation Support**: Designed for integration with external systems

#### Parse Mode Implementation Details

**URL Metadata Extraction:**
- **Hostname Analysis**: Extracts company name from domain (e.g., `company.com` → "company")
- **Path Parsing**: Uses URL path segments to infer job title
- **Source Detection**: Identifies the source platform from the domain
- **Fallback Handling**: Provides sensible defaults for missing information

**Output Format:**
```json
{
  "type": "parsed",
  "url": "https://example.com/job-posting",
  "title": "Job: senior-engineer",
  "company": "example",
  "location": null,
  "description": null,
  "source": "example.com",
  "salary": null,
  "team": null
}
```

**Error Handling:**
```json
{
  "type": "parseError",
  "url": "invalid-url",
  "error": "Missing --url"
}
```

**Exit Codes:**
- `0`: Successful parsing
- `1`: Parse error or missing URL
- Non-zero exit codes enable automation and error detection

## Configuration

### Environment Variables
- `FEATURE_JOBS`: Enable/disable job functionality (default: true)
- `FEATURE_COMPANY`: Enable company features (default: false)
- `FEATURE_FUNDING`: Enable funding features (default: false)
- `FEATURE_OTHER`: Enable other features (default: false)
- `CACHE_TTL_SECONDS`: Cache duration (default: 3600)

### Command Line Interface

#### Search Mode (Default)
```bash
# Search jobs from multiple sources
python main.py --sources ycombinator,hackernews --keywords python,remote --location "United States" --remote-only

# Search with JSON output
python main.py --json --sources ycombinator

# Search with custom pagination
python main.py --sources hackernews --max-pages 3 --per-source-limit 50
```

#### Parse Mode (Per-URL Parsing)
```bash
# Parse a specific job URL
python main.py --mode parse --url "https://example.com/job-posting"

# Parse with JSON output
python main.py --mode parse --url "https://company.com/careers/senior-engineer" --json
```

**Parse Mode Features:**
- **Single URL Processing**: Analyzes one specific job posting URL
- **URL-based Metadata Extraction**: Extracts basic information from URL structure
- **Error Handling**: Returns structured error responses for invalid URLs
- **Exit Codes**: Returns non-zero exit code on parse failures (useful for automation)
- **JSON Output**: Supports both human-readable and JSON output formats

## MCP Server Interface

### Resources
- `jobs://ycombinator`: Y Combinator job listings
- `jobs://hackernews`: Hacker News "Who's Hiring" threads
- `jobs://techcrunch`: TechCrunch job articles
- `jobs://linkedin`: LinkedIn jobs (limited)

### Tools
- `search_jobs`: Search jobs with filters
  - Parameters: keywords, sources, location, remote_only, max_pages, per_source_limit, tags
  - Returns: List of job postings with metadata

## Error Handling

### Crawler Errors
- **Network failures**: Graceful handling of HTTP errors
- **Parsing errors**: Continues processing other jobs
- **Rate limiting**: Built-in delays between requests
- **Timeout handling**: Configurable timeouts for requests

### Service Errors
- **Source validation**: Validates source names before processing
- **Exception handling**: Catches and reports crawler exceptions
- **Fallback behavior**: Continues with available sources if some fail

## Extensibility

### Adding New Crawlers
1. Inherit from `BaseCrawler[JobPosting]`
2. Implement `crawl()` method
3. Add to `JobService.SOURCE_MAP`
4. Register in server resources/tools

### Adding New Features
1. Create new modules in appropriate directories
2. Add feature flags in `config.py`
3. Wire into server with feature flag checks
4. Update MCP capabilities

## Performance Considerations

### Caching Strategy
- **Per-source caching**: Reduces redundant requests
- **TTL-based expiration**: Balances freshness vs performance
- **Memory management**: Proper cleanup of cached data

### Rate Limiting
- **Polite delays**: Built-in delays between requests
- **Session reuse**: Reuses HTTP connections when possible
- **Concurrent processing**: Parallel processing of multiple sources

### Memory Usage
- **Streaming**: Processes jobs page-by-page to limit memory
- **Deduplication**: Removes duplicate jobs to reduce memory footprint
- **Cleanup**: Proper session and resource cleanup

## Security Considerations

### User Agent
- **Realistic headers**: Uses browser-like user agent strings
- **Request headers**: Includes standard browser headers

### Rate Limiting
- **Respectful crawling**: Implements delays between requests
- **Error handling**: Graceful handling of rate limit responses

### Data Privacy
- **No personal data**: Only collects publicly available job information
- **URL canonicalization**: Removes tracking parameters from URLs

## Future Enhancements

### Planned Features
- **Company information**: Expand to include company details
- **Funding data**: Add startup funding information
- **Advanced filtering**: More sophisticated search capabilities
- **API integrations**: Better integration with official APIs
- **Enhanced Parse Mode**: 
  - Full job page parsing (currently only URL-based heuristics)
  - Integration with existing crawlers for detailed job extraction
  - Support for job description parsing and metadata extraction
  - Company-specific parsing rules for major job boards

### Technical Improvements
- **Async improvements**: Better async/await patterns
- **Error recovery**: More robust error handling
- **Monitoring**: Better logging and monitoring
- **Testing**: Comprehensive test coverage

## Usage Examples

### Basic Job Search
```python
async with JobService() as service:
    jobs = await service.search_jobs(
        keywords=["python", "remote"],
        sources=["ycombinator", "hackernews"],
        location="United States",
        remote_only=True
    )
```

### Streaming Jobs
```python
async with JobService() as service:
    async for event in service.search_jobs_stream(
        keywords=["javascript"],
        sources=["ycombinator"],
        location="San Francisco",
        remote_only=False
    ):
        if event["type"] == "job":
            print(f"Found job: {event['data']['title']}")
```

### MCP Client Integration
```python
# List available resources
resources = await client.list_resources()

# Read job data
jobs = await client.read_resource("jobs://ycombinator")

# Search jobs using tools
result = await client.call_tool("search_jobs", {
    "keywords": ["python"],
    "sources": ["ycombinator"],
    "location": "United States",
    "remote_only": True
})
```

### Parse Mode Usage
```python
# Parse a single job URL
import subprocess
import json

def parse_job_url(url: str) -> dict:
    """Parse a job URL and return structured data."""
    result = subprocess.run([
        "python", "main.py", 
        "--mode", "parse", 
        "--url", url, 
        "--json"
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        return json.loads(result.stdout.strip())
    else:
        return {"error": "Parse failed", "stderr": result.stderr}

# Example usage
job_data = parse_job_url("https://company.com/careers/senior-engineer")
print(f"Company: {job_data.get('company')}")
print(f"Title: {job_data.get('title')}")
```

### Batch URL Processing
```python
import asyncio
from typing import List, Dict

async def process_job_urls(urls: List[str]) -> List[Dict]:
    """Process multiple job URLs in parallel."""
    tasks = []
    for url in urls:
        task = asyncio.create_subprocess_exec(
            "python", "main.py", "--mode", "parse", "--url", url, "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        tasks.append((url, task))
    
    results = []
    for url, task in tasks:
        try:
            process = await task
            stdout, stderr = await process.communicate()
            if process.returncode == 0:
                data = json.loads(stdout.decode())
                results.append(data)
            else:
                results.append({
                    "url": url,
                    "error": stderr.decode(),
                    "type": "parseError"
                })
        except Exception as e:
            results.append({
                "url": url,
                "error": str(e),
                "type": "parseError"
            })
    
    return results

# Example usage
urls = [
    "https://company1.com/jobs/engineer",
    "https://company2.com/careers/developer",
    "https://company3.com/hiring/manager"
]
results = await process_job_urls(urls)
```

This MCP server provides a comprehensive solution for job aggregation and search, with a focus on extensibility, performance, and ease of use. The modular architecture allows for easy addition of new job sources and features while maintaining a consistent interface for clients.
