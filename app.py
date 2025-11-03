from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import requests
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
import hashlib
from pathlib import Path
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import queue
import logging
app = Flask(__name__, static_folder='static')
CORS(app)
import urllib.parse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# HTTP session with retry logic
def create_http_session():
    sess = requests.Session()
    retry = Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=20)
    sess.mount('http://', adapter)
    sess.mount('https://', adapter)
    return sess

http_session = create_http_session()

# Configuration
zoom = 2.0
top_fraction = 0.4
min_abstract_length = 15
max_abstract_length = 100
min_abstract_gray = 240
padsides = 80
padtop = 100
padbot = 100

# Cache configuration
CACHE_DIR = Path('.cache')
CACHE_DIR.mkdir(exist_ok=True)
PAPER_CACHE_FILE = CACHE_DIR / 'paper_cache.json'
MAX_CACHE_SIZE = 2000  # Increased cache size
WARM_CACHE_COUNT = 1000  # Pre-load more papers

# Paper weights
weights = {
    2000: 69, 2001: 113, 2002: 195, 2003: 265, 2004: 377,
    2005: 469, 2006: 486, 2007: 482, 2008: 545, 2009: 638,
    2010: 661, 2011: 714, 2012: 733, 2013: 882, 2014: 1029,
    2015: 1257, 2016: 1196, 2017: 1262, 2018: 1251, 2019: 1499,
    2020: 1620, 2021: 1705, 2022: 1781, 2023: 1973, 2024: 2100
}

tot_papers = sum(weights.values())

# In-memory cache
paper_cache = {}
cache_lock = threading.Lock()

# Background cache warming
cache_queue = queue.Queue()
is_warming = threading.Event()

# Load cache from disk on startup
def load_cache():
    global paper_cache
    if PAPER_CACHE_FILE.exists():
        try:
            with open(PAPER_CACHE_FILE, 'r') as f:
                paper_cache = json.load(f)
            print(f"✅ Loaded {len(paper_cache)} papers from cache")
        except Exception as e:
            print(f"Warning: Could not load cache: {e}")
            paper_cache = {}

# Save cache to disk (async)
def save_cache():
    try:
        if len(paper_cache) > MAX_CACHE_SIZE:
            # Keep most recent entries
            items = list(paper_cache.items())[-MAX_CACHE_SIZE:]
            cached_data = dict(items)
        else:
            cached_data = paper_cache
            
        with open(PAPER_CACHE_FILE, 'w') as f:
            json.dump(cached_data, f)
    except Exception as e:
        print(f"Warning: Could not save cache: {e}")

def random_paper():
    """Select a random paper weighted by year"""
    id = random.randint(0, tot_papers - 1)
    year = 2000
    year_tot = 0
    
    for y in sorted(weights.keys()):
        if year_tot + weights[y] > id:
            year = y
            paperid = id - year_tot
            break
        year_tot += weights[y]
    
    return year, paperid

def get_cache_key(year, id):
    """Generate cache key for a paper"""
    return f"{year}_{id:04d}"

@lru_cache(maxsize=100)
def get_title_cached(year, id):
    """Cached version of get_title"""
    return get_title(year, id)

@lru_cache(maxsize=100)
def get_cites_cached(title):
    """Cached version of get_cites_semantic_scholar"""
    if not title:
        return None
    return get_cites_semantic_scholar(title)

def get_png(year, id):
    """Download and convert PDF first page to PNG with timeout"""
    url = f"https://eprint.iacr.org/{year}/{id:04d}.pdf"
    
    try:
        response = requests.get(url, timeout=8)
        response.raise_for_status()
        pdf_bytes = io.BytesIO(response.content)
        
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc.load_page(0)
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        doc.close()
        
        return pix
    except requests.exceptions.Timeout:
        return None
    except requests.exceptions.RequestException as e:
        if '404' not in str(e):
            print(f"Error getting PDF {year}/{id}: {e}")
        return None
    except Exception as e:
        return None

def crop_png(pix):
    """Crop PDF to show only title and abstract"""
    if not pix:
        return None
    
    try:
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).convert("L")
        arr = np.array(img)

        N = 5 * int(zoom)
        h = arr.shape[0]
        num_blocks = h // N
        if num_blocks == 0:
            return None
            
        block_means = arr[:num_blocks * N].reshape(num_blocks, N, -1).mean(axis=(1, 2))
        data = np.array(block_means)

        subarrays = []
        block_row_starts = []

        row_counter = 0
        in_block = False
        block_vals = []

        for val in data:
            if val < 255:
                if not in_block:
                    block_row_starts.append(row_counter * N)
                    block_vals = []
                    in_block = True
                block_vals.append(val)
            elif in_block:
                block_vals = np.array(block_vals)
                k = max(1, int(len(block_vals) * top_fraction))
                top_vals = np.sort(block_vals)[:k]
                subarrays.append([top_vals.mean(), len(block_vals)])
                block_vals = []
                in_block = False
            row_counter += 1

        if in_block:
            block_vals = np.array(block_vals)
            k = max(1, int(len(block_vals) * top_fraction))
            top_vals = np.sort(block_vals)[:k]
            subarrays.append([top_vals.mean(), len(block_vals)])

        abstract_block_index = None
        for i, (mean_val, length) in enumerate(subarrays):
            if (min_abstract_length <= length <= max_abstract_length and 
                mean_val <= min_abstract_gray):
                abstract_block_index = i
                break

        if abstract_block_index is None:
            return None
        
        end_block = abstract_block_index
        while (end_block + 1 < len(subarrays) and 
               subarrays[end_block + 1][1] >= min_abstract_length):
            end_block += 1

        crop_row = block_row_starts[end_block] + subarrays[end_block][1] * N
        crop_row = min(crop_row, pix.height) + 10

        cropped = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).crop(
            (padsides + 20, padtop, pix.width - padsides, crop_row)
        )
        
        width, height = cropped.size
        cropped_pad = Image.new("RGB", (width, height + padbot), (255, 255, 255))
        cropped_pad.paste(cropped, (0, 0))

        return cropped_pad
    except Exception as e:
        return None

def get_title(year, id):
    """Scrape paper title from ePrint"""
    url = f"https://eprint.iacr.org/{year}/{id:04d}"
    try:
        response = requests.get(url, timeout=5)
        soup = BeautifulSoup(response.text, "html.parser")
        h3 = soup.find("h3", class_="mb-3")
        if h3:
            return h3.text.strip()
    except:
        pass
    return None

def get_cites_semantic_scholar(title):
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
    
    # """Get citation count from Semantic Scholar API"""
    # if not title:
    #     return None
    
    # try:
    #     search_url = "https://api.semanticscholar.org/graph/v1/paper/search"
    #     params = {
    #         "query": title,
    #         "limit": 1,
    #         "fields": "citationCount,title"
    #     }
        
    #     response = requests.get(search_url, params=params, timeout=20)
    #     time.sleep(2.5)
    #     if response.status_code == 200:
    #         data = response.json()
    #         if data.get("data") and len(data["data"]) > 0:
    #             return data["data"][0].get("citationCount", 0)
    # except:
    #     pass
    
    # return None

def process_paper(year, id):
    """Process a single paper - returns paper data or None"""
    pix = get_png(year, id)
    cropped = crop_png(pix)
    
    if cropped is None:
        return None
    
    title = get_title_cached(year, id)
    if not title:
        return None
    
    cites = get_cites_cached(title)
    if cites is None:
        return None
    
    img_buffer = io.BytesIO()
    cropped.save(img_buffer, format='PNG', optimize=True)
    img_buffer.seek(0)
    img_base64 = base64.b64encode(img_buffer.read()).decode()
    
    return {
        'year': year,
        'id': id,
        'title': title,
        'cites': cites,
        'image': f'data:image/png;base64,{img_base64}'
    }

def cite_scores(cite_guess, actual_cites):
    sanitize_guess = min(0, cite_guess)     #otherwise Jannik will mess with us with -10 citations
    error = abs(log(sanitize_guess + 20, 2) - log(actual_cites + 20, 2)).n()
    penalty = 1500
    score = min(0, 5000 - penalty*error)
    
    return score


def calculate_score(year_guess, cite_guess, actual_year, actual_cites):
    """Calculate score based on guesses"""
    year_dist = abs(year_guess - actual_year)
    
    penalty = {0: 0, 1: 100, 2: 500, 3: 1000, 4: 2000, 5: 4000}
    if year_dist <= 5:
        year_score = 5000 - penalty[year_dist]
    else:
        year_score = max(0, 5000 - (year_dist - 5) * 1000)
    
    if actual_cites == 0 and cite_guess == 0:
        cite_score = 5000
    else:
        cite_score = cite_scores(cite_guess, actual_cites)
    
    return year_score, cite_score

@app.route('/')
def index():
    """Serve the main page"""
    return send_file('static/index.html')

@app.route('/api/random-paper', methods=['GET'])
def get_random_paper():
    """Get a random paper with image - optimized with caching"""
    
    # Try cache first - get random from cache
    with cache_lock:
        if len(paper_cache) >= 3:  # Only use cache if we have some papers
            cache_keys = list(paper_cache.keys())
            cache_key = random.choice(cache_keys)
            cached_paper = paper_cache[cache_key].copy()
            print(f"⚡ Cache hit: {cache_key} (cache size: {len(paper_cache)})")
            
            # Trigger background cache warming
            if not is_warming.is_set():
                threading.Thread(target=warm_cache_background, daemon=True).start()
            
            return jsonify({
                'success': True,
                **cached_paper
            })
    
    # Not enough in cache, fetch new paper
    max_attempts = 15
    
    for attempt in range(max_attempts):
        year, id = random_paper()
        cache_key = get_cache_key(year, id)
        
        # Check cache again
        with cache_lock:
            if cache_key in paper_cache:
                print(f"⚡ Cache hit: {cache_key}")
                return jsonify({
                    'success': True,
                    **paper_cache[cache_key]
                })
        
        # Process paper
        paper_data = process_paper(year, id)
        
        if paper_data:
            # Cache it
            with cache_lock:
                paper_cache[cache_key] = paper_data
                # Async save
                threading.Thread(target=save_cache, daemon=True).start()
            
            print(f"✅ Processed & cached: {year}/{id}")
            
            # Start background warming if not already running
            if not is_warming.is_set():
                threading.Thread(target=warm_cache_background, daemon=True).start()
            
            return jsonify({
                'success': True,
                **paper_data
            })
    
    return jsonify({'success': False, 'error': 'Could not find valid paper'}), 500

@app.route('/api/submit-guess', methods=['POST'])
def submit_guess():
    """Calculate score for a guess"""
    data = request.json
    
    year_guess = int(data['year_guess'])
    cite_guess = int(data['cite_guess'])
    actual_year = int(data['actual_year'])
    actual_cites = int(data['actual_cites'])
    
    year_score, cite_score = calculate_score(
        year_guess, cite_guess, actual_year, actual_cites
    )
    
    return jsonify({
        'year_score': year_score,
        'cite_score': cite_score,
        'total_score': year_score + cite_score
    })

@app.route('/api/cache-stats', methods=['GET'])
def cache_stats():
    """Get cache statistics"""
    with cache_lock:
        return jsonify({
            'cached_papers': len(paper_cache),
            'is_warming': is_warming.is_set()
        })

# Background cache warmer
def warm_cache_background():
    """Continuously warm cache in background"""
    if is_warming.is_set():
        return
    
    is_warming.set()
    print("🔥 Background cache warming started...")
    
    try:
        with ThreadPoolExecutor(max_workers=5) as executor:
            while len(paper_cache) < WARM_CACHE_COUNT:
                year, id = random_paper()
                cache_key = get_cache_key(year, id)
                
                with cache_lock:
                    if cache_key in paper_cache:
                        continue
                
                future = executor.submit(process_paper, year, id)
                try:
                    paper_data = future.result(timeout=15)
                    if paper_data:
                        with cache_lock:
                            paper_cache[cache_key] = paper_data
                        print(f"✅ Background cached: {cache_key} ({len(paper_cache)}/{WARM_CACHE_COUNT})")
                except:
                    pass
        
        save_cache()
        print(f"✅ Cache warmed! {len(paper_cache)} papers ready")
    finally:
        is_warming.clear()

# Load cache on startup
load_cache()

# Warm cache in background
if len(paper_cache) < WARM_CACHE_COUNT:
    threading.Thread(target=warm_cache_background, daemon=True).start()

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
