import asyncio
import sys
from jobboard_mcp.tools.jobs import JobService

async def test_url(url: str):
    print(f"--- Testing URL: {url} ---")
    async with JobService() as svc:
        job = await svc.parse_job_url(url)
        # Print the dictionary representation of the JobPosting object
        print(job.__dict__)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        url_to_test = sys.argv[1]
        asyncio.run(test_url(url_to_test))
    else:
        print("Please provide a URL to test.")
