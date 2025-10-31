
const API_URL = 'http://178.156.186.180:5050';

// Game state
let currentPaper = null;
let roundNumber = 1;
let roundsPlayed = 0;

const loadingScreen = document.getElementById('loading');
const gameContainer = document.getElementById('game-container');
const paperImage = document.getElementById('paper-image');
const yearGuess = document.getElementById('year-guess');
const citeGuess = document.getElementById('cite-guess');
const submitBtn = document.getElementById('submit-btn');
const guessCard = document.getElementById('guess-card');
const resultsCard = document.getElementById('results-card');
const nextBtn = document.getElementById('next-btn');
const roundNumberSpan = document.getElementById('round-number');
const roundsPlayedSpan = document.getElementById('rounds-played');
const themeToggle = document.getElementById('theme-toggle');
const cacheBadge = document.getElementById('cache-badge');
const cacheCount = document.getElementById('cache-count');

// Theme management
function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
    updateThemeIcon(savedTheme);
}

function updateThemeIcon(theme) {
    const sunIcon = themeToggle.querySelector('.sun-icon');
    const moonIcon = themeToggle.querySelector('.moon-icon');
    if (theme === 'dark') {
        sunIcon.style.display = 'block';
        moonIcon.style.display = 'none';
    } else {
        sunIcon.style.display = 'none';
        moonIcon.style.display = 'block';
    }
}

themeToggle.addEventListener('click', () => {
    const newTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    updateThemeIcon(newTheme);
});

async function updateCacheStats() {
    try {
        const response = await fetch(`${API_URL}/api/cache-stats`, { credentials: 'include' });
        if (!response.ok) return;
        const data = await response.json();
        if (data.cached_papers > 0) {
            cacheBadge.style.display = 'flex';
            cacheCount.textContent = data.cached_papers;
        }
    } catch (error) {
        console.log('Could not fetch cache stats');
    }
}

async function fetchRandomPaper() {
    loadingScreen.style.display = 'flex';
    gameContainer.style.display = 'none';
    try {
        const response = await fetch(`${API_URL}/api/random-paper`, { credentials: 'include' });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || `Server returned status ${response.status}`);
        }
        currentPaper = { paper_id: data.paper_id };
        paperImage.src = data.image;
        paperImage.onload = () => {
            loadingScreen.style.display = 'none';
            gameContainer.style.display = 'grid';
            guessCard.style.display = 'block';
            resultsCard.style.display = 'none';
        };
    } catch (error) {
        loadingScreen.innerHTML = `<div class="loading-content"><p style="color: #e74c3c;">❌ Error loading paper</p><small>${error.message}</small><button onclick="location.reload()" class="btn-primary" style="margin-top: 20px;">Retry</button></div>`;
    }
}

function setSubmitButtonState(disabled, text) {
    submitBtn.disabled = disabled;
    const span = submitBtn.querySelector('span');
    if (span) span.textContent = text;
}

async function submitGuess() {
    const year = parseInt(yearGuess.value);
    const cites = parseInt(citeGuess.value);
    if (isNaN(year) || year < 2000 || year > 2025) { alert('Please enter a valid year.'); return; }
    if (isNaN(cites) || cites < 0) { alert('Please enter a valid citation count.'); return; }
    setSubmitButtonState(true, 'Submitting...');
    try {
        const response = await fetch(`${API_URL}/api/submit-guess`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ paper_id: currentPaper.paper_id, year_guess: year, cite_guess: cites })
        });
        const result = await response.json();
        if (!response.ok || !result.success) {
            // This will now display the helpful error message from the server
            throw new Error(result.error || `Server error: ${response.statusText}`);
        }
        roundsPlayed++;
        roundsPlayedSpan.textContent = roundsPlayed;
        displayResults(result, year, cites);
    } catch (error) {
        console.error('Error submitting guess:', error);
        alert('Error submitting guess: ' + error.message);
        setSubmitButtonState(false, 'Submit Your Guess');
    }
}

function displayResults(result, yearGuessed, citesGuessed) {
    const { year_score, cite_score, actual_year, actual_cites, actual_id, title } = result;
    document.getElementById('result-title').textContent = title;
    document.getElementById('result-year').textContent = actual_year;
    document.getElementById('result-cites').textContent = actual_cites.toLocaleString();
    const yearDiff = Math.abs(yearGuessed - actual_year);
    document.getElementById('year-feedback').innerHTML = `<div class="score-display">${year_score.toLocaleString()}/5,000</div><div class="diff-display">${yearDiff === 0 ? '🎯 Perfect!' : `Off by ${yearDiff} year${yearDiff > 1 ? 's' : ''}`}<small>Guessed: ${yearGuessed} | Actual: ${actual_year}</small></div>`;
    const citeDiff = Math.abs(citesGuessed - actual_cites);
    document.getElementById('cite-feedback').innerHTML = `<div class="score-display">${cite_score.toLocaleString()}/5,000</div><div class="diff-display">${citeDiff === 0 ? '🎯 Perfect!' : `Off by ${citeDiff.toLocaleString()}`}<small>Guessed: ${citesGuessed.toLocaleString()} | Actual: ${actual_cites.toLocaleString()}</small></div>`;
    
    // Use the non-padded ID for the link, as corrected previously
    document.getElementById('paper-link').href = `https://eprint.iacr.org/${actual_year}/${actual_id}`;
    
    guessCard.style.display = 'none';
    resultsCard.style.display = 'block';
    resultsCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function nextRound() {
    yearGuess.value = '';
    citeGuess.value = '';
    setSubmitButtonState(false, 'Submit Your Guess');
    roundNumber++;
    roundNumberSpan.textContent = roundNumber;
    fetchRandomPaper();
}

// Event listeners
submitBtn.addEventListener('click', submitGuess);
nextBtn.addEventListener('click', nextRound);
yearGuess.addEventListener('keypress', (e) => { if (e.key === 'Enter') citeGuess.focus(); });
citeGuess.addEventListener('keypress', (e) => { if (e.key === 'Enter' && !submitBtn.disabled) submitGuess(); });

// Initialize
initTheme();
fetchRandomPaper();
updateCacheStats();
setInterval(updateCacheStats, 30000);