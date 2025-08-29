# Changelog

## [0.2.0] - 2025-08-28
### Added
- Fresh, modular MCP server package `jobboard-mcp`.
- Feature toggles via env (jobs/company/funding/other).
- Separated crawlers for YC, HN, TechCrunch, LinkedIn.
- Tools and Resources registered behind feature flags.
- Pydantic models for validation and JSON output.

### Changed
- Replaced single-file script with structured package and services.

### Notes
- LinkedIn crawler returns mock data by default (avoid scraping).