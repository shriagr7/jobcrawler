from __future__ import annotations

import io
import json
from html import escape
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
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

st.set_page_config(
    page_title="RoleRadar",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
:root{--ink:#14213d;--muted:#71809a;--line:#e5eaf4;--blue:#5068e8;--blue-dark:#344ac8;--mint:#70e2c9;--canvas:#f4f7fc;--nav:#111b32;--purple:#8276ff;--surface:#fff}
html,body,[class*="css"]{font-family:'DM Sans',sans-serif}
.stApp{background:radial-gradient(ellipse at 92% 0%,#e5efff 0,transparent 27%),radial-gradient(ellipse at 0% 34%,#e6fbf6 0,transparent 23%),var(--canvas);color:var(--ink)}
.block-container{max-width:1510px;padding:1.65rem 2.25rem 3.5rem}
[data-testid="stHeader"]{background:transparent}
[data-testid="stToolbar"]{right:1.3rem}
::selection{background:#cad7ff;color:#17213c}

/* A more deliberate app shell */
[data-testid="stSidebar"]{background:linear-gradient(160deg,#10192e 0%,#172747 58%,#20365a 100%);border-right:1px solid #263958}
[data-testid="stSidebar"]>div:first-child{padding-top:1.25rem}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p{color:#c1cde1}
[data-testid="stSidebar"] hr{border-color:#30405e;margin:1.1rem 0}
.sidebar-brand{display:flex;align-items:center;gap:12px;padding:.4rem .25rem 1.05rem}
.sidebar-mark{height:45px;width:45px;display:flex;align-items:center;justify-content:center;border-radius:15px;background:linear-gradient(135deg,#93f1d7 0%,#8bb2ff 100%);color:#15203a;font:800 1.55rem Manrope,sans-serif;box-shadow:0 9px 24px #050a174d;position:relative}
.sidebar-name{font:800 1.52rem Manrope,sans-serif;letter-spacing:-.065em;color:#fff;line-height:1.08}
.sidebar-name span{color:#83eed8}
.sidebar-caption{font-size:.68rem;color:#9eafd0;letter-spacing:.025em;margin-top:5px}
.sidebar-label{font-size:.64rem!important;letter-spacing:.16em;text-transform:uppercase;font-weight:800;color:#8297ba!important;margin:.9rem 0 .4rem}
[data-testid="stSidebar"] [data-testid="stRadio"]>div{gap:5px}
[data-testid="stSidebar"] [data-testid="stRadio"] label{padding:.68rem .75rem;border-radius:12px;border:1px solid transparent;transition:all .16s ease;margin:.04rem 0}
[data-testid="stSidebar"] [data-testid="stRadio"] label p{font-size:.88rem;font-weight:600;color:#bac7de!important}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked){background:linear-gradient(100deg,#2a4167,#26395a);border-color:#3a5277;box-shadow:inset 3px 0 0 #77e6d1,0 5px 16px #080f1e20}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) p{color:#fff!important}
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover{background:#233653;border-color:#304768}
[data-testid="stSidebar"] [data-testid="stRadio"] label>div:first-child{display:none}
[data-testid="stSidebar"] div.stButton>button{background:linear-gradient(110deg,#6883ff,#7067f1);color:#fff;border:0;box-shadow:0 8px 22px #0a14304d}
[data-testid="stSidebar"] div.stButton>button:hover{background:linear-gradient(110deg,#8297ff,#8a7dff);color:#fff;border:0;transform:translateY(-1px)}
.sidebar-footer{border-top:1px solid #2d3e5d;margin-top:1.15rem;padding-top:.95rem;color:#97a8c7;font-size:.72rem;line-height:1.7}
.sidebar-status-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#70e2c9;margin-right:8px;box-shadow:0 0 0 4px #70e2c91b}

/* Workspace header */
.page-topline{display:flex;justify-content:space-between;align-items:center;gap:16px;margin:.1rem 0 1rem;color:#8b98ad;font-size:.66rem;font-weight:800;letter-spacing:.15em;text-transform:uppercase}
.topline-mark{color:#5b70df}
.page-heading{display:flex;justify-content:space-between;align-items:flex-end;gap:22px;margin:0 0 1.3rem}
.page-heading-copy{min-width:0}
.eyebrow{display:inline-flex;align-items:center;gap:7px;font-size:.65rem;letter-spacing:.15em;font-weight:800;color:#526ad7;text-transform:uppercase;margin-bottom:.52rem}
.eyebrow:before{content:"";display:inline-block;height:7px;width:7px;border-radius:50%;background:#6adbc2;box-shadow:0 0 0 4px #6adbc226}
.page-title{font:800 2.16rem Manrope,sans-serif;color:#14213d;letter-spacing:-.06em;line-height:1.08;margin:0}
.page-description{color:#74829a;font-size:.9rem;line-height:1.58;margin:.55rem 0 0;max-width:730px}
.workspace-pill{display:inline-flex;align-items:center;gap:8px;white-space:nowrap;padding:.66rem .9rem;border:1px solid #dce7f4;background:#ffffffc9;border-radius:999px;color:#4e607c;font-size:.72rem;font-weight:700;box-shadow:0 4px 14px #1b315008}
.pill-dot{height:7px;width:7px;border-radius:50%;display:inline-block;background:#35c49c;box-shadow:0 0 0 4px #35c49c1a}

/* Overview feature banner */
.hero-panel{isolation:isolate;position:relative;display:flex;align-items:center;justify-content:space-between;gap:24px;min-height:218px;padding:1.65rem 1.8rem;margin:.15rem 0 1.35rem;border-radius:23px;overflow:hidden;background:linear-gradient(112deg,#14213d 0%,#263f79 53%,#4a58b5 100%);box-shadow:0 18px 40px #233a731b}
.hero-panel:before{content:"";position:absolute;width:420px;height:420px;border-radius:50%;right:-90px;top:-220px;background:radial-gradient(circle,#8a8fff66 0,transparent 70%);z-index:-1}
.hero-panel:after{content:"";position:absolute;width:350px;height:350px;border-radius:50%;right:90px;bottom:-280px;border:1px solid #b5d4ff25;box-shadow:0 0 0 34px #b5d4ff0c,0 0 0 72px #b5d4ff09;z-index:-1}
.hero-copy{max-width:620px;position:relative;z-index:2}
.hero-kicker{display:inline-flex;align-items:center;gap:8px;color:#a7f2e3;font-size:.65rem;font-weight:800;letter-spacing:.16em;text-transform:uppercase;margin-bottom:.7rem}
.hero-kicker span{height:7px;width:7px;background:#7be9d2;border-radius:50%;box-shadow:0 0 0 4px #7be9d21a}
.hero-title{font:800 1.9rem/1.16 Manrope,sans-serif;letter-spacing:-.055em;color:white;margin:0;max-width:550px}
.hero-title span{color:#8debd7}
.hero-description{font-size:.84rem;line-height:1.65;color:#c8d5ed;margin:.72rem 0 0;max-width:520px}
.hero-tags{display:flex;flex-wrap:wrap;gap:8px;margin-top:1.15rem}
.hero-tag{display:inline-flex;align-items:center;gap:6px;padding:.42rem .65rem;border-radius:999px;background:#ffffff11;border:1px solid #ffffff24;color:#e4ecff;font-size:.67rem;font-weight:700}
.hero-art{width:260px;min-width:225px;height:170px;position:relative;display:flex;align-items:center;justify-content:center}
.hero-orbit{position:absolute;border:1px solid #c4d4ff30;border-radius:50%;width:165px;height:165px;transform:rotate(-22deg)}
.hero-orbit-two{width:220px;height:122px;transform:rotate(35deg);border-color:#8eead729}
.hero-orbit-three{width:126px;height:126px;transform:rotate(58deg);border-style:dashed;border-color:#c7d5ff38}
.hero-core{height:73px;width:73px;border-radius:23px;display:flex;align-items:center;justify-content:center;background:linear-gradient(145deg,#a0f3df,#8daeff);color:#162447;font:800 1.85rem Manrope,sans-serif;box-shadow:0 12px 36px #09142f61;transform:rotate(-7deg);z-index:1}
.hero-float{position:absolute;padding:.62rem .78rem;border-radius:13px;background:#ffffffed;box-shadow:0 12px 28px #09142f38;color:#182744;z-index:2;min-width:118px}
.hero-float-label{font-size:.58rem;letter-spacing:.08em;font-weight:800;color:#7d8ba3;text-transform:uppercase}
.hero-float-value{font:800 1.2rem Manrope,sans-serif;letter-spacing:-.04em;margin-top:.12rem}
.hero-float-note{font-size:.62rem;color:#75839b;margin-top:.1rem}
.hero-float-one{top:2px;right:0}
.hero-float-two{left:0;bottom:1px}
.hero-float-dot{display:inline-block;height:6px;width:6px;border-radius:50%;background:#35c49c;margin-right:5px}

/* KPI cards */
.metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:.4rem 0 1.6rem}
.metric-card{position:relative;min-height:126px;padding:1.08rem 1.12rem 1rem;background:linear-gradient(160deg,#fff 0%,#fcfdff 100%);border:1px solid #e4eaf3;border-radius:17px;box-shadow:0 5px 18px #172b4d08;overflow:hidden;transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
.metric-card:hover{transform:translateY(-3px);box-shadow:0 12px 25px #172b4d10;border-color:#d4def2}
.metric-top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:.9rem}
.metric-label{font-size:.76rem;color:#71809a;font-weight:700;line-height:1.3}
.metric-icon{height:36px;width:36px;border-radius:12px;display:flex;align-items:center;justify-content:center;background:#eef2ff;color:#5068e8;font-size:1.05rem;font-weight:800}
.metric-card:nth-child(2) .metric-icon{background:#e7faf4;color:#159a7c}
.metric-card:nth-child(3) .metric-icon{background:#f0edff;color:#7965e8}
.metric-card:nth-child(4) .metric-icon{background:#fff5e8;color:#cc8539}
.metric-value{font:800 1.9rem Manrope,sans-serif;color:#162440;line-height:1;letter-spacing:-.06em}
.metric-note{font-size:.69rem;color:#8a97ac;margin-top:.5rem;line-height:1.35}
.metric-accent{height:3px;position:absolute;left:0;bottom:0;right:0;background:linear-gradient(90deg,#73e4ce,#7388ff);opacity:.83}

/* Panels and empty states */
.section-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin:.15rem 0 .95rem}
.section-title{font:800 1.02rem Manrope,sans-serif;color:#1a2946;letter-spacing:-.03em}
.section-subtitle{font-size:.78rem;line-height:1.55;color:#8190a7;margin-top:.28rem}
.panel-kicker{font-size:.63rem;letter-spacing:.14em;font-weight:800;text-transform:uppercase;color:#7c8aa3;margin:.25rem 0 .65rem}
.panel-surface{padding:1rem 1.05rem;background:#fff;border:1px solid #e4eaf3;border-radius:17px;box-shadow:0 5px 18px #172b4d06}
.empty-state{padding:2rem 1rem;border:1px dashed #d4deed;border-radius:15px;background:linear-gradient(145deg,#fcfdff,#f7f9fe);text-align:center;color:#7a879d}
.empty-state-title{font:800 1rem Manrope,sans-serif;color:#344361;margin-bottom:.4rem}
.status{display:inline-block;border-radius:999px;padding:.26rem .62rem;background:#e8f8f1;color:#188368;font-size:.68rem;font-weight:800}
.company-name{font-weight:800;color:#1e2b46}
.company-url{font-size:.73rem;color:#8491a6;overflow-wrap:anywhere;margin-top:.2rem}
div[data-testid="stVerticalBlockBorderWrapper"]{border-color:#e3eaf4!important;border-radius:17px!important;box-shadow:0 5px 18px #172b4d06;background:#ffffffd9;transition:box-shadow .16s ease,border-color .16s ease}
div[data-testid="stVerticalBlockBorderWrapper"]:hover{border-color:#d7e1f2!important}

/* Inputs, buttons, tables and charts */
label,[data-testid="stWidgetLabel"]{color:#35435c!important;font-weight:700!important}
div[data-baseweb="input"]>div,div[data-baseweb="textarea"]>div,div[data-baseweb="select"]>div{border-color:#dfe6f0!important;border-radius:11px!important;background:#fff!important;min-height:42px}
div[data-baseweb="input"]>div:focus-within,div[data-baseweb="textarea"]>div:focus-within,div[data-baseweb="select"]>div:focus-within{border-color:#8799f3!important;box-shadow:0 0 0 3px #5576ed14!important}
input,textarea{font-family:'DM Sans',sans-serif!important}
div[data-testid="stFileUploader"]{background:#fbfcff;border:1px dashed #cbd6e8;border-radius:13px;padding:.55rem}
div.stButton>button,div.stFormSubmitButton>button,div[data-testid="stDownloadButton"]>button{border-radius:11px;font-weight:700;min-height:2.55rem;border:1px solid #dfe6f0;background:#fff;color:#35435c;transition:all .16s ease;box-shadow:0 2px 5px #1d31500a}
div.stButton>button:hover,div.stFormSubmitButton>button:hover,div[data-testid="stDownloadButton"]>button:hover{border-color:#aebcf4;color:#405ed5;box-shadow:0 6px 14px #2b4b9610;transform:translateY(-1px)}
div.stButton>button[kind="primary"],div.stFormSubmitButton>button[kind="primary"]{background:linear-gradient(110deg,#5069e9,#6d66ed);border:1px solid #5069e9;color:white;box-shadow:0 6px 15px #4b67e826}
div.stButton>button[kind="primary"]:hover,div.stFormSubmitButton>button[kind="primary"]:hover{background:linear-gradient(110deg,#405bd7,#5a54db);color:white;border-color:#405bd7}
[data-testid="stDataFrame"]{border:1px solid #e3e9f2;border-radius:13px;overflow:hidden;background:#fff;box-shadow:0 3px 10px #1c315008}
[data-testid="stTable"]{border-radius:12px;overflow:hidden}
[data-testid="stDataFrame"] [role="columnheader"]{font-weight:800!important}
div[data-testid="stProgress"]>div>div{background:linear-gradient(90deg,#70e0c9,#657df3)}
/* Premium live scan progress */
.scan-progress-card{position:relative;overflow:hidden;margin:.8rem 0 1.05rem;padding:1.15rem 1.2rem 1rem;border:1px solid #dfe7f5;border-radius:19px;background:linear-gradient(130deg,#fff 0%,#f8faff 54%,#f0fbf9 100%);box-shadow:0 12px 30px #263c720c}
.scan-progress-card:before{content:"";position:absolute;width:230px;height:230px;right:-92px;top:-148px;border-radius:50%;background:radial-gradient(circle,#95a5ff2c 0%,transparent 70%);pointer-events:none}
.scan-progress-head{position:relative;display:flex;align-items:flex-start;justify-content:space-between;gap:18px;margin-bottom:.95rem}
.scan-progress-kicker{display:flex;align-items:center;gap:8px;color:#7888a5;font-size:.64rem;font-weight:800;letter-spacing:.13em;text-transform:uppercase;margin-bottom:.35rem}
.scan-live-dot{width:8px;height:8px;border-radius:50%;background:#35c49c;box-shadow:0 0 0 4px #35c49c1c;display:inline-block;flex:none}.scan-live-dot.is-complete{background:#16866f;box-shadow:0 0 0 4px #16866f1c}.scan-live-dot.is-failed{background:#d55858;box-shadow:0 0 0 4px #d558581c}
.scan-progress-title{font:800 1.08rem Manrope,sans-serif;color:#1a2947;letter-spacing:-.035em;line-height:1.35}
.scan-progress-subtitle{color:#7b89a1;font-size:.76rem;line-height:1.5;margin-top:.25rem;max-width:650px;overflow-wrap:anywhere}
.scan-progress-percent{position:relative;flex:none;min-width:76px;text-align:right;color:#354ac8;font:800 1.65rem/1 Manrope,sans-serif;letter-spacing:-.07em}
.scan-progress-percent small{display:block;margin-top:.35rem;color:#8794aa;font:800 .58rem 'DM Sans',sans-serif;letter-spacing:.12em;text-transform:uppercase}
.scan-progress-track{position:relative;height:13px;border-radius:999px;background:#e7edf7;border:1px solid #e0e7f2;overflow:hidden;box-shadow:inset 0 2px 4px #182b4c0c}
.scan-progress-fill{position:relative;height:100%;min-width:0;border-radius:999px;background:linear-gradient(90deg,#4f67e8 0%,#8074f6 48%,#5fdbc2 100%);box-shadow:0 2px 9px #576ce64a;transition:width .65s cubic-bezier(.2,.7,.2,1)}
.scan-progress-fill.is-active:after{content:"";position:absolute;inset:0;transform:translateX(-100%);background:linear-gradient(100deg,transparent 20%,#ffffffa3 48%,transparent 74%);animation:scanShimmer 1.8s ease-in-out infinite}
@keyframes scanShimmer{to{transform:translateX(100%)}}
.scan-progress-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin-top:.95rem}
.scan-stat{min-width:0;padding:.65rem .75rem;border:1px solid #e6ecf5;border-radius:12px;background:#ffffffbd}
.scan-stat-label{color:#8190a8;font-size:.62rem;font-weight:800;letter-spacing:.07em;text-transform:uppercase}
.scan-stat-value{margin-top:.18rem;color:#253653;font:800 1rem Manrope,sans-serif;letter-spacing:-.025em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.scan-progress-stages{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin-top:1rem}
.scan-stage{display:flex;align-items:center;gap:7px;min-width:0;padding:.5rem .58rem;border:1px solid #e8edf5;border-radius:10px;background:#f9faff;color:#9aa6b8;font-size:.65rem;font-weight:700}
.scan-stage-number{width:20px;height:20px;flex:none;border-radius:50%;display:flex;align-items:center;justify-content:center;background:#e9eef6;color:#8593a8;font-size:.65rem;font-weight:800}
.scan-stage.is-done{border-color:#cdeee4;background:#f2fcf8;color:#287e6d}
.scan-stage.is-done .scan-stage-number{background:#c9f4e7;color:#167e68}
.scan-stage.is-current{border-color:#cdd7ff;background:#f3f5ff;color:#455bd0;box-shadow:inset 0 0 0 1px #e7eaff}
.scan-stage.is-current .scan-stage-number{background:linear-gradient(135deg,#657cf0,#8274f3);color:#fff;box-shadow:0 3px 8px #657cf038}
.scan-progress-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:.75rem;color:#8491a7;font-size:.68rem;line-height:1.45}
.scan-progress-status{display:inline-flex;align-items:center;gap:6px;color:#4961d6;font-weight:800}
.scan-progress-status.is-complete{color:#16866f}
.scan-progress-status.is-failed{color:#bf4545}
.scan-progress-status .mini-dot{height:6px;width:6px;border-radius:50%;background:currentColor;display:inline-block}
@media(max-width:760px){.scan-progress-card{padding:.95rem;border-radius:15px}.scan-progress-head{gap:10px}.scan-progress-percent{font-size:1.35rem;min-width:58px}.scan-progress-title{font-size:.98rem}.scan-progress-stats{gap:6px}.scan-stat{padding:.55rem}.scan-stat-value{font-size:.88rem}.scan-progress-stages{grid-template-columns:repeat(2,minmax(0,1fr))}.scan-stage{font-size:.63rem}.scan-progress-foot{align-items:flex-start;flex-direction:column}}
@media(prefers-reduced-motion:reduce){.scan-progress-fill,.scan-progress-fill:after{animation:none!important;transition:none!important}}
details[data-testid="stExpander"]{border:1px solid #e2e8f1;border-radius:14px;background:#fff;overflow:hidden}
details[data-testid="stExpander"] summary{font-weight:800;color:#263652;padding:.45rem .3rem}
div[data-testid="stAlert"]{border-radius:12px}
hr{border-color:#e6ebf3}
[data-testid="stCaptionContainer"]{color:#8995a8}
.scan-console{padding:.85rem 1rem;border-radius:12px;background:#111c32;color:#d8e2f5}

@media(max-width:1100px){.block-container{padding-left:1.2rem;padding-right:1.2rem}.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.page-title{font-size:1.9rem}.hero-art{width:220px;min-width:190px}.hero-panel{padding:1.4rem}}
@media(max-width:760px){.block-container{padding:1rem .8rem 2.5rem}.page-heading{align-items:flex-start;flex-direction:column;gap:12px}.workspace-pill{display:none}.metric-grid{gap:9px}.metric-card{padding:.9rem;min-height:112px}.metric-value{font-size:1.55rem}.metric-label{font-size:.7rem}.sidebar-name{font-size:1.35rem}.hero-panel{align-items:flex-start;min-height:0;padding:1.3rem;border-radius:18px}.hero-title{font-size:1.55rem}.hero-art{display:none}.hero-description{font-size:.8rem}.page-topline span:last-child{display:none}}
@media(prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
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


def filter_open_records(frame: pd.DataFrame) -> pd.DataFrame:
    """Strictly limit dashboard data to positively indicated open job postings."""
    if frame.empty or "job_status" not in frame.columns:
        return frame.iloc[0:0].copy()
    open_values = {"likely open", "open", "active", "currently open"}
    mask = frame["job_status"].fillna("").astype(str).str.strip().str.lower().isin(open_values)
    return frame.loc[mask].copy().reset_index(drop=True)


def read_scan_state() -> dict:
    try:
        state = json.loads(SCAN_STATE.read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_scan_state(state: dict) -> None:
    SCAN_STATE.parent.mkdir(parents=True, exist_ok=True)
    temp = SCAN_STATE.with_name(f".{SCAN_STATE.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temp.replace(SCAN_STATE)


def pid_is_alive(pid: object) -> bool:
    try:
        process_id = int(pid)
        if process_id <= 0:
            return False
        os.kill(process_id, 0)
        # A dead detached child can remain as a zombie until the parent reaps it.
        proc_stat = Path(f"/proc/{process_id}/stat")
        if proc_stat.exists():
            fields = proc_stat.read_text(encoding="utf-8").split()
            if len(fields) > 2 and fields[2] == "Z":
                return False
        return True
    except (TypeError, ValueError, OSError):
        return False


def current_scan_state() -> dict:
    state = read_scan_state()
    if state.get("status") == "running" and not pid_is_alive(state.get("worker_pid")):
        # Do not leave the dashboard in a permanent loading state if Render restarted.
        state["status"] = "failed"
        state["message"] = "The background worker stopped before reporting completion (possibly due to a service restart)."
        state["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_scan_state(state)
    return state


def load_results() -> tuple[pd.DataFrame, str | None]:
    url = db_url()
    if url:
        engine = None
        try:
            engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
            with engine.connect() as conn:
                df = pd.read_sql(sql_text("SELECT * FROM job_postings"), conn)
            return filter_open_records(df.fillna("")), None
        except Exception as exc:
            return pd.DataFrame(), str(exc)
        finally:
            if engine is not None:
                engine.dispose()
    if CSV.exists():
        try:
            return filter_open_records(pd.read_csv(CSV).fillna("")), None
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
    if not AGENT.exists() or not SCAN_WORKER.exists():
        st.error("agent.py and scan_worker.py must be in the same repository folder as streamlit_app.py.")
        return

    existing = current_scan_state()
    if existing.get("status") in {"running", "starting"}:
        st.warning("A scan is already running in the background. Follow its progress in the Scan monitor below.")
        return

    SCAN_DIR.mkdir(parents=True, exist_ok=True)
    scan_id = uuid.uuid4().hex[:12]
    selected_companies = normalize_company_rows(companies)
    cfg = load_config()
    cfg["companies"] = selected_companies
    # Do not overwrite the shared config or the full watchlist for a targeted scan.
    cfg_path = SCAN_DIR / f"config_{scan_id}.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    log_path = SCAN_DIR / f"scan_{scan_id}.log"
    log_path.write_text("Starting background worker…\n", encoding="utf-8")
    state = {
        "scan_id": scan_id,
        "status": "starting",
        "mode": mode,
        "companies": [c["name"] for c in selected_companies],
        "company_count": len(selected_companies),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "config_path": str(cfg_path),
        "log_path": str(log_path),
        "worker_pid": None,
        "message": "Background scan started.",
    }
    write_scan_state(state)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if db_url():
        env["DATABASE_URL"] = db_url()
    if mode == "30_days":
        env["SCAN_POSTED_WITHIN_DAYS"] = "30"
    else:
        env.pop("SCAN_POSTED_WITHIN_DAYS", None)

    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(SCAN_WORKER), "--scan-id", scan_id,
             "--config", str(cfg_path), "--state", str(SCAN_STATE), "--log", str(log_path)],
            cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True,
        )
        latest_state = read_scan_state()
        latest_state["worker_pid"] = proc.pid
        latest_state["status"] = "running"
        write_scan_state(latest_state)
        st.session_state["last_started_scan_id"] = scan_id
        st.success("Scan started in the background. You can navigate the dashboard while it runs.")
        st.rerun()
    except Exception as exc:
        state["status"] = "failed"
        state["message"] = f"Could not start worker: {type(exc).__name__}: {exc}"
        state["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_scan_state(state)
        st.error(state["message"])


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

# Load current data once for the selected workspace view.
data, db_error = load_results()
cleanup_notice = st.session_state.pop("cleanup_notice", None)
if cleanup_notice:
    st.success(cleanup_notice)

cfg = load_config()
company_count = len(st.session_state.companies)
job_count = len(data)
if not data.empty and "job_title" in data.columns:
    titles = data["job_title"].astype(str).str.strip()
    role_count = int(titles[titles.ne("")].nunique())
else:
    role_count = 0
if not data.empty and "date_posted" in data.columns:
    dates = pd.to_datetime(data["date_posted"], errors="coerce", utc=True)
    recent_count = int((dates >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)).sum())
else:
    recent_count = 0
if not data.empty and "job_status" in data.columns:
    likely_open_count = int(data["job_status"].astype(str).eq("Likely open").sum())
else:
    likely_open_count = 0

# Sidebar navigation and quick actions.
st.sidebar.markdown(
    '<div class="sidebar-brand"><div class="sidebar-mark">⌕</div><div>'
    '<div class="sidebar-name"><span>Role</span>Radar</div>'
    '<div class="sidebar-caption">Hiring intelligence workspace</div></div></div>',
    unsafe_allow_html=True,
)
st.sidebar.markdown('<div class="sidebar-label">Workspace</div>', unsafe_allow_html=True)
page = st.sidebar.radio(
    "Navigate",
    ["Overview", "Job board", "Companies", "Analytics", "Settings & data"],
    format_func=lambda item: {
        "Overview": "✦   Overview",
        "Job board": "⌕   Job board",
        "Companies": "▦   Companies",
        "Analytics": "↗   Analytics",
        "Settings & data": "⚙   Settings & data",
    }.get(item, item),
    label_visibility="collapsed",
    key="app_navigation",
)
st.sidebar.markdown("---")
st.sidebar.markdown('<div class="sidebar-label">Quick scan</div>', unsafe_allow_html=True)
st.sidebar.caption("Discover active roles from official careers pages only.")
if st.sidebar.button("Scan all companies", type="primary", use_container_width=True, key="sidebar_scan_all"):
    start_scan(st.session_state.companies, "all")
st.sidebar.markdown(
    '<div class="sidebar-footer"><span class="sidebar-status-dot"></span>'
    + ("Database connected" if not db_error and db_url() else "File-based results" if not db_url() else "Database needs attention")
    + '<br/>Track roles. Verify openings. Act on hiring signals.</div>',
    unsafe_allow_html=True,
)

page_copy = {
    "Overview": ("Your hiring landscape", "A clear snapshot of tracked companies and open roles discovered from official careers pages."),
    "Job board": ("Open positions", "Search and export active job postings discovered from official careers pages and approved ATS listings."),
    "Companies": ("Manage your watchlist", "Add official careers or open-positions pages, configure trusted ATS domains, and run scans."),
    "Analytics": ("Hiring intelligence", "Understand which active roles and companies account for the most open positions."),
    "Settings & data": ("Workspace settings", "Review the background worker, crawler scope, database status, and recent scan logs."),
}
page_title, page_description = page_copy[page]
st.markdown(
    '<div class="page-topline"><span><span class="topline-mark">ROLE RADAR</span> &nbsp;/&nbsp; HIRING INTELLIGENCE</span>'
    '<span>COMPANY CAREER MONITORING</span></div>'
    f'<div class="page-heading"><div class="page-heading-copy"><div class="eyebrow">{page.upper()} · WORKSPACE</div>'
    f'<h1 class="page-title">{page_title}</h1><p class="page-description">{page_description}</p></div>'
    '<div class="workspace-pill"><span class="pill-dot"></span> Open positions only</div></div>',
    unsafe_allow_html=True,
)


def render_metric(icon: str, label: str, value: int, note: str) -> str:
    return (
        '<div class="metric-card"><div class="metric-top"><div class="metric-label">' + label + '</div>'
        '<div class="metric-icon">' + icon + '</div></div><div class="metric-value">' + f'{value:,}' + '</div>'
        '<div class="metric-note">' + note + '</div><div class="metric-accent"></div></div>'
    )


def render_status(value: object) -> str:
    safe = str(value or "Needs verification").strip()
    return safe if safe else "Needs verification"


def job_frame(source: pd.DataFrame, default_status: bool = True) -> pd.DataFrame:
    frame = source.copy()
    if default_status and "job_status" not in frame.columns:
        frame["job_status"] = "Needs verification"
    if "job_status" in frame.columns:
        frame["job_status"] = frame["job_status"].astype(str).replace({"": "Needs verification", "nan": "Needs verification"})
    return frame


def filter_job_frame(frame: pd.DataFrame, status: str, company: str, query: str, location: str = "All locations") -> pd.DataFrame:
    filtered = frame.copy()
    # The entire workspace is intentionally limited to active/open postings.
    filtered = filter_open_records(filtered)
    if company != "All companies" and "company" in filtered.columns:
        filtered = filtered[filtered["company"].astype(str) == company]
    if location != "All locations" and "location_mention" in filtered.columns:
        filtered = filtered[filtered["location_mention"].astype(str) == location]
    if query.strip():
        q = query.strip().lower()
        searchable = [c for c in ["job_title", "company", "location_mention", "description", "employment_type_mention"] if c in filtered.columns]
        matched = pd.Series(False, index=filtered.index)
        for col in searchable:
            matched = matched | filtered[col].astype(str).str.lower().str.contains(q, regex=False, na=False)
        filtered = filtered[matched]
    return filtered


def navigate_to(page_name: str) -> None:
    """Switch the sidebar page through a Streamlit widget callback."""
    st.session_state.app_navigation = page_name


def render_jobs_table(frame: pd.DataFrame, height: int = 440) -> None:
    if frame.empty:
        st.markdown('<div class="empty-state"><div class="empty-state-title">No matching job postings</div>Try changing your filters, or run a scan to discover new roles.</div>', unsafe_allow_html=True)
        return
    display_cols = [c for c in [
        "job_title", "company", "job_status", "date_posted", "valid_through",
        "location_mention", "employment_type_mention", "work_arrangement_mention",
        "last_seen_utc", "source_url"
    ] if c in frame.columns]
    column_config = {
        "source_url": st.column_config.LinkColumn("Job posting", display_text="Open posting"),
        "job_status": st.column_config.TextColumn("Status"),
        "job_title": st.column_config.TextColumn("Role", width="large"),
        "company": st.column_config.TextColumn("Company", width="medium"),
        "location_mention": st.column_config.TextColumn("Location", width="medium"),
    }
    st.dataframe(frame[display_cols], use_container_width=True, hide_index=True, height=height, column_config=column_config)


# Render the monitor near the top of the page. Auto-poll only while a scan is running.
def render_scan_monitor_content(state: dict) -> None:
    if not state:
        return
    status = str(state.get("status", "idle"))
    scan_id = str(state.get("scan_id", ""))
    log_path = Path(str(state.get("log_path", ""))) if state.get("log_path") else None
    try:
        log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path and log_path.exists() else ""
    except OSError:
        log_text = ""
    lines = log_text.splitlines()
    total_companies = max(1, int(state.get("company_count", 1) or 1))
    completed_companies = sum(1 for line in lines if line.startswith("Company summary:"))
    company_headers = [line[4:-4].strip() for line in lines if line.startswith("=== ") and line.endswith(" ===")]
    current_company = company_headers[-1] if company_headers else "Preparing scan"
    visited_matches = re.findall(r"Visited\s+(\d+)/(\d+)", log_text)
    current_visited = int(visited_matches[-1][0]) if visited_matches else 0
    page_limit_matches = re.findall(r"page limit:\s*(\d+)", log_text)
    page_limit = max(1, int(page_limit_matches[-1])) if page_limit_matches else 20
    within_company = min(0.88, current_visited / max(5, min(page_limit, 20)) * 0.88)
    fraction = min(0.99, (completed_companies + (within_company if status in {"running", "starting"} else 0)) / total_companies)
    role_urls = set(re.findall(r"(?:JOB FOUND|JOB CARD FOUND) \[Likely open\]:.*?\|\s*(https?://\S+)", log_text))
    roles_found = len(role_urls)
    saving = "Saving verified open positions to PostgreSQL" in log_text

    heading_col, status_col = st.columns([1.3, .7], vertical_alignment="center")
    with heading_col:
        st.markdown('<div class="section-title">Background scan monitor</div><div class="section-subtitle">The scan runs in a separate background process while you use the dashboard.</div>', unsafe_allow_html=True)
    with status_col:
        if status in {"running", "starting"}:
            st.info("Running · live updates")
        elif status == "completed":
            st.success("Completed")
        elif status == "failed":
            st.error("Failed")
        else:
            st.caption(status.title())

    # Attractive custom progress panel: animated gradient, percentage, scan counters,
    # and stage indicators. It refreshes with the existing two-second Streamlit fragment.
    if status == "completed":
        percent = 100
        stage_index = 3
        progress_title = "Scan complete — open positions are ready"
        progress_note = "All configured companies have been processed. Review the open-positions board for saved results."
        progress_status_text = "Complete"
        current_company_label = "All companies processed"
    elif status == "failed":
        percent = int(max(0, min(99, round(fraction * 100))))
        if saving:
            stage_index = 3
        elif roles_found > 0:
            stage_index = 2
        elif current_visited > 0:
            stage_index = 1
        else:
            stage_index = 0
        progress_title = "Scan stopped before completion"
        progress_note = str(state.get("message", "Open the scan log below for the failure reason."))
        progress_status_text = "Failed"
        current_company_label = current_company
    else:
        percent = 99 if saving else int(max(0, min(99, round(fraction * 100))))
        if saving:
            stage_index = 3
            progress_title = "Saving and deduplicating open positions"
            progress_note = "The crawler has finished discovery and is writing verified results to PostgreSQL."
        elif roles_found > 0:
            stage_index = 2
            progress_title = "Checking job postings for open status"
            progress_note = "Potential role links have been found. RoleRadar is filtering for postings with positive open-position signals."
        elif current_visited > 0:
            stage_index = 1
            progress_title = "Discovering roles on careers pages"
            progress_note = "Scanning job listings and pagination only; unrelated company pages are excluded."
        else:
            stage_index = 0
            progress_title = "Connecting to company careers pages"
            progress_note = "Starting the crawler and preparing the careers-page queue. Progress updates automatically."
        progress_status_text = "Live scan"
        current_company_label = current_company

    stages = ["Open careers pages", "Discover job roles", "Verify open status", "Save results"]
    stage_bits = []
    for idx, stage_name in enumerate(stages):
        stage_cls = "is-done" if status == "completed" or idx < stage_index else ("is-current" if idx == stage_index else "")
        marker = "✓" if stage_cls == "is-done" else str(idx + 1)
        stage_bits.append(
            f'<div class="scan-stage {stage_cls}"><span class="scan-stage-number">{marker}</span>'
            f'<span>{escape(stage_name)}</span></div>'
        )

    status_dot_class = "is-complete" if status == "completed" else ("is-failed" if status == "failed" else "")
    animation_class = "is-active" if status in {"running", "starting"} else ""
    safe_company = escape(str(current_company_label))
    safe_title = escape(progress_title)
    safe_note = escape(progress_note)
    progress_html = f'''<div class="scan-progress-card">
      <div class="scan-progress-head">
        <div>
          <div class="scan-progress-kicker"><span class="scan-live-dot {status_dot_class}"></span> RoleRadar scan progress</div>
          <div class="scan-progress-title">{safe_title}</div>
          <div class="scan-progress-subtitle">{safe_note}</div>
        </div>
        <div class="scan-progress-percent">{percent}%<small>progress</small></div>
      </div>
      <div class="scan-progress-track" role="progressbar" aria-valuenow="{percent}" aria-valuemin="0" aria-valuemax="100" aria-label="Scan progress">
        <div class="scan-progress-fill {animation_class}" style="width:{percent}%"></div>
      </div>
      <div class="scan-progress-stats">
        <div class="scan-stat"><div class="scan-stat-label">Companies</div><div class="scan-stat-value">{min(completed_companies, total_companies)} / {total_companies}</div></div>
        <div class="scan-stat"><div class="scan-stat-label">Pages checked</div><div class="scan-stat-value">{current_visited:,}</div></div>
        <div class="scan-stat"><div class="scan-stat-label">Open-role links</div><div class="scan-stat-value">{roles_found:,}</div></div>
      </div>
      <div class="scan-progress-stages">{''.join(stage_bits)}</div>
      <div class="scan-progress-foot">
        <span>Current company: <strong>{safe_company}</strong></span>
        <span class="scan-progress-status {status_dot_class}"><span class="mini-dot"></span>{escape(progress_status_text)}</span>
      </div>
    </div>'''
    st.markdown(progress_html, unsafe_allow_html=True)

    if status == "completed":
        st.caption(f"{roles_found} unique open-role links appeared in the scan log. The job board displays only saved open positions.")
        st.caption(f"Finished at {state.get('finished_at', 'unknown time')}")
    elif status == "failed":
        st.error(state.get("message", "Check the scan log for the failure reason."))

    with st.expander("Live scan log", expanded=(status in {"running", "starting"})):
        if lines:
            st.code("\n".join(lines[-35:]), language="text")
        else:
            st.caption("Waiting for the crawler to write its first log entries…")

    if status in {"completed", "failed"} and scan_id and st.session_state.get("_scan_completion_seen") != scan_id:
        st.session_state["_scan_completion_seen"] = scan_id
        st.rerun()


@st.fragment(run_every="2s")
def render_running_scan_monitor() -> None:
    # Re-read the worker state and tail file on each small fragment refresh.
    render_scan_monitor_content(current_scan_state())


def render_scan_monitor() -> None:
    state = current_scan_state()
    if not state:
        return
    if state.get("status") in {"running", "starting"}:
        render_running_scan_monitor()
    else:
        render_scan_monitor_content(state)


render_scan_monitor()

if page == "Overview":
    st.markdown(
        f'<section class="hero-panel">'
        f'<div class="hero-copy">'
        f'<div class="hero-kicker"><span></span> YOUR HIRING RADAR</div>'
        f'<h2 class="hero-title">See the roles.<br><span>Spot the opportunity.</span></h2>'
        f'<p class="hero-description">One focused workspace for tracking career pages, discovering job postings, and prioritizing the roles worth a closer look.</p>'
        f'<div class="hero-tags"><span class="hero-tag">✦ &nbsp; Hiring signals in one place</span>'
        f'<span class="hero-tag">↗ &nbsp; Verify at the source</span></div>'
        f'</div>'
        f'<div class="hero-art" aria-hidden="true">'
        f'<div class="hero-orbit"></div><div class="hero-orbit hero-orbit-two"></div><div class="hero-orbit hero-orbit-three"></div>'
        f'<div class="hero-core">R</div>'
        f'<div class="hero-float hero-float-one"><div class="hero-float-label">Job postings</div><div class="hero-float-value">{job_count:,}</div><div class="hero-float-note">In your workspace</div></div>'
        f'<div class="hero-float hero-float-two"><div class="hero-float-label">Recent activity</div><div class="hero-float-value">{recent_count:,}</div><div class="hero-float-note"><span class="hero-float-dot"></span>Posted in 30 days</div></div>'
        f'</div></section>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="metric-grid">'
        + render_metric("⌂", "Companies monitored", company_count, "In your current watchlist")
        + render_metric("▤", "Open positions found", job_count, "Saved active postings only")
        + render_metric("✓", "Open positions", likely_open_count, "Positive open signals only")
        + render_metric("◷", "Posted in 30 days", recent_count, "Based on publication dates")
        + '</div>',
        unsafe_allow_html=True,
    )

    chart_col, company_col = st.columns([1.15, 1], gap="large")
    with chart_col:
        with st.container(border=True):
            st.markdown('<div class="section-head"><div><div class="section-title">Most detected roles</div><div class="section-subtitle">Job titles appearing most often in your results.</div></div></div>', unsafe_allow_html=True)
            if data.empty or "job_title" not in data.columns:
                st.markdown('<div class="empty-state"><div class="empty-state-title">Your role insights will appear here</div>Run a company scan to begin building your hiring view.</div>', unsafe_allow_html=True)
            else:
                role_counts = data["job_title"].astype(str).str.strip().replace("", pd.NA).dropna().value_counts().head(8)
                if role_counts.empty:
                    st.info("No job titles have been extracted yet.")
                else:
                    st.bar_chart(role_counts.rename_axis("Job title").to_frame("Postings"), height=300, use_container_width=True)
    with company_col:
        with st.container(border=True):
            st.markdown('<div class="section-head"><div><div class="section-title">Company coverage</div><div class="section-subtitle">Where your crawler has found roles.</div></div></div>', unsafe_allow_html=True)
            if data.empty or "company" not in data.columns:
                st.markdown('<div class="empty-state"><div class="empty-state-title">No company results yet</div>Your tracked companies will be summarized here after a scan.</div>', unsafe_allow_html=True)
            else:
                by_company = data.groupby("company", dropna=False).size().sort_values(ascending=False).head(8).rename("Postings").reset_index()
                by_company["company"] = by_company["company"].replace("", "Unknown company")
                st.dataframe(by_company, use_container_width=True, hide_index=True, height=300)

    st.markdown('<div class="section-head" style="margin-top:1.45rem"><div><div class="section-title">Latest discovered jobs</div><div class="section-subtitle">The most recently discovered open roles.</div></div></div>', unsafe_allow_html=True)
    if data.empty:
        st.markdown('<div class="empty-state"><div class="empty-state-title">No jobs discovered yet</div>Add companies to your watchlist and run your first scan.</div>', unsafe_allow_html=True)
        st.button("Go to company watchlist", type="primary", on_click=navigate_to, args=("Companies",))
    else:
        latest = data.copy()
        if "last_seen_utc" in latest.columns:
            latest = latest.sort_values("last_seen_utc", ascending=False, na_position="last")
        elif "date_posted" in latest.columns:
            latest = latest.sort_values("date_posted", ascending=False, na_position="last")
        else:
            latest = latest.iloc[::-1]
        overview_cols = [c for c in ["job_title", "company", "job_status", "location_mention", "date_posted", "source_url"] if c in latest.columns]
        if "job_status" not in latest.columns:
            latest["job_status"] = "Needs verification"
            overview_cols.insert(2, "job_status")
        st.dataframe(
            latest[overview_cols].head(8), use_container_width=True, hide_index=True, height=330,
            column_config={"source_url": st.column_config.LinkColumn("Job posting", display_text="View role"), "job_title": st.column_config.TextColumn("Role", width="large")},
        )
        st.button("View all job postings →", key="overview_open_jobs", on_click=navigate_to, args=("Job board",))


elif page == "Job board":
    st.markdown('<div class="metric-grid">'
                + render_metric("▤", "Open positions", job_count, "Active postings only")
                + render_metric("✓", "Open status", likely_open_count, "Positive open signals only")
                + render_metric("✦", "Unique roles", role_count, "Distinct job titles")
                + render_metric("◷", "Recent", recent_count, "Posted within 30 days")
                + '</div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div class="section-head"><div><div class="section-title">Open position directory</div><div class="section-subtitle">Search active roles by company, title, skills, or location. Closed and unverified roles are excluded.</div></div></div>', unsafe_allow_html=True)
        view = job_frame(data)
        status_options = ["Open positions only"]
        companies_options = ["All companies"]
        if "company" in view.columns:
            companies_options += sorted(c for c in view["company"].dropna().astype(str).unique().tolist() if c.strip())
        locations_options = ["All locations"]
        if "location_mention" in view.columns:
            locations_options += sorted(c for c in view["location_mention"].dropna().astype(str).unique().tolist() if c.strip())
        f1, f2, f3 = st.columns([1, 1, 1.5], gap="medium")
        with f1:
            chosen_status = st.selectbox("Result scope", status_options, key="job_status_filter", index=0)
        with f2:
            chosen_company = st.selectbox("Company", companies_options, key="job_company_filter")
        with f3:
            search_query = st.text_input("Search", key="job_search", placeholder="Title, skill, company, location…")
        f4, f5 = st.columns([1, 2], gap="medium")
        with f4:
            chosen_location = st.selectbox("Location", locations_options, key="job_location_filter")
        with f5:
            st.caption("Only active-listing or application-enabled roles are retained. Open status is best-effort and should be verified on the employer’s source page.")
        filtered = filter_job_frame(view, chosen_status, chosen_company, search_query, chosen_location)
        st.markdown(f'<div class="panel-kicker">RESULTS &nbsp;·&nbsp; {len(filtered):,} MATCHING RECORDS</div>', unsafe_allow_html=True)
        render_jobs_table(filtered, height=490)
        st.download_button(
            "Download filtered CSV",
            data=filtered.to_csv(index=False).encode("utf-8-sig"),
            file_name="role_radar_jobs.csv",
            mime="text/csv",
            use_container_width=False,
        )


elif page == "Companies":
    left, right = st.columns([.88, 1.12], gap="large")
    with left:
        with st.container(border=True):
            st.markdown('<div class="section-head"><div><div class="section-title">Add a company</div><div class="section-subtitle">Start with the official careers page. Add ATS hosts only when trusted.</div></div></div>', unsafe_allow_html=True)
            with st.form("add_company_form", clear_on_submit=True):
                new_name = st.text_input("Company name", placeholder="e.g. Microsoft")
                new_url = st.text_input("Careers page URL", placeholder="https://company.com/careers or /open-positions")
                extra_domains = st.text_input("Additional allowed domains (optional)", placeholder="boards.greenhouse.io, jobs.lever.co", help="Only add trusted ATS hosts that this company's career page links to. The career-page domain is included automatically.")
                add_clicked = st.form_submit_button("Add to watchlist", type="primary", use_container_width=True)
            if add_clicked:
                row = {"name": new_name.strip(), "career_url": normalized_url(new_url), "allowed_domains": [x.strip() for x in re.split(r"[,;\s]+", extra_domains) if x.strip()]}
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
                    st.success(f"{new_name.strip()} added to your watchlist.")
                    st.rerun()
        with st.container(border=True):
            st.markdown('<div class="section-head"><div><div class="section-title">Import a company list</div><div class="section-subtitle">Upload CSV or Excel to add companies in bulk.</div></div></div>', unsafe_allow_html=True)
            uploaded = st.file_uploader("Choose a CSV or XLSX file", type=["csv", "xlsx"], key="company_upload")
            if uploaded is not None:
                try:
                    uploaded_df = pd.read_csv(uploaded) if uploaded.name.lower().endswith(".csv") else pd.read_excel(uploaded)
                    uploaded_rows = uploaded_df.rename(columns={c: str(c).strip().lower() for c in uploaded_df.columns}).to_dict("records")
                    new_rows = normalize_company_rows(uploaded_rows)
                    st.caption(f"{len(new_rows)} valid rows detected. Expected columns: name and career_url (or company and url).")
                    if st.button("Import companies", type="primary", key="import_companies"):
                        merged = normalize_company_rows(st.session_state.companies + new_rows)
                        added = max(0, len(merged) - len(st.session_state.companies))
                        st.session_state.companies = merged
                        save_companies(merged)
                        st.success(f"Imported {added} new companies.")
                        st.rerun()
                except Exception as exc:
                    st.error(f"Could not read this file: {exc}")
    with right:
        with st.container(border=True):
            head_l, head_r = st.columns([1.4, .6], vertical_alignment="center")
            with head_l:
                st.markdown('<div class="section-title">Your watchlist</div><div class="section-subtitle">Official careers and open-positions pages configured for scanning.</div>', unsafe_allow_html=True)
            with head_r:
                st.markdown(f'<div style="text-align:right;font:800 1.65rem Manrope;color:#25395c">{company_count:,}<div style="font:600 .7rem DM Sans;color:#8592a7">companies</div></div>', unsafe_allow_html=True)
            if st.session_state.companies:
                active_scan_state = current_scan_state()
                active_scan_companies = set(active_scan_state.get("companies", []))
                for i, company in enumerate(st.session_state.companies):
                    if active_scan_state.get("status") in {"running", "starting"} and company["name"] in active_scan_companies:
                        status = "Scanning"
                    elif active_scan_state.get("status") == "completed" and company["name"] in active_scan_companies:
                        status = "Scanned"
                    else:
                        status = st.session_state.company_status.get(company["name"], "Ready")
                    with st.container(border=True):
                        name_col, status_col = st.columns([3, 1], vertical_alignment="center")
                        with name_col:
                            st.markdown(f'<div class="company-name">{company["name"]}</div><div class="company-url">{company["career_url"]}</div>', unsafe_allow_html=True)
                            base_host = (urlparse(company["career_url"]).hostname or "").lower().removeprefix("www.")
                            extra_hosts = [d for d in company.get("allowed_domains", []) if d != base_host]
                            if extra_hosts:
                                st.caption("ATS: " + ", ".join(extra_hosts))
                        with status_col:
                            st.markdown(f'<span class="status">{status}</span>', unsafe_allow_html=True)
                        btn_scan, btn_remove = st.columns([1, 1])
                        with btn_scan:
                            if st.button("Scan now", key=f"scan_company_{i}", type="primary", use_container_width=True):
                                start_scan([company], "company")
                        with btn_remove:
                            if st.button("Remove", key=f"remove_company_{i}", use_container_width=True):
                                st.session_state.companies.pop(i)
                                save_companies(st.session_state.companies)
                                st.rerun()
            else:
                st.markdown('<div class="empty-state"><div class="empty-state-title">Your watchlist is empty</div>Add a company or import a spreadsheet to get started.</div>', unsafe_allow_html=True)
            st.markdown("---")
            s1, s2 = st.columns(2, gap="small")
            with s1:
                if st.button("Scan all companies", type="primary", use_container_width=True, key="companies_scan_all"):
                    start_scan(st.session_state.companies, "all")
            with s2:
                if st.button("Scan · past 30 days", use_container_width=True, key="companies_scan_30"):
                    start_scan(st.session_state.companies, "30_days")


elif page == "Analytics":
    st.markdown('<div class="metric-grid">'
                + render_metric("▤", "Open positions", job_count, "Active postings only")
                + render_metric("✦", "Unique roles", role_count, "Distinct titles")
                + render_metric("⌂", "Companies monitored", company_count, "Configured watchlist")
                + render_metric("✓", "Open positions", likely_open_count, "Active postings only")
                + '</div>', unsafe_allow_html=True)
    if data.empty:
        st.markdown('<div class="empty-state"><div class="empty-state-title">Analytics will appear after your first scan</div>Once roles have been collected, use this page to compare job families, company activity, and locations.</div>', unsafe_allow_html=True)
    else:
        left, right = st.columns(2, gap="large")
        with left:
            with st.container(border=True):
                st.markdown('<div class="section-title">Most common job titles</div><div class="section-subtitle">Role frequency across all collected postings.</div>', unsafe_allow_html=True)
                if "job_title" in data.columns:
                    counts = data["job_title"].astype(str).str.strip().replace("", pd.NA).dropna().value_counts().head(12)
                    if not counts.empty:
                        st.bar_chart(counts.rename_axis("Job title").to_frame("Postings"), height=360, use_container_width=True)
                    else:
                        st.info("No job titles available.")
        with right:
            with st.container(border=True):
                st.markdown('<div class="section-title">Postings by company</div><div class="section-subtitle">Compare detected hiring activity across your watchlist.</div>', unsafe_allow_html=True)
                if "company" in data.columns:
                    by_company = data.groupby("company", dropna=False).size().sort_values(ascending=False).head(12)
                    st.bar_chart(by_company.rename_axis("Company").to_frame("Postings"), height=360, use_container_width=True)
        loc_col, status_col = st.columns(2, gap="large")
        with loc_col:
            with st.container(border=True):
                st.markdown('<div class="section-title">Locations mentioned</div><div class="section-subtitle">Most frequent location values detected in job pages.</div>', unsafe_allow_html=True)
                if "location_mention" in data.columns:
                    locs = data["location_mention"].astype(str).str.strip().replace("", pd.NA).dropna().value_counts().head(10)
                    if not locs.empty:
                        st.bar_chart(locs.rename_axis("Location").to_frame("Postings"), height=300, use_container_width=True)
                    else:
                        st.info("No location information was extracted.")
                else:
                    st.info("Location data is not available in the current results.")
        with status_col:
            with st.container(border=True):
                st.markdown('<div class="section-title">Open roles by employment type</div><div class="section-subtitle">Break down active roles by the employment arrangement detected in the posting.</div>', unsafe_allow_html=True)
                if "employment_type_mention" in data.columns:
                    types = data["employment_type_mention"].astype(str).str.strip().replace("", pd.NA).dropna().value_counts().head(10)
                    if not types.empty:
                        st.bar_chart(types.rename_axis("Employment type").to_frame("Open roles"), height=300, use_container_width=True)
                    else:
                        st.info("Employment type was not specified in the open postings collected so far.")
                else:
                    st.info("Employment type information is not available in the current results.")


elif page == "Settings & data":
    st.markdown('<div class="metric-grid">'
                + render_metric("⌂", "Companies", company_count, "Saved in config.json")
                + render_metric("▤", "Job records", job_count, "Currently stored")
                + render_metric("◷", "Page limit", int(cfg.get("max_pages_per_domain", 80)), "Maximum pages per company")
                + render_metric("⏱", "Request delay", float(cfg.get("request_delay_seconds", 2.0)), "Seconds between page requests")
                + '</div>', unsafe_allow_html=True)
    db_col, config_col = st.columns([1, 1], gap="large")
    with db_col:
        with st.container(border=True):
            st.markdown('<div class="section-title">Data connection</div><div class="section-subtitle">Where job results are loaded from.</div>', unsafe_allow_html=True)
            if db_url() and not db_error:
                st.success("PostgreSQL is configured and results loaded successfully.")
            elif db_url() and db_error:
                st.error("A database URL is configured, but the results could not be loaded.")
                with st.expander("Database error details"):
                    st.code(db_error)
            else:
                st.info("DATABASE_URL is not configured. The dashboard will use the local CSV fallback for viewing results; scans require PostgreSQL.")
            st.caption("Keep credentials in your hosting environment or Streamlit secrets. Do not commit database credentials to GitHub.")
    with config_col:
        with st.container(border=True):
            st.markdown('<div class="section-title">Crawler configuration</div><div class="section-subtitle">Current settings from config.json.</div>', unsafe_allow_html=True)
            st.write("**Maximum pages per domain:**", cfg.get("max_pages_per_domain", 80))
            st.write("**Request delay:**", f'{cfg.get("request_delay_seconds", 2.0)} seconds')
            st.write("**Job URL keywords:**", ", ".join(cfg.get("job_url_keywords", [])) or "Default keywords")
            st.write("**Exclude URL keywords:**", ", ".join(cfg.get("exclude_url_keywords", [])) or "Default exclusions")
    with st.container(border=True):
        st.markdown('<div class="section-title">Recent scan log</div><div class="section-subtitle">Persisted output from the latest background scan.</div>', unsafe_allow_html=True)
        scan_state_for_log = current_scan_state()
        scan_log_path = Path(str(scan_state_for_log.get("log_path", ""))) if scan_state_for_log.get("log_path") else None
        try:
            persisted_log = scan_log_path.read_text(encoding="utf-8", errors="replace").splitlines() if scan_log_path and scan_log_path.exists() else []
        except OSError:
            persisted_log = []
        if persisted_log:
            st.code("\n".join(persisted_log[-80:]), language="text")
        else:
            st.caption("No scan log yet. Start a background scan from the sidebar or company watchlist.")
    with st.expander("Data cleanup · Clear previous job results", expanded=False):
        st.markdown('<div class="section-title">Start with a clean results list</div>', unsafe_allow_html=True)
        st.warning("This permanently deletes all saved job-posting rows and local crawler CSV/XLSX exports. Your configured companies and crawler settings will be kept.")
        with st.form("clear_job_data_form", clear_on_submit=True):
            confirm_clear = st.checkbox("I understand this will delete all previous job results.")
            submit_clear = st.form_submit_button("Delete all previous job data", type="primary")
        if submit_clear:
            if not confirm_clear:
                st.error("Check the confirmation box before deleting previous job data.")
            else:
                try:
                    rows_deleted, files_deleted = clear_saved_job_data()
                    st.session_state["cleanup_notice"] = f"Previous job data cleared. Database rows deleted: {rows_deleted:,}. Local export files deleted: {files_deleted:,}. Company settings were preserved."
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not fully clear previous data: {exc}")

if db_error and page != "Settings & data":
    st.warning("Could not load results from the database. Check DATABASE_URL and the job_postings table.")

