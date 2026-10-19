from __future__ import annotations

import io
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
    page_title="RoleRadar",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
:root{--ink:#111d46;--muted:#66748e;--line:#e4eaf5;--blue:#4057ff;--purple:#7650ff}
html,body,[class*="css"]{font-family:'DM Sans',sans-serif}
.stApp{background:linear-gradient(120deg,#f6f9ff,#fff 55%,#f5f7ff)}
.block-container{max-width:1450px;padding-top:1.2rem;padding-bottom:2rem}
[data-testid="stHeader"]{background:transparent}
.brand{display:flex;align-items:center;gap:13px;margin:.2rem 0 1.25rem}
.brand-icon{width:55px;height:55px;display:flex;align-items:center;justify-content:center;border-radius:17px;background:linear-gradient(135deg,#20cde0,#584cff);color:white;font-size:29px;box-shadow:0 8px 24px #4057ff30}
.brand-name{font:800 2.2rem Manrope,sans-serif;letter-spacing:-.065em;color:#111d46;line-height:1.05}
.brand-name span{color:#4057ff}
.brand-sub{font-size:.9rem;color:#687793;margin-top:.3rem}
.header-pill{border:1px solid #dce4ff;border-radius:15px;padding:.85rem 1rem;background:#eef2ff;color:#1b2b65;font-weight:600}
.metric-card{background:white;border:1px solid #e4eaf5;border-radius:15px;padding:1rem;min-height:105px;box-shadow:0 5px 18px #1e3a8a06}
.metric-row{display:flex;align-items:center;gap:12px}
.metric-icon{height:46px;width:46px;border-radius:13px;display:flex;align-items:center;justify-content:center;background:#edf2ff;font-size:23px}
.metric-value{font:800 1.8rem Manrope,sans-serif;color:#101b49;line-height:1.15}
.metric-label{font-weight:600;color:#18264d;font-size:.88rem}
.metric-note{font-size:.73rem;color:#77849c;margin-top:.15rem}
.panel-title{font:800 1.12rem Manrope,sans-serif;color:#101b49}
.panel-sub{font-size:.82rem;color:#71809a;margin:.15rem 0 .9rem}
.panel-icon{display:inline-flex;width:38px;height:38px;align-items:center;justify-content:center;border-radius:11px;background:#eef3ff;margin-right:9px;font-size:20px;vertical-align:middle}
.company-card{background:#fff;border:1px solid #e4eaf5;border-radius:14px;padding:.8rem 1rem;margin:.45rem 0}
.company-name{font-weight:700;color:#17244c}
.company-url{font-size:.78rem;color:#71809a;overflow-wrap:anywhere}
.status{display:inline-block;border-radius:999px;padding:.2rem .55rem;background:#eef2ff;color:#4057ff;font-size:.72rem;font-weight:700}
div.stButton>button,div.stFormSubmitButton>button{border-radius:10px;font-weight:700;min-height:2.5rem;border-color:#d9e1f5}
div.stButton>button[kind="primary"],div.stFormSubmitButton>button[kind="primary"]{background:linear-gradient(100deg,#4057ff,#6849ff);border:0;color:#fff}
div[data-testid="stProgress"]>div>div{background:linear-gradient(90deg,#4057ff,#8a5cff)}
[data-testid="stDataFrame"]{border:1px solid #e3e9f4;border-radius:10px;overflow:hidden}
div[data-testid="stFileUploader"]{background:#f9faff;border:1px dashed #cbd5ee;border-radius:12px;padding:.4rem}
hr{border-color:#e7ebf5}
.small-muted{font-size:.78rem;color:#7b879d}
@media(max-width:750px){.brand-name{font-size:1.8rem}.header-pill{display:none}}
</style>
""", unsafe_allow_html=True)


def db_url() -> str:
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        try:
            value = str(st.secrets.get("DATABASE_URL", "")).strip()
        except Exception:
            value = ""
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://"):]
    if value.startswith("postgresql://") and "+" not in value.split(":", 1)[0]:
        return "postgresql+psycopg://" + value[len("postgresql://"):]
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
        loaded = json.loads(CONFIG.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            defaults.update(loaded)
    except Exception:
        pass
    return defaults


def save_config(cfg: dict) -> None:
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def normalized_url(value: str) -> str:
    value = value.strip()
    if value and not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    return value.rstrip("/")


def normalize_company_rows(rows: list[dict]) -> list[dict]:
    """Validate company rows and preserve explicitly configured ATS domains."""
    clean_rows = []
    seen = set()
    for row in rows:
        name = str(row.get("name", row.get("company", ""))).strip()
        url = normalized_url(str(row.get("career_url", row.get("careers_url", row.get("url", "")))))
        parsed = urlparse(url)
        if not name or name.upper() == "ADD COMPANY NAME" or "example.com" in url.lower():
            continue
        if parsed.scheme not in ("http", "https") or not parsed.hostname or "." not in parsed.hostname:
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        domains = [parsed.hostname.lower().removeprefix("www.")]
        supplied = row.get("allowed_domains", []) or []
        if isinstance(supplied, str):
            supplied = re.split(r"[,;\s]+", supplied)
        if not isinstance(supplied, (list, tuple, set)):
            supplied = []
        for domain in supplied:
            domain = str(domain).strip().lower().removeprefix("www.").strip("/")
            # Accept hostname entries only, not arbitrary URL paths or schemes.
            domain = urlparse("https://" + domain).hostname or ""
            if domain and "." in domain and domain not in domains:
                domains.append(domain)
        clean_rows.append({"name": name, "career_url": url, "allowed_domains": domains})
    return clean_rows


def save_companies(companies: list[dict]) -> None:
    cfg = load_config()
    cfg["companies"] = normalize_company_rows(companies)
    save_config(cfg)


def load_results() -> tuple[pd.DataFrame, str | None]:
    url = db_url()
    if url:
        engine = None
        try:
            engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
            with engine.connect() as conn:
                df = pd.read_sql(sql_text("SELECT * FROM job_postings"), conn)
            return df.fillna(""), None
        except Exception as exc:
            return pd.DataFrame(), str(exc)
        finally:
            if engine is not None:
                engine.dispose()
    if CSV.exists():
        try:
            return pd.read_csv(CSV).fillna(""), None
        except Exception as exc:
            return pd.DataFrame(), str(exc)
    return pd.DataFrame(), None


def card(icon: str, value: str, label: str, note: str) -> None:
    st.markdown(
        f'<div class="metric-card"><div class="metric-row"><div class="metric-icon">{icon}</div>'
        f'<div><div class="metric-value">{value}</div><div class="metric-label">{label}</div>'
        f'<div class="metric-note">{note}</div></div></div></div>',
        unsafe_allow_html=True,
    )


def start_scan(companies: list[dict], mode: str) -> None:
    if not companies:
        st.warning("Add at least one company first.")
        return
    if not db_url():
        st.error("DATABASE_URL is not configured in Render → Environment.")
        return
    if not AGENT.exists():
        st.error("agent.py must be in the same GitHub repository folder as streamlit_app.py.")
        return
    cfg = load_config()
    cfg["companies"] = normalize_company_rows(companies)
    cfg["max_pages_per_domain"] = int(cfg.get("max_pages_per_domain", 80))
    cfg["request_delay_seconds"] = float(cfg.get("request_delay_seconds", 2))
    save_config(cfg)
    st.session_state["pending_scan"] = {"mode": mode, "companies": cfg["companies"]}
    st.rerun()


# Persist configured companies in session and config.
if "companies" not in st.session_state:
    st.session_state.companies = normalize_company_rows(load_config().get("companies", []))
if "pending_scan" not in st.session_state:
    st.session_state.pending_scan = None
if "scan_log" not in st.session_state:
    st.session_state.scan_log = []
if "scan_status" not in st.session_state:
    st.session_state.scan_status = "Ready"
if "company_status" not in st.session_state:
    st.session_state.company_status = {}

# Header
st.markdown(
    '<div class="brand"><div class="brand-icon">◎</div><div>'
    '<div class="brand-name"><span>Role</span>Radar</div>'
    '<div class="brand-sub">A simple view of hiring activity across your target companies.</div></div>'
    '<div style="flex:1"></div><div class="header-pill">🎯 &nbsp; Company hiring dashboard</div></div>',
    unsafe_allow_html=True,
)

data, db_error = load_results()
company_count = len(st.session_state.companies)
job_count = len(data)
role_count = 0
if not data.empty and "job_title" in data.columns:
    titles = data["job_title"].astype(str).str.strip()
    role_count = titles[titles.ne("")].nunique()
recent_count = 0
if not data.empty and "date_posted" in data.columns:
    dates = pd.to_datetime(data["date_posted"], errors="coerce", utc=True)
    recent_count = int((dates >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)).sum())

# Simple dashboard: four numbers, company list and per-company scan buttons, and roles.
metrics = st.columns(4, gap="medium")
with metrics[0]:
    card("▦", f"{company_count:,}", "Companies", "Configured")
with metrics[1]:
    card("▤", f"{job_count:,}", "Job Postings", "Saved in results")
with metrics[2]:
    card("♟", f"{role_count:,}", "Unique Job Roles", "Distinct titles")
with metrics[3]:
    card("▦", f"{recent_count:,}", "Past 30 Days", "Based on posted date")

st.markdown("")

left, right = st.columns([1.15, 1], gap="medium")
with left:
    with st.container(border=True):
        st.markdown('<div class="panel-title"><span class="panel-icon">＋</span>Companies</div>', unsafe_allow_html=True)
        st.markdown('<div class="panel-sub">Add one company or upload a CSV/XLSX list.</div>', unsafe_allow_html=True)

        with st.form("add_company_form", clear_on_submit=True):
            c1, c2 = st.columns([.75, 1.25])
            with c1:
                new_name = st.text_input("Company name", placeholder="e.g. Microsoft")
            with c2:
                new_url = st.text_input("Careers page URL", placeholder="https://careers.company.com/")
            extra_domains = st.text_input(
                "Additional allowed domains (optional)",
                placeholder="boards.greenhouse.io, jobs.lever.co",
                help="Only add trusted ATS hosts that this company's career page links to. The career-page domain is included automatically.",
            )
            add_clicked = st.form_submit_button("＋ Add company", type="primary")
        if add_clicked:
            row = {
                "name": new_name.strip(),
                "career_url": normalized_url(new_url),
                "allowed_domains": [x.strip() for x in re.split(r"[,;\s]+", extra_domains) if x.strip()],
            }
            merged = normalize_company_rows(st.session_state.companies + [row])
            if not new_name.strip():
                st.error("Enter a company name.")
            elif not row["career_url"]:
                st.error("Enter the careers page URL.")
            elif len(merged) == len(st.session_state.companies):
                st.warning("That URL is already configured or is invalid.")
            else:
                st.session_state.companies = merged
                save_companies(merged)
                st.success(f"{new_name.strip()} added.")
                st.rerun()

        uploaded = st.file_uploader("Upload company list (CSV or Excel)", type=["csv", "xlsx"], key="company_upload")
        if uploaded is not None:
            try:
                if uploaded.name.lower().endswith(".csv"):
                    uploaded_df = pd.read_csv(uploaded)
                else:
                    uploaded_df = pd.read_excel(uploaded)
                uploaded_rows = uploaded_df.rename(columns={c: str(c).strip().lower() for c in uploaded_df.columns}).to_dict("records")
                new_rows = normalize_company_rows(uploaded_rows)
                if st.button("Import company list", type="primary", key="import_companies"):
                    merged = normalize_company_rows(st.session_state.companies + new_rows)
                    added = max(0, len(merged) - len(st.session_state.companies))
                    st.session_state.companies = merged
                    save_companies(merged)
                    st.success(f"Imported {added} new companies.")
                    st.rerun()
                st.caption(f"{len(new_rows)} valid company rows detected. Expected columns: `name` and `career_url` (or `company` and `url`).")
            except Exception as exc:
                st.error(f"Could not read this file: {exc}")

        st.markdown(f"**Configured companies · {len(st.session_state.companies)}**")
        if st.session_state.companies:
            for i, company in enumerate(st.session_state.companies):
                status = st.session_state.company_status.get(company["name"], "Ready")
                with st.container(border=True):
                    r1, r2, r3 = st.columns([2.3, 1, .8], vertical_alignment="center")
                    with r1:
                        st.markdown(f"**{company['name']}**")
                        st.markdown(f'<div class="company-url">{company["career_url"]}</div>', unsafe_allow_html=True)
                        base_host = (urlparse(company["career_url"]).hostname or "").lower().removeprefix("www.")
                        extra_hosts = [d for d in company.get("allowed_domains", []) if d != base_host]
                        if extra_hosts:
                            st.caption("ATS domains: " + ", ".join(extra_hosts))
                    with r2:
                        st.markdown(f'<span class="status">{status}</span>', unsafe_allow_html=True)
                    with r3:
                        if st.button("Scan", key=f"scan_company_{i}", type="primary", use_container_width=True):
                            start_scan([company], "company")
                    x1, x2 = st.columns([1, 5])
                    with x1:
                        if st.button("Remove", key=f"remove_company_{i}", use_container_width=True):
                            st.session_state.companies.pop(i)
                            save_companies(st.session_state.companies)
                            st.rerun()
        else:
            st.info("No companies added yet.")

        if st.session_state.companies:
            st.markdown("---")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("▶ Scan all companies", type="primary", use_container_width=True):
                    start_scan(st.session_state.companies, "all")
            with c2:
                if st.button("Scan all · Past 30 days", use_container_width=True):
                    start_scan(st.session_state.companies, "30_days")

with right:
    with st.container(border=True):
        st.markdown('<div class="panel-title"><span class="panel-icon">▥</span>Job roles</div>', unsafe_allow_html=True)
        st.markdown('<div class="panel-sub">Most frequently detected job titles.</div>', unsafe_allow_html=True)
        if data.empty or "job_title" not in data.columns:
            st.info("No saved job results yet. Scan a company to populate this dashboard.")
        else:
            titles = data["job_title"].astype(str).str.strip()
            titles = titles[titles.ne("")]
            if "company" in data.columns:
                companies = ["All companies"] + sorted(data["company"].astype(str).replace("", pd.NA).dropna().unique().tolist())
                selected = st.selectbox("Company filter", companies, key="role_company_filter")
                if selected != "All companies":
                    titles = data.loc[data["company"].astype(str) == selected, "job_title"].astype(str).str.strip()
                    titles = titles[titles.ne("")]
            counts = titles.value_counts().head(10)
            if counts.empty:
                st.info("Job titles have not been extracted yet.")
            else:
                chart = counts.rename_axis("Job Role").reset_index(name="Postings")
                st.bar_chart(chart.set_index("Job Role"), height=290, use_container_width=True)
                st.dataframe(chart, use_container_width=True, hide_index=True, height=250)

st.markdown("")
with st.expander("Job postings and export", expanded=True):
    if data.empty:
        st.info("No results to show. Add a company and run a scan.")
    else:
        view = data.copy()
        if "job_status" not in view.columns:
            view["job_status"] = "Needs verification"
        view["job_status"] = view["job_status"].astype(str).replace("", "Needs verification")
        other_statuses = sorted(x for x in view["job_status"].unique().tolist() if x not in {"Likely open", "Needs verification"})
        status_values = ["Potentially open", "All statuses", "Likely open", "Needs verification"] + other_statuses
        chosen_status = st.selectbox("Job status", status_values, index=0, key="job_status_filter")
        search_query = st.text_input("Search title, company, or location", key="job_search")
        if chosen_status == "Potentially open":
            view = view[view["job_status"].isin(["Likely open", "Needs verification"])]
        elif chosen_status != "All statuses":
            view = view[view["job_status"].astype(str) == chosen_status]
        if search_query.strip():
            q = search_query.strip().lower()
            searchable_cols = [c for c in ["job_title", "company", "location_mention", "description"] if c in view.columns]
            match = pd.Series(False, index=view.index)
            for col in searchable_cols:
                match = match | view[col].astype(str).str.lower().str.contains(q, regex=False, na=False)
            view = view[match]
        display_cols = [c for c in [
            "job_title", "company", "job_status", "date_posted", "valid_through",
            "location_mention", "employment_type_mention", "work_arrangement_mention",
            "last_seen_utc", "source_url"
        ] if c in view.columns]
        st.caption(f"Showing {len(view):,} of {len(data):,} stored job records. 'Likely open' is a heuristic; verify on the employer's site.")
        if "source_url" in display_cols:
            st.dataframe(
                view[display_cols],
                use_container_width=True,
                hide_index=True,
                height=420,
                column_config={
                    "source_url": st.column_config.LinkColumn("Job posting", display_text="Open posting"),
                    "job_status": st.column_config.TextColumn("Status"),
                },
            )
        else:
            st.dataframe(view[display_cols], use_container_width=True, hide_index=True, height=420)
        st.download_button(
            "Export filtered postings CSV",
            data=view.to_csv(index=False).encode("utf-8-sig"),
            file_name="role_radar_jobs.csv",
            mime="text/csv",
        )


if db_error:
    st.warning("Could not load results from the database. Check DATABASE_URL and the job_postings table.")
    with st.expander("Database details"):
        st.code(db_error)

# Run queued scan, showing progress and logs on the same dashboard.
pending = st.session_state.get("pending_scan")
if pending:
    st.session_state.pending_scan = None
    st.markdown("---")
    st.markdown("### Scan progress")
    progress = st.progress(0, text="Starting scan…")
    status_text = st.empty()
    log_view = st.empty()
    log_lines: list[str] = []
    companies_to_scan = pending["companies"]
    mode = pending["mode"]
    started = time.time()
    failed = False
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if db_url():
        env["DATABASE_URL"] = db_url()
    if mode == "30_days":
        env["SCAN_POSTED_WITHIN_DAYS"] = "30"
    else:
        env.pop("SCAN_POSTED_WITHIN_DAYS", None)

    try:
        # agent.py reads config.json, so temporarily restrict it to the selected company list.
        cfg = load_config()
        original_companies = cfg.get("companies", [])
        cfg["companies"] = normalize_company_rows(companies_to_scan)
        save_config(cfg)
        proc = subprocess.Popen(
            [sys.executable, "-u", str(AGENT)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        try:
            while True:
                line = proc.stdout.readline() if proc.stdout else ""
                if line:
                    line = line.rstrip()
                    log_lines.append(line)
                    st.session_state.scan_log = log_lines[-500:]
                    m = re.search(r"Visited\s+(\d+)/(\d+)", line)
                    if m:
                        visited, total = int(m.group(1)), max(1, int(m.group(2)))
                        progress.progress(min(95, max(5, int(visited / total * 90))),
                                          text=f"Scanning pages · {visited}/{total}")
                    else:
                        progress.progress(min(90, max(5, int((time.time() - started) / 20 * 5))),
                                          text="Scanning company career pages…")
                    status_text.caption(f"Elapsed {int(time.time() - started)}s · {len(log_lines)} log lines")
                    log_view.code("\n".join(log_lines[-20:]), language="text")
                elif proc.poll() is not None:
                    break
                else:
                    time.sleep(.1)
                if time.time() - started > 1800:
                    proc.kill()
                    log_lines.append("Scan stopped after 30 minutes.")
                    failed = True
                    break
            return_code = proc.wait()
        finally:
            # Restore the complete company list after this run.
            cfg = load_config()
            cfg["companies"] = normalize_company_rows(st.session_state.companies)
            save_config(cfg)

        if return_code == 0 and not failed:
            st.session_state.scan_status = "Completed"
            progress.progress(100, text="Scan completed")
            st.success("Scan finished. Results have been refreshed below.")
            refreshed, refreshed_error = load_results()
            if refreshed_error:
                st.warning("The scan ended, but results could not be read back from the database.")
            else:
                data = refreshed
                st.rerun()
        else:
            st.session_state.scan_status = "Failed"
            progress.progress(0, text="Scan failed — check the log")
            st.error("Scan failed. Review the crawler log below.")
        if log_lines:
            log_view.code("\n".join(log_lines[-100:]), language="text")
            st.session_state.scan_log = log_lines[-500:]
    except Exception as exc:
        # Restore the complete company list even if the subprocess could not start.
        try:
            cfg = load_config()
            cfg["companies"] = normalize_company_rows(st.session_state.companies)
            save_config(cfg)
        except Exception:
            pass
        st.session_state.scan_status = "Failed to start"
        st.error(f"Could not start agent.py: {exc}")
