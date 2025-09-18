import asyncio
from collections import Counter
from urllib.parse import urlparse

from jobboard_mcp.tools.jobs import JobService

async def main():
    async with JobService(cache_ttl_seconds=300) as svc:
        jobs = await svc.search_jobs(
            keywords=None,
            sources=["hackernews_jobs", "ycombinator", "workatastartup"],
            location="",
            remote_only=False,
            max_pages=1,
            per_source_limit=40,
            enrich=True,
            enrich_limit=10,
        )

        print("Fetched:", len(jobs))

        if not jobs:
            return

        # Domain distribution of the first N jobs (to see what ATS we hit)
        N = min(40, len(jobs))
        domains = Counter(urlparse(j.url).netloc for j in jobs[:N] if getattr(j, "url", ""))
        print("Top domains in first", N, "jobs:")
        for dom, cnt in domains.most_common():
            print(f"- {dom}: {cnt}")

        # Show first 10 URLs and description lengths to verify enrichment
        print("\nFirst 10 jobs (source_key, url, desc_len):")
        for j in jobs[:10]:
            source_key = getattr(j, 'source_key', 'unknown')
            print(source_key, j.url, "desc_len=", len(j.description or ""))

        # Print a richer sample of the first job
        print("\nSample job (first item):")
        sample = jobs[0].__dict__
        for k, v in sample.items():
            if k == "description" and v:
                preview = (v[:200] + "...") if len(v) > 200 else v
                print(f"- {k}: {preview} (len={len(v)})")
            else:
                print(f"- {k}: {v}")

if __name__ == "__main__":
    asyncio.run(main())