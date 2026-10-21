from __future__ import annotations

import json
import os
import io
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, inspect as sqlalchemy_inspect, text as sql_text

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.json"
CSV = ROOT / "job_requirements.csv"
AGENT = ROOT / "agent.py"
SCAN_WORKER = ROOT / "scan_worker.py"
SCAN_STATE = ROOT / ".roleradar_scan_state.json"
SCAN_DIR = ROOT / ".roleradar_runs"
LOGO_SVG = ROOT / "roleradar_logo.svg"
OPEN_STATUSES = {"likely open", "open", "active", "currently open"}
LISTING_TITLES = {
    "careers", "career", "jobs", "job", "open positions", "current openings",
    "job search", "search jobs", "search roles", "find jobs", "find your next role", "join our team", "join us",
    "career opportunities", "job opportunities", "all positions", "all open positions", "all openings",
    "available roles", "open roles", "search openings", "careers and jobs",
}
LISTING_ENDINGS = {
    "career", "careers", "jobs", "job", "open-positions", "open_positions", "openpositions",
    "positions", "openings", "current-openings", "current_openings", "job-search", "job_search",
    "career-search", "career_search", "role-search", "role_search", "search-roles", "search_roles",
    "search-jobs", "search_jobs", "search", "vacancies", "vacancy", "all-jobs", "all_jobs",
    "all-openings", "all_openings", "find-jobs", "find_jobs", "job-listings", "job_listings",
    "job-board", "job_board", "positions-list", "positions_list", "job-opportunities", "job_opportunities",
    "career-opportunities", "career_opportunities", "listings", "browse-jobs", "browse_jobs",
}

st.set_page_config(page_title="RoleRadar", page_icon="🎯", layout="wide", initial_sidebar_state="expanded")

st.markdown(r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
:root{--ink:#17233e;--muted:#71809a;--line:#e4e9f2;--blue:#5865f2;--purple:#7c65f7;--mint:#68e0c1;--canvas:#f6f8fc;--navy:#111a31}
html,body,[class*="css"]{font-family:'DM Sans',sans-serif}
.stApp{background:radial-gradient(ellipse at 92% -8%,#e6ebff 0,transparent 31%),radial-gradient(ellipse at 2% 28%,#def9f0 0,transparent 24%),linear-gradient(180deg,#f8faff 0%,#f6f8fc 58%,#f9fbff 100%);color:var(--ink)}
.block-container{max-width:1380px;padding:1.55rem 2rem 3rem}
[data-testid="stHeader"]{background:transparent}
[data-testid="stSidebar"]{background:linear-gradient(155deg,#10182d 0%,#172642 57%,#1c2e4e 100%);border-right:1px solid #293855;box-shadow:8px 0 32px #16274a0d}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p{color:#d5dfef}
[data-testid="stSidebar"] hr{border-color:#354661;margin:1rem 0}
.brand-row{display:flex;align-items:center;gap:.72rem;padding:.25rem .1rem .35rem}
.brand-icon{display:flex;width:46px;height:46px;flex:0 0 46px;align-items:center;justify-content:center;filter:drop-shadow(0 6px 12px #5375ef24)}.brand-icon svg{display:block;width:46px;height:46px}
.brand-wordmark{font:800 1.34rem Manrope,sans-serif;letter-spacing:-.055em;color:#fff;line-height:1.15}.brand-wordmark span{color:#76ebd0}.brand-sub{font-size:.73rem;color:#a9b8d1!important;margin:.1rem 0 1.2rem!important;line-height:1.5}
.sidebar-eyebrow{font-size:.62rem;letter-spacing:.14em;text-transform:uppercase;color:#7f94b5;font-weight:800;margin:.45rem 0 .45rem .15rem}
[data-testid="stSidebar"] [data-testid="stRadio"] label{padding:.62rem .72rem;border-radius:12px;margin:.1rem 0;border:1px solid transparent;transition:background .18s ease,border-color .18s ease}
[data-testid="stSidebar"] [data-testid="stRadio"] label p{color:#c4d0e4!important;font-weight:600;font-size:.91rem}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked){background:linear-gradient(105deg,#354d7b,#2b3e66);border:1px solid #49638d;box-shadow:inset 3px 0 #76ead1,0 5px 14px #050b1833}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) p{color:#fff!important}
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover{background:#ffffff0c}
div.stButton>button,div[data-testid="stDownloadButton"]>button,div[data-testid="stLinkButton"]>a,div.stFormSubmitButton>button{border-radius:12px;font-weight:700;min-height:2.65rem;border:1px solid #dce4f1;background:#fff;color:#344562;box-shadow:0 3px 8px #172b4d05;transition:all .18s ease}
div.stButton>button[kind="primary"],div.stFormSubmitButton>button[kind="primary"]{background:linear-gradient(110deg,#5865f2,#8264f7);color:#fff;border-color:#665ff3;box-shadow:0 7px 18px #625ff02e}
div.stButton>button:hover,div[data-testid="stLinkButton"]>a:hover,div[data-testid="stDownloadButton"]>button:hover{border-color:#aab7ee;color:#4658da;transform:translateY(-1px)}
label,[data-testid="stWidgetLabel"]{color:#394862!important;font-weight:700!important}
div[data-baseweb="input"]>div,div[data-baseweb="select"]>div{border-color:#dce5f1!important;border-radius:12px!important;min-height:44px;background:#fff}
.page-title{font:800 2.28rem Manrope,sans-serif;letter-spacing:-.065em;color:#17233e;margin:0;line-height:1.18}
.page-subtitle{font-size:.93rem;color:#75829a;margin:.48rem 0 1.35rem;line-height:1.65;max-width:900px}
.stat-row{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:.8rem 0 1.45rem}
.stat-card{position:relative;overflow:hidden;padding:1.05rem 1.15rem;background:linear-gradient(140deg,#fff 0%,#fbfcff 100%);border:1px solid #e4e9f3;border-radius:18px;box-shadow:0 10px 28px #20375b08}
.stat-card:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:linear-gradient(180deg,#5865f2,#68e0c1)}
.stat-label{font-size:.74rem;color:#77859c;font-weight:700;letter-spacing:.01em}.stat-value{font:800 1.9rem Manrope,sans-serif;letter-spacing:-.06em;color:#192744;margin-top:.25rem}.stat-note{font-size:.72rem;color:#96a1b3;margin-top:.15rem}
.progress-card{padding:1.2rem 1.25rem 1.05rem;margin:.45rem 0 1.3rem;border:1px solid #e0e7f4;border-radius:20px;background:linear-gradient(128deg,#fff 0%,#f7f8ff 54%,#effcf8 100%);box-shadow:0 12px 32px #263c720c}
.progress-head{display:flex;justify-content:space-between;gap:15px;align-items:flex-start;margin-bottom:.85rem}.progress-kicker{font-size:.65rem;font-weight:800;letter-spacing:.13em;color:#7182a1;text-transform:uppercase;margin-bottom:.3rem}.progress-title{font:800 1.06rem Manrope,sans-serif;color:#1a2947}.progress-note{font-size:.79rem;color:#7887a0;margin-top:.3rem;line-height:1.5}.progress-percent{font:800 1.65rem Manrope,sans-serif;color:#5a62ed;white-space:nowrap}.progress-percent small{display:block;font:800 .58rem 'DM Sans',sans-serif;letter-spacing:.1em;text-transform:uppercase;color:#8996ad;text-align:right;margin-top:.2rem}
.progress-track{height:14px;background:#e8edf7;border:1px solid #e0e7f2;border-radius:999px;overflow:hidden;box-shadow:inset 0 2px 4px #182b4c0c}.progress-fill{height:100%;border-radius:999px;background:linear-gradient(90deg,#5865f2 0%,#8969f7 52%,#61dec0 100%);box-shadow:0 2px 9px #576ce64a;transition:width .6s ease;position:relative}.progress-fill.running:after{content:"";position:absolute;inset:0;transform:translateX(-100%);background:linear-gradient(100deg,transparent 20%,#ffffffa8 48%,transparent 74%);animation:shimmer 1.8s ease-in-out infinite}@keyframes shimmer{to{transform:translateX(100%)}}
.progress-foot{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;font-size:.72rem;color:#8794a8;margin-top:.72rem}
.job-card{padding:1rem 1.15rem;background:linear-gradient(145deg,#fff,#fcfdff);border:1px solid var(--line);border-radius:17px;box-shadow:0 6px 20px #20375b06;margin:.6rem 0;transition:transform .16s ease,border-color .16s ease,box-shadow .16s ease}.job-card:hover{border-color:#cbd5f3;transform:translateY(-2px);box-shadow:0 12px 28px #22375b0c}.job-title{font:800 1.04rem Manrope,sans-serif;letter-spacing:-.025em;color:#1e2c49}.job-company{font-weight:700;color:#5663ce;margin-top:.22rem}.job-meta{font-size:.78rem;color:#7b89a0;margin-top:.48rem}.job-description{font-size:.82rem;line-height:1.6;color:#596983;margin-top:.7rem}.company-card{padding:.95rem 1.05rem;border:1px solid var(--line);border-radius:15px;background:#fff;margin:.5rem 0;box-shadow:0 4px 14px #20375b04}.empty{padding:2rem 1.1rem;border:1px dashed #cbd7e9;border-radius:17px;background:#ffffffb8;text-align:center;color:#7c8aa0}.empty strong{display:block;color:#344562;margin-bottom:.3rem}
div[data-testid="stVerticalBlockBorderWrapper"]{border-color:var(--line)!important;border-radius:17px!important;background:#ffffffd9;box-shadow:0 5px 18px #20375b04}
[data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:13px;overflow:hidden}
div[data-testid="stMetric"]{background:linear-gradient(140deg,#fff,#fbfcff);border:1px solid var(--line);border-radius:16px;padding:.9rem 1rem;box-shadow:0 6px 18px #20375b06}
div[data-testid="stMetricLabel"]{color:#77859c;font-weight:700}div[data-testid="stMetricValue"]{font-family:Manrope,sans-serif;color:#192744}
[data-testid="stPlotlyChart"],[data-testid="stVegaLiteChart"]{border-radius:14px}
[data-testid="stAlert"]{border-radius:13px}
@media(max-width:760px){.block-container{padding:.95rem .72rem 2rem}.page-title{font-size:1.8rem}.stat-row{gap:7px}.stat-card{padding:.8rem}.stat-value{font-size:1.45rem}.progress-head{gap:8px}.progress-percent{font-size:1.3rem}.brand-icon{width:42px;height:42px;flex-basis:42px}.brand-icon svg{width:42px;height:42px}}
@media(prefers-reduced-motion:reduce){.progress-fill,.progress-fill:after,.job-card{animation:none!important;transition:none!important}}
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
        value = "postgresql+psycopg://" + value[len("postgres://"):]
    elif value.startswith("postgresql://") and "+" not in value.split(":", 1)[0]:
        value = "postgresql+psycopg://" + value[len("postgresql://"):]
    return value


def load_config() -> dict:
    defaults = {
        "companies": [],
        "max_pages_per_domain": 80,
        "request_delay_seconds": 2.0,
        "job_url_keywords": ["job", "jobs", "career", "careers", "opening", "position", "vacancy", "requisition", "apply", "role"],
        "exclude_url_keywords": ["privacy", "terms", "cookie", "login", "signup"],
        "enable_playwright": True,
    }
    try:
        stored = json.loads(CONFIG.read_text(encoding="utf-8"))
        if isinstance(stored, dict):
            defaults.update(stored)
    except (OSError, json.JSONDecodeError):
        pass
    return defaults


def save_config(cfg: dict) -> None:
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def normalized_url(value: object) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    if not url.lower().startswith(("https://", "http://")):
        url = "https://" + url
    parts = urlparse(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return ""
    return url.rstrip("/")


def normalize_companies(rows: list[dict]) -> list[dict]:
    clean_rows: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        lowered = {str(k).strip().lower(): v for k, v in row.items()}
        name = str(lowered.get("name") or lowered.get("company") or lowered.get("company_name") or "").strip()
        url = normalized_url(lowered.get("career_url") or lowered.get("careers_url") or lowered.get("url") or lowered.get("website_url"))
        if not name or not url or name.upper() == "ADD COMPANY NAME":
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        supplied = lowered.get("allowed_domains", []) or []
        if isinstance(supplied, str):
            supplied = re.split(r"[,;\s]+", supplied)
        domains = [host]
        if isinstance(supplied, (tuple, list, set)):
            for raw_domain in supplied:
                raw_domain = str(raw_domain).strip()
                if not raw_domain:
                    continue
                parsed_host = urlparse(raw_domain if "://" in raw_domain else "https://" + raw_domain).hostname
                domain = (parsed_host or "").lower().removeprefix("www.")
                if domain and domain not in domains:
                    domains.append(domain)
        clean_rows.append({"name": name, "career_url": url, "allowed_domains": domains})
    return clean_rows


def save_companies(companies: list[dict]) -> None:
    cfg = load_config()
    cfg["companies"] = normalize_companies(companies)
    save_config(cfg)


def listing_title(value: object) -> bool:
    title = re.split(r"\s+[|–—-]\s+", str(value or "").strip(), maxsplit=1)[0].strip().lower()
    if title in LISTING_TITLES:
        return True
    return bool(re.fullmatch(r"(?:careers? at .+|jobs? at .+|career opportunities at .+|job opportunities at .+|open roles at .+|explore (?:our )?careers?|careers? and jobs|work (?:at|with us)|life at .+|join (?:our team|us))", title, re.I))


def is_landing_url(value: object) -> bool:
    url = str(value or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return True
    parts = urlparse(url)
    path = (parts.path or "").rstrip("/").lower()
    segments = [part for part in path.split("/") if part]
    last = segments[-1] if segments else ""
    query = (parts.query or "").lower()
    if re.search(r"(?:^|&)(?:gh_jid|jobid|job_id|reqid|requisitionid|postingid|positionid|jid|id)=?[^&]+", query):
        return False
    if last in LISTING_ENDINGS:
        return True
    host = (parts.hostname or "").lower().removeprefix("www.")
    ats_domains = ("greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "smartrecruiters.com", "icims.com", "workable.com", "bamboohr.com", "jobvite.com", "teamtailor.com", "recruitee.com")
    is_ats = any(host == domain or host.endswith("." + domain) for domain in ats_domains)
    if is_ats and len(segments) <= 1:
        return True
    if is_ats and len(segments) == 2 and last in {"jobs", "careers", "positions", "openings", "search"}:
        return True
    return False


def filter_actual_open_records(frame: pd.DataFrame, companies: list[dict]) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    if "job_status" not in frame.columns or "extraction_note" not in frame.columns:
        return frame.iloc[0:0].copy()
    verified = frame["extraction_note"].fillna("").astype(str).str.startswith("Verified individual job posting page.")
    allowed_status = frame["job_status"].fillna("").astype(str).str.strip().str.lower().isin(OPEN_STATUSES)
    result = frame.loc[verified & allowed_status].copy()
    seeds = {str(row.get("name", "")).strip().lower(): normalized_url(row.get("career_url", "")).rstrip("/").lower() for row in companies}
    keep_indexes = []
    for index, row in result.iterrows():
        title = str(row.get("job_title", "") or "").strip()
        url = str(row.get("source_url", "") or "").strip()
        company = str(row.get("company", "") or "").strip().lower()
        if not title or listing_title(title) or is_landing_url(url):
            continue
        if not url.lower().startswith(("http://", "https://")):
            continue
        seed = seeds.get(company, "")
        if seed and url.rstrip("/").lower() == seed:
            continue
        keep_indexes.append(index)
    result = result.loc[keep_indexes].copy()
    if "source_url" in result.columns:
        result = result.drop_duplicates(subset=["source_url"], keep="last")
    return result.reset_index(drop=True)


def read_scan_state() -> dict:
    try:
        stored = json.loads(SCAN_STATE.read_text(encoding="utf-8"))
        return stored if isinstance(stored, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_scan_state(state: dict) -> None:
    SCAN_DIR.mkdir(parents=True, exist_ok=True)
    temp = SCAN_STATE.with_name(f".{SCAN_STATE.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temp.replace(SCAN_STATE)


def process_is_alive(pid: object) -> bool:
    try:
        process_id = int(pid)
        if process_id <= 0:
            return False
        os.kill(process_id, 0)
        stat_path = Path(f"/proc/{process_id}/stat")
        if stat_path.exists() and len(stat_path.read_text(encoding="utf-8").split()) > 2:
            if stat_path.read_text(encoding="utf-8").split()[2] == "Z":
                return False
        return True
    except (TypeError, ValueError, OSError):
        return False


def current_scan_state() -> dict:
    state = read_scan_state()
    if state.get("status") in {"running", "starting"} and state.get("worker_pid") and not process_is_alive(state.get("worker_pid")):
        state["status"] = "failed"
        state["message"] = "The scan stopped before it could finish. Start it again to retry."
        state["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_scan_state(state)
    return state


def load_results() -> tuple[pd.DataFrame, bool]:
    cfg_companies = normalize_companies(load_config().get("companies", []))
    url = db_url()
    if url:
        engine = None
        try:
            engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
            with engine.connect() as conn:
                if not sqlalchemy_inspect(conn).has_table("job_postings"):
                    return pd.DataFrame(), False
                frame = pd.read_sql(sql_text("SELECT * FROM job_postings ORDER BY company, job_title"), conn).fillna("")
            return filter_actual_open_records(frame, cfg_companies), False
        except Exception:
            return pd.DataFrame(), True
        finally:
            if engine is not None:
                engine.dispose()
    if CSV.exists():
        try:
            return filter_actual_open_records(pd.read_csv(CSV).fillna(""), cfg_companies), False
        except Exception:
            return pd.DataFrame(), True
    return pd.DataFrame(), False


def start_scan(companies: list[dict], mode: str = "all") -> None:
    selected = normalize_companies(companies)
    if not selected:
        st.warning("Add a company before starting a scan.")
        return
    if not db_url():
        st.warning("Scanning is not ready yet. Please ask your app administrator to finish the setup.")
        return
    if not AGENT.exists() or not SCAN_WORKER.exists():
        st.error("The scanning service is unavailable. Please redeploy the app files and try again.")
        return
    state_before = current_scan_state()
    if state_before.get("status") in {"running", "starting"}:
        st.info("A scan is already running. Its progress is shown below.")
        return

    SCAN_DIR.mkdir(parents=True, exist_ok=True)
    scan_id = uuid.uuid4().hex[:12]
    cfg = load_config()
    cfg["companies"] = selected
    config_path = SCAN_DIR / f"config_{scan_id}.json"
    config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    log_path = SCAN_DIR / f"scan_{scan_id}.log"
    log_path.write_text("Starting scan…\n", encoding="utf-8")
    state = {
        "scan_id": scan_id,
        "status": "starting",
        "mode": mode,
        "companies": [row["name"] for row in selected],
        "company_count": len(selected),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path),
        "log_path": str(log_path),
        "worker_pid": None,
        "message": "Your scan is starting.",
    }
    write_scan_state(state)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["DATABASE_URL"] = db_url()
    if mode == "30_days":
        env["SCAN_POSTED_WITHIN_DAYS"] = "30"
    else:
        env.pop("SCAN_POSTED_WITHIN_DAYS", None)
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(SCAN_WORKER), "--scan-id", scan_id,
             "--config", str(config_path), "--state", str(SCAN_STATE), "--log", str(log_path)],
            cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True,
        )
        latest = read_scan_state()
        latest["worker_pid"] = proc.pid
        latest["status"] = "running"
        write_scan_state(latest)
        st.session_state["last_started_scan_id"] = scan_id
        st.success("Scan started. You can keep using RoleRadar while it runs.")
        st.rerun()
    except Exception:
        state["status"] = "failed"
        state["message"] = "The scan could not be started. Please try again."
        state["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_scan_state(state)
        st.error(state["message"])


def get_scan_summary(state: dict) -> dict:
    log_path = Path(str(state.get("log_path", ""))) if state.get("log_path") else None
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace") if log_path and log_path.exists() else ""
    except OSError:
        content = ""
    lines = content.splitlines()
    company_headers = [line[4:-4].strip() for line in lines if line.startswith("=== ") and line.endswith(" ===")]
    completed = sum(1 for line in lines if line.startswith("Company summary:"))
    visited = re.findall(r"Visited\s+(\d+)/(\d+)", content)
    pages_current = int(visited[-1][0]) if visited else 0
    max_pages = int(visited[-1][1]) if visited else 20
    role_urls = set(re.findall(r"JOB FOUND \[Likely open\]:.*?\|\s*(https?://\S+)", content))
    total_companies = max(1, int(state.get("company_count", 1) or 1))
    current_fraction = min(0.85, (pages_current / max(1, max_pages)) * 0.85)
    fraction = min(0.99, (completed + current_fraction) / total_companies)
    return {
        "content": content,
        "current_company": company_headers[-1] if company_headers else "Preparing your scan",
        "completed_companies": completed,
        "total_companies": total_companies,
        "pages_current": pages_current,
        "roles_found": len(role_urls),
        "fraction": fraction,
    }


def render_scan_monitor_content(state: dict) -> None:
    if not state:
        return
    status = str(state.get("status", "idle"))
    summary = get_scan_summary(state)
    if status == "completed":
        percent, title, note, current = 100, "Scan complete — your jobs are ready", "Your saved open positions have been refreshed.", "All companies checked"
    elif status == "failed":
        percent = min(99, max(0, round(summary["fraction"] * 100)))
        title, note, current = "Scan stopped before completion", str(state.get("message", "Please start the scan again.")), summary["current_company"]
    else:
        percent = min(99, max(3, round(summary["fraction"] * 100)))
        if summary["roles_found"]:
            title, note = "Checking individual job postings", "Reviewing job links and saving confirmed open roles."
        elif summary["pages_current"]:
            title, note = "Looking for open positions", "Checking careers listings for direct links to individual roles."
        else:
            title, note = "Starting your scan", "Connecting to company careers pages."
        current = summary["current_company"]
    status_class = "done" if status == "completed" else ("failed" if status == "failed" else "running")
    animation = "running" if status in {"running", "starting"} else ""
    html = f'''<div class="progress-card">
      <div class="progress-head"><div><div class="progress-kicker">● &nbsp; ROLE RADAR SCAN</div>
      <div class="progress-title">{escape(title)}</div><div class="progress-note">{escape(note)}</div></div>
      <div class="progress-percent">{percent}%<small>complete</small></div></div>
      <div class="progress-track" role="progressbar" aria-valuenow="{percent}" aria-valuemin="0" aria-valuemax="100">
      <div class="progress-fill {animation}" style="width:{percent}%"></div></div>
      <div class="progress-foot"><span>Companies: <strong>{min(summary['completed_companies'], summary['total_companies'])} of {summary['total_companies']}</strong></span>
      <span>Open roles found: <strong>{summary['roles_found']}</strong></span><span>Now checking: <strong>{escape(current)}</strong></span></div></div>'''
    st.markdown(html, unsafe_allow_html=True)
    if status == "failed":
        st.warning(note)
    if status in {"completed", "failed"}:
        scan_id = str(state.get("scan_id", ""))
        if scan_id and st.session_state.get("scan_completion_seen") != scan_id:
            st.session_state["scan_completion_seen"] = scan_id
            st.rerun()


@st.fragment(run_every="2s")
def render_live_scan_monitor() -> None:
    render_scan_monitor_content(current_scan_state())


def render_scan_monitor() -> None:
    state = current_scan_state()
    if not state:
        return
    if state.get("status") in {"running", "starting"}:
        render_live_scan_monitor()
    else:
        render_scan_monitor_content(state)


def display_date(value: object) -> str:
    raw = str(value or "").strip()
    if not raw or raw.lower() in {"nan", "nat", "none"}:
        return ""
    dt = pd.to_datetime(raw, errors="coerce", utc=True)
    if pd.isna(dt):
        return raw[:20]
    return dt.strftime("%b %d, %Y")


def set_navigation(page_name: str) -> None:
    st.session_state["nav"] = page_name


def render_job_cards(frame: pd.DataFrame, limit: int | None = None) -> None:
    if frame.empty:
        st.markdown('<div class="empty"><strong>No individual open jobs found yet</strong>Add companies and run a scan. RoleRadar will show direct links to job postings here—not general careers pages.</div>', unsafe_allow_html=True)
        return
    shown = frame.head(limit) if limit else frame
    for _, row in shown.iterrows():
        title = str(row.get("job_title", "Open position")).strip()
        company = str(row.get("company", "Company")).strip() or "Company"
        location = str(row.get("location_mention", "")).strip()
        employment = str(row.get("employment_type_mention", "")).strip()
        posted = display_date(row.get("date_posted", ""))
        desc = re.sub(r"\s+", " ", str(row.get("description", "")).strip())
        if len(desc) > 300:
            desc = desc[:297].rsplit(" ", 1)[0] + "…"
        url = str(row.get("source_url", "")).strip()
        with st.container(border=True):
            left, right = st.columns([5, 1.35])
            with left:
                st.markdown(f'<div class="job-title">{escape(title)}</div><div class="job-company">{escape(company)}</div>', unsafe_allow_html=True)
                meta = [x for x in [location, employment, f"Posted {posted}" if posted else ""] if x and x.lower() not in {"nan", "none"}]
                st.markdown(f'<div class="job-meta">{escape(" · ".join(meta) if meta else "Open position")}</div>', unsafe_allow_html=True)
                if desc:
                    st.markdown(f'<div class="job-description">{escape(desc)}</div>', unsafe_allow_html=True)
            with right:
                if url.startswith(("https://", "http://")):
                    st.link_button("View job posting ↗", url, use_container_width=True)
                else:
                    st.caption("Job link unavailable")


def build_role_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """Group equivalent job titles and show how widely each role appears."""
    columns = ["_role_key", "Job role", "Openings", "Companies hiring", "Companies"]
    if frame.empty or "job_title" not in frame.columns:
        return pd.DataFrame(columns=columns)

    work = frame.copy()
    work["job_title"] = work["job_title"].fillna("").astype(str).str.strip()
    work["_role_key"] = work["job_title"].str.casefold()
    work = work[work["_role_key"].ne("") & ~work["_role_key"].isin({"nan", "none", "nat"})]
    if work.empty:
        return pd.DataFrame(columns=columns)
    if "company" not in work.columns:
        work["company"] = "Company not specified"
    work["company"] = work["company"].fillna("").astype(str).str.strip().replace({"": "Company not specified", "nan": "Company not specified"})

    grouped = work.groupby("_role_key", dropna=False).agg(
        **{
            "Job role": ("job_title", "first"),
            "Openings": ("job_title", "size"),
            "Companies hiring": ("company", "nunique"),
            "Companies": ("company", lambda values: ", ".join(sorted(set(v for v in values.astype(str) if v.strip())))),
        }
    ).reset_index()
    return grouped.sort_values(["Openings", "Companies hiring", "Job role"], ascending=[False, False, True]).reset_index(drop=True)


def _clean_category_counts(frame: pd.DataFrame, column: str, label: str, limit: int = 10) -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return pd.DataFrame(columns=[label, "Openings"])
    values = frame[column].fillna("").astype(str).str.strip()
    values = values.mask(values.eq("") | values.str.lower().isin({"nan", "none", "nat"}), "Not specified")
    result = values.value_counts().head(limit).rename_axis(label).rename("Openings").reset_index()
    return result


def export_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the user-facing job fields in a stable, readable order."""
    mapping = {
        "job_title": "Job title", "company": "Company", "location_mention": "Location",
        "date_posted": "Date posted", "employment_type_mention": "Employment type",
        "work_arrangement_mention": "Work arrangement", "experience_mentions": "Experience",
        "salary_mention": "Salary", "description": "Job description",
        "source_url": "Job posting URL",
    }
    cols = [name for name in mapping if name in frame.columns]
    return frame[cols].rename(columns=mapping)


def build_excel_export(frame: pd.DataFrame, sheet_name: str = "Open jobs") -> bytes:
    """Create a styled Excel workbook with clickable individual-job links."""
    from openpyxl.styles import Alignment, Font, PatternFill

    output = io.BytesIO()
    workbook_data = export_columns(frame).copy()
    if "Job posting URL" in workbook_data.columns:
        urls = workbook_data["Job posting URL"].fillna("").astype(str)
        workbook_data.insert(
            1 if "Job title" in workbook_data.columns else 0,
            "View job description",
            urls.map(lambda value: "View job description ↗" if value.startswith(("https://", "http://")) else ""),
        )

    # Keep the worksheet name within Excel's 31-character limit.
    safe_sheet_name = (sheet_name or "Open jobs")[:31]
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        workbook_data.to_excel(writer, index=False, sheet_name=safe_sheet_name)
        ws = writer.sheets[safe_sheet_name]
        ws.freeze_panes = "A2"
        if ws.max_row >= 1 and ws.max_column >= 1:
            ws.auto_filter.ref = ws.dimensions

        header_fill = PatternFill(fill_type="solid", fgColor="172642")
        header_font = Font(name="Aptos", bold=True, color="FFFFFF", size=10)
        link_font = Font(name="Aptos", color="4F46E5", underline="single", size=10)
        body_font = Font(name="Aptos", color="263653", size=10)
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.row_dimensions[1].height = 30

        column_positions = {str(cell.value): cell.column for cell in ws[1]}
        link_col = column_positions.get("View job description")
        url_col = column_positions.get("Job posting URL")
        desc_col = column_positions.get("Job description")
        title_col = column_positions.get("Job title")
        company_col = column_positions.get("Company")

        for row_idx in range(2, ws.max_row + 1):
            ws.row_dimensions[row_idx].height = 32
            for cell in ws[row_idx]:
                cell.font = body_font
                cell.alignment = Alignment(vertical="top", wrap_text=(cell.column == desc_col))
            url = str(ws.cell(row=row_idx, column=url_col).value or "").strip() if url_col else ""
            if url.startswith(("https://", "http://")):
                if link_col:
                    link_cell = ws.cell(row=row_idx, column=link_col)
                    link_cell.hyperlink = url
                    link_cell.font = link_font
                    link_cell.alignment = Alignment(vertical="top")
                if url_col:
                    url_cell = ws.cell(row=row_idx, column=url_col)
                    url_cell.hyperlink = url
                    url_cell.font = link_font
                    url_cell.alignment = Alignment(vertical="top", wrap_text=True)
            # Keep long descriptions readable without making every row excessively tall.
            if desc_col:
                description = str(ws.cell(row=row_idx, column=desc_col).value or "")
                if description:
                    ws.row_dimensions[row_idx].height = min(96, max(38, 24 + (len(description) // 95) * 12))

        for col_idx in range(1, ws.max_column + 1):
            header = str(ws.cell(row=1, column=col_idx).value or "")
            if header == "Job title":
                width = 34
            elif header == "View job description":
                width = 25
            elif header == "Company":
                width = 27
            elif header == "Location":
                width = 24
            elif header == "Job description":
                width = 62
            elif header == "Job posting URL":
                width = 46
            elif header in {"Date posted", "Employment type", "Work arrangement", "Experience", "Salary"}:
                width = 20
            else:
                width = 18
            ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = width

    return output.getvalue()


# Session settings
cfg = load_config()
companies = normalize_companies(cfg.get("companies", []))
if "nav" not in st.session_state or st.session_state.get("nav") not in {"Overview", "Job dashboard", "Open jobs", "Companies"}:
    st.session_state["nav"] = "Overview"

with st.sidebar:
    # Inline the local SVG so the logo remains visible on Render and does not rely on a remote image host.
    try:
        logo_markup = LOGO_SVG.read_text(encoding="utf-8")
    except OSError:
        logo_markup = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="46" height="46"><rect width="64" height="64" rx="18" fill="#5865f2"/><circle cx="32" cy="32" r="20" fill="none" stroke="#fff" stroke-opacity=".55" stroke-width="2"/><circle cx="32" cy="32" r="13" fill="none" stroke="#fff" stroke-opacity=".7" stroke-width="2"/><path d="M32 32 48 16" stroke="#68e0c1" stroke-width="4" stroke-linecap="round"/><circle cx="32" cy="32" r="4" fill="#68e0c1"/></svg>"""
    st.markdown(f'<div class="brand-row"><div class="brand-icon">{logo_markup}</div><div class="brand-wordmark">Role<span>Radar</span></div></div><p class="brand-sub">Find real, open job opportunities.</p><div class="sidebar-eyebrow">Workspace</div>', unsafe_allow_html=True)
    st.radio("Menu", ["Overview", "Job dashboard", "Open jobs", "Companies"], key="nav", label_visibility="collapsed")
    st.markdown("---")
    if st.button("Scan all companies", type="primary", use_container_width=True, key="sidebar_scan_all"):
        start_scan(companies, "all")
    state_sidebar = current_scan_state()
    if state_sidebar.get("status") in {"running", "starting"}:
        st.caption("A scan is running in the background.")
    st.markdown("<div style='margin-top:1.1rem;padding:.75rem .8rem;border-radius:13px;background:#ffffff0b;border:1px solid #ffffff14;color:#aebed7;font-size:.72rem;line-height:1.55'>Only individual job postings<br><span style='color:#73e6ce;font-weight:700'>Verified open roles</span></div>", unsafe_allow_html=True)

page = st.session_state["nav"]
data, results_error = load_results()
if results_error:
    st.warning("Saved jobs could not be loaded right now. Please refresh or ask your app administrator for help.")

# Keep scan progress visible wherever the user navigates.
active_scan = current_scan_state()
if active_scan:
    render_scan_monitor()

if page == "Overview":
    st.markdown('<div class="page-title">Your open jobs</div><div class="page-subtitle">Individual job listings gathered from the careers pages you follow.</div>', unsafe_allow_html=True)
    if not active_scan:
        st.caption("Use **Scan all companies** in the left menu to refresh the latest openings. Scans run in the background.")

    total_jobs = len(data)
    count_companies = int(data["company"].astype(str).nunique()) if not data.empty and "company" in data.columns else 0
    recent_count = 0
    if not data.empty and "date_posted" in data.columns:
        dates = pd.to_datetime(data["date_posted"], errors="coerce", utc=True)
        recent_count = int((dates >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)).sum())
    st.markdown(f'''<div class="stat-row">
      <div class="stat-card"><div class="stat-label">Open job listings</div><div class="stat-value">{total_jobs:,}</div><div class="stat-note">Individual postings only</div></div>
      <div class="stat-card"><div class="stat-label">Companies hiring</div><div class="stat-value">{count_companies:,}</div><div class="stat-note">With open roles found</div></div>
      <div class="stat-card"><div class="stat-label">Posted in 30 days</div><div class="stat-value">{recent_count:,}</div><div class="stat-note">Based on posting dates</div></div>
    </div>''', unsafe_allow_html=True)
    dash_button_col, dash_note_col = st.columns([1.1, 3.2], gap="medium")
    with dash_button_col:
        st.button("View job dashboard →", key="overview_job_dashboard", on_click=set_navigation, args=("Job dashboard",), use_container_width=True)
    with dash_note_col:
        st.caption("Compare the most common job roles, which companies are hiring for them, and where openings are concentrated.")

    st.markdown("### Latest job listings")
    if not data.empty:
        if "last_seen_utc" in data.columns:
            latest = data.sort_values("last_seen_utc", ascending=False, na_position="last")
        elif "date_posted" in data.columns:
            latest = data.sort_values("date_posted", ascending=False, na_position="last")
        else:
            latest = data
        render_job_cards(latest, limit=8)
        st.button("See all open jobs →", key="all_open_jobs", on_click=set_navigation, args=("Open jobs",))
    else:
        render_job_cards(data)
        if not companies:
            st.info("Start by adding companies on the Companies page.")

elif page == "Job dashboard":
    st.markdown('<div class="page-title">Overall Job Dashboard Summary</div><div class="page-subtitle">A cross-company view of the open roles RoleRadar has verified. Use the charts to see which roles are most common and which companies are hiring.</div>', unsafe_allow_html=True)

    all_role_summary = build_role_summary(data)
    total_open_jobs = int(len(data))
    total_hiring_companies = int(data["company"].fillna("").astype(str).str.strip().replace("", pd.NA).nunique()) if not data.empty and "company" in data.columns else 0
    total_distinct_roles = int(len(all_role_summary))
    recent_open_jobs = 0
    if not data.empty and "date_posted" in data.columns:
        posted_dates = pd.to_datetime(data["date_posted"], errors="coerce", utc=True)
        recent_open_jobs = int((posted_dates >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)).sum())

    k1, k2, k3, k4 = st.columns(4, gap="medium")
    k1.metric("Open job listings", f"{total_open_jobs:,}")
    k2.metric("Different job roles", f"{total_distinct_roles:,}")
    k3.metric("Companies hiring", f"{total_hiring_companies:,}")
    k4.metric("Posted in last 30 days", f"{recent_open_jobs:,}")

    st.markdown("### Compare job roles across companies")
    filter_col, role_search_col = st.columns([1.1, 2], gap="medium")
    dash_company_options = ["All companies"]
    if not data.empty and "company" in data.columns:
        dash_company_options += sorted(n for n in data["company"].dropna().astype(str).unique() if n.strip() and n.lower() != "nan")
    with filter_col:
        dash_company = st.selectbox("Company filter", dash_company_options, key="dashboard_company_filter")
    with role_search_col:
        dash_role_search = st.text_input("Find a job role", placeholder="e.g. Data Engineer, Claims Analyst, QA Lead", key="dashboard_role_search")

    dashboard_data = data.copy()
    if dash_company != "All companies" and "company" in dashboard_data.columns:
        dashboard_data = dashboard_data[dashboard_data["company"].astype(str) == dash_company]
    if dash_role_search.strip() and "job_title" in dashboard_data.columns:
        dashboard_data = dashboard_data[dashboard_data["job_title"].astype(str).str.contains(dash_role_search.strip(), case=False, regex=False, na=False)]

    role_summary = build_role_summary(dashboard_data)
    st.caption(f"Showing {len(dashboard_data):,} open listing(s) across {dashboard_data['company'].nunique() if not dashboard_data.empty and 'company' in dashboard_data.columns else 0:,} company/companies for this view. The headline figures above always summarize all saved open jobs.")

    chart_left, chart_right = st.columns(2, gap="large")
    with chart_left:
        st.markdown("#### Most common job roles")
        if not role_summary.empty:
            chart_roles = role_summary.head(12).set_index("Job role")[["Openings"]]
            st.bar_chart(chart_roles, height=330, use_container_width=True, horizontal=True)
        else:
            st.info("No job roles match the selected filters yet.")
    with chart_right:
        st.markdown("#### Companies with the most openings")
        company_chart = _clean_category_counts(dashboard_data, "company", "Company", 12)
        if not company_chart.empty:
            st.bar_chart(company_chart.set_index("Company")[["Openings"]], height=330, use_container_width=True, horizontal=True)
        else:
            st.info("Company comparisons will appear after open jobs are found.")

    if not role_summary.empty:
        st.markdown("### Job role summary across companies")
        role_display = role_summary[["Job role", "Openings", "Companies hiring", "Companies"]].head(50).copy()
        st.dataframe(role_display, use_container_width=True, hide_index=True, column_config={
            "Job role": st.column_config.TextColumn("Job role", help="Job title as listed by the employer"),
            "Openings": st.column_config.NumberColumn("Openings", format="%d"),
            "Companies hiring": st.column_config.NumberColumn("Companies hiring", format="%d"),
            "Companies": st.column_config.TextColumn("Companies with this role", help="Companies with at least one matching open job"),
        })

        st.markdown("### Company-by-role comparison")
        st.caption("Counts show how many matching open postings each company has for each job title. This matrix uses the 15 most common roles and 12 companies in the current view.")
        role_keys = role_summary.head(15)["_role_key"].tolist()
        if "company" in dashboard_data.columns:
            top_companies = dashboard_data["company"].fillna("").astype(str).value_counts().head(12).index.tolist()
            matrix_source = dashboard_data.copy()
            matrix_source["_role_key"] = matrix_source["job_title"].fillna("").astype(str).str.strip().str.casefold()
            matrix_source = matrix_source[matrix_source["_role_key"].isin(role_keys) & matrix_source["company"].astype(str).isin(top_companies)]
            role_labels = role_summary.set_index("_role_key")["Job role"].to_dict()
            matrix_source["Job role"] = matrix_source["_role_key"].map(role_labels)
            if not matrix_source.empty:
                matrix = matrix_source.pivot_table(index="Job role", columns="company", values="job_title", aggfunc="count", fill_value=0)
                matrix = matrix.loc[matrix.sum(axis=1).sort_values(ascending=False).index]
                st.dataframe(matrix, use_container_width=True)
            else:
                st.info("No role/company combinations match the current filters.")

    breakdown_left, breakdown_right = st.columns(2, gap="large")
    with breakdown_left:
        st.markdown("#### Openings by location")
        location_chart = _clean_category_counts(dashboard_data, "location_mention", "Location", 10)
        if not location_chart.empty:
            st.bar_chart(location_chart.set_index("Location")[["Openings"]], height=300, use_container_width=True, horizontal=True)
        else:
            st.caption("Location details will appear when employers provide them.")
    with breakdown_right:
        st.markdown("#### Openings by employment type")
        employment_chart = _clean_category_counts(dashboard_data, "employment_type_mention", "Employment type", 8)
        if not employment_chart.empty:
            st.bar_chart(employment_chart.set_index("Employment type")[["Openings"]], height=300, use_container_width=True, horizontal=True)
        else:
            st.caption("Employment type details will appear when available.")

    if not dashboard_data.empty:
        download_csv_col, download_excel_col, _ = st.columns([1, 1, 2], gap="small")
        with download_csv_col:
            st.download_button(
                "Download CSV",
                data=export_columns(dashboard_data).to_csv(index=False).encode("utf-8-sig"),
                file_name="roleradar_job_dashboard.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with download_excel_col:
            st.download_button(
                "Download Excel (.xlsx)",
                data=build_excel_export(dashboard_data, "Job dashboard"),
                file_name="roleradar_job_dashboard.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="download_dashboard_excel",
            )
    else:
        st.markdown('<div class="empty"><strong>No matching job listings</strong>Run a scan or change the selected company or role filter.</div>', unsafe_allow_html=True)

elif page == "Open jobs":
    st.markdown('<div class="page-title">Open job listings</div><div class="page-subtitle">Search real roles and open the direct posting to review or apply.</div>', unsafe_allow_html=True)
    search_col, company_col = st.columns([2.2, 1], gap="medium")
    with search_col:
        query = st.text_input("Search jobs", placeholder="Job title, company, skill, or location", key="jobs_query")
    company_options = ["All companies"]
    if not data.empty and "company" in data.columns:
        company_options.extend(sorted(name for name in data["company"].dropna().astype(str).unique() if name.strip()))
    with company_col:
        chosen_company = st.selectbox("Company", company_options, key="jobs_company")
    filtered = data.copy()
    if chosen_company != "All companies" and "company" in filtered.columns:
        filtered = filtered[filtered["company"].astype(str) == chosen_company]
    if query.strip():
        terms = [col for col in ["job_title", "company", "location_mention", "description", "employment_type_mention"] if col in filtered.columns]
        matched = pd.Series(False, index=filtered.index)
        for col in terms:
            matched |= filtered[col].astype(str).str.contains(query.strip(), case=False, regex=False, na=False)
        filtered = filtered[matched]
    st.caption(f"{len(filtered):,} open job listing(s)")
    out = export_columns(filtered)
    download_csv_col, download_excel_col, _ = st.columns([1, 1, 2], gap="small")
    with download_csv_col:
        st.download_button(
            "Download CSV",
            data=out.to_csv(index=False).encode("utf-8-sig"),
            file_name="roleradar_open_jobs.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with download_excel_col:
        st.download_button(
            "Download Excel (.xlsx)",
            data=build_excel_export(filtered, "Open jobs"),
            file_name="roleradar_open_jobs.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="download_open_jobs_excel",
        )
    render_job_cards(filtered)

elif page == "Companies":
    st.markdown('<div class="page-title">Companies</div><div class="page-subtitle">Choose the official careers or open-positions page for each company. RoleRadar will find the individual job postings from there.</div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("### Add a company")
        with st.form("add_company_form", clear_on_submit=True):
            name = st.text_input("Company name", placeholder="e.g. Acme Insurance")
            career_url = st.text_input("Careers or open positions URL", placeholder="https://company.com/careers")
            submitted = st.form_submit_button("Add company", type="primary", use_container_width=False)
        if submitted:
            new_row = {"name": name.strip(), "career_url": normalized_url(career_url)}
            if not new_row["name"] or not new_row["career_url"]:
                st.error("Enter a company name and a valid careers-page URL.")
            elif any(r["career_url"].lower().rstrip("/") == new_row["career_url"].lower().rstrip("/") for r in companies):
                st.warning("That company URL is already in your watchlist.")
            else:
                companies = normalize_companies(companies + [new_row])
                save_companies(companies)
                st.success(f"{name.strip()} added.")
                st.rerun()

    with st.container(border=True):
        head_l, head_r = st.columns([4, 1])
        with head_l:
            st.markdown("### Your watchlist")
            st.caption(f"{len(companies)} compan(ies) added")
        with head_r:
            if st.button("Scan all", type="primary", use_container_width=True, key="companies_scan_all"):
                start_scan(companies, "all")
        if not companies:
            st.markdown('<div class="empty"><strong>No companies added yet</strong>Add a company above to start finding open roles.</div>', unsafe_allow_html=True)
        else:
            state = current_scan_state()
            active_names = set(state.get("companies", [])) if state.get("status") in {"running", "starting"} else set()
            for index, company in enumerate(companies):
                with st.container(border=True):
                    left, scan_col, remove_col = st.columns([4, 1.15, .85])
                    with left:
                        st.markdown(f"**{company['name']}**")
                        st.caption("Scan running" if company["name"] in active_names else "Official careers page connected")
                    with scan_col:
                        if st.button("Scan", key=f"scan_company_{index}", use_container_width=True):
                            start_scan([company], "company")
                    with remove_col:
                        if st.button("Remove", key=f"remove_company_{index}", use_container_width=True):
                            companies = [row for i, row in enumerate(companies) if i != index]
                            save_companies(companies)
                            st.rerun()

    with st.expander("Import a company list"):
        uploaded = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx"], key="company_import")
        if uploaded is not None:
            try:
                df = pd.read_csv(uploaded) if uploaded.name.lower().endswith(".csv") else pd.read_excel(uploaded)
                rows = df.rename(columns={col: str(col).strip().lower() for col in df.columns}).to_dict("records")
                imported = normalize_companies(rows)
                st.caption(f"{len(imported)} valid companies found in the file.")
                if st.button("Import companies", type="primary", key="import_company_list"):
                    companies = normalize_companies(companies + imported)
                    save_companies(companies)
                    st.success("Company list imported.")
                    st.rerun()
            except Exception:
                st.error("This file could not be read. Please upload a valid CSV or Excel file with company names and careers-page URLs.")
