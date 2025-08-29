# Changelog

## [Unreleased]
### Added
- ATS enrichment subsystem
  - Domain-specific HTML parsers wired via ATS handler registry.
  - Currently supported:
    - Ashby (jobs.ashbyhq.com, www.ashbyhq.com)
    - Lever (jobs.lever.co)
    - Greenhouse (boards.greenhouse.io)
    - Work at a Startup (www.workatastartup.com)
    - Deepnote careers (deepnote.com)
- Expanded Ashby enrichment:
  - Broader selector coverage (data-testid/class variants)
  - Fallback to largest text block within main region
  - Salary/remote heuristics
- Enrichment debug logging:
  - Prints handler selection, HTML length, and empty-description cases (first few items).

### Changed
- Hardened Ashby parser to improve description extraction across more tenants.
- Minor normalization in text_collapse for cleaner line breaks/spaces.

### Fixed
- YCombinator crawler: replace ambiguous regex character class to remove warning.
- Ensure source_key is set and tags are lists in crawlers to aid downstream enrichment.

### TODO
- Lightweight handler for YC company job pages
  - Domain: www.ycombinator.com
  - Paths: /companies/*/jobs/* (and optionally /companies/*/jobs)
  - Extract visible description blocks; follow link-out when present
  - Avoid nav/footer; add selectors for main content
  - Register under ATS handler registry for domain=www.ycombinator.com

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