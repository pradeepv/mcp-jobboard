import asyncio
from jobboard_mcp.tools.jobs import JobService

async def main():
    async with JobService(cache_ttl_seconds=300) as svc:
        jobs = await svc.search_jobs(
            keywords=None,
            sources=["ycombinator"],  # isolate a single source first
            location="",
            remote_only=False,
            max_pages=1,
            per_source_limit=100,
        )
        print("Fetched:", len(jobs))
        if jobs:
            sample = jobs[0].model_dump() if hasattr(jobs[0], "model_dump") else jobs[0].__dict__
            print("Sample job:")
            for k, v in sample.items():
                print(f"- {k}: {v}")

if __name__ == "__main__":
    asyncio.run(main())