# Testing MCP Parsers (Quick Guide)

## 1) Setup

- From repo root:
  - Create and activate a venv
    - `python3 -m venv .venv`
    - `source .venv/bin/activate`
  - Install deps
    - `pip install -e .`
    - (If needed) `pip install aiohttp beautifulsoup4 lxml`

## 2) Quick test (single URL)

- Run the helper script to parse a URL and print a compact summary:
  - `python scripts/quick_parse_url.py "<URL>"`

## 3) Parser diagnostics (which parser, sections, lists)

- Run the diagnostic script for richer output:
  - `python scripts/diagnose_url.py "<URL>"`

Try each source:
- YC: `https://www.ycombinator.com/companies/<company>/jobs/<job-slug>`
- Ashby: `https://jobs.ashbyhq.com/<company>/<job-id>`
- Lever: `https://jobs.lever.co/<company>/<job-id>`
- Greenhouse: `https://boards.greenhouse.io/<company>/jobs/<id>`
- Generic careers page
- Hub/listing page (should classify as `redirect_hub`)

## 4) Expected outcomes

- YC/Ashby/Lever/Greenhouse
  - Correct parser selected; descriptionText length typically > 400
  - Sections >= 2 on structured pages
  - requirements/responsibilities/benefits populated when headings exist
  - techStack includes terms when present (React, TypeScript, AWS, etc.)
- Generic
  - Parser `generic_html`; non-empty descriptionText; 1+ sections
- Hub/Form
  - Parser `redirect_hub`; guidance message in descriptionText; `warnings` contains `hub_or_form_detected`

## 5) Troubleshooting

- Parser mismatch: adjust detect() scoring for that parser
- Empty description: improve container selection or allowed tags
- Missing lists: add heading synonyms in `classify_section()`
- Encoding artifacts: extend `normalize_text()` fixups

## 6) Scripts

- `scripts/quick_parse_url.py`: prints basic JobPosting mapping summary
- `scripts/diagnose_url.py`: prints parser name, detection score/reason, description length, sections, list sizes, tech stack

---

Keep PRs tight. If a URL fails, capture the URL and output and we’ll refine the parser or heuristics in a focused branch.
