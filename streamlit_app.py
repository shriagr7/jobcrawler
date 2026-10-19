from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text as sql_text

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.json"
CSV = ROOT / "job_requirements.csv"
XLSX = ROOT / "job_requirements.xlsx"
AGENT = ROOT / "agent.py"

st.set_page_config(page_title="RoleRadar | Hiring Intelligence", page_icon="🎯", layout="wide", initial_sidebar_state="expanded")

# ---------- Styling ----------
st.markdown(r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
:root { --ink:#17233b; --muted:#6b7890; --line:#e5eaf2; --blue:#315efb; --teal:#18b6a4; }
html, body, [class*="css"] { font-family:'DM Sans',sans-serif; }
.stApp { background:#f6f8fc; }
[data-testid="stHeader"] { background:rgba(246,248,252,.9); }
.block-container { max-width:1480px; padding-top:1.4rem; padding-bottom:3rem; }
[data-testid="stSidebar"] { background:#111b30; border-right:1px solid #26324b; }
[data-testid="stSidebar"] * { color:#edf3ff; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color:#b9c5dc; }
.brand-wrap { display:flex; align-items:center; gap:11px; padding:.4rem 0 1.4rem; }
.brand-mark { width:44px;height:44px;border-radius:14px;background:linear-gradient(140deg,#5b78ff,#20c6ad);display:flex;align-items:center;justify-content:center;color:#fff;font-size:23px;font-weight:800;box-shadow:0 8px 22px #172d5b70; }
.brand-name { font:800 1.2rem 'Manrope',sans-serif;letter-spacing:-.04em;color:white; }
.brand-tag { font-size:.68rem;color:#9eacc7;letter-spacing:.12em;text-transform:uppercase;margin-top:2px; }
.hero { background:linear-gradient(115deg,#172442 0%,#243f78 63%,#167b7d 100%); padding:1.7rem 2rem; border-radius:22px; color:white; margin:.2rem 0 1.25rem; box-shadow:0 14px 32px #213d6d18; }
.hero-kicker { font-size:.72rem;letter-spacing:.15em;text-transform:uppercase;font-weight:800;color:#91f0df;margin-bottom:.55rem; }
.hero h1 { color:white;font:800 clamp(1.7rem,3vw,2.35rem) 'Manrope',sans-serif;letter-spacing:-.055em;line-height:1.12;margin:0 0 .55rem; }
.hero p { color:#d9e5fa;font-size:.96rem;margin:0;max-width:780px; }
.hero-pills { display:flex;flex-wrap:wrap;gap:8px;margin-top:1rem; }
.hero-pill { border:1px solid #ffffff3a;background:#ffffff12;border-radius:999px;padding:.35rem .7rem;font-size:.75rem;color:#f0fffd; }
.section-title { font:800 1.12rem 'Manrope',sans-serif;color:#17233b;letter-spacing:-.025em;margin:.3rem 0 .2rem; }
.section-subtitle { color:#718098;font-size:.88rem;margin-bottom:.8rem; }
.metric-card { background:white;border:1px solid var(--line);border-radius:16px;padding:1rem 1.1rem;min-height:108px; }
.metric-label { color:#718098;font-size:.74rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;margin-bottom:.5rem; }
.metric-value { color:#17233b;font:800 1.8rem 'Manrope',sans-serif;letter-spacing:-.05em;line-height:1.05; }
.metric-note { color:#8a95a8;font-size:.74rem;margin-top:.4rem; }
.info-card { background:white;border:1px solid var(--line);border-radius:16px;padding:1rem 1.1rem; }
.small-muted { color:#718098;font-size:.82rem; }
div.stButton > button, div.stFormSubmitButton > button { border-radius:11px;font-weight:700;min-height:2.65rem; }
div.stButton > button[kind="primary"], div.stFormSubmitButton > button[kind="primary"] { background:#315efb;border:1px solid #315efb; }
[data-testid="stDataFrame"] { border:1px solid var(--line);border-radius:12px;overflow:hidden; }
hr { border-color:#e5eaf2; }
</style>
""", unsafe_allow_html=True)


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
        return {"companies": [], "max_pages_per_domain": 80, "request_delay_seconds": 2.0,
                "job_url_keywords": ["job", "career", "opening", "position", "requisition", "vacancy"]}


def save_config(cfg: dict) -> None:
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def normalize_url(value: str) -> str:
    value = value.strip()
    if value and not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    return value


def get_local_results() -> pd.DataFrame:
    if CSV.exists():
        try:
            return pd.read_csv(CSV).fillna("")
        except Exception:
            pass
    return pd.DataFrame()


def get_db_results() -> pd.DataFrame:
    url = get_database_url()
    if not url:
        return pd.DataFrame()
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and "+" not in url.split(":", 1)[0]:
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    try:
        engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
        try:
            with engine.connect() as conn:
                return pd.read_sql(sql_text("SELECT * FROM job_postings"), conn).fillna("")
        finally:
            engine.dispose()
    except Exception:
        return pd.DataFrame()


def get_results() -> pd.DataFrame:
    db_data = get_db_results()
    return db_data if not db_data.empty else get_local_results()


def metric_card(label: str, value: str, note: str) -> None:
    st.markdown(f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div><div class="metric-note">{note}</div></div>', unsafe_allow_html=True)


def start_scan(mode: str, max_pages: int, delay: float) -> None:
    cfg = load_config()
    companies = st.session_state.get("companies", [])
    if not companies:
        st.error("Add at least one company before running a scan.")
        return
    if not get_database_url():
        st.error("DATABASE_URL is not configured. Add it in Render → Environment.")
        return
    if not AGENT.exists():
        st.error("agent.py was not found beside streamlit_app.py.")
        return
    cfg["companies"] = []
    for company in companies:
        host = urlparse(company["career_url"]).hostname or ""
        cfg["companies"].append({"name": company["name"], "career_url": company["career_url"], "allowed_domains": [host.removeprefix("www.")]})
    cfg["max_pages_per_domain"] = int(max_pages)
    cfg["request_delay_seconds"] = float(delay)
    save_config(cfg)
    st.session_state.scan_mode = mode
    st.session_state.scan_requested = True
    st.session_state.last_scan_status = "Queued"


# ---------- State ----------
if "companies" not in st.session_state:
    old = load_config().get("companies", [])
    st.session_state.companies = [{"name": c.get("name", ""), "career_url": c.get("career_url", "")} for c in old if c.get("career_url") and "example.com" not in c.get("career_url", "")]
if "scan_log" not in st.session_state:
    st.session_state.scan_log = []
if "last_scan_status" not in st.session_state:
    st.session_state.last_scan_status = "Not run yet"

# ---------- Sidebar brand/navigation ----------
with st.sidebar:
    st.markdown('<div class="brand-wrap"><div class="brand-mark">R</div><div><div class="brand-name">RoleRadar</div><div class="brand-tag">Hiring intelligence</div></div></div>', unsafe_allow_html=True)
    page = st.radio("Workspace", ["Dashboard", "Add Company", "Run Scan", "Scan Activity"], label_visibility="visible")
    st.divider()
    if get_database_url():
        st.success("Neon PostgreSQL configured")
    else:
        st.warning("Database connection missing")
        st.caption("Set DATABASE_URL in Render → Environment.")
    st.caption("Python crawler · Structured job requirements")
    st.caption("Robots.txt-aware crawling; no paid AI APIs.")

# ---------- Header ----------
st.markdown('''<div class="hero"><div class="hero-kicker">Career-page intelligence workspace</div><h1>Meet your next hiring signal.</h1><p>Scan company career pages, turn job descriptions into structured requirements, and explore hiring demand role by role.</p><div class="hero-pills"><span class="hero-pill">✦ Role-wise insights</span><span class="hero-pill">↗ Controlled scans</span><span class="hero-pill">▤ PostgreSQL-backed results</span></div></div>''', unsafe_allow_html=True)

# ---------- Dashboard ----------
data = get_results()
company_count = data["company"].nunique() if not data.empty and "company" in data.columns else 0
job_count = len(data)

if page == "Dashboard":
    st.markdown('<div class="section-title">Hiring dashboard</div><div class="section-subtitle">A quick view of extracted roles and company coverage.</div>', unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4, gap="medium")
    with m1: metric_card("Extracted job records", f"{job_count:,}", "Current records available")
    with m2: metric_card("Companies covered", f"{company_count:,}", "Companies represented in jobs")
    with m3: metric_card("Companies in queue", f"{len(st.session_state.companies):,}", "Career pages ready to scan")
    with m4: metric_card("Last scan", st.session_state.last_scan_status, "Latest run in this session")

    left, right = st.columns([1.35, 1], gap="large")
    with left:
        st.markdown('<div class="section-title">Job role-wise breakdown</div><div class="section-subtitle">Most frequently detected job titles.</div>', unsafe_allow_html=True)
        if not data.empty and "job_title" in data.columns:
            role_counts = data["job_title"].astype(str).str.strip().replace("", "Untitled role").value_counts().head(12)
            if not role_counts.empty:
                chart_df = role_counts.rename_axis("Job role").reset_index(name="Jobs")
                st.bar_chart(chart_df.set_index("Job role"), horizontal=True, use_container_width=True)
                st.dataframe(chart_df, use_container_width=True, hide_index=True, height=280)
            else:
                st.info("No job titles found yet. Run a scan to populate role insights.")
        else:
            st.info("Your role-wise dashboard will appear after the first successful scan.")
    with right:
        st.markdown('<div class="section-title">Quick actions</div><div class="section-subtitle">Manage sources and collect fresh job data.</div>', unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("**＋ Add a company**")
            st.caption("Save an official career-page URL to your scan queue.")
            if st.button("Open Add Company", use_container_width=True):
                st.session_state.next_page = "Add Company"
                st.info("Choose **Add Company** from the sidebar to continue.")
            st.markdown("---")
            st.markdown("**▶ Run a scan**")
            st.caption("Scan configured career pages or review recent job postings when date metadata is available.")
            if st.button("Open scan options", type="primary", use_container_width=True):
                st.info("Choose **Run Scan** from the sidebar to start.")
        st.markdown("<div class='small-muted'>Results are stored in Neon PostgreSQL. Local CSV/Excel exports are optional and may not persist across Render restarts.</div>", unsafe_allow_html=True)

    if not data.empty:
        st.markdown('<div class="section-title">Latest extracted jobs</div>', unsafe_allow_html=True)
        cols = [c for c in ["job_title", "company", "location_mention", "employment_type_mention", "source_url"] if c in data.columns]
        st.dataframe(data[cols].head(10), use_container_width=True, hide_index=True)

elif page == "Add Company":
    st.markdown('<div class="section-title">Add a company</div><div class="section-subtitle">Use the company’s official careers or job listings page.</div>', unsafe_allow_html=True)
    form_col, list_col = st.columns([.9, 1.1], gap="large")
    with form_col:
        with st.container(border=True):
            with st.form("company_form", clear_on_submit=True):
                name = st.text_input("Company name", placeholder="e.g. Techment")
                career_url = st.text_input("Career page URL", placeholder="https://www.example.com/careers")
                submitted = st.form_submit_button("＋ Add company", type="primary", use_container_width=True)
            if submitted:
                candidate = normalize_url(career_url)
                parsed = urlparse(candidate)
                if not candidate or parsed.scheme not in ("http", "https") or not parsed.hostname or "." not in parsed.hostname:
                    st.error("Enter a valid career page URL, such as https://company.com/careers.")
                elif any(c["career_url"].rstrip("/") == candidate.rstrip("/") for c in st.session_state.companies):
                    st.warning("That career URL is already in your queue.")
                else:
                    host = parsed.hostname.removeprefix("www.")
                    company_name = name.strip() or host.split(".")[0].replace("-", " ").title()
                    st.session_state.companies.append({"name": company_name, "career_url": candidate})
                    st.success(f"{company_name} added to your queue.")
                    st.rerun()
    with list_col:
        with st.container(border=True):
            st.markdown(f"**Company queue · {len(st.session_state.companies)} sources**")
            if not st.session_state.companies:
                st.info("No companies added yet.")
            for i, company in enumerate(list(st.session_state.companies)):
                st.markdown(f"**{company['name']}**  \n`{company['career_url']}`")
                if st.button("Remove", key=f"remove_company_{i}"):
                    st.session_state.companies.pop(i)
                    st.rerun()
                st.divider()

elif page == "Run Scan":
    st.markdown('<div class="section-title">Run a scan</div><div class="section-subtitle">Choose how you want to collect job information.</div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(f"**Ready to scan:** {len(st.session_state.companies)} company career page(s)")
        c1, c2 = st.columns(2)
        with c1:
            max_pages = st.slider("Maximum pages per company", min_value=10, max_value=300, value=int(load_config().get("max_pages_per_domain", 80)), step=10)
        with c2:
            delay = st.slider("Delay between requests (seconds)", min_value=1.0, max_value=10.0, value=float(load_config().get("request_delay_seconds", 2.0)), step=0.5)
        st.caption("The crawler checks robots.txt and stays within the configured company domain. Larger scans can take several minutes.")
        run1, run2 = st.columns(2)
        with run1:
            if st.button("▶ Run full scan", type="primary", use_container_width=True):
                start_scan("all", max_pages, delay)
                st.rerun()
        with run2:
            if st.button("◷ Run scan — past 30 days", use_container_width=True):
                start_scan("30_days", max_pages, delay)
                st.rerun()
    if st.session_state.get("scan_mode") == "30_days":
        st.info("This option runs the crawl and then limits the displayed results to postings with a published date in the last 30 days. The current agent.py does not yet save a date_posted field, so accurate 30-day filtering requires a small companion update to agent.py.")
    if not get_database_url():
        st.warning("Add DATABASE_URL to Render → Environment before scanning.")
    if not st.session_state.companies:
        st.warning("Add at least one company first.")

elif page == "Scan Activity":
    st.markdown('<div class="section-title">Scan activity</div><div class="section-subtitle">Latest run status and crawler output.</div>', unsafe_allow_html=True)
    st.metric("Last scan status", st.session_state.last_scan_status)
    if st.session_state.scan_log:
        st.code("\n".join(st.session_state.scan_log[-120:]), language="text")
        st.download_button("Download scan log", "\n".join(st.session_state.scan_log), file_name="role_radar_scan_log.txt", mime="text/plain")
    else:
        st.info("No scan logs in this session yet.")

# ---------- Execute scan with live log/progress ----------
if st.session_state.get("scan_requested"):
    st.session_state.scan_requested = False
    mode = st.session_state.get("scan_mode", "all")
    st.markdown('<div class="section-title">Scan in progress</div><div class="section-subtitle">Keep this page open while the crawler runs.</div>', unsafe_allow_html=True)
    progress = st.progress(0, text="Starting crawler…")
    status = st.empty()
    log_box = st.empty()
    lines: list[str] = []
    try:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        if get_database_url():
            env["DATABASE_URL"] = get_database_url()
        # The current crawler doesn't yet implement a published-date cutoff. This variable is
        # available for the companion agent.py update and does not affect full scans.
        if mode == "30_days":
            env["SCAN_POSTED_WITHIN_DAYS"] = "30"
        proc = subprocess.Popen([sys.executable, "-u", str(AGENT)], cwd=str(ROOT), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        start = time.time()
        page_total = 0
        while True:
            line = proc.stdout.readline() if proc.stdout else ""
            if line:
                line = line.rstrip()
                lines.append(line)
                st.session_state.scan_log = lines[-500:]
                match = re.search(r"Visited\s+(\d+)/(\d+)", line)
                if match:
                    visited, limit = int(match.group(1)), max(1, int(match.group(2)))
                    page_total += 1
                    # A practical estimate from pages visited; final completion sets 100%.
                    pct = min(94, max(5, int(visited / limit * 90)))
                    progress.progress(pct, text=f"Scanning career pages · {visited}/{limit} pages for current company")
                    status.caption(f"Elapsed: {int(time.time() - start)} sec · Pages reported: {page_total}")
                else:
                    progress.progress(min(90, max(5, int((time.time() - start) / 25 * 5))), text="Scanning career pages…")
                log_box.code("\n".join(lines[-35:]), language="text")
            elif proc.poll() is not None:
                break
            else:
                time.sleep(.1)
            if time.time() - start > 1800:
                proc.kill()
                lines.append("Scan stopped after 30 minutes. Try fewer companies or fewer pages.")
                break
        rc = proc.wait()
        progress.progress(100 if rc == 0 else 0, text="Scan completed" if rc == 0 else "Scan failed")
        st.session_state.last_scan_status = "Completed" if rc == 0 else "Failed — review logs"
        if rc == 0:
            st.success("Scan completed. Open Dashboard to review extracted roles.")
            if mode == "30_days":
                result = get_results()
                if "date_posted" in result.columns:
                    dates = pd.to_datetime(result["date_posted"], errors="coerce", utc=True)
                    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)
                    recent = result.loc[dates >= cutoff]
                    st.info(f"{len(recent):,} postings have a published date within the past 30 days.")
                    st.dataframe(recent, use_container_width=True, hide_index=True)
                else:
                    st.warning("The scan succeeded, but agent.py does not currently save date_posted. The app cannot reliably identify jobs published in the past 30 days until that field is added to the crawler.")
        else:
            st.error("The crawler exited with an error. Review the log below.")
        st.session_state.scan_log = lines[-500:]
        if lines:
            log_box.code("\n".join(lines[-100:]), language="text")
    except Exception as exc:
        st.session_state.last_scan_status = "Failed to start"
        st.error(f"Could not start the crawler: {exc}")

# ---------- Exports available from dashboard data ----------
if not data.empty and page == "Dashboard":
    with st.expander("Export current job records"):
        st.download_button("Download CSV", data.to_csv(index=False).encode("utf-8-sig"), file_name="role_radar_jobs.csv", mime="text/csv")
        st.caption("The crawler also creates a local Excel file when supported by the installed dependencies.")
