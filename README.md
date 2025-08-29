# JobBoard MCP

A modular MCP server exposing job board resources and tools, designed to be extended to company, funding, and other information domains. Feature toggles let you enable/disable domains without code changes.

## Quick start

- python -m venv .venv && source .venv/bin/activate
- pip install -e .
- cp .env.example .env
- jobboard-mcp

Integrate the binary `jobboard-mcp` with your MCP-compatible client over stdio.

## Feature flags
Set in `.env`:

- FEATURE_JOBS=true|false
- FEATURE_COMPANY=true|false
- FEATURE_FUNDING=true|false
- FEATURE_OTHER=true|false

## Extending
Add new domain modules under:
- `src/jobboard_mcp/resources/`
- `src/jobboard_mcp/tools/`
- `src/jobboard_mcp/models/`
- `src/jobboard_mcp/crawlers/`

Wire them in `server.py` gated by feature flags.