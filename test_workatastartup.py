#!/usr/bin/env python3
"""
Test script for the WorkAtStartup crawler.
Run this to verify the crawler is working properly.
"""

import asyncio
import sys
import os

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from jobboard_mcp.crawlers.workatastartup import WorkAtStartupCrawler


async def test_workatastartup_crawler():
    """Test the WorkAtStartup crawler"""
    print("🚀 Testing WorkAtStartup Crawler...")
    
    async with WorkAtStartupCrawler() as crawler:
        try:
            # Test basic crawling
            print("📡 Fetching jobs from Work at a Startup...")
            jobs = await crawler.crawl(max_pages=1, per_page_limit=10)
            
            print(f"✅ Successfully crawled {len(jobs)} jobs")
            
            # Display sample jobs
            for i, job in enumerate(jobs[:3], 1):
                print(f"\n--- Job {i} ---")
                print(f"Company: {job.company}")
                print(f"Title: {job.title}")
                print(f"Location: {job.location}")
                print(f"Remote OK: {job.remote_ok}")
                print(f"Tags: {job.tags}")
                print(f"Source: {job.source}")
                print(f"URL: {job.url}")
                if job.description:
                    print(f"Description: {job.description[:100]}...")
            
            # Test keyword filtering
            print(f"\n🔍 Testing keyword filtering...")
            python_jobs = await crawler.crawl(keywords=["python"], max_pages=1, per_page_limit=20)
            print(f"✅ Found {len(python_jobs)} jobs matching 'python'")
            
            remote_jobs = await crawler.crawl(keywords=["remote"], max_pages=1, per_page_limit=20)
            print(f"✅ Found {len(remote_jobs)} jobs matching 'remote'")
            
            if len(jobs) > 0:
                print("\n🎉 WorkAtStartup Crawler test completed successfully!")
                return True
            else:
                print("\n❌ No jobs found - check crawler implementation")
                return False
                
        except Exception as e:
            print(f"❌ Error during crawling: {e}")
            import traceback
            traceback.print_exc()
            return False


async def test_job_service_integration():
    """Test the job service integration"""
    print("\n🔗 Testing JobService integration...")
    
    from jobboard_mcp.services.job_service import JobService
    
    service = JobService()
    try:
        result = await service.search_jobs(
            sources=["workatastartup"],
            max_pages=1,
            per_source_limit=5
        )
        
        jobs = result.get("jobs", [])
        metadata = result.get("metadata", {})
        
        print(f"✅ JobService found {len(jobs)} jobs")
        print(f"📊 Metadata: {metadata}")
        
        if len(jobs) > 0:
            print("🎉 JobService integration test passed!")
            return True
        else:
            print("❌ JobService integration failed - no jobs returned")
            return False
            
    except Exception as e:
        print(f"❌ Error in JobService integration: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await service.close()


async def main():
    """Main test runner"""
    print("=" * 60)
    print("🧪 WorkAtStartup Crawler Test Suite")
    print("=" * 60)
    
    # Test crawler directly
    crawler_success = await test_workatastartup_crawler()
    
    # Test integration with job service
    service_success = await test_job_service_integration()
    
    print("\n" + "=" * 60)
    if crawler_success and service_success:
        print("🎉 All tests passed! The crawler is working correctly.")
        return 0
    else:
        print("❌ Some tests failed. Please check the implementation.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)