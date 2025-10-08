#!/usr/bin/env python3
"""
MCP Job Board Server - Main entry point with enhanced parsing support.
Supports both job searching and individual job URL parsing with fallbacks.
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv
from .logging_config import setup_logging
from .server import JobBoardServer
from .services.job_service import JobService
from .utils.fallback import (
    detect_career_page,
    extract_job_links_from_career_page,
    create_fallback_job_posting,
    to_standardized_dict
)
from .models.job import JobPosting

# Configure logging
log = logging.getLogger(__name__)


def run():
    """Default MCP server mode for stdio communication."""
    load_dotenv()
    setup_logging()
    asyncio.run(_amain())


async def _amain():
    """Run MCP server on stdio."""
    server = JobBoardServer()
    await server.run_stdio()


async def search_jobs_mode(
    service: JobService,
    keywords: Optional[List[str]] = None,
    sources: Optional[List[str]] = None,
    location: Optional[str] = None,
    remote_only: bool = False,
    max_pages: int = 3,
    per_source_limit: int = 50
):
    """Execute job search with streaming output."""
    try:
        async for job in service.search_jobs_stream(
            keywords=keywords,
            sources=sources,
            location=location,
            remote_only=remote_only,
            max_pages=max_pages,
            per_source_limit=per_source_limit
        ):
            # Convert to standardized format
            job_dict = to_standardized_dict(job)

            # Output JSON event
            event = {
                "type": "job",
                "data": job_dict
            }
            print(json.dumps(event))
            sys.stdout.flush()

    except Exception as e:
        log.exception("Search failed")
        error_event = {
            "type": "error",
            "data": {
                "message": f"Search failed: {str(e)}",
                "timestamp": "2024-01-01T00:00:00Z"  # Will be updated
            }
        }
        print(json.dumps(error_event))
        sys.stdout.flush()


async def parse_job_mode(service: JobService, url: str):
    """Parse individual job URL with career page detection."""
    try:
        log.info(f"Starting parse for URL: {url}")

        # Emit start event
        start_event = {
            "type": "start",
            "data": {
                "url": url,
                "message": f"Starting parse for {url}"
            }
        }
        print(json.dumps(start_event))
        sys.stdout.flush()

        # Get content for career page detection
        html_content = await service._get_html_content(url)

        # Check if it's a career page
        if detect_career_page(url, html_content or ""):
            log.info(f"Career page detected for URL: {url}")

            # Try to extract job links from career page
            job_links = extract_job_links_from_career_page(html_content or "", url)

            if job_links:
                # Return the first few job links as suggestions
                result_event = {
                    "type": "career_page",
                    "data": {
                        "url": url,
                        "message": "Career page detected - multiple positions available",
                        "job_links": job_links[:5],  # Return first 5 links
                        "total_jobs": len(job_links)
                    }
                }
                print(json.dumps(result_event))
                sys.stdout.flush()
                return
            else:
                # Career page but couldn't extract jobs
                error_event = {
                    "type": "parseError",
                    "data": {
                        "url": url,
                        "error": "Career page detected but no job links found",
                        "message": "This appears to be a career page. Please visit the URL directly to see all positions."
                    }
                }
                print(json.dumps(error_event))
                sys.stdout.flush()
                return

        # Try to parse as individual job posting
        job = await service.parse_job_url(url)

        if job:
            # Success - return parsed job
            job_dict = to_standardized_dict(job)

            result_event = {
                "type": "parsed",
                "data": job_dict
            }
            print(json.dumps(result_event))
            sys.stdout.flush()
        else:
            # Parse failed - return fallback
            log.warning(f"Parse failed for URL: {url}, creating fallback")

            fallback_job = create_fallback_job_posting({
                "url": url,
                "title": "",
                "company": "",
                "description": "Unable to parse job details. This might be a career page or the job posting may have been removed.",
                "source": "unknown"
            })

            fallback_dict = to_standardized_dict(fallback_job)
            fallback_dict["parse_error"] = True

            result_event = {
                "type": "parsed",
                "data": fallback_dict
            }
            print(json.dumps(result_event))
            sys.stdout.flush()

    except Exception as e:
        log.exception(f"Parse failed for URL {url}")
        error_event = {
            "type": "parseError",
            "data": {
                "url": url,
                "error": str(e),
                "message": f"Failed to parse job posting: {str(e)}"
            }
        }
        print(json.dumps(error_event))
        sys.stdout.flush()


async def standalone_main():
    """Main entry point for command line usage."""
    parser = argparse.ArgumentParser(description='MCP Job Board Server')
    parser.add_argument('--mode', choices=['search', 'parse'], default='search',
                       help='Operation mode: search for jobs or parse individual URL')
    parser.add_argument('--url', help='URL to parse (for parse mode)')
    parser.add_argument('--keywords', nargs='+', help='Search keywords')
    parser.add_argument('--sources', nargs='+', help='Job sources to search')
    parser.add_argument('--location', help='Location filter')
    parser.add_argument('--remote-only', action='store_true', help='Remote jobs only')
    parser.add_argument('--max-pages', type=int, default=3, help='Maximum pages per source')
    parser.add_argument('--per-source-limit', type=int, default=50, help='Jobs per source limit')
    parser.add_argument('--json', action='store_true', help='Output JSON events')
    parser.add_argument('--server', action='store_true', help='Run MCP server mode')

    args = parser.parse_args()

    if args.server:
        # Run MCP server mode
        await _amain()
        return

    # Initialize job service
    service = JobService()

    if args.mode == 'parse':
        if not args.url:
            log.error("URL required for parse mode")
            sys.exit(1)

        await parse_job_mode(service, args.url)
    else:
        # Search mode
        await search_jobs_mode(
            service=service,
            keywords=args.keywords,
            sources=args.sources,
            location=args.location,
            remote_only=args.remote_only,
            max_pages=args.max_pages,
            per_source_limit=args.per_source_limit
        )


if __name__ == "__main__":
    # Check if we're being called with command line args
    if len(sys.argv) > 1:
        asyncio.run(standalone_main())
    else:
        # Default MCP server mode
        run()