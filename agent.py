"""RoleRadar job-requirements extraction agent.

Free/local-first crawler using requests, BeautifulSoup, pandas and PostgreSQL.
It obeys robots.txt, crawls only configured domains, and does not use paid APIs.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
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

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:  # Static HTML crawling remains available without Playwright.
    sync_playwright = None
    PLAYWRIGHT_AVAILABLE = False

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
    "job_key", "job_id", "job_title", "company", "date_posted", "valid_through",
    "job_status", "location_mention", "employment_type_mention",
    "work_arrangement_mention", "experience_mentions", "education_mentions",
    "salary_mention", "responsibilities", "requirements", "preferred_qualifications",
    "benefits", "description", "source_url", "first_seen_utc", "last_seen_utc",
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


def jsonld_job_data(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Extract every Schema.org JobPosting object found in JSON-LD."""
    results: list[dict[str, str]] = []
    seen: set[str] = set()
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
                    val = address_text(loc.get("address", {}))
                    if val:
                        locations.append(val)
            emp = item.get("employmentType", "")
            if isinstance(emp, list):
                emp = "; ".join(clean(x) for x in emp if clean(x))
            description_html = item.get("description", "")
            description = BeautifulSoup(str(description_html), "html.parser").get_text(" ", strip=True)
            identifier = item.get("identifier", "")
            if isinstance(identifier, dict):
                identifier = identifier.get("value") or identifier.get("name") or ""
            elif isinstance(identifier, list):
                identifier = "; ".join(clean(x.get("value") if isinstance(x, dict) else x) for x in identifier)
            record = {
                "job_title": clean(item.get("title", "")),
                "company": clean(org.get("name", "")) if isinstance(org, dict) else "",
                "location_mention": "; ".join(dict.fromkeys(locations)),
                "employment_type_mention": clean(emp),
                "description": clean(description),
                "date_posted": clean(item.get("datePosted", "")),
                "valid_through": clean(item.get("validThrough", "")),
                "url": clean(item.get("url", "")),
                "job_id": clean(identifier),
            }
            # Avoid duplicate objects included in multiple JSON-LD scripts.
            dedupe_key = "|".join([record["url"], record["job_id"], record["job_title"], record["company"]])
            if dedupe_key not in seen:
                seen.add(dedupe_key)
                results.append(record)
    return results


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
    """Return configured companies, skipping example placeholders."""
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
            "No valid companies found. Add a company name and official career_url in config.json."
        )
    return valid


def is_job_detail_url(url: str, seed_url: str, keywords: list[str]) -> bool:
    """Avoid recording the careers landing page as a job; favor detail URLs."""
    url = canonical_url(url).rstrip("/")
    seed = canonical_url(seed_url).rstrip("/")
    if url == seed:
        return False

    target_parts = urlparse(url)
    seed_parts = urlparse(seed)
    path_and_query = f"{target_parts.path}?{target_parts.query}".lower()
    seed_path = seed_parts.path.strip("/").lower()

    # A path nested beneath a career/jobs root is normally a detail page.
    path = target_parts.path.strip("/").lower()
    if seed_path and path.startswith(seed_path + "/") and len(path.split("/")) > len(seed_path.split("/")):
        return True
    return any(keyword.lower() in path_and_query for keyword in keywords)


# Well-known applicant-tracking systems (ATS). External ATS links are followed only
# when they are linked from a company's configured careers page and look job-related.
KNOWN_ATS_DOMAINS = {
    "greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com",
    "workday.com", "smartrecruiters.com", "icims.com", "jobvite.com",
    "bamboohr.com", "teamtailor.com", "recruitee.com", "workable.com",
    "applytojob.com", "successfactors.com", "taleo.net", "oraclecloud.com",
    "dayforcehcm.com", "phenompeople.com", "rippling.com", "paylocity.com",
    "ultipro.com", "jazz.co", "hireology.com", "pinpointhq.com",
    "applicantpro.com", "jobappnetwork.com", "careers-page.com",
    "breezy.hr", "breezy.com", "personio.com", "teamtailor.com",
}
JOB_CONTEXT_RE = re.compile(
    r"job|career|position|opening|vacanc|requisition|posting|listing|search.?result|"
    r"job.?title|job.?card|role.?card|opportunit|employment|job.?item|career.?item",
    re.I,
)
GENERIC_LINK_RE = re.compile(
    r"^(apply(?: now)?|apply here|view|view job|view role|view position|details|"
    r"learn more|read more|click here|view details|more details|more|search jobs|browse jobs|current openings|"
    r"open positions|all positions|all jobs|all job openings|job opportunities|career opportunities|"
    r"view all jobs|see all jobs|find a job|browse careers|careers?|join our team|see details|job details|show more)$", re.I,
)


def host_is_allowed(host: str, allowed: set[str]) -> bool:
    """Match configured hostnames and their subdomains."""
    host = (host or "").lower().removeprefix("www.").rstrip(".")
    for domain in allowed:
        domain = (domain or "").lower().removeprefix("www.").strip("./")
        if domain and (host == domain or host.endswith("." + domain)):
            return True
    return False


def is_known_ats_host(host: str) -> bool:
    host = (host or "").lower().removeprefix("www.").rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in KNOWN_ATS_DOMAINS)


def looks_like_job_title(label: str) -> bool:
    label = clean(label)
    if not (5 <= len(label) <= 150) or GENERIC_LINK_RE.match(label):
        return False
    if len(label.split()) > 18:
        return False
    if re.search(r"\b(cookie settings|privacy policy|terms of use|sign in|log in|subscribe|newsletter)\b", label, re.I):
        return False
    return bool(re.search(r"[A-Za-z]{2,}", label))


def card_context_for_anchor(anchor: Any) -> tuple[Any | None, str]:
    """Return the closest plausible job-card ancestor and its semantic attributes."""
    node = anchor
    fallback = None
    fallback_attrs = ""
    for _ in range(7):
        if node is None or not getattr(node, "name", None):
            break
        attrs = []
        for key in ("class", "id", "role", "aria-label", "data-testid", "data-automation", "data-test", "itemprop"):
            value = node.get(key, "")
            if isinstance(value, list):
                attrs.extend(str(x) for x in value)
            elif value:
                attrs.append(str(value))
        attr_text = " ".join(attrs)
        text_len = len(clean(node.get_text(" ", strip=True)))
        if JOB_CONTEXT_RE.search(attr_text) and text_len <= 6000:
            return node, attr_text
        if node.name in {"article", "li", "tr"} and text_len <= 6000:
            fallback, fallback_attrs = node, attr_text
        node = node.parent
    return fallback, fallback_attrs


def anchor_looks_job_related(anchor: Any, target_url: str, keywords: list[str]) -> bool:
    """Classify role links by URL, label, card semantics, or a recognized ATS URL."""
    parts = urlparse(target_url)
    path_and_query = f"{parts.path}?{parts.query}".lower()
    if any(keyword.lower() in path_and_query for keyword in keywords):
        return True

    label = clean(anchor.get_text(" ", strip=True))[:180]
    if re.search(
        r"\b(apply|view (?:job|role|position)|see (?:job|role|position)|job details|"
        r"current (?:jobs|roles|positions|openings)|open positions|browse jobs|job description)\b",
        label,
        re.I,
    ):
        return True

    card, attr_context = card_context_for_anchor(anchor)
    if card is not None and JOB_CONTEXT_RE.search(attr_context):
        return True

    # Some ATS providers use opaque IDs without /job/ or /careers/ in the URL.
    if is_known_ats_host(parts.hostname or "") and looks_like_job_title(label):
        path_segments = [segment for segment in parts.path.split("/") if segment]
        if len(path_segments) >= 2:
            return True
    return False


def extract_listing_cards(
    soup: BeautifulSoup,
    page_url: str,
    allowed: set[str],
    keywords: list[str],
) -> list[dict[str, str]]:
    """Extract title/link pairs from visible job cards when listing pages lack JobPosting JSON-LD."""
    found: dict[str, dict[str, str]] = {}
    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "data:")):
            continue
        target = canonical_url(urljoin(page_url, href))
        parts = urlparse(target)
        host = normalized_host(target)
        if parts.scheme not in ("http", "https"):
            continue
        # The calling page must actually link to an ATS; this is not a general-purpose
        # crawler for arbitrary external sites. The caller still checks robots.txt.
        if not host_is_allowed(host, allowed) and not is_known_ats_host(host):
            continue

        label = clean(anchor.get_text(" ", strip=True)) or clean(anchor.get("aria-label", ""))
        if GENERIC_LINK_RE.match(label):
            continue
        card, attrs = card_context_for_anchor(anchor)
        card_text = clean(card.get_text(" ", strip=True))[:5000] if card is not None else label
        title = label
        if not looks_like_job_title(title) and card is not None:
            title_node = card.find(["h1", "h2", "h3", "h4", "h5"])
            if title_node:
                title = clean(title_node.get_text(" ", strip=True))
            if not looks_like_job_title(title):
                # Some ATS pages mark title elements via data attributes rather than headings.
                title_node = card.select_one("[data-automation*='title'], [data-testid*='title'], [class*='job-title'], [class*='posting-title'], [itemprop='title']")
                if title_node:
                    title = clean(title_node.get_text(" ", strip=True))

        path_hint = any(keyword.lower() in f"{parts.path}?{parts.query}".lower() for keyword in keywords)
        semantic_card = card is not None and bool(JOB_CONTEXT_RE.search(attrs))
        ats_hint = is_known_ats_host(host) and len([x for x in parts.path.split("/") if x]) >= 2
        if not looks_like_job_title(title):
            continue
        if not (path_hint or semantic_card or ats_hint):
            continue
        if any(word in f"{parts.path}?{parts.query}".lower() for word in DEFAULT_EXCLUDE_URL_KEYWORDS):
            continue

        # Prefer explicit machine-readable location labels in the card.
        location = ""
        if card is not None:
            loc_node = card.select_one("[itemprop='jobLocation'], [data-automation*='location'], [data-testid*='location'], [class*='location'], [class*='Location']")
            if loc_node:
                location = clean(loc_node.get_text(" ", strip=True))[:250]
        item = {
            "job_title": title,
            "company": "",
            "location_mention": location,
            "employment_type_mention": "",
            "description": card_text,
            "date_posted": "",
            "valid_through": "",
            "url": target,
            "job_id": "",
            "_specific_url": True,
        }
        found[target] = item
    return list(found.values())


def parse_page_html(html: str) -> tuple[BeautifulSoup, BeautifulSoup, list[dict[str, str]], str, str]:
    """Parse raw HTML and return soups, JSON-LD jobs, page title and visible text."""
    raw_soup = BeautifulSoup(html or "", "html.parser")
    jobdata_list = jsonld_job_data(raw_soup)
    clean_soup = BeautifulSoup(html or "", "html.parser")
    for tag in clean_soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        tag.decompose()
    heading = clean_soup.find("h1")
    title_tag = clean_soup.find("title")
    page_title = clean((heading or title_tag or clean_soup).get_text(" ", strip=True))[:300]
    page_text = clean(clean_soup.get_text(" ", strip=True))
    return raw_soup, clean_soup, jobdata_list, page_title, page_text


def relevant_job_link_count(soup: BeautifulSoup, page_url: str, allowed: set[str], keywords: list[str]) -> int:
    """Count unique same-company/explicitly-approved job-related links on a page."""
    found: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        target = canonical_url(urljoin(page_url, href))
        parts = urlparse(target)
        if parts.scheme not in ("http", "https") or not (host_is_allowed(normalized_host(target), allowed) or is_known_ats_host(normalized_host(target))):
            continue
        if anchor_looks_job_related(anchor, target, keywords):
            found.add(target)
    return len(found)


def should_render_with_browser(
    soup: BeautifulSoup,
    jobdata_list: list[dict[str, str]],
    page_title: str,
    page_text: str,
    page_url: str,
    seed_url: str,
    allowed: set[str],
    keywords: list[str],
    cfg: dict,
) -> bool:
    """Choose Playwright only when static HTML likely lacks rendered job content."""
    if jobdata_list or not bool(cfg.get("enable_playwright", True)):
        return False

    # The configured URL is the highest-value page to render: modern career portals often
    # place all job cards in a client-side widget while static HTML looks like a complete page.
    is_seed_listing = (
        canonical_url(page_url).rstrip("/") == canonical_url(seed_url).rstrip("/")
        and not is_job_detail_url(page_url, seed_url, keywords)
    )
    if is_seed_listing:
        return True

    min_text = max(200, int(cfg.get("playwright_min_static_text_chars", 1200)))
    min_links = max(0, int(cfg.get("playwright_min_job_links", 2)))
    text_lower = (page_title + " " + page_text).lower()
    js_placeholder = bool(re.search(
        r"enable javascript|javascript is required|loading (?:jobs|openings|positions)|"
        r"please wait while we load|your browser does not support javascript",
        text_lower,
        re.I,
    ))
    link_count = relevant_job_link_count(soup, page_url, allowed, keywords)
    detail_page_with_content = (
        is_job_detail_url(page_url, seed_url, keywords)
        and len(page_text) >= 700
        and bool(re.search(
            r"responsibilities|qualifications|required skills|years of experience|apply now|"
            r"job description|what you.?ll do|what you.?ll need",
            page_text,
            re.I,
        ))
    )
    if detail_page_with_content and not js_placeholder:
        return False
    return js_placeholder or len(page_text) < min_text or link_count < min_links


def render_page_with_playwright(
    context: Any,
    url: str,
    cfg: dict,
) -> tuple[str | None, str, str]:
    """Render a page with headless Chromium and return (HTML, final URL, diagnostic)."""
    if context is None:
        return None, url, "Playwright browser context is unavailable"

    timeout_ms = max(8000, int(cfg.get("playwright_timeout_ms", 25000)))
    wait_ms = max(0, min(10000, int(cfg.get("playwright_render_wait_ms", 2500))))
    scroll_count = max(0, min(8, int(cfg.get("playwright_scroll_count", 3))))
    load_more_clicks = max(0, min(8, int(cfg.get("playwright_load_more_clicks", 3))))
    page = None
    try:
        page = context.new_page()
        page.set_default_navigation_timeout(timeout_ms)
        page.set_default_timeout(min(timeout_ms, 10000))
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        if response is not None:
            status = int(response.status)
            if status in (401, 403, 429):
                return None, page.url, f"Browser returned HTTP {status}; access is restricted or rate-limited"
            if status >= 400:
                return None, page.url, f"Browser returned HTTP {status}"

        # Give client-side job widgets a chance to fetch their data. Some sites never
        # reach network-idle because of analytics/long polling, so this wait is bounded.
        try:
            page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 4500))
        except Exception:
            pass
        if wait_ms:
            page.wait_for_timeout(wait_ms)

        # Support simple lazy-loading lists that append cards as the page is scrolled.
        for _ in range(scroll_count):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(250)

        # Click only clearly labelled, non-application expansion controls.
        more_pattern = re.compile(r"^(load more(?: jobs)?|show more(?: jobs)?|view more(?: jobs)?|more jobs)$", re.I)
        for _ in range(load_more_clicks):
            try:
                locator = page.get_by_role("button", name=more_pattern)
                if locator.count() == 0:
                    locator = page.get_by_role("link", name=more_pattern)
                if locator.count() == 0:
                    break
                control = locator.first
                if not control.is_visible() or not control.is_enabled():
                    break
                control.click(timeout=2500)
                page.wait_for_timeout(400)
            except Exception:
                break

        return page.content(), canonical_url(page.url), "rendered with Playwright Chromium"
    except Exception as exc:
        return None, url, f"Playwright rendering failed ({type(exc).__name__}: {exc})"
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass


def start_playwright(cfg: dict, user_agent: str) -> tuple[Any, Any, Any]:
    """Start one Chromium browser for this scan; return (driver, browser, context)."""
    if not bool(cfg.get("enable_playwright", True)):
        print("Playwright fallback is disabled in config.json.")
        return None, None, None
    if not PLAYWRIGHT_AVAILABLE or sync_playwright is None:
        print("WARNING: Playwright is not installed; continuing with static HTML only. Add playwright to requirements and install Chromium.")
        return None, None, None
    driver = None
    try:
        driver = sync_playwright().start()
        browser = driver.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1440, "height": 1000},
            locale="en-US",
        )
        print("Playwright fallback is ready (headless Chromium).")
        return driver, browser, context
    except Exception as exc:
        if driver is not None:
            try:
                driver.stop()
            except Exception:
                pass
        print(f"WARNING: Could not start Playwright Chromium ({type(exc).__name__}: {exc}). Static HTML fallback only.")
        return None, None, None


def is_listing_page_title(page_title: str) -> bool:
    """Recognize common careers/search results page titles to avoid saving them as jobs."""
    first_part = re.split(r"\s+[|–—-]\s+", clean(page_title), maxsplit=1)[0].strip().lower()
    return bool(re.match(
        r"^(?:careers?|jobs?|open positions|current openings|job search|search jobs|find jobs|"
        r"join our team|career opportunities|job opportunities|all positions|available roles|"
        r"open roles|search openings)(?:\b|$)",
        first_part,
        re.I,
    ))


def extract_job_record(
    company_name: str,
    source_url: str,
    page_title: str,
    page_text: str,
    clean_soup: BeautifulSoup,
    jobdata: dict[str, str] | None = None,
) -> dict[str, str] | None:
    """Build a job record and classify its status conservatively."""
    jobdata = jobdata or {}
    title = jobdata.get("job_title") or page_title
    body = jobdata.get("description") or page_text
    inferred = infer_fields(title, body)
    sections = extract_sections(clean_soup, page_text)
    if not title or len(title) > 300:
        return None
    if re.search(r"\b(careers? at|join our team|current openings|job opportunities|search jobs)\b", title, re.I):
        return None

    now = datetime.now(timezone.utc)
    valid_through = clean(jobdata.get("valid_through", ""))
    parsed_expiry = pd.to_datetime(valid_through, errors="coerce", utc=True)
    closure_pattern = r"(?:this position|this job|the job|the position) (?:is )?(?:closed|no longer available|has been filled)|no longer accepting applications|job posting has expired|position has been filled|vacancy is closed"
    if pd.notna(parsed_expiry) and parsed_expiry.to_pydatetime() < now:
        status = "Expired"
    elif re.search(closure_pattern, page_text, re.I):
        status = "Closed"
    elif re.search(r"apply now|apply for this job|submit application|start application|apply today", page_text, re.I):
        status = "Likely open"
    else:
        status = "Needs verification"

    candidate_url = clean(jobdata.get("url", ""))
    if candidate_url:
        candidate_url = urljoin(source_url, candidate_url)
    else:
        candidate_url = source_url

    posted = clean(jobdata.get("date_posted", ""))
    job_id = clean(jobdata.get("job_id", ""))
    identity = job_id or (candidate_url if jobdata.get("_specific_url") else f"{candidate_url}|{title}|{jobdata.get('location_mention', '')}")
    job_key = hashlib.sha256(f"{company_name.lower()}|{identity.lower()}".encode("utf-8")).hexdigest()
    timestamp = now.isoformat()
    return {
        "job_key": job_key,
        "job_id": job_id,
        "job_title": title,
        "company": jobdata.get("company") or company_name,
        "date_posted": posted,
        "valid_through": valid_through,
        "job_status": status,
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
        "source_url": candidate_url,
        "first_seen_utc": timestamp,
        "last_seen_utc": timestamp,
        "extracted_at_utc": timestamp,
        "extraction_note": "Rules-based extraction. 'Likely open' is a heuristic, not a guarantee; verify on the source page. Blank fields mean not confidently detected.",
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
    """Create the schema and upsert this scan without deleting other companies' rows."""
    engine = database_engine(database_url)
    quoted_columns = ", ".join(f'"{column}"' for column in FIELDS)
    update_columns = [c for c in FIELDS if c not in ("job_key", "first_seen_utc")]
    update_sql = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_columns)
    update_sql += ", \"first_seen_utc\" = COALESCE(NULLIF(job_postings.first_seen_utc, ''), EXCLUDED.\"first_seen_utc\")"
    stage = "job_postings_scan_stage_" + uuid.uuid4().hex
    try:
        with engine.begin() as con:
            con.execute(text("""
                CREATE TABLE IF NOT EXISTS job_postings (
                    job_key TEXT, job_id TEXT, job_title TEXT, company TEXT, date_posted TEXT,
                    valid_through TEXT, job_status TEXT, location_mention TEXT,
                    employment_type_mention TEXT, work_arrangement_mention TEXT,
                    experience_mentions TEXT, education_mentions TEXT, salary_mention TEXT,
                    responsibilities TEXT, requirements TEXT, preferred_qualifications TEXT,
                    benefits TEXT, description TEXT, source_url TEXT, first_seen_utc TEXT,
                    last_seen_utc TEXT, extracted_at_utc TEXT, extraction_note TEXT
                )
            """))
            for column in FIELDS:
                con.execute(text(f'ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS "{column}" TEXT'))
            con.execute(text("CREATE INDEX IF NOT EXISTS idx_job_company ON job_postings (company)"))
            con.execute(text("CREATE INDEX IF NOT EXISTS idx_job_title ON job_postings (job_title)"))
            con.execute(text("CREATE INDEX IF NOT EXISTS idx_job_status ON job_postings (job_status)"))
            # Partial uniqueness avoids collisions with legacy rows that have no job_key.
            con.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_job_postings_job_key_unique
                ON job_postings (job_key)
                WHERE job_key IS NOT NULL AND job_key <> ''
            """))
            if not df.empty:
                stage_df = df.reindex(columns=FIELDS).copy()
                stage_df = stage_df.drop_duplicates(subset=["job_key"], keep="last")
                stage_df.to_sql(stage, con, if_exists="replace", index=False, method="multi", chunksize=250)
                # Remove matching pre-upgrade rows that did not have job_key populated.
                con.execute(text(f"""
                    DELETE FROM job_postings AS target
                    USING {stage} AS incoming
                    WHERE (target.job_key IS NULL OR target.job_key = '')
                      AND target.company = incoming.company
                      AND target.job_title = incoming.job_title
                      AND target.source_url = incoming.source_url
                """))
                con.execute(text(f"""
                    INSERT INTO job_postings ({quoted_columns})
                    SELECT {quoted_columns} FROM {stage}
                    ON CONFLICT (job_key) WHERE job_key IS NOT NULL AND job_key <> ''
                    DO UPDATE SET {update_sql}
                """))
                con.execute(text(f"DROP TABLE IF EXISTS {stage}"))
    finally:
        engine.dispose()


def export_all_database_results(database_url: str) -> pd.DataFrame:
    """Read the cumulative table for CSV/Excel exports."""
    engine = database_engine(database_url)
    try:
        with engine.connect() as con:
            return pd.read_sql(text("SELECT * FROM job_postings ORDER BY company, job_title"), con).fillna("")
    finally:
        engine.dispose()



def main() -> None:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Missing config.json next to agent.py: {CONFIG_PATH}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"config.json is not valid JSON: {exc}")

    companies_to_scan = company_configs(cfg)
    ua = clean(cfg.get("user_agent")) or "RoleRadarBot/1.0"
    delay = max(1.0, float(cfg.get("request_delay_seconds", 2)))
    max_pages = max(1, int(cfg.get("max_pages_per_domain", cfg.get("max_pages_per_company", 80))))
    job_keywords = [clean(k).lower() for k in cfg.get("job_url_keywords", DEFAULT_JOB_URL_KEYWORDS) if clean(k)] or DEFAULT_JOB_URL_KEYWORDS
    exclude_keywords = [clean(k).lower() for k in cfg.get("exclude_url_keywords", DEFAULT_EXCLUDE_URL_KEYWORDS) if clean(k)] or DEFAULT_EXCLUDE_URL_KEYWORDS

    session = requests.Session()
    session.headers.update({"User-Agent": ua, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    robots_cache: dict[str, tuple[bool, urllib.robotparser.RobotFileParser | None, str]] = {}
    records: list[dict[str, str]] = []
    visited_total = 0
    blocked_total = 0
    rendered_total = 0
    browser_errors = 0

    playwright_driver, browser, browser_context = start_playwright(cfg, ua)
    try:
        for company_cfg in companies_to_scan:
            company_name = clean(company_cfg.get("name"))
            seed = clean(company_cfg.get("career_url"))
            if not seed.lower().startswith(("https://", "http://")):
                print(f"SKIP {company_name}: career_url must begin with http:// or https://: {seed}")
                continue

            configured_domains = company_cfg.get("allowed_domains", []) or []
            if isinstance(configured_domains, str):
                configured_domains = re.split(r"[,;\s]+", configured_domains)
            allowed = {clean(domain).lower().removeprefix("www.").strip("/") for domain in configured_domains if clean(domain)}
            allowed.add(normalized_host(seed))

            company_records_before = len(records)
            queue = deque([canonical_url(seed)])
            seen: set[str] = set()
            general_links_queued: set[str] = set()
            general_link_budget = max(0, int(cfg.get("general_link_discovery_pages", 10)))
            print(f"\n=== {company_name} ===")
            print(f"Start URL: {seed} | allowed domains: {', '.join(sorted(allowed))} | page limit: {max_pages}")

            while queue and len(seen) < max_pages:
                url = canonical_url(queue.popleft())
                if not url or url in seen:
                    continue
                parsed = urlparse(url)
                host = normalized_host(url)
                if parsed.scheme not in ("http", "https") or not host_is_allowed(host, allowed):
                    continue
                seen.add(url)
                allowed_by_robots, robots_message = robots_check(url, ua, session, robots_cache)
                if not allowed_by_robots:
                    blocked_total += 1
                    print(f"SKIP robots.txt: {url} | {robots_message}")
                    continue

                final_url = url
                page_html: str | None = None
                content_type = ""
                try:
                    response = session.get(url, timeout=25, allow_redirects=True)
                    final_url = canonical_url(response.url)
                    final_host = normalized_host(final_url)
                    if not host_is_allowed(final_host, allowed):
                        if is_known_ats_host(final_host):
                            allowed.add(final_host)
                            print(f"TRUSTED ATS REDIRECT: {url} -> {final_url} (robots.txt will still be checked)")
                        else:
                            print(f"SKIP redirect outside allowed_domains: {url} -> {final_url}")
                            continue
                    if final_url != url:
                        redirect_allowed, redirect_message = robots_check(final_url, ua, session, robots_cache)
                        if not redirect_allowed:
                            blocked_total += 1
                            print(f"SKIP redirected URL by robots/access policy: {final_url} | {redirect_message}")
                            continue
                    if response.status_code in (401, 403, 429):
                        print(f"HTTP {response.status_code}: {url} | not retrying restricted/rate-limited access with a browser")
                        continue
                    if response.status_code != 200:
                        print(f"HTTP {response.status_code}: {url}")
                        continue
                    content_type = response.headers.get("Content-Type", "").lower()
                    if "html" not in content_type and "xhtml" not in content_type:
                        print(f"SKIP non-HTML content ({content_type or 'unknown content type'}): {url}")
                        continue
                    page_html = response.text
                except requests.RequestException as exc:
                    print(f"REQUEST ERROR {url}: {type(exc).__name__}: {exc}")
                    # A transient requests failure may still be readable in the browser.
                    # robots.txt has already been checked, and redirected hosts remain restricted.
                    if browser_context is not None:
                        rendered_html, rendered_url, render_note = render_page_with_playwright(browser_context, url, cfg)
                        if rendered_html:
                            if not host_is_allowed(normalized_host(rendered_url), allowed):
                                if is_known_ats_host(normalized_host(rendered_url)):
                                    allowed.add(normalized_host(rendered_url))
                                    print(f"TRUSTED ATS BROWSER REDIRECT: {url} -> {rendered_url}")
                                else:
                                    print(f"SKIP browser redirect outside allowed_domains: {url} -> {rendered_url}")
                                    continue
                            if rendered_url != url:
                                redirect_allowed, redirect_message = robots_check(rendered_url, ua, session, robots_cache)
                                if not redirect_allowed:
                                    blocked_total += 1
                                    print(f"SKIP browser redirect by robots/access policy: {rendered_url} | {redirect_message}")
                                    continue
                            page_html, final_url = rendered_html, rendered_url
                            rendered_total += 1
                            print(f"PLAYWRIGHT: {url} | {render_note}")
                        else:
                            browser_errors += 1
                            print(f"PLAYWRIGHT FALLBACK FAILED: {url} | {render_note}")
                            continue
                    else:
                        continue

                if not page_html:
                    print(f"EMPTY HTML: {url}")
                    continue

                raw_soup, clean_soup, jobdata_list, page_title, page_text = parse_page_html(page_html)
                is_detail = is_job_detail_url(final_url, seed, job_keywords)
                has_job_signals = bool(re.search(
                    r"responsibilities|qualifications|required skills|years of experience|apply now|job description|jobposting|what you.?ll do|what you.?ll need|no longer accepting applications",
                    page_text, re.I,
                ))

                # Use Playwright only when static markup looks incomplete. This is particularly
                # useful for React/Next/Vue career portals, client-rendered job cards and lazy lists.
                if browser_context is not None and should_render_with_browser(
                    raw_soup, jobdata_list, page_title, page_text, final_url, seed, allowed, job_keywords, cfg
                ):
                    rendered_html, rendered_url, render_note = render_page_with_playwright(browser_context, final_url, cfg)
                    if rendered_html:
                        if not host_is_allowed(normalized_host(rendered_url), allowed):
                            if is_known_ats_host(normalized_host(rendered_url)):
                                allowed.add(normalized_host(rendered_url))
                                print(f"TRUSTED ATS BROWSER REDIRECT: {final_url} -> {rendered_url}")
                            else:
                                print(f"SKIP browser redirect outside allowed_domains: {final_url} -> {rendered_url}")
                                continue
                        if rendered_url != final_url:
                            redirect_allowed, redirect_message = robots_check(rendered_url, ua, session, robots_cache)
                            if not redirect_allowed:
                                blocked_total += 1
                                print(f"SKIP browser redirect by robots/access policy: {rendered_url} | {redirect_message}")
                                continue
                        page_html, final_url = rendered_html, rendered_url
                        raw_soup, clean_soup, jobdata_list, page_title, page_text = parse_page_html(page_html)
                        is_detail = is_job_detail_url(final_url, seed, job_keywords)
                        has_job_signals = bool(re.search(
                            r"responsibilities|qualifications|required skills|years of experience|apply now|job description|jobposting|what you.?ll do|what you.?ll need|no longer accepting applications",
                            page_text, re.I,
                        ))
                        rendered_total += 1
                        print(f"PLAYWRIGHT: {final_url} | {render_note} | rendered text chars={len(page_text)}")
                    else:
                        browser_errors += 1
                        print(f"PLAYWRIGHT FALLBACK FAILED: {final_url} | {render_note}")

                page_jobs_before = len(records)
                # Extract cards before classifying the current page as a job detail page.
                # URLs like /careers/jobs/ or /positions/ can be listings, not one job.
                cards: list[dict[str, str]] = []
                if not jobdata_list:
                    cards = extract_listing_cards(raw_soup, final_url, allowed, job_keywords)

                if jobdata_list:
                    for jobdata in jobdata_list:
                        item_url = clean(jobdata.get("url", ""))
                        record_url = urljoin(final_url, item_url) if item_url else final_url
                        if not host_is_allowed(normalized_host(record_url), allowed):
                            if is_known_ats_host(normalized_host(record_url)):
                                allowed.add(normalized_host(record_url))
                            else:
                                print(f"SKIP structured job URL outside allowed_domains: {record_url}")
                                continue
                        jobdata = {**jobdata, "url": record_url, "_specific_url": bool(item_url)}
                        record = extract_job_record(company_name, record_url, page_title, page_text, clean_soup, jobdata)
                        if record:
                            records.append(record)
                            print(f"JOB FOUND [{record['job_status']}]: {record['job_title']} | {record['source_url']}")
                elif is_detail and has_job_signals and len(page_text) > 400 and not is_listing_page_title(page_title):
                    record = extract_job_record(company_name, final_url, page_title, page_text, clean_soup, {"url": final_url, "_specific_url": True})
                    if record:
                        records.append(record)
                        print(f"JOB FOUND [{record['job_status']}]: {record['job_title']} | {final_url}")

                # Save listing-card title/link pairs as discovery records, then crawl their
                # URLs for full descriptions and requirements. URL-based keys merge both.
                card_records_added = 0
                for card_data in cards:
                    record_url = clean(card_data.get("url", ""))
                    record_host = normalized_host(record_url)
                    if is_known_ats_host(record_host) and not host_is_allowed(record_host, allowed):
                        allowed.add(record_host)
                        print(f"TRUSTED ATS LINK: {record_url} (discovered on {final_url})")
                    record = extract_job_record(
                        company_name, record_url, card_data.get("job_title", ""),
                        card_data.get("description", ""), clean_soup, card_data,
                    )
                    if record:
                        records.append(record)
                        card_records_added += 1
                        print(f"JOB CARD FOUND [{record['job_status']}]: {record['job_title']} | {record['source_url']}")
                if cards:
                    print(f"LISTING CARD DIAGNOSTIC: candidates={len(cards)}, records_added={card_records_added}, page={final_url}")

                links_added = 0
                job_targets: list[str] = []
                general_targets: list[str] = []
                for anchor in raw_soup.find_all("a", href=True):
                    href = clean(anchor.get("href"))
                    if not href or href.startswith(("mailto:", "tel:", "javascript:", "data:")):
                        continue
                    target = canonical_url(urljoin(final_url, href))
                    target_parts = urlparse(target)
                    target_host = normalized_host(target)
                    if target_parts.scheme not in ("http", "https"):
                        continue
                    path_query = f"{target_parts.path}?{target_parts.query}".lower()
                    if any(word in path_query for word in exclude_keywords):
                        continue
                    if target in seen or target in queue:
                        continue
                    looks_job = anchor_looks_job_related(anchor, target, job_keywords)
                    if not host_is_allowed(target_host, allowed):
                        if is_known_ats_host(target_host) and looks_job:
                            allowed.add(target_host)
                            print(f"TRUSTED ATS LINK: {target} (discovered on {final_url})")
                        else:
                            if looks_job:
                                print(f"EXTERNAL JOB LINK NOT FOLLOWED: {target} | add hostname '{target_host}' to this company’s allowed_domains if this is its genuine ATS")
                            continue
                    if looks_job:
                        job_targets.append(target)
                    elif target not in general_links_queued:
                        general_targets.append(target)

                # Always place job-specific links at the front of the queue so navigation
                # links don't consume the page limit before actual roles are discovered.
                for target in dict.fromkeys(job_targets):
                    if target not in seen and target not in queue:
                        queue.appendleft(target)
                        links_added += 1
                if general_link_budget > len(general_links_queued):
                    remaining_general = general_link_budget - len(general_links_queued)
                    for target in list(dict.fromkeys(general_targets))[:remaining_general]:
                        if target not in seen and target not in queue:
                            queue.append(target)
                            general_links_queued.add(target)
                            links_added += 1

                if not jobdata_list and not cards and (not is_detail or is_listing_page_title(page_title)):
                    print(f"NO LISTING CARDS DETECTED: DOM has no structured job data or recognizable job cards | {final_url}")

                visited_total += 1
                print(
                    f"Visited {len(seen)}/{max_pages}: {final_url} | "
                    f"jobs found this company: {len(records) - company_records_before} | "
                    f"jobs found on page: {len(records) - page_jobs_before} | links queued: {links_added}"
                )
                time.sleep(delay)

            if not seen:
                print(f"WARNING: No permitted in-domain URLs were visited for {company_name}.")
            print(
                f"Company summary: visited={len(seen)}, robots/access skips={blocked_total}, "
                f"jobs extracted={len(records) - company_records_before}"
            )
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if playwright_driver is not None:
            try:
                playwright_driver.stop()
            except Exception:
                pass

    df = pd.DataFrame(records, columns=FIELDS)
    if not df.empty:
        df = df.drop_duplicates(subset=["job_key"], keep="last")

    within_days = os.environ.get("SCAN_POSTED_WITHIN_DAYS", "").strip()
    if within_days and not df.empty:
        try:
            days = max(1, int(within_days))
        except ValueError:
            raise SystemExit("SCAN_POSTED_WITHIN_DAYS must be a positive integer, such as 30.")
        before_filter = len(df)
        df, excluded_undated, excluded_outside = filter_posted_within_days(df, days)
        print(f"Date filter: last {days} days | kept={len(df)} | removed={before_filter - len(df)} (undated={excluded_undated}, outside window/future={excluded_outside})")

    database_env = clean(cfg.get("database_url_env", "DATABASE_URL")) or "DATABASE_URL"
    database_url = os.environ.get(database_env, "").strip()
    if not database_url:
        raise SystemExit(f"PostgreSQL connection is not configured. Set {database_env} in Render → Environment (or Streamlit secrets).")
    try:
        save_records_to_postgres(df, database_url)
        export_df = export_all_database_results(database_url)
    except Exception as exc:
        raise SystemExit(f"PostgreSQL save/read failed ({type(exc).__name__}: {exc}). Check DATABASE_URL, the psycopg driver, and database permissions.")

    csv_path = cfg.get("export_csv", "job_requirements.csv")
    excel_path = cfg.get("export_excel", "job_requirements.xlsx")
    export_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    try:
        export_df.to_excel(excel_path, index=False)
    except Exception as exc:
        print(f"WARNING: Could not create Excel export ({type(exc).__name__}: {exc}). CSV was saved.")

    print(
        f"\nDone. Extracted {len(df)} candidate job records in this scan; visited {visited_total} HTML pages; "
        f"Playwright-rendered pages={rendered_total}; browser fallback errors={browser_errors}; robots/access skips={blocked_total}."
    )
    print(f"Created cumulative exports: {csv_path}, {excel_path}; PostgreSQL table: job_postings")
    if not records:
        print("No job pages were extracted. Check robots.txt messages, the career URL, allowed_domains, the scan logs and whether job cards are present in the rendered DOM.")
    print("Status note: 'Likely open' is inferred from page signals; verify each job on its official source page. A missing result in a crawl is not automatically treated as closed.")


if __name__ == "__main__":
    main()
