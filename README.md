# RoleRadar — Excel job export

This update adds downloadable Excel workbooks to both **Open jobs** and **Job dashboard** while preserving the current branded UI, individual-job filtering, and background scanning behavior.

## Excel workbook contents

- Job title and company
- A clickable **View job description** hyperlink that opens the individual job-posting page
- Location, date posted, employment type, work arrangement, experience, and salary when available
- The full job description when available
- The job-posting URL as a second direct hyperlink

The export follows the currently selected company and search filters. The Job dashboard export follows the dashboard filters; the Open jobs export follows the open-jobs filters.

## Files

- `streamlit_app.py` — updated dashboard with Excel and CSV downloads
- `agent.py` — current job crawler
- `scan_worker.py` — current background worker
- `requirements.txt` — dependencies, including `openpyxl` for Excel export
- `roleradar_logo.svg` — sidebar logo

## Deploy to GitHub / Render

1. Replace these files in the root of the existing RoleRadar repository.
2. Keep the existing `config.json`, `DATABASE_URL`, and current Render settings unchanged.
3. Commit and push the changes. Let Render redeploy.

No schema change or database migration is required. The workbook is generated when the user downloads it and does not write files to the server disk.

## Validation performed

- Python syntax compilation passed for `streamlit_app.py`, `agent.py`, and `scan_worker.py`.
- Excel export smoke test passed using sample jobs; verified the workbook contains a job description column, a clickable direct-posting link, a URL hyperlink, and a frozen header row.
