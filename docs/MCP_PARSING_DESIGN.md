# MCP Parsing Design

This document defines a multi-parser architecture for robust job posting extraction across Y Combinator (YC) pages and common ATS platforms (Ashby, Lever, Greenhouse), with a generic HTML fallback and hub/form-gated handling.

## Goals
- Extract rich, structured job data reliably across varied page structures.
- Preserve semantic sections (About role/company, Responsibilities, Requirements, Benefits, Salary, Location, etc.).
- Provide high-signal fields for downstream AI analysis.
- Be resilient to redirects, listing hubs, and form-gated flows.

## Data Model (ParsedJob)
- Core
  - `id`, `source`, `url`, `title`, `company`, `location`, `postedDate`, `salary`, `jobType`, `remoteOk`, `tags[]`
- Rich content
  - `descriptionHtml`, `descriptionText`
  - `sections[]`: `{ heading, html, text }` in order
  - `salaryInfo`: `{ min, max, currency, periodicity, raw }`
  - `requirements[]`, `responsibilities[]`, `benefits[]`, `techStack[]`, `seniority`
  - `companyProfile`: `{ name, tagline, aboutHtml, aboutText, links: { careers, website, linkedin, twitter }, locations[] }`
- Provenance/meta
  - `parser`: `yc_job | ashby_job | lever_job | greenhouse_job | generic_html | redirect_hub`
  - `contentScore`: number (0–100)
  - `warnings[]`: strings

## Parser Registry
- `detect(url, doc)` chooses a parser by URL/domain and DOM signature.
- Parsers implement `parse(url, doc) -> ParsedJob` and return a populated model with `parser` and `contentScore`.
- Order of detection: ATS-specific → YC → generic → hub/form-gated fallback.

## Source-Specific Strategies

### Y Combinator Job Pages (`yc_job`)
- Anchors
  - `div.space-y-1` → company name + tagline
  - `h1.ycdc-section-title.mb-2` → job title (nearby metadata for salary/location)
  - Multiple `h2.ycdc-section-title` → section headings (About role/company, etc.)
  - `div.prose.max-w-full` → section body with `p`, `ul/li`, nested headings
- Extraction
  - Title, company, metadata (salary/location/remote) next to title
  - Iterate sections: collect content until next `h2`, sanitize to `html`, normalize to `text`
  - Build `requirements[]`, `responsibilities[]`, `benefits[]` from `ul/li`
  - Extract `techStack[]` via dictionary matching
- Output
  - `descriptionText` is concatenated section texts; keep `sections[]`

### Ashby (`ashby_job`)
- Detect by domain/DOM: presence of `.job-posting`, meta, or standard containers
- Title in `h1`; sections in content container; bullets from `ul/li`
- Parse salary/location metadata when present

### Lever (`lever_job`)
- Detect by `.posting` and related class names
- Headline in `h2.posting-headline`; sections under `.section`
- Extract bullets and metadata

### Greenhouse (`greenhouse_job`)
- Detect by GH app scaffolding and classes
- Extract title, sections, bullets, and metadata

### Generic HTML (`generic_html`)
- Heuristics
  - Primary heading (top `h1/h2`) as title if missing
  - Largest continuous text container (density-based) as description root
  - Split into sections via `h2/h3`; gather bullets
  - Normalize whitespace, decode encoding issues, sanitize allowed tags (`p, ul, ol, li, em, strong, br, a`)
- Scoring by completeness/length

### Redirect/Hub/Form-Gated (`redirect_hub`)
- Detect job cards/listing grids or pure forms with no job content
- If hub: return `jobs[]` (title, url, location, snippet) and `companyProfile`; add warning
- If form-gated: return `companyProfile` and a generic explanatory description; add warning

## Sanitization & Normalization
- Encoding fixes for artifacts like `â€¢` → `•`
- Whitespace normalization; preserve bullets
- Salary normalization via regex into `{ min, max, currency, periodicity }`
- Location normalization (Remote, Hybrid, City, Region)

## Tech Stack Extraction
- Dictionary-based tokenization + normalization from `descriptionText` and `sections[]`

## Logging & Metrics
- Log chosen parser, `descriptionText.length`, `sections.length`, `contentScore`, `warnings`

## Implementation Plan & Estimates
- 0) Registry + model + utils (0.5–1d)
- 1) YC parser (1.5–2d)
- 2) Ashby parser (1.5–2d)
- 3) Lever parser (1–1.5d)
- 4) Greenhouse parser (1–1.5d)
- 5) Generic HTML fallback (2d)
- 6) Hub/form-gated detection (1–1.5d)
- 7) Tech stack extraction (0.5d)
- 8) Salary/location normalization (0.5–1d)
- 9) Output schema compatibility (0.5d)
- 10) Logging/metrics (0.5d)
- 11) Documentation updates (0.5d)

Total: ~10–12 days (single engineer), parallelizable.

## Deliverables
- Parser registry and ParsedJob model
- Implemented parsers (YC first), with unit tests using saved HTML snapshots
- Integrated logs and warnings surfaced to orchestrator
- This design document kept up to date with examples
