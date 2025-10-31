from flask import Flask, jsonify, request, send_file, session
from flask_cors import CORS
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import fitz  # PyMuPDF
import random
import io
from PIL import Image
import numpy as np
from bs4 import BeautifulSoup
import base64
from math import log
import time
import json
import secrets
from pathlib import Path
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
import threading
import urllib.parse
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = secrets.token_hex(32)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = 86400
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True if using HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True

# CORS(app, 
#      supports_credentials=True,
#      origins=['http://178.156.186.180:5050', 'http://localhost:5050', 'http://127.0.0.1:5050'],
#      allow_headers=['Content-Type'],
#      expose_headers=['Set-Cookie'],
#      max_age=3600)

frontend_origins = [
    "null",
    "http://127.0.0.1:5050",
    "http://localhost:5050",
    # For your deployed server
    "http://178.156.186.180:5050"
]

CORS(app,
     supports_credentials=True,
     origins=frontend_origins)

# Configuration
zoom = 2.0
top_fraction = 0.4
min_abstract_length = 15
max_abstract_length = 100
min_abstract_gray = 240
padsides = 80
padtop = 100
padbot = 100

# Citation API settings
FETCH_CITATIONS_ON_DEMAND = True
SKIP_CITATIONS_IN_WARMING = False
CITATION_API_MIN_DELAY = 2.0
CITATION_API_BACKOFF = 5.0

# Cache configuration
CACHE_DIR = Path('.cache')
CACHE_DIR.mkdir(exist_ok=True)
PAPER_CACHE_FILE = CACHE_DIR / 'paper_cache.json'
MAX_CACHE_SIZE = 500
BACKGROUND_CACHE_TARGET = 100

# Paper weights (total papers per year)
weights = {
    2000: 69, 2001: 113, 2002: 195, 2003: 265, 2004: 377,
    2005: 469, 2006: 486, 2007: 482, 2008: 545, 2009: 638,
    2010: 661, 2011: 714, 2012: 733, 2013: 882, 2014: 1029,
    2015: 1257, 2016: 1196, 2017: 1262, 2018: 1251, 2019: 1499,
    2020: 1620, 2021: 1705, 2022: 1781, 2023: 1973, 2024: 2100
}
tot_papers = sum(weights.values())

# Session management
active_sessions = {}
session_lock = threading.Lock()
SESSION_TIMEOUT = 3600

# Paper processing cache
paper_cache = {}
cache_lock = threading.Lock()

# Track seen papers globally
global_seen_papers = set()
global_seen_lock = threading.Lock()
MAX_GLOBAL_SEEN = 1000

# Background processing
is_warming = False
warming_lock = threading.Lock()

# HTTP session with retry logic
def create_http_session():
    sess = requests.Session()
    retry = Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=20)
    sess.mount('http://', adapter)
    sess.mount('https://', adapter)
    return sess

http_session = create_http_session()

### CORRECTED ###
def get_cache_key(year, id):
    """Generate cache key for a paper without zero-padding the ID."""
    return f"{year}_{id}"

def random_paper(exclude_set=None):
    if exclude_set is None:
        exclude_set = set()
    
    max_attempts = 50
    for attempt in range(max_attempts):
        idx = random.randint(0, tot_papers - 1)
        year_tot = 0
        year = 2000
        paperid = 0
        for y in sorted(weights.keys()):
            if year_tot + weights[y] > idx:
                year = y
                paperid = idx - year_tot + 1 # Paper IDs are 1-indexed
                break
            year_tot += weights[y]
        
        paper_key = get_cache_key(year, paperid)
        if paper_key not in exclude_set:
            return year, paperid
    return year, paperid

def load_cache():
    global paper_cache
    if PAPER_CACHE_FILE.exists():
        try:
            with open(PAPER_CACHE_FILE, 'r') as f:
                paper_cache = json.load(f)
            logger.info(f"✅ Loaded {len(paper_cache)} papers from cache")
        except Exception as e:
            logger.error(f"Could not load cache: {e}")

def save_cache_async():
    def save():
        try:
            with cache_lock:
                if len(paper_cache) > MAX_CACHE_SIZE:
                    sorted_items = sorted(paper_cache.items(), key=lambda x: x[1].get('timestamp', 0), reverse=True)
                    cached_data = dict(sorted_items[:MAX_CACHE_SIZE])
                else:
                    cached_data = paper_cache.copy()
            with open(PAPER_CACHE_FILE, 'w') as f:
                json.dump(cached_data, f)
            logger.info(f"💾 Saved {len(cached_data)} papers to cache")
        except Exception as e:
            logger.error(f"Could not save cache: {e}")
    threading.Thread(target=save, daemon=True).start()

### CORRECTED ###
def get_png(year, id):
    """Download and convert PDF first page to PNG with retries and correct URL."""
    url = f"https://eprint.iacr.org/{year}/{id}.pdf"
    cache_key = get_cache_key(year, id)
    
    for attempt in range(3):
        try:
            response = http_session.get(url, timeout=15)
            response.raise_for_status()
            pdf_bytes = io.BytesIO(response.content)
            
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            page = doc.load_page(0)
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            doc.close()
            
            logger.debug(f"📄 {cache_key}: PDF downloaded on attempt {attempt+1}")
            return pix
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.warning(f"🚫 {cache_key}: Paper not found (404), not retrying.")
                return None
            logger.debug(f"🚫 {cache_key}: HTTP {e.response.status_code} on attempt {attempt+1}")
        except requests.exceptions.RequestException as e:
            logger.debug(f"🌐 {cache_key}: Network error on attempt {attempt+1} - {str(e)[:50]}")
        except Exception as e:
            logger.debug(f"💥 {cache_key}: PDF processing error on attempt {attempt+1} - {str(e)[:50]}")

        if attempt < 2:
             time.sleep(2 * (attempt + 1))

    logger.warning(f"❌ {cache_key}: Failed to get PDF after 3 attempts")
    return None

def crop_png(pix):
    if not pix: return None
    try:
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).convert("L")
        arr = np.array(img)
        N = 5 * int(zoom)
        h = arr.shape[0]
        num_blocks = h // N
        if num_blocks == 0: return None
        block_means = arr[:num_blocks * N].reshape(num_blocks, N, -1).mean(axis=(1, 2))
        data = np.array(block_means)
        subarrays, block_row_starts, row_counter, in_block, block_vals = [], [], 0, False, []
        for val in data:
            if val < 255:
                if not in_block:
                    block_row_starts.append(row_counter * N); block_vals = []; in_block = True
                block_vals.append(val)
            elif in_block:
                block_vals_arr = np.array(block_vals)
                k = max(1, int(len(block_vals_arr) * top_fraction)); top_vals = np.sort(block_vals_arr)[:k]
                subarrays.append([top_vals.mean(), len(block_vals_arr)]); block_vals = []; in_block = False
            row_counter += 1
        if in_block:
            block_vals_arr = np.array(block_vals); k = max(1, int(len(block_vals_arr) * top_fraction))
            top_vals = np.sort(block_vals_arr)[:k]; subarrays.append([top_vals.mean(), len(block_vals_arr)])
        abstract_block_index = None
        for i, (mean_val, length) in enumerate(subarrays):
            if min_abstract_length <= length <= max_abstract_length and mean_val <= min_abstract_gray:
                abstract_block_index = i; break
        if abstract_block_index is None: return None
        end_block = abstract_block_index
        while end_block + 1 < len(subarrays) and subarrays[end_block + 1][1] >= min_abstract_length:
            end_block += 1
        crop_row = block_row_starts[end_block] + subarrays[end_block][1] * N
        crop_row = min(crop_row, pix.height) + 10
        cropped = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).crop((padsides + 20, padtop, pix.width - padsides, crop_row))
        width, height = cropped.size
        cropped_pad = Image.new("RGB", (width, height + padbot), (255, 255, 255))
        cropped_pad.paste(cropped, (0, 0))
        return cropped_pad
    except Exception as e:
        logger.error(f"Error cropping image: {e}"); return None

### CORRECTED ###
@lru_cache(maxsize=200)
def get_paper_details(year, id):
    """Scrape paper details using the correct non-padded ID URL."""
    url = f"https://eprint.iacr.org/{year}/{id}"
    for attempt in range(2):
        try:
            response = http_session.get(url, timeout=5)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            h3 = soup.find("h3", class_="mb-3")
            title = h3.text.strip() if h3 else None
            doi_link = soup.find('a', href=lambda href: href and "doi.org" in href)
            doi = doi_link.text.replace('DOI:', '').strip() if doi_link and doi_link.text else None
            if title: return title, doi
        except Exception:
            time.sleep(0.5)
    return None, None

# --- Citation Logic ---
citation_api_lock = threading.Lock()
last_citation_call = {'time': 0}
citation_failures = {'count': 0, 'last_reset': time.time()}

@lru_cache(maxsize=200)
def get_cites_by_doi(doi):
    if not doi or not FETCH_CITATIONS_ON_DEMAND: return 0
    wait_duration = 0
    with citation_api_lock:
        current_time = time.time()
        if current_time - citation_failures['last_reset'] > 300:
            citation_failures['count'], citation_failures['last_reset'] = 0, current_time
        if citation_failures['count'] > 5: return 0
        time_since_last = current_time - last_citation_call['time']
        if time_since_last < CITATION_API_MIN_DELAY:
            wait_duration = CITATION_API_MIN_DELAY - time_since_last
        last_citation_call['time'] = current_time + wait_duration
    if wait_duration > 0:
        logger.debug(f"⏱️  S2 Rate limiting: waiting {wait_duration:.1f}s")
        time.sleep(wait_duration)
    try:
        api_url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
        response = http_session.get(api_url, params={"fields": "citationCount"}, timeout=10)
        if response.status_code == 429:
            with citation_api_lock: citation_failures['count'] += 1
            logger.warning(f"⏸️  S2 RATE LIMITED! Backing off {CITATION_API_BACKOFF}s")
            time.sleep(CITATION_API_BACKOFF); return 0
        response.raise_for_status()
        data = response.json()
        count = data.get("citationCount", 0) or 0
        if count:
            logger.info(f"📊 S2 SUCCESS: Found {count} citations for DOI: {doi}")
            with citation_api_lock: citation_failures['count'] = max(0, citation_failures['count'] - 1)
        return count
    except Exception as e:
        with citation_api_lock: citation_failures['count'] += 1
        logger.warning(f"⚠️ S2 API error for DOI {doi}: {e}"); return 0

def get_cites_by_title_openalex(title):
    if not title: return 0
    try:
        encoded_title = urllib.parse.quote(title)
        url = f"https://api.openalex.org/works?filter=title.search:{encoded_title}&per_page=1"
        headers = {'User-Agent': 'PaperGuesser/1.0 (mailto:youremail@example.com)'}
        response = http_session.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('results'):
            count = data['results'][0].get('cited_by_count', 0) or 0
            if count > 0:
                 logger.info(f"📊 OpenAlex SUCCESS: Found {count} citations for title: {title[:40]}...")
            return count
        return 0
    except Exception as e:
        logger.warning(f"⚠️ OpenAlex API error: {e}"); return 0

def get_cites(doi, title):
    if not FETCH_CITATIONS_ON_DEMAND: return 0
    if doi:
        cites = get_cites_by_doi(doi)
        if cites > 0:
            return cites
    logger.debug(f"DOI lookup failed for '{title[:40]}...'. Falling back to title search.")
    return get_cites_by_title_openalex(title)


def process_paper(year, id, fetch_citations=True):
    """Process a single paper and return a dictionary including year and id."""
    cache_key = get_cache_key(year, id)
    pix = get_png(year, id)
    if not pix: return None
    cropped = crop_png(pix)
    if not cropped:
        logger.warning(f"❌ {cache_key}: Failed to crop (no abstract found)"); return None
    title, doi = get_paper_details(year, id)
    if not title:
        logger.warning(f"❌ {cache_key}: Failed to get title"); return None
    
    cites = get_cites(doi, title) if fetch_citations else 0
    
    img_buffer = io.BytesIO()
    cropped.save(img_buffer, format='PNG', optimize=True, quality=85)
    img_base64 = base64.b64encode(img_buffer.getvalue()).decode()
    logger.info(f"✅ {cache_key}: Successfully processed (cites: {cites})")
    
    return {
        'year': year,
        'id': id,
        'image': f'data:image/png;base64,{img_base64}',
        'title': title,
        'doi': doi,
        'cites': cites,
        'timestamp': time.time()
    }

def get_or_process_paper(year, id, fetch_citations=True):
    cache_key = get_cache_key(year, id)
    with cache_lock:
        if cache_key in paper_cache:
            paper_data = paper_cache[cache_key].copy()
            paper_data['timestamp'] = time.time()
            if (fetch_citations and paper_data.get('cites', 0) == 0):
                logger.debug(f"🔄 Lazy-fetching citations for: {cache_key}")
                real_cites = get_cites(paper_data.get('doi'), paper_data.get('title'))
                if real_cites > 0:
                    paper_data['cites'] = real_cites
                    paper_cache[cache_key]['cites'] = real_cites
                    logger.info(f"📊 Updated {cache_key}: {real_cites} citations")
            logger.info(f"⚡ Cache hit: {cache_key}"); return paper_data
    paper_data = process_paper(year, id, fetch_citations=fetch_citations)
    if paper_data:
        with cache_lock: paper_cache[cache_key] = paper_data
        save_cache_async()
    return paper_data

def warm_cache_background():
    global is_warming
    with warming_lock:
        if is_warming: return
        is_warming = True
    logger.info("🔥 Background cache warming started.")
    try:
        with global_seen_lock: exclude_set = global_seen_papers.copy()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = []
            while len(paper_cache) < BACKGROUND_CACHE_TARGET:
                year, id = random_paper(exclude_set)
                cache_key = get_cache_key(year, id)
                with cache_lock:
                    if cache_key in paper_cache: continue
                futures.append(executor.submit(process_paper, year, id, not SKIP_CITATIONS_IN_WARMING))
                time.sleep(random.uniform(0.5, 1.5))
                
                done_futures = [f for f in futures if f.done()]
                for future in done_futures:
                    try:
                        paper_data = future.result(timeout=0.1)
                        if paper_data:
                            # Use the already generated cache_key from this loop's context
                            with cache_lock: paper_cache[get_cache_key(paper_data['year'], paper_data['id'])] = paper_data
                            logger.info(f"✅ Cached background: {get_cache_key(paper_data['year'], paper_data['id'])} ({len(paper_cache)}/{BACKGROUND_CACHE_TARGET})")
                    except Exception:
                        pass
                    futures.remove(future)
                
                if len(paper_cache) >= BACKGROUND_CACHE_TARGET: break
        save_cache_async()
        logger.info(f"✅ Cache warming complete!")
    finally:
        with warming_lock: is_warming = False

# --- Flask Routes ---
@app.route('/')
def index(): return send_file('static/index.html')

@app.route('/api/cache-stats', methods=['GET'])
def get_cache_stats():
    """Return cache statistics"""
    return jsonify({
        'cached_papers': len(paper_cache),
        'success': True
    })

@app.route('/api/random-paper', methods=['GET'])
def get_random_paper():
    # Create session if it doesn't exist
    if 'session_id' not in session:
        session['session_id'] = secrets.token_hex(16)
        session.permanent = True
        logger.info(f"🆕 New session created: {session['session_id']}")
    
    session_id = session['session_id']
    
    # Initialize session data
    with session_lock:
        if session_id not in active_sessions:
            active_sessions[session_id] = {
                'created': time.time(), 
                'papers': {}, 
                'seen_papers': set()
            }
            logger.info(f"📝 Session data initialized for: {session_id}")
    
    with session_lock: 
        user_seen = active_sessions[session_id]['seen_papers'].copy()
    with global_seen_lock: 
        exclude_set = user_seen | global_seen_papers
    
    for attempt in range(30):
        year, id = random_paper(exclude_set)
        paper_data = get_or_process_paper(year, id)
        if paper_data:
            paper_id = secrets.token_hex(8)
            cache_key = get_cache_key(year, id)
            with session_lock:
                active_sessions[session_id]['papers'][paper_id] = {
                    'year': year, 
                    'id': id, 
                    'title': paper_data['title'], 
                    'cites': paper_data['cites']
                }
                active_sessions[session_id]['seen_papers'].add(cache_key)
            with global_seen_lock:
                global_seen_papers.add(cache_key)
                if len(global_seen_papers) > MAX_GLOBAL_SEEN:
                    to_remove = random.sample(list(global_seen_papers), len(global_seen_papers) // 5)
                    global_seen_papers.difference_update(to_remove)
            if len(paper_cache) < BACKGROUND_CACHE_TARGET and not is_warming:
                threading.Thread(target=warm_cache_background, daemon=True).start()
            logger.info(f"✨ Serving paper: {cache_key} to session {session_id}")
            return jsonify({'success': True, 'paper_id': paper_id, 'image': paper_data['image']})
    
    logger.error("Could not find valid paper after 30 attempts")
    return jsonify({'success': False, 'error': 'Server is busy finding papers, please try again.'}), 503

### CORRECTED ###
@app.route('/api/submit-guess', methods=['POST'])
def submit_guess():
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': 'Missing JSON in request'}), 400

        # Validate session
        if 'session_id' not in session:
            logger.warning("❌ Submit attempt with no session")
            return jsonify({'success': False, 'error': 'Invalid session - please refresh the page'}), 401
        
        session_id = session['session_id']
        paper_id = data.get('paper_id')
        
        logger.info(f"📥 Submit guess from session: {session_id}, paper: {paper_id}")
        
        # Validate paper_id and retrieve paper info
        with session_lock:
            if session_id not in active_sessions:
                logger.warning(f"❌ Session {session_id} not found in active sessions")
                return jsonify({'success': False, 'error': 'Session expired - please refresh the page'}), 400
            
            if paper_id not in active_sessions[session_id]['papers']:
                logger.warning(f"❌ Paper {paper_id} not found in session {session_id}")
                return jsonify({'success': False, 'error': 'Invalid paper or session ID'}), 400
            
            paper_info = active_sessions[session_id]['papers'].pop(paper_id, None)
            if not paper_info:
                # This can happen in a race condition, it's a safe way to handle it.
                return jsonify({'success': False, 'error': 'Paper already guessed or invalid'}), 400

        # Get and validate guesses
        year_guess = int(data['year_guess'])
        cite_guess = int(data['cite_guess'])
        
        actual_year = paper_info.get('year')
        actual_cites = paper_info.get('cites') or 0
        
        if actual_year is None:
            logger.error(f"FATAL: Stored paper info for {paper_id} is missing 'year'.")
            return jsonify({'success': False, 'error': 'Internal server error processing paper data.'}), 500

        # Calculate scores
        year_dist = abs(year_guess - actual_year)
        penalty = {0: 0, 1: 100, 2: 500, 3: 1000, 4: 2000, 5: 4000}
        year_score = 5000 - penalty.get(year_dist, 4000 + (year_dist - 5) * 1000)
        year_score = max(0, year_score)
        
        cite_score = 5000 if actual_cites == cite_guess == 0 else max(0, int(5000 - abs(log(actual_cites + 1) - log(cite_guess + 1)) * 800))
        
        logger.info(f"✅ Successful guess submission for {paper_id}")
        
        return jsonify({
            'success': True,
            'year_score': year_score,
            'cite_score': cite_score,
            'total_score': year_score + cite_score,
            'actual_year': actual_year,
            'actual_cites': actual_cites,
            'actual_id': paper_info.get('id'),
            'title': paper_info.get('title')
        })

    except (KeyError, ValueError) as e:
        logger.error(f"Invalid guess format: {e}")
        return jsonify({'success': False, 'error': 'Invalid guess format. Guesses must be numbers.'}), 400
    except Exception as e:
        logger.error(f"An unexpected error occurred in submit_guess: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'An internal server error occurred.'}), 500
    
if __name__ == '__main__':
    load_cache()
    logger.info("Server starting...")
    if len(paper_cache) < 20:
        threading.Thread(target=warm_cache_background, daemon=True).start()
    app.run(debug=False, host='0.0.0.0', port=5050)