from __future__ import annotations

import asyncio
import sys

from jobboard_mcp.services.job_service import JobService


def trunc(s: str | None, n: int = 200) -> str:
    if not s:
        return ""
    return (s[:n] + "...") if len(s) > n else s


async def run(url: str) -> None:
    svc = JobService()
    try:
        jp = await svc.parse_job_url(url)
        print("URL:", url)
        print("Title:", jp.title)
        print("Company:", jp.company)
        print("Location:", jp.location)
        print("Source:", jp.source)
        d = jp.description or ""
        print("Description length:", len(d))
        print("Description preview:", trunc(d))
    finally:
        await svc.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/quick_parse_url.py <URL>")
        sys.exit(1)
    asyncio.run(run(sys.argv[1]))

