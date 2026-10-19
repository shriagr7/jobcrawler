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
from sqlalchemy import create_engine, inspect as sqlalchemy_inspect, text as sql_text

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
:root{
  --ink:#101a35; --muted:#72809a; --line:#e4eaf4;
  --blue:#4776ff; --teal:#31d4c5; --violet:#8764ff;
  --surface:#ffffff; --canvas:#f3f6fb;
}
html, body, [class*="css"]{font-family:'DM Sans',sans-serif}
.stApp{background:radial-gradient(circle at 4% 0%,#e8f1ff 0,transparent 27%),linear-gradient(180deg,#f7f9fd 0%,#f2f5fa 100%);color:var(--ink)}
.block-container{max-width:1510px;padding-top:1.5rem;padding-bottom:3rem;padding-left:2rem;padding-right:2rem}
[data-testid="stHeader"]{background:transparent}
[data-testid="stToolbar"]{right:1.5rem}

/* Hero header */
.brand{display:flex;align-items:center;gap:17px;margin:.1rem 0 1.65rem;padding:27px 29px;border:1px solid #273b69;border-radius:23px;background:radial-gradient(circle at 88% -35%,rgba(49,212,197,.24) 0,transparent 29%),radial-gradient(circle at 72% 130%,rgba(71,118,255,.28) 0,transparent 34%),linear-gradient(118deg,#0b1633 0%,#142751 58%,#20376a 100%);box-shadow:0 16px 38px rgba(21,39,82,.15);color:#fff;overflow:hidden}
.brand-icon{width:58px;height:58px;flex:0 0 58px;display:flex;align-items:center;justify-content:center;border-radius:18px;background:linear-gradient(135deg,#31d4c5,#5591ff);color:#071632;font-size:32px;font-weight:800;box-shadow:0 8px 25px rgba(49,212,197,.2)}
.brand-copy{min-width:0}
.brand-kicker{font-size:.67rem;letter-spacing:.17em;font-weight:800;color:#9fb5e8;margin-bottom:5px}
.brand-name{font:800 2.18rem Manrope,sans-serif;letter-spacing:-.065em;color:#fff;line-height:1.04}
.brand-name span{color:#55e3d1}
.brand-sub{font-size:.88rem;color:#c2cee8;margin-top:.42rem;line-height:1.5}
.header-pill{margin-left:auto;white-space:nowrap;border:1px solid rgba(205,221,255,.23);border-radius:999px;padding:.68rem .9rem;background:rgba(255,255,255,.07);color:#e2ebff;font-size:.68rem;letter-spacing:.09em;font-weight:800}

/* Overview intro */
.section-intro{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:.2rem 0 1.15rem;padding:.1rem 0}
.section-eyebrow{color:#5675bd;font-size:.68rem;font-weight:800;letter-spacing:.16em;margin-bottom:.32rem}
.section-heading{font:800 1.48rem Manrope,sans-serif;letter-spacing:-.045em;color:#111d3d;line-height:1.25}
.section-description{font-size:.87rem;color:#71809a;margin-top:.34rem}
.overview-chip{display:flex;align-items:center;gap:8px;white-space:nowrap;border:1px solid #dce5f5;background:#fff;border-radius:999px;padding:.62rem .85rem;color:#5a6b89;font-size:.75rem;font-weight:700;box-shadow:0 3px 12px rgba(26,49,91,.04)}
.overview-dot,.sync-dot{width:8px;height:8px;display:inline-block;border-radius:50%;background:#31c7a7;box-shadow:0 0 0 3px rgba(49,199,167,.14)}

/* KPI cards */
.metric-card{position:relative;overflow:hidden;background:rgba(255,255,255,.96);border:1px solid #e2e9f4;border-radius:18px;padding:1.05rem 1.1rem;min-height:118px;box-shadow:0 7px 22px rgba(27,51,94,.045);transition:transform .18s ease,box-shadow .18s ease}
.metric-card:before{content:"";position:absolute;top:0;left:0;width:100%;height:4px;background:linear-gradient(90deg,#31d4c5,#4776ff 58%,#8764ff)}
.metric-row{display:flex;align-items:center;gap:13px}
.metric-icon{height:47px;width:47px;flex:0 0 47px;border-radius:15px;display:flex;align-items:center;justify-content:center;background:linear-gradient(145deg,#eaf8fb,#eef2ff);font-size:22px;color:#405fe5}
.metric-value{font:800 1.82rem Manrope,sans-serif;color:#101a35;line-height:1.14;letter-spacing:-.045em}
.metric-label{font-weight:800;color:#293855;font-size:.82rem;margin-top:.13rem}
.metric-note{font-size:.72rem;color:#8490a6;margin-top:.25rem}

/* Panels and sections */
.panel-title{font:800 1.08rem Manrope,sans-serif;color:#14213e;letter-spacing:-.025em}
.panel-sub{font-size:.82rem;color:#79869e;margin:.28rem 0 1rem;line-height:1.5}
.panel-icon{display:inline-flex;width:36px;height:36px;align-items:center;justify-content:center;border-radius:12px;background:#eef4ff;color:#4269e8;margin-right:9px;font-size:20px;vertical-align:middle}
.company-card{background:#fff;border:1px solid #e4eaf4;border-radius:15px;padding:.85rem 1rem;margin:.48rem 0;box-shadow:0 4px 12px rgba(27,51,94,.025)}
.company-name{font-weight:800;color:#172544}
.company-url{font-size:.77rem;color:#8290a8;overflow-wrap:anywhere;margin-top:.18rem}
.status{display:inline-block;border-radius:999px;padding:.28rem .62rem;background:#e9f8f4;color:#148269;font-size:.7rem;font-weight:800;letter-spacing:.01em}
.small-muted{font-size:.78rem;color:#7b879d}

/* Streamlit inputs */
label, [data-testid="stWidgetLabel"]{color:#34435f!important;font-weight:700!important}
div[data-baseweb="input"]>div,div[data-baseweb="textarea"]>div,div[data-baseweb="select"]>div{border-color:#dce4f0!important;border-radius:11px!important;background:#fff!important}
div[data-baseweb="input"]>div:focus-within,div[data-baseweb="textarea"]>div:focus-within,div[data-baseweb="select"]>div:focus-within{border-color:#7290ff!important;box-shadow:0 0 0 3px rgba(71,118,255,.1)!important}
div[data-testid="stFileUploader"]{background:#f8faff;border:1px dashed #c8d5ed;border-radius:14px;padding:.55rem}

/* Buttons */
div.stButton>button,div.stFormSubmitButton>button,div[data-testid="stDownloadButton"]>button{border-radius:11px;font-weight:800;min-height:2.55rem;border:1px solid #dbe4f3;background:#fff;color:#2b3b5b;transition:all .15s ease;box-shadow:0 2px 4px rgba(28,48,86,.025)}
div.stButton>button:hover,div.stFormSubmitButton>button:hover,div[data-testid="stDownloadButton"]>button:hover{border-color:#a9bbf8;color:#335ce0;transform:translateY(-1px);box-shadow:0 6px 14px rgba(43,75,150,.09)}
div.stButton>button[kind="primary"],div.stFormSubmitButton>button[kind="primary"]{background:linear-gradient(110deg,#3769ef,#6c62ff);border:0;color:#fff;box-shadow:0 6px 15px rgba(70,100,235,.19)}
div.stButton>button[kind="primary"]:hover,div.stFormSubmitButton>button[kind="primary"]:hover{color:#fff;box-shadow:0 8px 18px rgba(70,100,235,.26)}

/* Tables, expanders, alerts, progress */
[data-testid="stDataFrame"]{border:1px solid #e1e8f3;border-radius:14px;overflow:hidden;background:#fff}
[data-testid="stTable"]{border-radius:12px;overflow:hidden}
div[data-testid="stProgress"]>div>div{background:linear-gradient(90deg,#31d4c5,#4776ff,#8764ff)}
details[data-testid="stExpander"]{border:1px solid #e0e7f2;border-radius:16px;background:rgba(255,255,255,.76);overflow:hidden}
details[data-testid="stExpander"] summary{font-weight:800;color:#1d2b49}
div[data-testid="stAlert"]{border-radius:13px}
hr{border-color:#e3e9f3}
[data-testid="stCaptionContainer"]{color:#8290a6}

@media(max-width:900px){.block-container{padding-left:1rem;padding-right:1rem}.brand{padding:22px;gap:13px}.header-pill{display:none}.metric-value{font-size:1.55rem}}
@media(max-width:600px){.brand{align-items:flex-start;padding:19px;border-radius:19px}.brand-icon{width:47px;height:47px;flex-basis:47px;border-radius:14px;font-size:26px}.brand-name{font-size:1.8rem}.brand-sub{font-size:.8rem}.section-intro{align-items:flex-start}.overview-chip{display:none}}
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


def clear_saved_job_data() -> tuple[int, int]:
    """Delete saved job rows and local crawler exports, preserving company settings."""
    cfg = load_config()
    configured_exports = [
        CSV,
        ROOT / "job_requirements.xlsx",
        Path(str(cfg.get("export_csv", "job_requirements.csv"))),
        Path(str(cfg.get("export_excel", "job_requirements.xlsx"))),
    ]
    safe_exports: set[Path] = set()
    for path in configured_exports:
        candidate = path if path.is_absolute() else ROOT / path
        resolved = candidate.resolve()
        # Never delete files outside this application's folder.
        if resolved != ROOT and ROOT in resolved.parents:
            safe_exports.add(resolved)

    database_rows_deleted = 0
    url = db_url()
    if url:
        engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
        try:
            with engine.begin() as conn:
                if sqlalchemy_inspect(conn).has_table("job_postings"):
                    database_rows_deleted = int(
                        conn.execute(sql_text("SELECT COUNT(*) FROM job_postings")).scalar_one()
                    )
                    conn.execute(sql_text("DELETE FROM job_postings"))
                # Remove a stale crawler staging table if a previous scan was interrupted.
                conn.execute(sql_text("DROP TABLE IF EXISTS job_postings_scan_stage"))
        except Exception as exc:
            raise RuntimeError(
                "The database could not be cleared, so local exports were left untouched. "
                f"Database error: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            engine.dispose()

    files_deleted = 0
    for path in safe_exports:
        try:
            if path.is_file():
                path.unlink()
                files_deleted += 1
        except OSError as exc:
            raise RuntimeError(
                f"Database rows were cleared, but could not delete local export {path.name}: {exc}"
            ) from exc
    return database_rows_deleted, files_deleted


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
    '<div class="brand"><div class="brand-icon">⌁</div><div class="brand-copy">'
    '<div class="brand-kicker">HIRING INTELLIGENCE WORKSPACE</div>'
    '<div class="brand-name"><span>Role</span>Radar</div>'
    '<div class="brand-sub">Track career pages. Discover roles. Verify opportunities.</div></div>'
    '<div style="flex:1"></div><div class="header-pill">JOB DISCOVERY WORKSPACE</div></div>',
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="section-intro"><div><div class="section-eyebrow">WORKSPACE OVERVIEW</div>'
    '<div class="section-heading">Hiring activity, at a glance</div>'
    '<div class="section-description">Your watchlist, detected job postings, and recent hiring activity.</div></div>'
    '<div class="overview-chip"><span class="overview-dot"></span> Results overview</div></div>',
    unsafe_allow_html=True,
)

data, db_error = load_results()
cleanup_notice = st.session_state.pop("cleanup_notice", None)
if cleanup_notice:
    st.success(cleanup_notice)
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

# Snapshot metrics, company watchlist, role distribution, and searchable job records.
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


with st.expander("Data cleanup · Clear previous job results", expanded=False):
    st.markdown("**Start with a clean results list**")
    st.warning(
        "This permanently deletes all saved job-posting rows and local crawler CSV/XLSX exports. "
        "Your configured companies and crawler settings will be kept."
    )
    with st.form("clear_job_data_form", clear_on_submit=True):
        confirm_clear = st.checkbox("I understand this will delete all previous job results.")
        submit_clear = st.form_submit_button("Delete all previous job data", type="primary")
    if submit_clear:
        if not confirm_clear:
            st.error("Check the confirmation box before deleting previous job data.")
        else:
            try:
                rows_deleted, files_deleted = clear_saved_job_data()
                st.session_state["cleanup_notice"] = (
                    f"Previous job data cleared. Database rows deleted: {rows_deleted:,}. "
                    f"Local export files deleted: {files_deleted:,}. Company settings were preserved."
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Could not fully clear previous data: {exc}")


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
