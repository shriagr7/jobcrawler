"""Free, local-first job requirements extraction MVP for company career pages.

Uses requests, BeautifulSoup, pandas, and PostgreSQL. No paid APIs or scraping services.
Crawls only configured domains, checks robots.txt, and never bypasses access controls.
"""
from __future__ import annotations
import json, os, re, time, urllib.robotparser
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin
import requests
import pandas as pd
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text

CONFIG_PATH = Path(__file__).with_name("config.json")
FIELDS = [
    "job_title", "company", "location_mention", "employment_type_mention",
    "work_arrangement_mention", "experience_mentions", "education_mentions",
    "salary_mention", "responsibilities", "requirements", "preferred_qualifications",
    "benefits", "description", "source_url", "extracted_at_utc", "extraction_note"
]

def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()

def robots_allowed(url: str, user_agent: str, cache: dict) -> bool:
    p = urlparse(url)
    robots_url = f"{p.scheme}://{p.netloc}/robots.txt"
    if robots_url not in cache:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        try:
            rp.read()
            cache[robots_url] = rp
        except Exception:
            # Conservative: if robots.txt cannot be checked, do not crawl the host.
            cache[robots_url] = None
    rp = cache[robots_url]
    return bool(rp and rp.can_fetch(user_agent, url))

def jsonld_job_data(soup: BeautifulSoup) -> dict:
    """Read standard Schema.org JobPosting fields where present."""
    def walk(obj):
        if isinstance(obj, dict):
            typ = obj.get("@type", [])
            if typ == "JobPosting" or (isinstance(typ, list) and "JobPosting" in typ):
                yield obj
            for value in obj.values():
                yield from walk(value)
        elif isinstance(obj, list):
            for value in obj:
                yield from walk(value)
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text()
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for item in walk(parsed):
            org = item.get("hiringOrganization") or {}
            locs = item.get("jobLocation") or []
            if isinstance(locs, dict): locs = [locs]
            loc_text = []
            for loc in locs:
                addr = loc.get("address", {}) if isinstance(loc, dict) else {}
                if isinstance(addr, dict):
                    val = ", ".join(filter(None, [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry") if isinstance(addr.get("addressCountry"), str) else (addr.get("addressCountry", {}).get("name") if isinstance(addr.get("addressCountry"), dict) else None)]))
                    if val: loc_text.append(val)
            return {
                "job_title": clean(item.get("title", "")),
                "company": clean(org.get("name", "")) if isinstance(org, dict) else "",
                "location_mention": "; ".join(dict.fromkeys(loc_text)),
                "employment_type_mention": clean("; ".join(item.get("employmentType", [])) if isinstance(item.get("employmentType"), list) else str(item.get("employmentType", ""))),
                "description": clean(BeautifulSoup(item.get("description", ""), "html.parser").get_text(" ", strip=True)),
                "date_posted": clean(item.get("datePosted", "")),
            }
    return {}

def extract_sections(soup: BeautifulSoup, full_text: str) -> dict:
    patterns = {
        "responsibilities": r"responsibilit|what you.ll do|duties|role overview|day.to.day|key accountabilities",
        "requirements": r"requirement|qualifications|what you.ll need|must have|minimum qualification|essential criteria|what you bring|skills and experience",
        "preferred_qualifications": r"preferred|nice to have|desirable|bonus points|good to have",
        "benefits": r"benefits|what we offer|perks|rewards|total rewards",
    }
    found = {k: [] for k in patterns}
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "strong"]):
        label = clean(heading.get_text(" ", strip=True))
        if not label or len(label) > 120: continue
        key = next((k for k, pat in patterns.items() if re.search(pat, label, re.I)), None)
        if not key: continue
        pieces, node, steps = [], heading.find_next_sibling(), 0
        while node and steps < 12:
            if getattr(node, "name", None) in ["h1", "h2", "h3", "h4"]: break
            value = clean(node.get_text(" ", strip=True))
            if value: pieces.append(value)
            node, steps = node.find_next_sibling(), steps + 1
        if pieces: found[key].append(" ".join(pieces))
    out = {k: clean(" ".join(v)) for k, v in found.items()}
    out["description"] = full_text[:16000]
    return out

def infer_fields(title: str, text: str) -> dict:
    exp = re.findall(r"\b(?:\d+\+?\s*(?:-|to)?\s*\d*\s*years?)(?:\s+of)?\s+(?:relevant\s+)?experience\b", text, re.I)
    degree = re.findall(r"\b(?:bachelor(?:'s)?|master(?:'s)?|Ph\.?D\.?|MBA|B\.?S\.?|B\.?Tech|M\.?Tech|associate degree|high school diploma)\b[^.;\n]{0,100}", text, re.I)
    work_type = next((x for x in ["Remote", "Hybrid", "On-site", "Onsite"] if re.search(rf"\b{re.escape(x)}\b", text, re.I)), "")
    employment = next((x for x in ["Full-time", "Part-time", "Contract", "Temporary", "Internship"] if re.search(rf"\b{re.escape(x)}\b", text, re.I)), "")
    salary_match = re.search(r"(?:\$|USD\s*)\s?\d[\d,]*(?:\.\d{2})?\s*(?:-|to|–)?\s*(?:\$\s?)?\d[\d,]*(?:\.\d{2})?\s*(?:per\s+(?:year|hour|month)|/\s*(?:yr|year|hr|hour))?", text, re.I)
    return {"job_title": title, "experience_mentions": "; ".join(dict.fromkeys(clean(x) for x in exp)), "education_mentions": "; ".join(dict.fromkeys(clean(x) for x in degree)), "work_arrangement_mention": work_type, "employment_type_mention": employment, "salary_mention": salary_match.group(0) if salary_match else ""}

def company_configs(cfg: dict) -> list[dict]:
    companies = cfg.get("companies", [])
    valid = [c for c in companies if c.get("career_url") and "example.com" not in c.get("career_url", "") and c.get("name") != "ADD COMPANY NAME"]
    if not valid:
        raise SystemExit("Please edit config.json and add at least one real company name, official career_url, and allowed_domains entry.")
    return valid

def main():
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    ua = cfg.get("user_agent", "JobRequirementsResearchBot/1.0")
    delay = max(1.0, float(cfg.get("request_delay_seconds", 2)))
    max_pages = int(cfg.get("max_pages_per_domain", 80))
    session = requests.Session()
    session.headers.update({"User-Agent": ua, "Accept": "text/html,application/xhtml+xml"})
    robots_cache, records = {}, []
    for company_cfg in company_configs(cfg):
        company_name = company_cfg["name"].strip()
        allowed = {d.lower().removeprefix("www.") for d in company_cfg.get("allowed_domains", [])}
        seed = company_cfg["career_url"].strip()
        if not allowed:
            allowed = {(urlparse(seed).hostname or "").lower().removeprefix("www.")}
        queue, seen = deque([seed]), set()
        print(f"\n=== {company_name} ===")
        while queue and len(seen) < max_pages:
            url = queue.popleft().split("#", 1)[0]
            if url in seen: continue
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower().removeprefix("www.")
            if parsed.scheme not in ("http", "https") or host not in allowed: continue
            seen.add(url)
            if not robots_allowed(url, ua, robots_cache):
                print(f"SKIP robots.txt: {url}"); continue
            try:
                resp = session.get(url, timeout=20, allow_redirects=True)
                if resp.status_code != 200 or "text/html" not in resp.headers.get("Content-Type", ""):
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")
                jobdata = jsonld_job_data(soup)
                clean_soup = BeautifulSoup(resp.text, "html.parser")
                for tag in clean_soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]): tag.decompose()
                h1 = clean_soup.find("h1")
                page_title = clean((h1 or clean_soup.find("title") or clean_soup).get_text(" ", strip=True))[:300]
                page_text = clean(clean_soup.get_text(" ", strip=True))
                current_url = resp.url
                url_l = current_url.lower()
                is_job_url = any(k in url_l for k in cfg.get("job_url_keywords", []))
                has_job_signals = bool(re.search(r"responsibilities|qualifications|required skills|years of experience|apply now|job description|jobposting", page_text, re.I))
                if (jobdata or (is_job_url and has_job_signals and len(page_text) > 400)):
                    sections = extract_sections(clean_soup, page_text)
                    inferred = infer_fields(jobdata.get("job_title") or page_title, jobdata.get("description") or page_text)
                    records.append({
                        "job_title": jobdata.get("job_title") or inferred["job_title"],
                        "company": jobdata.get("company") or company_name,
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
                        "source_url": current_url,
                        "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
                        "extraction_note": "Rules-based extraction; verify against source page. Blank fields mean not confidently detected."
                    })
                for a in clean_soup.find_all("a", href=True):
                    href = urljoin(current_url, a["href"]).split("#", 1)[0]
                    hp = urlparse(href)
                    hhost = (hp.hostname or "").lower().removeprefix("www.")
                    if hp.scheme in ("http", "https") and hhost in allowed and href not in seen:
                        if any(x in href.lower() for x in cfg.get("exclude_url_keywords", [])): continue
                        if any(k in href.lower() for k in cfg.get("job_url_keywords", [])) or len(seen) < 10:
                            queue.append(href)
                print(f"Visited {len(seen)}/{max_pages}: {url} | candidate job pages found: {len(records)}")
            except requests.RequestException as e:
                print(f"ERROR {url}: {e}")
            time.sleep(delay)
    df = pd.DataFrame(records, columns=FIELDS)
    if not df.empty:
        df = df.drop_duplicates(subset=["source_url"], keep="first")
    df.to_csv(cfg.get("export_csv", "job_requirements.csv"), index=False, encoding="utf-8-sig")
    df.to_excel(cfg.get("export_excel", "job_requirements.xlsx"), index=False)
    database_url = os.environ.get(cfg.get("database_url_env", "DATABASE_URL"), "").strip()
    if not database_url:
        raise SystemExit(
            "PostgreSQL connection is not configured. Set the DATABASE_URL environment variable "
            "(or add DATABASE_URL to Streamlit secrets) before running a scan."
        )
    # Support common provider URLs while using psycopg 3 as the PostgreSQL driver.
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgres://"):]
    elif database_url.startswith("postgresql://") and "+" not in database_url.split(":", 1)[0]:
        database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as con:
            df.to_sql("job_postings", con, if_exists="replace", index=False, method="multi", chunksize=500)
            con.execute(text("CREATE INDEX IF NOT EXISTS idx_job_company ON job_postings (company)"))
            con.execute(text("CREATE INDEX IF NOT EXISTS idx_job_title ON job_postings (job_title)"))
    finally:
        engine.dispose()
    print(f"\nDone. Extracted {len(df)} candidate job pages.")
    print(f"Created: {cfg.get('export_csv', 'job_requirements.csv')}, {cfg.get('export_excel', 'job_requirements.xlsx')}, PostgreSQL table job_postings")
    print("Note: heuristic results require review. Some career sites need a site-specific parser or render JavaScript and may not be crawlable with this MVP.")

if __name__ == "__main__":
    main()
