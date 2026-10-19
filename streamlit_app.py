from __future__ import annotations
import json, os, re, subprocess, sys, time
from pathlib import Path
from urllib.parse import urlparse
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'config.json'
CSV = ROOT / 'job_requirements.csv'
XLSX = ROOT / 'job_requirements.xlsx'
AGENT = ROOT / 'agent.py'
st.set_page_config(page_title='Job Requirements Agent', page_icon='🔎', layout='wide')
st.title('Job Requirements Extraction Agent')
st.caption('Add company careers websites, run a scan, review extracted requirements, and export results.')
st.info('Rules-based MVP; checks robots.txt, stays on each entered host, uses PostgreSQL for persistent storage, and uses no paid APIs. Some JavaScript-heavy career portals may not be readable.')

def get_database_url():
    value = os.environ.get('DATABASE_URL', '').strip()
    if not value:
        try:
            value = str(st.secrets.get('DATABASE_URL', '')).strip()
        except Exception:
            value = ''
    return value

database_url = get_database_url()
if database_url:
    st.success('PostgreSQL connection string found. Scan results will be saved to the PostgreSQL job_postings table.')
else:
    st.warning('PostgreSQL is not configured yet. Set DATABASE_URL as an environment variable or in .streamlit/secrets.toml before running a scan.')

if 'companies' not in st.session_state:
    try:
        old = json.loads(CONFIG.read_text(encoding='utf-8')).get('companies', [])
        st.session_state.companies = [{'name': c.get('name',''), 'career_url': c.get('career_url','')} for c in old if c.get('career_url') and 'example.com' not in c.get('career_url','')]
    except Exception:
        st.session_state.companies = []

with st.container(border=True):
    st.subheader('1. Add a company website')
    with st.form('add_company', clear_on_submit=True):
        name = st.text_input('Company name (optional)', placeholder='e.g., Acme Insurance')
        url = st.text_input('Official careers website URL', placeholder='https://company.com/careers', help='Use the company careers/jobs page when possible.')
        add = st.form_submit_button('Add company', type='primary')
    if add:
        candidate = url.strip()
        if candidate and not re.match(r'^https?://', candidate, re.I): candidate = 'https://' + candidate
        parsed = urlparse(candidate)
        if not candidate:
            st.error('Enter a careers website URL first.')
        elif parsed.scheme not in ('http','https') or not parsed.hostname or '.' not in parsed.hostname:
            st.error('Enter a valid HTTP/HTTPS URL, such as https://company.com/careers.')
        elif any(c['career_url'].rstrip('/') == candidate.rstrip('/') for c in st.session_state.companies):
            st.warning('That careers URL is already in the list.')
        else:
            host = parsed.hostname.removeprefix('www.')
            st.session_state.companies.append({'name': name.strip() or host.split('.')[0].replace('-', ' ').title(), 'career_url': candidate})
            st.success('Company added to the scan list.')

with st.container(border=True):
    st.subheader('2. Companies queued for scanning')
    if st.session_state.companies:
        for i, c in enumerate(list(st.session_state.companies)):
            a,b,d = st.columns([2,5,1])
            a.write(c['name']); b.write(c['career_url'])
            if d.button('Remove', key=f'remove_{i}'):
                st.session_state.companies.pop(i); st.rerun()
        st.caption(f"{len(st.session_state.companies)} website(s) queued.")
    else:
        st.write('No websites added yet. Add one above to get started.')
    a,b = st.columns(2)
    max_pages = a.number_input('Max pages per domain', min_value=10, max_value=300, value=80, step=10)
    delay = b.number_input('Delay between requests (seconds)', min_value=1.0, max_value=10.0, value=2.0, step=0.5)
    run = st.button('▶ Run scan', type='primary', disabled=(not st.session_state.companies or not database_url))

if run:
    cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
    cfg['companies'] = []
    for c in st.session_state.companies:
        host = urlparse(c['career_url']).hostname or ''
        cfg['companies'].append({'name': c['name'], 'career_url': c['career_url'], 'allowed_domains': [host.removeprefix('www.')]})
    cfg['max_pages_per_domain'] = int(max_pages)
    cfg['request_delay_seconds'] = float(delay)
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
    for path in (CSV, XLSX):
        try: path.unlink()
        except FileNotFoundError: pass
    st.subheader('3. Scan progress')
    log = st.empty(); progress = st.progress(0, text='Starting scan…'); lines=[]
    try:
        child_env = os.environ.copy()
        if database_url:
            child_env['DATABASE_URL'] = database_url
        proc = subprocess.Popen([sys.executable, '-u', str(AGENT)], cwd=str(ROOT), env=child_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        start = time.time()
        while True:
            line = proc.stdout.readline() if proc.stdout else ''
            if line:
                lines.append(line.rstrip()); log.code('\n'.join(lines[-100:]), language='text')
                progress.progress(min(95, 5 + len(lines) % 90), text='Scanning career pages…')
            elif proc.poll() is not None: break
            else: time.sleep(.1)
            if time.time() - start > 1800:
                proc.kill(); st.error('Scan stopped after 30 minutes. Try fewer pages or companies.'); break
        rc = proc.wait(); progress.progress(100, text='Scan finished.')
        if rc == 0: st.success('Scan completed. Review the results below.')
        else: st.error('The scan ended with an error. Review the log above.')
    except Exception as e:
        st.error(f'Could not start the scan: {e}')

if CSV.exists():
    try:
        data = pd.read_csv(CSV).fillna('')
        st.subheader('Extracted job requirements')
        a,b,c = st.columns(3)
        a.metric('Jobs extracted', len(data)); b.metric('Companies', data['company'].nunique() if 'company' in data else 0); c.metric('Fields per job', len(data.columns))
        term = st.text_input('Filter results', placeholder='Search company, title, location, requirements…')
        shown = data
        if term:
            mask = data.astype(str).apply(lambda col: col.str.contains(term, case=False, na=False)).any(axis=1)
            shown = data[mask]
        st.dataframe(shown, use_container_width=True, hide_index=True)
        a,b = st.columns(2)
        with a:
            if XLSX.exists(): st.download_button('Download Excel', XLSX.read_bytes(), file_name='job_requirements.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', use_container_width=True)
            else: st.download_button('Download CSV', CSV.read_bytes(), file_name='job_requirements.csv', mime='text/csv', use_container_width=True)
        with b:
            st.download_button('Download CSV', CSV.read_bytes(), file_name='job_requirements.csv', mime='text/csv', use_container_width=True)
        if data.empty: st.warning('No job pages were extracted. Confirm this is a careers page and review the scan log. JavaScript-heavy portals may need a site-specific parser.')
        st.caption('Heuristic extraction should be verified against each source URL. Blank fields mean the parser did not confidently detect a value.')
    except Exception as e: st.warning(f'Could not load results: {e}')

with st.expander('What this scanner does / limitations'):
    st.markdown('- Reads accessible HTML on the company host entered in the UI.\n- Checks robots.txt and waits between requests.\n- Extracts common job metadata and requirements sections.\n- Saves results to PostgreSQL and exports CSV/Excel files.\n- Does not bypass logins, CAPTCHAs, paywalls, or access controls.\n- Hosted local files may not persist across restarts/redeployments; download results you need to keep.\n- If publicly deployed, anyone with access to the app may be able to trigger scans.')
