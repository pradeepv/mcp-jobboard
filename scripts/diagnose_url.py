from __future__ import annotations

import asyncio
import sys

import aiohttp
from bs4 import BeautifulSoup  # type: ignore

from jobboard_mcp.parsing import (
    ParserRegistry,
    YcJobParser,
    AshbyJobParser,
    LeverJobParser,
    GreenhouseJobParser,
    HubOrFormParser,
    GenericHtmlParser,
)


def trunc(s: str | None, n: int = 300) -> str:
    if not s:
        return ""
    return (s[:n] + "...") if len(s) > n else s


async def fetch_html(url: str) -> str:
    async with aiohttp.ClientSession() as s:
        async with s.get(url, timeout=30) as r:
            r.raise_for_status()
            return await r.text()


async def run(url: str) -> None:
    html = await fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")
    reg = ParserRegistry()
    reg.register(YcJobParser())
    reg.register(AshbyJobParser())
    reg.register(LeverJobParser())
    reg.register(GreenhouseJobParser())
    reg.register(HubOrFormParser())
    reg.register(GenericHtmlParser())

    parser, det = reg.choose(url, soup)
    parsed = parser.parse(url, soup)

    print("URL:", url)
    print("Parser:", parsed.parser, f"(detect score={det.score}, reason={det.reason})")
    print("Title:", parsed.title)
    print("Company:", parsed.company)
    print("Location:", parsed.location)
    print("DescriptionText length:", len(parsed.descriptionText or ""))
    print("Sections:", len(parsed.sections))
    print(
        "Requirements:", len(parsed.requirements),
        "Responsibilities:", len(parsed.responsibilities),
        "Benefits:", len(parsed.benefits),
    )
    print("TechStack:", parsed.techStack)
    print("ContentScore:", parsed.contentScore)
    print("Warnings:", parsed.warnings)
    try:
        cp = getattr(parsed, "companyProfile", None)
        if cp:
            print("CompanyProfile:", {
                "name": cp.name,
                "tagline": cp.tagline,
                "links": cp.links,
                "locations": cp.locations,
            })
    except Exception:
        pass
    print("Preview:", trunc(parsed.descriptionText))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/diagnose_url.py <URL>")
        sys.exit(1)
    asyncio.run(run(sys.argv[1]))
