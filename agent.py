"""RoleRadar job-requirements extraction agent.

Free/local-first crawler using requests, BeautifulSoup, pandas and PostgreSQL.
It obeys robots.txt, crawls only configured domains, and does not use paid APIs.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.robotparser
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urldefrag

import pandas as pd
import requests
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text

CONFIG_PATH = Path(__file__).with_name("config.json")
DEFAULT_JOB_URL_KEYWORDS = [
    "job", "jobs", "career", "careers", "opening", "position", "vacancy",
    "requisition", "jobid", "job-id", "opportunity", "apply", "role",
]
DEFAULT_EXCLUDE_URL_KEYWORDS = [
    "login", "signup", "privacy", "terms", "cookie", "advertisement",
    "benefits-enrollment", "sharepoint", "mailto:",
]
FIELDS = [
    "job_title", "company", "date_posted", "location_mention",
    "employment_type_mention", "work_arrangement_mention", "experience_mentions",
    "education_mentions", "salary_mention", "responsibilities", "requirements",
    "preferred_qualifications", "benefits", "description", "source_url",
    "extracted_at_utc", "extraction_note",
]


def clean(value: Any) -> str:
    """Collapse whitespace and return a safe string."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalized_host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def canonical_url(url: str) -> str:
    return urldefrag(url.strip())[0]


def robots_check(
    url: str,
    user_agent: str,
    session: requests.Session,
    cache: dict[str, tuple[bool, urllib.robotparser.RobotFileParser | None, str]],
) -> tuple[bool, str]:
    """Check robots.txt with useful diagnostics; fail closed for uncertain errors.

    RFC-style handling: 404/410 means no robots file was found; 401/403 and server
    errors block crawling. Network failures also fail closed. A successfully fetched
    robots file is evaluated for the configured User-Agent.
    """
    parts = urlparse(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    if robots_url not in cache:
        try:
            response = session.get(robots_url, timeout=15, allow_redirects=True)
            status = response.status_code
            if status in (404, 410):
                cache[robots_url] = (True, None, f"robots.txt returned HTTP {status}; no policy file found")
            elif status in (401, 403):
                cache[robots_url] = (False, None, f"robots.txt returned HTTP {status}; host access is restricted")
            elif status >= 500 or status == 429:
                cache[robots_url] = (False, None, f"robots.txt returned HTTP {status}; failing closed")
            elif 200 <= status < 300:
                parser = urllib.robotparser.RobotFileParser()
                parser.set_url(response.url)
                parser.parse(response.text.splitlines())
                cache[robots_url] = (True, parser, f"robots.txt fetched (HTTP {status})")
            elif 400 <= status < 500:
                # Unknown client errors are treated conservatively rather than ignored.
                cache[robots_url] = (False, None, f"robots.txt returned HTTP {status}; unable to verify permission")
            else:
                cache[robots_url] = (False, None, f"unexpected robots.txt HTTP status {status}; unable to verify permission")
        except requests.RequestException as exc:
            cache[robots_url] = (False, None, f"robots.txt request failed ({type(exc).__name__}); failing closed")

    available, parser, status_message = cache[robots_url]
    if not available:
        return False, status_message
    if parser is None:
        return True, status_message
    try:
        allowed = parser.can_fetch(user_agent, url)
    except Exception as exc:  # malformed robots rules should not stop the whole app
        return False, f"could not evaluate robots.txt ({type(exc).__name__}); failing closed"
    if not allowed:
        return False, f"explicitly disallowed by robots.txt for User-Agent {user_agent!r}"
    return True, status_message


def walk_jobpostings(obj: Any):
    """Yield JobPosting objects from nested JSON-LD data."""
    if isinstance(obj, dict):
        typ = obj.get("@type", [])
        if typ == "JobPosting" or (isinstance(typ, list) and "JobPosting" in typ):
            yield obj
        for value in obj.values():
            yield from walk_jobpostings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk_jobpostings(value)


def address_text(value: Any) -> str:
    if isinstance(value, str):
        return clean(value)
    if not isinstance(value, dict):
        return ""
    parts = [value.get("streetAddress"), value.get("addressLocality"), value.get("addressRegion")]
    country = value.get("addressCountry")
    if isinstance(country, str):
        parts.append(country)
    elif isinstance(country, dict):
        parts.append(country.get("name"))
    return ", ".join(clean(x) for x in parts if clean(x))


def jsonld_job_data(soup: BeautifulSoup) -> dict[str, str]:
    """Extract common Schema.org JobPosting fields, if present."""
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text()
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        for item in walk_jobpostings(parsed):
            org = item.get("hiringOrganization") or {}
            location = item.get("jobLocation") or []
            if not isinstance(location, list):
                location = [location]
            locations = []
            for loc in location:
                if isinstance(loc, dict):
                    addr = loc.get("address", {})
                    val = address_text(addr)
                    if val:
                        locations.append(val)
            emp = item.get("employmentType", "")
            if isinstance(emp, list):
                emp = "; ".join(clean(x) for x in emp if clean(x))
            description_html = item.get("description", "")
            description = BeautifulSoup(str(description_html), "html.parser").get_text(" ", strip=True)
            return {
                "job_title": clean(item.get("title", "")),
                "company": clean(org.get("name", "")) if isinstance(org, dict) else "",
                "location_mention": "; ".join(dict.fromkeys(locations)),
                "employment_type_mention": clean(emp),
                "description": clean(description),
                "date_posted": clean(item.get("datePosted", "")),
                "valid_through": clean(item.get("validThrough", "")),
            }
    return {}


def extract_sections(soup: BeautifulSoup, full_text: str) -> dict[str, str]:
    patterns = {
        "responsibilities": r"responsibilit|what you.?ll do|duties|role overview|day.to.day|key accountabilities",
        "requirements": r"requirement|qualifications|what you.?ll need|must have|minimum qualification|essential criteria|what you bring|skills and experience",
        "preferred_qualifications": r"preferred|nice to have|desirable|bonus points|good to have",
        "benefits": r"benefits|what we offer|perks|rewards|total rewards",
    }
    found: dict[str, list[str]] = {key: [] for key in patterns}
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "strong"]):
        label = clean(heading.get_text(" ", strip=True))
        if not label or len(label) > 120:
            continue
        key = next((name for name, pattern in patterns.items() if re.search(pattern, label, re.I)), None)
        if not key:
            continue
        pieces, node, steps = [], heading.find_next_sibling(), 0
        while node and steps < 20:
            if getattr(node, "name", None) in ["h1", "h2", "h3", "h4"]:
                break
            value = clean(node.get_text(" ", strip=True))
            if value:
                pieces.append(value)
            node, steps = node.find_next_sibling(), steps + 1
        if pieces:
            found[key].append(" ".join(pieces))
    out = {key: clean(" ".join(values)) for key, values in found.items()}
    out["description"] = full_text[:16000]
    return out


def infer_fields(title: str, body_text: str) -> dict[str, str]:
    exp = re.findall(
        r"\b(?:\d+\+?\s*(?:-|to)?\s*\d*\s*years?)(?:\s+of)?\s+(?:relevant\s+)?experience\b",
        body_text, re.I,
    )
    degree = re.findall(
        r"\b(?:bachelor(?:'s)?|master(?:'s)?|Ph\.?D\.?|MBA|B\.?S\.?|B\.?Tech|M\.?Tech|associate degree|high school diploma)\b[^.;\n]{0,100}",
        body_text, re.I,
    )
    work_type = next((x for x in ["Remote", "Hybrid", "On-site", "Onsite"] if re.search(rf"\b{re.escape(x)}\b", body_text, re.I)), "")
    employment = next((x for x in ["Full-time", "Part-time", "Contract", "Temporary", "Internship"] if re.search(rf"\b{re.escape(x)}\b", body_text, re.I)), "")
    salary_match = re.search(
        r"(?:\$|USD\s*)\s?\d[\d,]*(?:\.\d{2})?\s*(?:-|to|–)?\s*(?:\$\s?)?\d[\d,]*(?:\.\d{2})?\s*(?:per\s+(?:year|hour|month)|/\s*(?:yr|year|hr|hour))?",
        body_text, re.I,
    )
    return {
        "job_title": title,
        "experience_mentions": "; ".join(dict.fromkeys(clean(x) for x in exp)),
        "education_mentions": "; ".join(dict.fromkeys(clean(x) for x in degree)),
        "work_arrangement_mention": work_type,
        "employment_type_mention": employment,
        "salary_mention": salary_match.group(0) if salary_match else "",
    }


def company_configs(cfg: dict) -> list[dict]:
    companies = cfg.get("companies", [])
    valid = [
        company for company in companies
        if isinstance(company, dict)
        and clean(company.get("name"))
        and clean(company.get("career_url"))
        and "example.com" not in clean(company.get("career_url")).lower()
        and clean(company.get("name")).upper() != "ADD COMPANY NAME"
    ]
    if not valid:
        raise SystemExit(
            "No valid companies found. Add a company name, official career_url, and allowed_domains in config.json."
        )
    return valid


def is_job_detail_url(url: str, seed_url: str, keywords: list[str]) -> bool:
    """Avoid recording the careers landing page as a job; favor detail URLs."""
    url = canonical_url(url).rstrip("/")
    seed = canonical_url(seed_url).rstrip("/")
    if url == seed:
        return False
    path = urlparse(url).path.strip("/").lower()
    seed_path = urlparse(seed).path.strip("/").lower()
    # A path nested beneath a career/jobs root is normally a detail page.
    if seed_path and path.startswith(seed_path + "/") and len(path.split("/")) > len(seed_path.split("/")):
        return True
    return any(keyword.lower() in url.lower() for keyword in keywords)


def extract_job_record(
    company_name: str,
    source_url: str,
    page_title: str,
    page_text: str,
    clean_soup: BeautifulSoup,
    jobdata: dict[str, str],
) -> dict[str, str] | None:
    inferred = infer_fields(jobdata.get("job_title") or page_title, jobdata.get("description") or page_text)
    sections = extract_sections(clean_soup, page_text)
    title = jobdata.get("job_title") or inferred["job_title"]
    # Skip generic career/home titles even when a page contains hiring-related words.
    if not title or len(title) > 300:
        return None
    if re.search(r"\b(careers? at|join our team|current openings|job opportunities)\b", title, re.I):
        return None
    return {
        "job_title": title,
        "company": jobdata.get("company") or company_name,
        "date_posted": jobdata.get("date_posted", ""),
        "location_mention": jobdata.get("location_mention", ""),
        "employment_type_mention": jobdata.get("employment_type_mention") or inferred["employment_type_mention"],
        "work_arrangement_mention": inferred["work_arrangement_mention"],
        "experience_mentions": inferred["experience_mentions"],
        "education_mentions": inferred["education_mentions"],
        "salary_mention": inferred["salary_mention"],
        "responsibilities": sections["responsibilities"],
        "requirements": sections["requirements"],
        "preferred_qualifications": sections["preferred_qualifications"],
        "benefits": sections["benefits"],
        "description": jobdata.get("description") or sections["description"],
        "source_url": source_url,
        "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
        "extraction_note": "Rules-based extraction; verify against the source page. Blank fields mean not confidently detected.",
    }


def filter_posted_within_days(df: pd.DataFrame, within_days: int | None) -> tuple[pd.DataFrame, int, int]:
    """Keep only dated postings in the requested window; unknown dates are excluded."""
    if within_days is None or df.empty:
        return df, 0, 0
    dates = pd.to_datetime(df["date_posted"], errors="coerce", utc=True)
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=within_days)
    keep = dates.notna() & (dates >= cutoff) & (dates <= pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=1))
    excluded_undated = int(dates.isna().sum())
    excluded_outside = int((dates.notna() & ~keep).sum())
    return df.loc[keep].copy(), excluded_undated, excluded_outside


def database_engine(database_url: str):
    """Normalize common PostgreSQL URLs for psycopg 3 / SQLAlchemy."""
    database_url = database_url.strip()
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgres://"):]
    elif database_url.startswith("postgresql://") and "+" not in database_url.split(":", 1)[0]:
        database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]
    return create_engine(database_url, pool_pre_ping=True)


def save_records_to_postgres(df: pd.DataFrame, database_url: str) -> None:
    """Append/update scanned URLs without replacing results from other companies."""
    engine = database_engine(database_url)
    quoted_columns = ", ".join(f'"{column}"' for column in FIELDS)
    try:
        with engine.begin() as con:
            # Create a stable schema if the table has not existed yet. All extracted
            # values are stored as TEXT; the dashboard can parse dates for display.
            con.execute(text("""
                CREATE TABLE IF NOT EXISTS job_postings (
                    job_title TEXT, company TEXT, date_posted TEXT,
                    location_mention TEXT, employment_type_mention TEXT,
                    work_arrangement_mention TEXT, experience_mentions TEXT,
                    education_mentions TEXT, salary_mention TEXT,
                    responsibilities TEXT, requirements TEXT,
                    preferred_qualifications TEXT, benefits TEXT,
                    description TEXT, source_url TEXT, extracted_at_utc TEXT,
                    extraction_note TEXT
                )
            """))
            for column in FIELDS:
                con.execute(text(f'ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS "{column}" TEXT'))

            stage = "job_postings_scan_stage"
            # Stage is only temporary scan data; target rows for other URLs stay intact.
            df.reindex(columns=FIELDS).to_sql(
                stage, con, if_exists="replace", index=False, method="multi", chunksize=250
            )
            if not df.empty:
                con.execute(text(f"""
                    DELETE FROM job_postings AS target
                    USING {stage} AS incoming
                    WHERE target.source_url = incoming.source_url
                      AND incoming.source_url IS NOT NULL
                """))
                con.execute(text(f"INSERT INTO job_postings ({quoted_columns}) SELECT {quoted_columns} FROM {stage}"))
            con.execute(text(f"DROP TABLE IF EXISTS {stage}"))
            con.execute(text("CREATE INDEX IF NOT EXISTS idx_job_company ON job_postings (company)"))
            con.execute(text("CREATE INDEX IF NOT EXISTS idx_job_title ON job_postings (job_title)"))
    finally:
        engine.dispose()


def main() -> None:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Missing config.json next to agent.py: {CONFIG_PATH}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"config.json is not valid JSON: {exc}")

    ua = clean(cfg.get("user_agent")) or "RoleRadarBot/1.0"
    delay = max(1.0, float(cfg.get("request_delay_seconds", 2)))
    max_pages = max(1, int(cfg.get("max_pages_per_domain", cfg.get("max_pages_per_company", 80))))
    job_keywords = [clean(k).lower() for k in cfg.get("job_url_keywords", DEFAULT_JOB_URL_KEYWORDS) if clean(k)]
    if not job_keywords:
        job_keywords = DEFAULT_JOB_URL_KEYWORDS
    exclude_keywords = [clean(k).lower() for k in cfg.get("exclude_url_keywords", DEFAULT_EXCLUDE_URL_KEYWORDS) if clean(k)]
    if not exclude_keywords:
        exclude_keywords = DEFAULT_EXCLUDE_URL_KEYWORDS

    session = requests.Session()
    session.headers.update({"User-Agent": ua, "Accept": "text/html,application/xhtml+xml,application/xhtml+xml;q=0.9,*/*;q=0.8"})
    robots_cache: dict[str, tuple[bool, urllib.robotparser.RobotFileParser | None, str]] = {}
    records: list[dict[str, str]] = []
    visited_total = 0
    blocked_total = 0

    for company_cfg in company_configs(cfg):
        company_name = clean(company_cfg.get("name"))
        seed = clean(company_cfg.get("career_url"))
        if not seed.lower().startswith(("https://", "http://")):
            print(f"SKIP {company_name}: career_url must begin with http:// or https://: {seed}")
            continue

        configured_domains = company_cfg.get("allowed_domains", []) or []
        allowed = {clean(domain).lower().removeprefix("www.") for domain in configured_domains if clean(domain)}
        if not allowed:
            allowed = {normalized_host(seed)}
        if normalized_host(seed) not in allowed:
            print(f"CONFIG ERROR {company_name}: career_url host {normalized_host(seed)!r} is not in allowed_domains {sorted(allowed)!r}")
            continue

        company_records_before = len(records)
        queue = deque([canonical_url(seed)])
        seen: set[str] = set()
        rejected = 0
        print(f"\n=== {company_name} ===")
        print(f"Start URL: {seed} | allowed domains: {', '.join(sorted(allowed))} | page limit: {max_pages}")

        while queue and len(seen) < max_pages:
            url = canonical_url(queue.popleft())
            if not url or url in seen:
                continue
            parsed = urlparse(url)
            host = normalized_host(url)
            if parsed.scheme not in ("http", "https") or host not in allowed:
                continue
            seen.add(url)
            allowed_by_robots, robots_message = robots_check(url, ua, session, robots_cache)
            if not allowed_by_robots:
                blocked_total += 1
                print(f"SKIP robots.txt: {url} | {robots_message}")
                continue
            try:
                response = session.get(url, timeout=25, allow_redirects=True)
                final_url = canonical_url(response.url)
                final_host = normalized_host(final_url)
                if final_host not in allowed:
                    print(f"SKIP redirect outside allowed_domains: {url} -> {final_url}")
                    continue
                if response.status_code != 200:
                    print(f"HTTP {response.status_code}: {url}")
                    continue
                content_type = response.headers.get("Content-Type", "").lower()
                if "html" not in content_type and "xhtml" not in content_type:
                    print(f"SKIP non-HTML content ({content_type or 'unknown content type'}): {url}")
                    continue

                raw_soup = BeautifulSoup(response.text, "html.parser")
                jobdata = jsonld_job_data(raw_soup)
                clean_soup = BeautifulSoup(response.text, "html.parser")
                for tag in clean_soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
                    tag.decompose()
                heading = clean_soup.find("h1")
                title_tag = clean_soup.find("title")
                page_title = clean((heading or title_tag or clean_soup).get_text(" ", strip=True))[:300]
                page_text = clean(clean_soup.get_text(" ", strip=True))

                is_detail = is_job_detail_url(final_url, seed, job_keywords)
                has_job_signals = bool(re.search(
                    r"responsibilities|qualifications|required skills|years of experience|apply now|job description|jobposting|what you.?ll do|what you.?ll need",
                    page_text, re.I,
                ))
                if jobdata or (is_detail and has_job_signals and len(page_text) > 400):
                    record = extract_job_record(company_name, final_url, page_title, page_text, clean_soup, jobdata)
                    if record:
                        records.append(record)
                        print(f"JOB FOUND: {record['job_title']} | {final_url}")

                # Discover links from every permitted HTML page, not just a fixed
                # number of links on the start page. Keep the crawl domain-scoped.
                links_added = 0
                for anchor in raw_soup.find_all("a", href=True):
                    href = clean(anchor.get("href"))
                    if not href or href.startswith(("mailto:", "tel:", "javascript:")):
                        continue
                    target = canonical_url(urljoin(final_url, href))
                    target_parts = urlparse(target)
                    target_host = normalized_host(target)
                    if target_parts.scheme not in ("http", "https") or target_host not in allowed:
                        continue
                    lower_url = target.lower()
                    if any(word in lower_url for word in exclude_keywords):
                        continue
                    if target not in seen and target not in queue:
                        # Prioritize links with job-related words; also follow
                        # internal links on career pages so ATS/detail links can be found.
                        target_is_job_related = any(word in lower_url for word in job_keywords)
                        if target_is_job_related or len(seen) < 10:
                            queue.append(target)
                            links_added += 1
                visited_total += 1
                print(
                    f"Visited {len(seen)}/{max_pages}: {final_url} | "
                    f"jobs found this company: {len(records) - company_records_before} | "
                    f"links queued: {links_added}"
                )
            except requests.RequestException as exc:
                print(f"REQUEST ERROR {url}: {type(exc).__name__}: {exc}")
            except Exception as exc:
                # A broken page should not crash all of the companies in one scan.
                print(f"PAGE ERROR {url}: {type(exc).__name__}: {exc}")
            time.sleep(delay)

        if not seen:
            print(f"WARNING: No in-domain URLs were visited for {company_name}.")
        print(f"Company summary: visited={len(seen)}, total URLs blocked by robots/access check={blocked_total}, jobs extracted={len(records) - company_records_before}")

    df = pd.DataFrame(records, columns=FIELDS)
    if not df.empty:
        df = df.drop_duplicates(subset=["source_url"], keep="first")

    within_days = os.environ.get("SCAN_POSTED_WITHIN_DAYS", "").strip()
    if within_days:
        try:
            days = max(1, int(within_days))
        except ValueError:
            raise SystemExit("SCAN_POSTED_WITHIN_DAYS must be a positive integer, such as 30.")
        before_filter = len(df)
        df, excluded_undated, excluded_outside = filter_posted_within_days(df, days)
        print(
            f"Date filter: last {days} days | kept={len(df)} | removed={before_filter - len(df)} "
            f"(undated={excluded_undated}, outside window/future={excluded_outside})"
        )

    csv_path = cfg.get("export_csv", "job_requirements.csv")
    excel_path = cfg.get("export_excel", "job_requirements.xlsx")
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    try:
        df.to_excel(excel_path, index=False)
    except Exception as exc:
        print(f"WARNING: Could not create Excel export ({type(exc).__name__}: {exc}). CSV was saved.")

    database_env = clean(cfg.get("database_url_env", "DATABASE_URL")) or "DATABASE_URL"
    database_url = os.environ.get(database_env, "").strip()
    if not database_url:
        raise SystemExit(
            f"PostgreSQL connection is not configured. Set {database_env} in Render → Environment "
            "(or Streamlit secrets) before running a scan. CSV export was still created."
        )
    try:
        save_records_to_postgres(df, database_url)
    except Exception as exc:
        raise SystemExit(
            f"PostgreSQL save failed ({type(exc).__name__}: {exc}). Check DATABASE_URL, the psycopg driver, "
            f"and database permissions. CSV export was saved to {csv_path}."
        )

    print(f"\nDone. Extracted {len(df)} candidate job pages; visited {visited_total} HTML pages; robots/access skips={blocked_total}.")
    print(f"Created/updated: {csv_path}, {excel_path}, PostgreSQL table job_postings")
    if not records:
        print("No job pages were extracted. Check the robots.txt explanations above, the career URL, allowed_domains, and whether the careers site renders job listings with JavaScript.")
    print("Note: heuristic extraction should be reviewed against each source page. Undisclosed fields remain blank.")


if __name__ == "__main__":
    main()
