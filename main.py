import asyncio
import argparse
import json
import sys
import warnings
from typing import List, Optional

from jobboard_mcp.tools.jobs import JobService

warnings.filterwarnings("ignore", category=FutureWarning)


def as_obj(x):
    try:
        if hasattr(x, "model_dump"):
            return x.model_dump()
        d = getattr(x, "__dict__", None)
        if isinstance(d, dict):
            return dict(d)
    except Exception:
        pass
    return x


def print_event(event: dict):
    # Ensure a compact JSON line per event for SSE relay
    try:
        sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except Exception as ex:
        # As a last resort, emit a minimal error
        sys.stdout.write(json.dumps({"type": "error", "message": str(ex)}) + "\n")
        sys.stdout.flush()


async def run_stream(
    svc: JobService,
    sources: List[str],
    keywords: Optional[str],
    location: str,
    remote_only: bool,
    max_pages: int,
    per_source_limit: int,
    emit_json: bool,
):
    # keywords: string from CLI; convert to list[str] or None for service
    kw_list = None
    if keywords and keywords.strip():
        parts = [p.strip() for p in keywords.split(",")]
        kw_list = [p for p in parts if p]

    if not emit_json:
        async for ev in svc.search_jobs_stream(
            keywords=kw_list,
            sources=sources,
            location=location,
            remote_only=remote_only,
            max_pages=max_pages,
            per_source_limit=per_source_limit,
        ):
            t = ev.get("type")
            if t == "start":
                print(
                    f"Start: sources={ev.get('sources')} max_pages={ev.get('max_pages')} per_source_limit={ev.get('per_source_limit')}",
                    flush=True,
                )
            elif t == "source_start":
                print(f"Source start: {ev.get('source')}", flush=True)
            elif t == "page_start":
                print(
                    f"  Page start: source={ev.get('source')} page={ev.get('page')}",
                    flush=True,
                )
            elif t == "job":
                data = ev.get("data", {})
                title = data.get("title") or "Untitled"
                company = data.get("company") or "Unknown"
                print(
                    f"    Job: [{ev.get('source')}] p{ev.get('page')} {title} @ {company}",
                    flush=True,
                )
            elif t == "page_complete":
                print(
                    f"  Page complete: source={ev.get('source')} page={ev.get('page')} count={ev.get('count')}",
                    flush=True,
                )
            elif t == "source_complete":
                print(
                    f"Source complete: {ev.get('source')} pages={ev.get('pages')} total={ev.get('total')}",
                    flush=True,
                )
            elif t == "complete":
                print(
                    f"Complete: total_jobs={ev.get('total_jobs')} sources={ev.get('sources')} pages={ev.get('pages')}",
                    flush=True,
                )
            elif t == "error":
                print(
                    f"[ERROR] {ev.get('message')} (source={ev.get('source')} page={ev.get('page')})",
                    flush=True,
                )
        return

    # JSON event mode
    async for ev in svc.search_jobs_stream(
        keywords=kw_list,
        sources=sources,
        location=location,
        remote_only=remote_only,
        max_pages=max_pages,
        per_source_limit=per_source_limit,
    ):
        if "data" in ev:
            ev["data"] = as_obj(ev["data"])
        print_event(ev)


async def run_parse(svc: JobService, url: str, emit_json: bool):
    """
    Minimal per-URL parse mode.
    - Emits exactly one JSON line with type="parsed" on success.
    - Emits one JSON line with type="parseError" on failure, and returns nonzero exit.
    """
    if not url or not url.strip():
        msg = {"type": "parseError", "url": url or "", "error": "Missing --url"}
        if emit_json:
            print_event(msg)
        else:
            print(f"[ERROR] {msg['error']}: {msg['url']}")
        # Let caller decide exit code; main() handles it
        return 1

    try:
        # Use the new dedicated method to parse job URL
        job_posting = await svc.parse_job_url(url)

        result = as_obj(job_posting)
        result["type"] = "parsed"

        if emit_json:
            print_event(result)
        else:
            print(
                f"Parsed job: {getattr(job_posting, 'title', 'Unknown')} at {getattr(job_posting, 'company', 'Unknown')}"
            )
            print(f"URL: {getattr(job_posting, 'url', '')}")
            print(f"Location: {getattr(job_posting, 'location', 'Unknown')}")
            if getattr(job_posting, "salary", None):
                print(f"Salary: {getattr(job_posting, 'salary', '')}")
            if getattr(job_posting, "description", None):
                print(
                    f"Description: {getattr(job_posting, 'description', '')[:200]}..."
                )
        return 0
    except Exception as ex:
        error_msg = {"type": "parseError", "url": url, "error": str(ex)}
        if emit_json:
            print_event(error_msg)
        else:
            print(f"[ERROR] Failed to parse job URL {url}: {ex}")
        return 1


async def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--sources", type=str, default="ycombinator", help="Comma-separated sources"
    )
    p.add_argument(
        "--keywords", type=str, default="", help="Comma-separated keywords (optional)"
    )
    p.add_argument(
        "--location", type=str, default="", help="Location filter (optional)"
    )
    p.add_argument(
        "--remote-only", action="store_true", help="Only remote-friendly roles"
    )
    p.add_argument("--max-pages", type=int, default=1, help="Max pages per source")
    p.add_argument(
        "--per-source-limit",
        type=int,
        default=100,
        help="Approx items per page / per source batch",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON events, one per line")

    # New: per-URL parse mode (backwards-compatible default to 'search')
    p.add_argument(
        "--mode",
        type=str,
        choices=["search", "parse"],
        default="search",
        help="Operation mode",
    )
    p.add_argument(
        "--url", type=str, default="", help="Job posting URL for --mode parse"
    )

    # Future flags (unchanged)
    p.add_argument(
        "--continuous",
        action="store_true",
        help="Run continuously (not used in finite mode yet)",
    )
    p.add_argument(
        "--poll-interval-hours",
        type=float,
        default=12.0,
        help="Polling interval if --continuous is enabled (future)",
    )

    args = p.parse_args()

    # Ensure line-buffered stdout for SSE
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    # Banner for search mode only (preserves existing behavior)
    if args.mode == "search":
        sources = [s.strip() for s in args.sources.split(",") if s.strip()]
        keywords = args.keywords or None
        if args.json:
            print_event(
                {
                    "type": "banner",
                    "mode": "finite",
                    "sources": sources,
                    "max_pages": args.max_pages,
                    "per_source_limit": args.per_source_limit,
                    "remote_only": args.remote_only,
                    "location": args.location,
                }
            )
        else:
            print(
                f"Running finite stream: sources={sources} max_pages={args.max_pages} per_source_limit={args.per_source_limit}",
                flush=True,
            )

    exit_code = 0
    async with JobService(cache_ttl_seconds=300) as svc:
        if args.mode == "parse":
            exit_code = await run_parse(svc=svc, url=args.url, emit_json=args.json)
        else:
            sources = [s.strip() for s in args.sources.split(",") if s.strip()]
            keywords = args.keywords or None
            await run_stream(
                svc=svc,
                sources=sources,
                keywords=keywords,
                location=args.location,
                remote_only=args.remote_only,
                max_pages=args.max_pages,
                per_source_limit=args.per_source_limit,
                emit_json=args.json,
            )

    sys.stdout.flush()
    # Exit nonzero on parse error to help Java detect failures
    if exit_code != 0:
        sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
