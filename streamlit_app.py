from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.json"
CSV = ROOT / "job_requirements.csv"
XLSX = ROOT / "job_requirements.xlsx"
AGENT = ROOT / "agent.py"

st.set_page_config(
    page_title="TalentSignal | Job Intelligence",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- Styling ----------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');
    :root { --ink:#172033; --muted:#667085; --line:#e7ebf2; --blue:#315efb; --teal:#17a89b; }
    html, body, [class*="css"] { font-family:'DM Sans',sans-serif; }
    .stApp { background: #f5f7fb; }
    [data-testid="stHeader"] { background: rgba(245,247,251,.92); }
    .block-container { padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1500px; }
    [data-testid="stSidebar"] { background:#111a2e; border-right:1px solid #202b43; }
    [data-testid="stSidebar"] * { color:#edf2ff; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color:#bdc7dd; }
    .brand { font-family:'Manrope',sans-serif; font-size:1.05rem; font-weight:800; letter-spacing:-.03em; color:white; padding:.4rem 0 1.4rem; }
    .brand span { color:#73e0d3; }
    .eyebrow { color:#315efb; font-size:.72rem; text-transform:uppercase; letter-spacing:.14em; font-weight:800; margin-bottom:.4rem; }
    .hero { background:linear-gradient(120deg,#17233f 0%,#233c71 68%,#236c7b 100%); padding:1.8rem 2rem; border-radius:22px; color:white; margin:.25rem 0 1.35rem; box-shadow:0 12px 30px rgba(29,54,100,.12); }
    .hero h1 { color:white; font-family:'Manrope',sans-serif; font-weight:800; font-size:2.05rem; letter-spacing:-.045em; line-height:1.15; margin:0 0 .55rem; }
    .hero p { color:#d6e1f7; font-size:.98rem; margin:0; max-width:800px; }
    .hero-pill { display:inline-block; margin-top:1rem; padding:.35rem .7rem; border:1px solid rgba(255,255,255,.24); border-radius:999px; color:#e7fffb; font-size:.75rem; background:rgba(255,255,255,.08); }
    .section-head { font-family:'Manrope',sans-serif; font-size:1.08rem; font-weight:800; letter-spacing:-.02em; color:#172033; margin:.2rem 0 .75rem; }
    .subtle { color:#667085; font-size:.88rem; }
    .metric-card { background:white; border:1px solid #e7ebf2; border-radius:16px; padding:1rem 1.15rem; min-height:112px; }
    .metric-label { color:#667085; font-size:.78rem; font-weight:600; margin-bottom:.55rem; }
    .metric-value { color:#172033; font-family:'Manrope',sans-serif; font-size:1.85rem; font-weight:800; line-height:1.05; letter-spacing:-.04em; }
    .metric-note { color:#8791a5; font-size:.74rem; margin-top:.45rem; }
    .status-dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:#18b981; margin-right:7px; }
    .company-card { background:white; border:1px solid #e7ebf2; border-radius:13px; padding:.85rem 1rem; margin-bottom:.55rem; }
    .company-name { color:#172033; font-weight:700; font-size:.92rem; }
    .company-url { color:#667085; font-size:.78rem; overflow-wrap:anywhere; }
    div.stButton > button, div.stFormSubmitButton > button { border-radius:10px; font-weight:700; min-height:2.55rem; }
    div.stButton > button[kind="primary"], div.stFormSubmitButton > button[kind="primary"] { background:#315efb; border:1px solid #315efb; }
    [data-testid="stMetric"] { background:white; border:1px solid #e7ebf2; padding:1rem; border-radius:14px; }
    [data-testid="stDataFrame"] { border:1px solid #e7ebf2; border-radius:12px; overflow:hidden; }
    .small-note { color:#7a8498; font-size:.76rem; }
    hr { border-color:#e7ebf2; }
    </style>
    """,
    unsafe_allow_html=True,
)


def get_database_url() -> str:
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        try:
            value = str(st.secrets.get("DATABASE_URL", "")).strip()
        except Exception:
            value = ""
    return value


def load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {"companies": [], "max_pages_per_domain": 80, "request_delay_seconds": 2.0}


def normalize_url(value: str) -> str:
    value = value.strip()
    if value and not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    return value


def read_results() -> pd.DataFrame:
    if not CSV.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(CSV).fillna("")
    except Exception:
        return pd.DataFrame()


def metric_card(label: str, value: str, note: str) -> None:
    st.markdown(
        f'<div class="metric-card"><div class="metric-label">{label}</div>'
        f'<div class="metric-value">{value}</div><div class="metric-note">{note}</div></div>',
        unsafe_allow_html=True,
    )


if "companies" not in st.session_state:
    old_companies = load_config().get("companies", [])
    st.session_state.companies = [
        {"name": c.get("name", ""), "career_url": c.get("career_url", "")}
        for c in old_companies
        if c.get("career_url") and "example.com" not in c.get("career_url", "")
    ]
if "scan_log" not in st.session_state:
    st.session_state.scan_log = []
if "last_scan_status" not in st.session_state:
    st.session_state.last_scan_status = "Not run yet"

# ---------- Sidebar ----------
with st.sidebar:
    st.markdown('<div class="brand">Talent<span>Signal</span> <span style="color:#9eabc5;font-weight:500">/ JOB INTELLIGENCE</span></div>', unsafe_allow_html=True)
    st.markdown("### Workspace")
    st.caption("Career-page research workspace")
    page = st.radio(
        "Navigate",
        ["Overview", "Companies", "Extracted jobs", "Scan activity"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    db_url = get_database_url()
    if db_url:
        st.markdown('<span class="status-dot"></span> **PostgreSQL configured**', unsafe_allow_html=True)
        st.caption("Neon connection variable detected")
    else:
        st.markdown("🔴 **Database not configured**")
        st.caption("Add DATABASE_URL in Render → Environment.")
    st.markdown("---")
    st.caption("Rules-based extraction · No paid AI APIs")
    st.caption("Crawls only configured domains and respects robots.txt.")

# ---------- Data and page header ----------
data = read_results()
job_count = len(data)
company_count = data["company"].nunique() if "company" in data.columns and not data.empty else 0
queued_count = len(st.session_state.companies)

st.markdown(
    '<div class="hero"><div class="eyebrow" style="color:#8ce7dc">JOB REQUIREMENTS EXTRACTION</div>'
    '<h1>Turn career pages into<br>structured hiring intelligence.</h1>'
    '<p>Collect job listings from company career sites, extract consistent requirements, and review the results in one workspace.</p>'
    '<span class="hero-pill">● Python crawler &nbsp; · &nbsp; PostgreSQL storage &nbsp; · &nbsp; CSV / Excel exports</span></div>',
    unsafe_allow_html=True,
)

# ---------- Overview ----------
if page == "Overview":
    st.markdown('<div class="section-head">Workspace overview</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4, gap="medium")
    with c1: metric_card("JOBS EXTRACTED", f"{job_count:,}", "Rows in the latest local export")
    with c2: metric_card("COMPANIES COVERED", f"{company_count:,}", "Companies represented in results")
    with c3: metric_card("SITES IN QUEUE", f"{queued_count:,}", "Career pages ready to scan")
    with c4: metric_card("DATABASE", "Connected" if db_url else "Setup needed", "Neon PostgreSQL" if db_url else "Set DATABASE_URL in Render")

    st.markdown("<br>", unsafe_allow_html=True)
    left, right = st.columns([1.25, .75], gap="large")
    with left:
        st.markdown('<div class="section-head">Get started</div>', unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("**01 · Add career pages**")
            st.caption("Enter the official careers or jobs URL for each company.")
            if st.button("Manage companies →", use_container_width=True):
                st.session_state._nav_to = "Companies"
                st.rerun()
            st.markdown("---")
            st.markdown("**02 · Run a controlled scan**")
            st.caption("Set a page limit and request delay before starting the crawler.")
            if st.button("Open scan controls →", type="primary", use_container_width=True):
                st.session_state._nav_to = "Companies"
                st.rerun()
    with right:
        st.markdown('<div class="section-head">Latest workspace status</div>', unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown(f"**Last scan:** {st.session_state.last_scan_status}")
            st.markdown(f"**Career pages queued:** {queued_count}")
            st.markdown(f"**Export available:** {'Yes' if CSV.exists() else 'Not yet'}")
            st.markdown("---")
            st.markdown("<span class='small-note'>Tip: start with one careers URL to validate extraction before adding more companies.</span>", unsafe_allow_html=True)

    if not data.empty:
        st.markdown('<div class="section-head">Latest extracted records</div>', unsafe_allow_html=True)
        preferred = [c for c in ["company", "job_title", "location_mention", "employment_type_mention", "source_url"] if c in data.columns]
        st.dataframe(data[preferred].head(8), use_container_width=True, hide_index=True)
        if st.button("View all extracted jobs →"):
            st.session_state._nav_to = "Extracted jobs"
            st.rerun()

# ---------- Companies and scan ----------
elif page == "Companies":
    st.markdown('<div class="section-head">Company sources</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtle">Add official career pages, maintain your scan queue, and control crawl depth.</div>', unsafe_allow_html=True)
    add_col, queue_col = st.columns([.9, 1.1], gap="large")
    with add_col:
        with st.container(border=True):
            st.markdown("**Add a company**")
            with st.form("add_company", clear_on_submit=True):
                company_name = st.text_input("Company name", placeholder="e.g. Acme Insurance")
                career_url = st.text_input("Career page URL", placeholder="https://company.com/careers")
                add = st.form_submit_button("＋ Add to queue", type="primary", use_container_width=True)
            if add:
                candidate = normalize_url(career_url)
                parsed = urlparse(candidate)
                if not candidate:
                    st.error("Enter a career page URL first.")
                elif parsed.scheme not in ("http", "https") or not parsed.hostname or "." not in parsed.hostname:
                    st.error("Enter a valid URL, e.g. https://company.com/careers")
                elif any(c["career_url"].rstrip("/") == candidate.rstrip("/") for c in st.session_state.companies):
                    st.warning("That URL is already in your queue.")
                else:
                    host = parsed.hostname.removeprefix("www.")
                    st.session_state.companies.append({
                        "name": company_name.strip() or host.split(".")[0].replace("-", " ").title(),
                        "career_url": candidate,
                    })
                    st.success("Company added to the scan queue.")
                    st.rerun()
            st.markdown("---")
            st.markdown("**Scan settings**")
            max_pages = st.slider("Maximum pages per company", min_value=10, max_value=300, value=80, step=10)
            delay = st.slider("Delay between requests", min_value=1.0, max_value=10.0, value=2.0, step=0.5, help="A higher delay is gentler on the source website.")
            st.caption("The crawler stays on the host you enter and follows robots.txt.")
    with queue_col:
        with st.container(border=True):
            st.markdown(f"**Scan queue** &nbsp; <span style='color:#667085;font-weight:500'>({len(st.session_state.companies)} sources)</span>", unsafe_allow_html=True)
            if st.session_state.companies:
                for i, company in enumerate(list(st.session_state.companies)):
                    st.markdown(
                        f'<div class="company-card"><div class="company-name">{company["name"]}</div>'
                        f'<div class="company-url">{company["career_url"]}</div></div>',
                        unsafe_allow_html=True,
                    )
                    _, remove_col = st.columns([4, 1])
                    if remove_col.button("Remove", key=f"remove_{i}", use_container_width=True):
                        st.session_state.companies.pop(i)
                        st.rerun()
            else:
                st.info("Your queue is empty. Add a career page to begin.")
            st.markdown("---")
            if not db_url:
                st.warning("Add DATABASE_URL in Render → Environment before scanning.")
            if st.button("▶  Run scan", type="primary", disabled=(not st.session_state.companies or not db_url or not AGENT.exists()), use_container_width=True):
                cfg = load_config()
                cfg["companies"] = []
                for company in st.session_state.companies:
                    host = urlparse(company["career_url"]).hostname or ""
                    cfg["companies"].append({"name": company["name"], "career_url": company["career_url"], "allowed_domains": [host.removeprefix("www.")]})
                cfg["max_pages_per_domain"] = int(max_pages)
                cfg["request_delay_seconds"] = float(delay)
                CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
                for file_path in (CSV, XLSX):
                    try: file_path.unlink()
                    except FileNotFoundError: pass
                st.session_state.scan_log = []
                st.session_state.last_scan_status = "Running"
                st.session_state.scan_requested = True
                st.rerun()

# Run requested scan after rerun so progress UI is displayed
if st.session_state.get("scan_requested"):
    st.session_state.scan_requested = False
    st.markdown('<div class="section-head">Scan activity</div>', unsafe_allow_html=True)
    progress = st.progress(0, text="Starting crawler…")
    log_box = st.empty()
    lines: list[str] = []
    try:
        env = os.environ.copy()
        if db_url:
            env["DATABASE_URL"] = db_url
        proc = subprocess.Popen(
            [sys.executable, "-u", str(AGENT)], cwd=str(ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        start = time.time()
        while True:
            line = proc.stdout.readline() if proc.stdout else ""
            if line:
                lines.append(line.rstrip())
                st.session_state.scan_log = lines[-300:]
                log_box.code("\n".join(lines[-80:]), language="text")
                progress.progress(min(95, max(5, int((time.time() - start) / 18 * 5))), text="Scanning career pages…")
            elif proc.poll() is not None:
                break
            else:
                time.sleep(.1)
            if time.time() - start > 1800:
                proc.kill()
                lines.append("Scan stopped after 30 minutes. Try fewer pages or companies.")
                break
        rc = proc.wait()
        progress.progress(100, text="Scan finished")
        if rc == 0:
            st.session_state.last_scan_status = "Completed"
            st.success("Scan completed. Open Extracted jobs to review results.")
        else:
            st.session_state.last_scan_status = "Failed — review logs"
            st.error("The crawler exited with an error. Review the log output below.")
        st.session_state.scan_log = lines[-300:]
        if lines:
            log_box.code("\n".join(lines[-100:]), language="text")
    except Exception as exc:
        st.session_state.last_scan_status = "Failed to start"
        st.error(f"Could not start the crawler: {exc}")

# ---------- Results ----------
elif page == "Extracted jobs":
    st.markdown('<div class="section-head">Extracted job requirements</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtle">Search, filter, inspect, and export the latest extraction results.</div>', unsafe_allow_html=True)
    data = read_results()
    if data.empty:
        st.info("No local export is available yet. Add a company and run a scan first. If the scan completed but this view is empty after a restart, the export file may not persist on the hosting instance.")
    else:
        a, b, c = st.columns(3)
        a.metric("Jobs", len(data))
        b.metric("Companies", data["company"].nunique() if "company" in data else 0)
        c.metric("Extracted fields", len(data.columns))
        search = st.text_input("Search all fields", placeholder="Try a title, company, location, or skill…")
        company_options = sorted(data["company"].astype(str).replace("", "Unknown").unique()) if "company" in data else []
        selected_companies = st.multiselect("Filter by company", company_options, placeholder="All companies")
        shown = data.copy()
        if search:
            mask = shown.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False, regex=False)).any(axis=1)
            shown = shown[mask]
        if selected_companies and "company" in shown:
            shown = shown[shown["company"].replace("", "Unknown").isin(selected_companies)]
        st.caption(f"Showing {len(shown):,} of {len(data):,} records")
        st.dataframe(shown, use_container_width=True, hide_index=True, height=520)
        dl1, dl2 = st.columns(2)
        dl1.download_button("⬇ Download CSV", data=shown.to_csv(index=False).encode("utf-8-sig"), file_name="job_requirements.csv", mime="text/csv", use_container_width=True)
        if XLSX.exists():
            try:
                dl2.download_button("⬇ Download Excel", XLSX.read_bytes(), file_name="job_requirements.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            except Exception:
                dl2.download_button("⬇ Download filtered CSV", data=shown.to_csv(index=False).encode("utf-8-sig"), file_name="job_requirements_filtered.csv", mime="text/csv", use_container_width=True)
        else:
            dl2.download_button("⬇ Download filtered CSV", data=shown.to_csv(index=False).encode("utf-8-sig"), file_name="job_requirements_filtered.csv", mime="text/csv", use_container_width=True)
        st.caption("Extraction is heuristic. Review each source URL and verify important requirements before using them for decisions.")

# ---------- Activity ----------
elif page == "Scan activity":
    st.markdown('<div class="section-head">Scan activity & diagnostics</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtle">Review the latest crawler status and diagnostic output.</div>', unsafe_allow_html=True)
    a, b = st.columns(2)
    a.metric("Last scan", st.session_state.last_scan_status)
    b.metric("Log lines retained", len(st.session_state.scan_log))
    if st.session_state.scan_log:
        st.code("\n".join(st.session_state.scan_log), language="text")
        st.download_button("Download scan log", "\n".join(st.session_state.scan_log), file_name="scan_log.txt", mime="text/plain")
    else:
        st.info("No scan log in this session yet. Run a scan from Companies to populate activity.")
    with st.expander("How extraction works and known limitations"):
        st.markdown(
            "- Crawls accessible pages on the configured company host.\n"
            "- Checks robots.txt and uses a configurable delay between requests.\n"
            "- Extracts common job metadata and requirements using rules and page structure.\n"
            "- Uses PostgreSQL for persistent database storage; CSV/Excel files on Render may not persist across restarts.\n"
            "- Does not bypass logins, CAPTCHAs, paywalls, or other access controls.\n"
            "- Some JavaScript-heavy career portals may require a dedicated parser.\n"
            "- Restrict access to this dashboard if you deploy it publicly, since users can trigger scans."
        )

# Navigation click bridge for overview shortcuts
if st.session_state.get("_nav_to"):
    target = st.session_state.pop("_nav_to")
    # Streamlit radio state is updated on the next run by assigning its widget key only if keyed.
    # Avoid changing the current radio widget programmatically; the sidebar remains the navigation source.
    st.info(f"Use the sidebar to open **{target}**.")
