# Company Career Page Job Requirements Agent (Free / Local-First)

A rules-based Python starter that crawls configured company career pages, extracts job-posting details, and saves results to **PostgreSQL** and creates **CSV and Excel** exports. It uses free libraries and does not call paid APIs, commercial scraping services, or external AI services.

## What it extracts

- Job title and company
- Location when available in Schema.org `JobPosting` structured data
- Employment type and work-arrangement mentions
- Experience and education mentions
- Salary when a recognizable salary pattern is present
- Responsibilities, requirements, preferred qualifications, benefits
- Description, source URL, UTC extraction timestamp, and a review note

The rules-based extractor preserves a description and leaves uncertain fields blank rather than inventing values. Extraction is heuristic, not guaranteed to be complete.

## 1. Requirements

- Python 3.10 or newer
- A PostgreSQL database (local or hosted)
- Internet access to company career pages you are authorized to crawl
- Windows, macOS, or Linux

## 2. Configure companies

Open `config.json`. Replace the sample company entry with each target company. Example structure:

```json
{
  "name": "Company Name",
  "career_url": "https://official-company-site.example/careers",
  "allowed_domains": ["official-company-site.example"]
}
```

Use the company's **official career landing page**. `allowed_domains` must list only domains you intend to crawl. If the company routes job details to a separate ATS domain (such as a hosted recruiting platform), add that domain only after checking the site's terms and robots.txt and confirming automated access is permitted. This MVP does not automatically cross into unlisted domains.

Set `user_agent` to identify your crawler and replace the contact placeholder with an appropriate monitored email. Start with a small `max_pages_per_domain` (e.g. 20) and keep `request_delay_seconds` at 2 or higher.

## 3. Install and run

### Windows (PowerShell)

```powershell
cd job_requirements_agent
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DATABASE"
python agent.py
```

If PowerShell blocks activation, use `\.venv\Scripts\python.exe -m pip install -r requirements.txt` and then `\.venv\Scripts\python.exe agent.py`.

### macOS / Linux

```bash
cd job_requirements_agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
$env:DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DATABASE"
python agent.py
```

## 4. Output files

The run creates these files in the project folder:

- `job_requirements.csv` — portable data for spreadsheets
- `job_requirements.xlsx` — Excel workbook
- PostgreSQL table `job_postings` — persistent database storage

Each run currently replaces the contents of `job_postings` with that run's results; it does not yet maintain historical snapshots. The CSV and Excel exports remain available even though PostgreSQL is the database.

## 5. Important limits

- The crawler checks `robots.txt` and skips pages disallowed for the configured user-agent. If `robots.txt` cannot be checked, it skips that host.
- It does not bypass logins, paywalls, CAPTCHAs, rate limits, or anti-bot controls.
- Some career sites render postings in JavaScript or use ATS domains; those may return few/no results until a permitted, site-specific parser is added.
- A career landing page may not expose all job links in ordinary HTML. Test one company at a time and inspect the output.
- Respect each website's terms, robots policy, and applicable law. Use extracted data for permitted research and retain source URLs for verification.

## Suggested pilot

1. Configure 2–3 company career pages.
2. Set `max_pages_per_domain` to 20.
3. Run the agent and check that job titles and source URLs are correct.
4. Compare at least 10 extracted postings with the original pages.
5. Add site-specific parsers only for sources where the generic parser misses important fields.
