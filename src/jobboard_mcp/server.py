import json
import logging
from typing import Dict, List, Optional

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions  # stays here for your SDK
from mcp.types import (  # move these types here
    Resource,
    Tool,
    TextContent,
    ListResourcesResult,
    ReadResourceRequest,
    ReadResourceResult,
    ListToolsResult,
    CallToolRequest,
    CallToolResult,
)

from .config import get_settings
from .resources.jobs import list_job_resources
from .tools.jobs import list_job_tools, JobService
from .config import get_settings
from .resources.jobs import list_job_resources
from .tools.jobs import list_job_tools, JobService

class JobBoardServer:
    def __init__(self):
        self.app = Server("jobboard-mcp")
        self.log = logging.getLogger("jobboard-mcp")
        self.settings = get_settings()

        # Domain services (feature-flagged)
        self.job_service: Optional[JobService] = None
        if self.settings.features.jobs:
            self.job_service = JobService(cache_ttl_seconds=self.settings.cache_ttl_seconds)

        self._register_routes()

    def _register_routes(self):
        app = self.app

        @app.list_resources()
        async def list_resources() -> ListResourcesResult:
            resources: List[Resource] = []
            if self.settings.features.jobs:
                resources.extend(list_job_resources())
            return ListResourcesResult(resources=resources)

        @app.read_resource()
        async def read_resource(req: ReadResourceRequest) -> ReadResourceResult:
            if not self.settings.features.jobs or self.job_service is None:
                return ReadResourceResult(contents=[TextContent(type="text", text=json.dumps({"error": "jobs feature disabled"}) )])

            uri = req.uri
            # Map URIs to source crawlers
            mapping = {
                "jobs://ycombinator": "ycombinator",
                "jobs://hackernews": "hackernews",
                "jobs://techcrunch": "techcrunch",
                "jobs://linkedin": "linkedin",
            }
            src = mapping.get(uri)
            if not src:
                return ReadResourceResult(contents=[TextContent(type="text", text=json.dumps({"error": f"Unknown resource: {uri}"}) )])

            # Dispatch to search with a single source
            jobs = await self.job_service.search_jobs(keywords=None, sources=[src], location="United States", remote_only=False)
            data = [j.model_dump() for j in jobs]
            return ReadResourceResult(contents=[TextContent(type="text", text=json.dumps(data, indent=2))])

        @app.list_tools()
        async def list_tools() -> ListToolsResult:
            tools: List[Tool] = []
            if self.settings.features.jobs:
                tools.extend(list_job_tools())
            # Future: company/funding tools gated here
            return ListToolsResult(tools=tools)

        @app.call_tool()
        async def call_tool(req: CallToolRequest) -> CallToolResult:
            if req.name in {"search_jobs", "get_job_stats"}:
                if not self.settings.features.jobs or self.job_service is None:
                    return CallToolResult(content=[TextContent(type="text", text=json.dumps({"error": "jobs feature disabled"}))])

                try:
                    args = req.arguments or {}
                    if req.name == "search_jobs":
                        keywords = args.get("keywords")
                        sources = args.get("sources", ["ycombinator", "hackernews"])
                        location = args.get("location", "United States")
                        remote_only = bool(args.get("remote_only", False))
                        jobs = await self.job_service.search_jobs(keywords, sources, location, remote_only)
                        return CallToolResult(content=[TextContent(type="text", text=json.dumps({
                            "total_jobs": len(jobs),
                            "sources_searched": sources,
                            "keywords": keywords or [],
                            "remote_only": remote_only,
                            "jobs": [j.model_dump() for j in jobs],
                        }, indent=2))])
                    else:
                        # get_job_stats based on in-memory caches of crawlers
                        caches = {k: v for k, v in {
                            "ycombinator": self.job_service.yc.cache.get("ycombinator", []),
                            "hackernews": self.job_service.hn.cache.get("hackernews", []),
                            "techcrunch": self.job_service.tc.cache.get("techcrunch", []),
                            "linkedin": self.job_service.li.cache.get("linkedin", []),
                        }.items()}
                        stats = {
                            k: {"count": len(v), "remote_jobs": len([j for j in v if j.remote_ok])}
                            for k, v in caches.items()
                        }
                        stats["total"] = sum(s["count"] for s in stats.values())
                        return CallToolResult(content=[TextContent(type="text", text=json.dumps(stats, indent=2))])
                except Exception as e:
                    self.log.exception("Tool error")
                    return CallToolResult(content=[TextContent(type="text", text=json.dumps({"error": str(e)}) )])

            return CallToolResult(content=[TextContent(type="text", text=json.dumps({"error": f"Unknown tool {req.name}"}))])

    async def run_stdio(self):
            from mcp.server.models import InitializationOptions
            from mcp.server import NotificationOptions
            try:
                import mcp.server.stdio as mcp_stdio
            except ImportError:
                import mcp.server.transport.stdio as mcp_stdio  # fallback

            async with mcp_stdio.stdio_server() as (read_stream, write_stream):
                await self.app.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name="jobboard-mcp",
                        server_version="0.2.0",
                        capabilities=self.app.get_capabilities(
                            notification_options=NotificationOptions(),
                            experimental_capabilities={},
                        ),
                    ),
                )