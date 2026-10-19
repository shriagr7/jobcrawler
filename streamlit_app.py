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
from sqlalchemy import create_engine, text as sql_text

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.json"
CSV = ROOT / "job_requirements.csv"
AGENT = ROOT / "agent.py"

st.set_page_config(
    page_title="RoleRadar | Hiring Intelligence",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- UI styling ----------
st.markdown(r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
:root{--ink:#111d46;--muted:#64748b;--line:#e5eaf5;--blue:#4057ff;--purple:#7847ff;}
html,body,[class*="css"]{font-family:'DM Sans',sans-serif}
.stApp{background:linear-gradient(120deg,#f6f9ff 0%,#fbfcff 55%,#f4f7ff 100%)}
[data-testid="stHeader"]{background:rgba(248,250,255,.88)}
.block-container{max-width:1600px;padding-top:1rem;padding-bottom:2.5rem}
[data-testid="stSidebar"]{background:linear-gradient(180deg,#101a39 0%,#101b3b 60%,#13254d 100%);border-right:1px solid #26365d}
[data-testid="stSidebar"] *{color:#f1f5ff}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p{color:#bdc9e6}
.brand{display:flex;align-items:center;gap:12px;padding:.45rem 0 1.3rem}
.brand-icon{width:48px;height:48px;border-radius:16px;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#24d0df,#654cff);font-size:26px;box-shadow:0 8px 25px #0003}
.brand-name{font:800 1.55rem Manrope,sans-serif;letter-spacing:-.06em;color:#fff}
.brand-sub{font-size:.68rem;color:#b9c7e7;letter-spacing:.13em;text-transform:uppercase}
.sidebar-note{margin-top:2rem;padding:1rem;border:1px solid #ffffff20;border-radius:14px;background:#ffffff08;color:#c5d2ee;font-size:.82rem;line-height:1.5}
.page-head{display:flex;justify-content:space-between;align-items:center;gap:1rem;margin:.15rem 0 1rem}
.logo-title{font:800 clamp(2rem,3vw,3rem) Manrope,sans-serif;letter-spacing:-.065em;line-height:1;color:#111d46}
.logo-title span{color:#4057ff}
.tagline{font-size:.93rem;color:#64748b;margin-top:.45rem}
.live-pill{padding:.85rem 1rem;border:1px solid #dce4ff;background:linear-gradient(120deg,#edf1ff,#f7f8ff);border-radius:15px;color:#192c66;max-width:290px;font-weight:600}
.section-title{font:800 1.12rem Manrope,sans-serif;color:#111d46;letter-spacing:-.03em;margin:.1rem 0 .18rem}
.section-subtitle{font-size:.84rem;color:#71809a;margin-bottom:.85rem}
.metric-card{background:#fff;border:1px solid #e4eaf5;border-radius:16px;padding:1rem 1.05rem;min-height:112px;box-shadow:0 5px 20px #1e3a8a05}
.metric-top{display:flex;align-items:center;gap:12px}
.metric-icon{height:48px;width:48px;display:flex;align-items:center;justify-content:center;border-radius:13px;background:#edf2ff;font-size:23px}
.metric-value{font:800 1.85rem Manrope,sans-serif;color:#101b49;line-height:1.1}
.metric-label{font-weight:600;color:#18264d;font-size:.88rem}
.metric-note{font-size:.73rem;color:#77849c;margin-top:.18rem}
.panel{background:#fff;border:1px solid #e3e9f4;border-radius:16px;padding:1rem 1.05rem;box-shadow:0 5px 20px #1e3a8a05;height:100%}
.panel-head{display:flex;align-items:center;gap:10px;margin-bottom:.15rem}
.panel-icon{height:42px;width:42px;display:flex;align-items:center;justify-content:center;background:#eef3ff;border-radius:12px;font-size:22px}
.panel-title{font:800 1.08rem Manrope,sans-serif;color:#101b49}
div.stButton>button,div.stFormSubmitButton>button{border-radius:10px;font-weight:700;min-height:2.55rem;border-color:#d9e1f5}
div.stButton>button[kind="primary"],div.stFormSubmitButton>button[kind="primary"]{background:linear-gradient(100deg,#4057ff,#6849ff);border:0;color:#fff}
[data-testid="stDataFrame"]{border:1px solid #e3e9f4;border-radius:10px;overflow:hidden}
[data-testid="stMetric"]{background:#fff;border:1px solid #e3e9f4;border-radius:13px;padding:.8rem}
div[data-testid="stProgress"]>div>div{background:linear-gradient(90deg,#4057ff,#8a5cff)}
.small-muted{font-size:.78rem;color:#7b879d}
hr{border-color:#e7ebf5}
@media(max-width:900px){.live-pill{display:none}.logo-title{font-size:2rem}}
</style>
""", unsafe_allow_html=True)


def database_url() -> str:
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        try:
            value = str(st.secrets.get("DATABASE_URL", "")).strip()
        except Exception:
            value = ""
    return value


def load_config() -> dict:
    defaults = {
        "companies": [],
        "max_pages_per_domain": 80,
        "request_delay_seconds": 2.0,
        "job_url_keywords": ["job", "career", "opening", "position", "requisition", "vacancy"],
        "exclude_url_keywords": ["privacy", "cookie", "benefit", "event", "login"],
    }
    try:
        existing = json.loads(CONFIG.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            defaults.update(existing)
    except Exception:
        pass
    return defaults


def save_config(cfg: dict) -> None:
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def normalize_url(value: str) -> str:
    value = value.strip()
    if value and not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    return value.rstrip("/")


def get_results() -> pd.DataFrame:
    url = database_url()
    if url:
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://") and "+" not in url.split(":", 1)[0]:
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        try:
            engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
            try:
                with engine.connect() as conn:
                    df = pd.read_sql(sql_text("SELECT * FROM job_postings"), conn)
                if not df.empty:
                    return df.fillna("")
            finally:
                engine.dispose()
        except Exception as exc:
            st.session_state["db_read_error"] = str(exc)
    if CSV.exists():
        try:
            return pd.read_csv(CSV).fillna("")
        except Exception:
            pass
    return pd.DataFrame()


def metric_card(icon: str, value: str, label: str, note: str) -> None:
    st.markdown(
        f'<div class="metric-card"><div class="metric-top"><div class="metric-icon">{icon}</div>'
        f'<div><div class="metric-value">{value}</div><div class="metric-label">{label}</div>'
        f'<div class="metric-note">{note}</div></div></div></div>',
        unsafe_allow_html=True,
    )


def panel_heading(icon: str, title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="panel-head"><div class="panel-icon">{icon}</div>'
        f'<div><div class="panel-title">{title}</div><div class="small-muted">{subtitle}</div></div></div>',
        unsafe_allow_html=True,
    )


def save_companies(companies: list[dict]) -> None:
    cfg = load_config()
    cfg["companies"] = []
    for company in companies:
        host = (urlparse(company["career_url"]).hostname or "").lower().removeprefix("www.")
        cfg["companies"].append({
            "name": company["name"],
            "career_url": company["career_url"],
            "allowed_domains": [host] if host else [],
        })
    save_config(cfg)


def queue_scan(mode: str, max_pages: int, delay: float) -> None:
    companies = st.session_state.get("companies", [])
    if not companies:
        st.error("Add at least one company before running a scan.")
        return
    if not database_url():
        st.error("DATABASE_URL is missing. Add it in Render → Environment.")
        return
    if not AGENT.exists():
        st.error("agent.py was not found beside streamlit_app.py.")
        return
    cfg = load_config()
    cfg["companies"] = []
    for company in companies:
        host = (urlparse(company["career_url"]).hostname or "").lower().removeprefix("www.")
        cfg["companies"].append({
            "name": company["name"],
            "career_url": company["career_url"],
            "allowed_domains": [host] if host else [],
        })
    cfg["max_pages_per_domain"] = int(max_pages)
    cfg["request_delay_seconds"] = float(delay)
    save_config(cfg)
    st.session_state.scan_mode = mode
    st.session_state.scan_requested = True
    st.session_state.last_scan_status = "Queued"


# ---------- Session state ----------
if "companies" not in st.session_state:
    st.session_state.companies = [
        {"name": c.get("name", ""), "career_url": c.get("career_url", "")}
        for c in load_config().get("companies", [])
        if c.get("name") and c.get("career_url") and "example.com" not in c.get("career_url", "")
    ]
if "scan_log" not in st.session_state:
    st.session_state.scan_log = []
if "last_scan_status" not in st.session_state:
    st.session_state.last_scan_status = "Not run yet"
if "scan_requested" not in st.session_state:
    st.session_state.scan_requested = False

# ---------- Sidebar ----------
with st.sidebar:
    st.markdown(
        '<div class="brand"><div class="brand-icon">◎</div><div>'
        '<div class="brand-name">RoleRadar</div><div class="brand-sub">Hiring intelligence</div></div></div>',
        unsafe_allow_html=True,
    )
    page = st.radio(
        "Workspace",
        ["Dashboard", "Add Company", "Run Scan", "Scan Activity", "Job Roles"],
        label_visibility="collapsed",
    )
    st.divider()
    if database_url():
        st.success("Neon PostgreSQL connected")
    else:
        st.warning("Database not configured")
        st.caption("Set DATABASE_URL in Render → Environment.")
    st.markdown(
        '<div class="sidebar-note"><b>Discover job opportunities</b><br><br>'
        'Collect job postings from company career pages and explore hiring demand by role.</div>',
        unsafe_allow_html=True,
    )

# ---------- Page header ----------
st.markdown(
    '<div class="page-head"><div><div class="logo-title">◎ <span>Role</span>Radar</div>'
    '<div class="tagline">Scan. Extract. Analyze. Understand the Talent Demand.</div></div>'
    '<div class="live-pill">🎯 &nbsp; Track hiring signals<br>from company career pages</div></div>',
    unsafe_allow_html=True,
)

data = get_results()
company_count = data["company"].nunique() if not data.empty and "company" in data.columns else 0
job_count = len(data)
roles_count = data["job_title"].astype(str).str.strip().replace("", pd.NA).nunique() if not data.empty and "job_title" in data.columns else 0
recent_count = 0
if not data.empty and "date_posted" in data.columns:
    posted = pd.to_datetime(data["date_posted"], errors="coerce", utc=True)
    recent_count = int((posted >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)).sum())

# ---------- Dashboard ----------
if page == "Dashboard":
    m1, m2, m3, m4 = st.columns(4, gap="medium")
    with m1:
        metric_card("▦", f"{len(st.session_state.companies):,}", "Companies", "Configured for scan")
    with m2:
        metric_card("▤", f"{job_count:,}", "Total Job Postings", "Extracted till now")
    with m3:
        metric_card("♟", f"{roles_count:,}", "Unique Job Roles", "Identified")
    with m4:
        metric_card("▦", f"{recent_count:,}", "Jobs (Past 30 Days)", "Based on published date")

    left, right = st.columns([1.05, 1.1], gap="medium")
    with left:
        with st.container(border=True):
            panel_heading("▦", "Add Company", "Enter the company name and its official careers page URL")
            with st.form("quick_add_company", clear_on_submit=True):
                c1, c2 = st.columns([.8, 1.2])
                with c1:
                    name = st.text_input("Company Name", placeholder="e.g. Google")
                with c2:
                    career_url = st.text_input("Careers Page URL", placeholder="https://company.com/careers")
                submitted = st.form_submit_button("＋ Add Company", type="primary", use_container_width=False)
            if submitted:
                candidate = normalize_url(career_url)
                parsed = urlparse(candidate)
                if not name.strip():
                    st.error("Enter a company name.")
                elif parsed.scheme not in ("http", "https") or not parsed.hostname or "." not in parsed.hostname:
                    st.error("Enter a valid careers URL.")
                elif any(c["career_url"].rstrip("/") == candidate.rstrip("/") for c in st.session_state.companies):
                    st.warning("That careers URL is already configured.")
                else:
                    st.session_state.companies.append({"name": name.strip(), "career_url": candidate})
                    save_companies(st.session_state.companies)
                    st.success(f"{name.strip()} added.")
                    st.rerun()

            st.markdown(f"**Configured Companies ({len(st.session_state.companies)})**")
            if st.session_state.companies:
                display = pd.DataFrame([
                    {"#": i + 1, "Company Name": c["name"], "Careers URL": c["career_url"]}
                    for i, c in enumerate(st.session_state.companies[:6])
                ])
                st.dataframe(display, use_container_width=True, hide_index=True, height=225,
                             column_config={"Careers URL": st.column_config.LinkColumn("Careers URL")})
                if len(st.session_state.companies) > 6:
                    st.caption(f"Showing 6 of {len(st.session_state.companies)} configured companies. Manage the full list under Add Company.")
            else:
                st.info("Add your first company to start collecting job postings.")

    with right:
        with st.container(border=True):
            panel_heading("▶", "Run Job Scan", "Start scanning the configured company career pages")
            cfg = load_config()
            max_pages = st.slider("Maximum pages per company", 10, 300, int(cfg.get("max_pages_per_domain", 80)), 10, key="dash_max_pages")
            delay = st.slider("Delay between requests (seconds)", 1.0, 10.0, float(cfg.get("request_delay_seconds", 2.0)), .5, key="dash_delay")
            b1, b2 = st.columns(2)
            with b1:
                if st.button("▶  Run Full Scan", type="primary", use_container_width=True):
                    queue_scan("all", max_pages, delay)
                    st.rerun()
            with b2:
                if st.button("▦  Scan — Past 30 Days", use_container_width=True):
                    queue_scan("30_days", max_pages, delay)
                    st.rerun()
            st.markdown("---")
            st.markdown(f"**Latest scan status:** `{st.session_state.last_scan_status}`")
            if st.session_state.scan_log:
                st.code("\n".join(st.session_state.scan_log[-8:]), language="text")
            else:
                st.caption("Scan output and progress will appear here while a scan runs.")

    st.markdown("---")
    with st.container(border=True):
        panel_heading("▥", "Job Roles Dashboard", "Job postings grouped by role title (based on extracted data)")
        if data.empty or "job_title" not in data.columns:
            st.info("No job records are available yet. Run a scan; if it returns zero jobs, review Scan Activity for crawler messages.")
        else:
            chart_col, table_col = st.columns([1.5, 1], gap="medium")
            roles = data["job_title"].astype(str).str.strip()
            roles = roles[roles.ne("")]
            counts = roles.value_counts().head(10)
            if counts.empty:
                st.info("The crawler has saved records, but no job titles were detected.")
            else:
                with chart_col:
                    chart_df = counts.rename_axis("Job Role").reset_index(name="Number of Postings")
                    st.bar_chart(chart_df.set_index("Job Role"), horizontal=False, height=300, use_container_width=True)
                with table_col:
                    st.markdown("**Job Roles (Top 10)**")
                    role_table = counts.rename_axis("Job Role").reset_index(name="Number of Postings")
                    role_table.insert(0, "#", range(1, len(role_table) + 1))
                    st.dataframe(role_table, use_container_width=True, hide_index=True, height=330)

    if not data.empty:
        with st.expander("Latest extracted job postings"):
            cols = [c for c in ["job_title", "company", "location_mention", "employment_type_mention", "source_url"] if c in data.columns]
            st.dataframe(data[cols].head(25), use_container_width=True, hide_index=True)
        with st.expander("Export results"):
            st.download_button("Download job records as CSV", data.to_csv(index=False).encode("utf-8-sig"),
                               file_name="role_radar_jobs.csv", mime="text/csv")

# ---------- Add Company ----------
elif page == "Add Company":
    with st.container(border=True):
        panel_heading("＋", "Add Company", "Use the official careers or job listings page.")
        with st.form("add_company_page", clear_on_submit=True):
            name = st.text_input("Company name", placeholder="e.g. Microsoft")
            career_url = st.text_input("Official careers page URL", placeholder="https://careers.company.com/")
            submitted = st.form_submit_button("＋ Add Company", type="primary")
        if submitted:
            candidate = normalize_url(career_url)
            parsed = urlparse(candidate)
            if not name.strip():
                st.error("Enter a company name.")
            elif parsed.scheme not in ("http", "https") or not parsed.hostname or "." not in parsed.hostname:
                st.error("Enter a valid URL beginning with https://.")
            elif any(c["career_url"].rstrip("/") == candidate.rstrip("/") for c in st.session_state.companies):
                st.warning("That URL is already in your company list.")
            else:
                st.session_state.companies.append({"name": name.strip(), "career_url": candidate})
                save_companies(st.session_state.companies)
                st.success("Company saved to config.json.")
                st.rerun()

    st.markdown("### Configured Companies")
    if st.session_state.companies:
        for i, company in enumerate(list(st.session_state.companies)):
            with st.container(border=True):
                c1, c2, c3 = st.columns([1, 2.3, .6])
                c1.write(f"**{company['name']}**")
                c2.markdown(f"[{company['career_url']}]({company['career_url']})")
                if c3.button("Remove", key=f"remove_{i}"):
                    st.session_state.companies.pop(i)
                    save_companies(st.session_state.companies)
                    st.rerun()
    else:
        st.info("No companies configured yet.")

# ---------- Run Scan ----------
elif page == "Run Scan":
    with st.container(border=True):
        panel_heading("▶", "Run Job Scan", "Choose the crawl size and launch a scan.")
        cfg = load_config()
        max_pages = st.slider("Maximum pages per company", 10, 300, int(cfg.get("max_pages_per_domain", 80)), 10, key="scan_max_pages")
        delay = st.slider("Delay between requests (seconds)", 1.0, 10.0, float(cfg.get("request_delay_seconds", 2.0)), .5, key="scan_delay")
        st.caption("The crawler checks robots.txt and stays within each configured domain. Some JavaScript-driven career sites may need a site-specific parser.")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("▶ Run Full Scan", type="primary", use_container_width=True):
                queue_scan("all", max_pages, delay)
                st.rerun()
        with c2:
            if st.button("▦ Scan — Past 30 Days", use_container_width=True):
                queue_scan("30_days", max_pages, delay)
                st.rerun()
        if not st.session_state.companies:
            st.warning("Add at least one company before scanning.")
        if not database_url():
            st.warning("DATABASE_URL is not configured in Render → Environment.")

# ---------- Scan Activity ----------
elif page == "Scan Activity":
    with st.container(border=True):
        panel_heading("◷", "Scan Activity", "Latest run status and crawler output.")
        st.metric("Last scan status", st.session_state.last_scan_status)
        if st.session_state.scan_log:
            st.code("\n".join(st.session_state.scan_log[-150:]), language="text")
            st.download_button("Download scan log", "\n".join(st.session_state.scan_log),
                               file_name="role_radar_scan_log.txt", mime="text/plain")
        else:
            st.info("No scan logs recorded in this app session yet.")
        if st.session_state.get("db_read_error"):
            st.error("Could not read the job_postings table from Neon PostgreSQL.")
            st.code(st.session_state.db_read_error)

# ---------- Job Roles ----------
elif page == "Job Roles":
    with st.container(border=True):
        panel_heading("▥", "Job Roles", "Explore extracted postings by title.")
        if data.empty or "job_title" not in data.columns:
            st.info("No job roles found yet. Run a scan and check the scan log if no records are saved.")
        else:
            roles = data.copy()
            roles["job_title"] = roles["job_title"].astype(str).str.strip()
            roles = roles[roles["job_title"].ne("")]
            if "company" in roles.columns:
                company_options = ["All companies"] + sorted(roles["company"].dropna().astype(str).unique().tolist())
                chosen_company = st.selectbox("Filter by company", company_options)
                if chosen_company != "All companies":
                    roles = roles[roles["company"] == chosen_company]
            query = st.text_input("Search job titles", placeholder="e.g. Data Scientist")
            if query:
                roles = roles[roles["job_title"].str.contains(query, case=False, na=False)]
            counts = roles["job_title"].value_counts().rename_axis("Job Role").reset_index(name="Number of Postings")
            st.dataframe(counts, use_container_width=True, hide_index=True)
            st.download_button("Download role summary", counts.to_csv(index=False).encode("utf-8-sig"),
                               file_name="role_radar_role_summary.csv", mime="text/csv")

# ---------- Execute queued scan ----------
if st.session_state.get("scan_requested"):
    st.session_state.scan_requested = False
    mode = st.session_state.get("scan_mode", "all")
    st.markdown("---")
    st.markdown('<div class="section-title">Scanning in progress…</div><div class="section-subtitle">Keep this page open while the crawler runs.</div>', unsafe_allow_html=True)
    progress = st.progress(0, text="Starting crawler…")
    status = st.empty()
    log_box = st.empty()
    lines: list[str] = []
    try:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        if database_url():
            env["DATABASE_URL"] = database_url()
        if mode == "30_days":
            env["SCAN_POSTED_WITHIN_DAYS"] = "30"
        proc = subprocess.Popen(
            [sys.executable, "-u", str(AGENT)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        start = time.time()
        while True:
            line = proc.stdout.readline() if proc.stdout else ""
            if line:
                line = line.rstrip()
                lines.append(line)
                st.session_state.scan_log = lines[-500:]
                match = re.search(r"Visited\s+(\d+)/(\d+)", line)
                if match:
                    visited, limit = int(match.group(1)), max(1, int(match.group(2)))
                    pct = min(94, max(5, int(visited / limit * 90)))
                    progress.progress(pct, text=f"Scanning career pages · {visited}/{limit} pages for current company")
                    status.caption(f"Elapsed: {int(time.time() - start)} seconds")
                else:
                    progress.progress(min(90, max(5, int((time.time() - start) / 25 * 5))), text="Scanning career pages…")
                log_box.code("\n".join(lines[-30:]), language="text")
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
        st.session_state.scan_log = lines[-500:]
        if rc == 0:
            st.success("Scan process completed. Check the extracted count in the log and open Dashboard for results.")
            if any(re.search(r"Extracted\s+0\s+candidate job pages", item, re.I) for item in lines):
                st.warning("The crawler completed but extracted zero job pages. This is a crawler/discovery issue, not a dashboard styling issue.")
        else:
            st.error("The crawler exited with an error. Review the output below.")
        if lines:
            log_box.code("\n".join(lines[-100:]), language="text")
    except Exception as exc:
        st.session_state.last_scan_status = "Failed to start"
        st.error(f"Could not start the crawler: {exc}")
