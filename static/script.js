// Theme Management - DARK MODE AS DEFAULT
const themeToggle = document.getElementById('theme-toggle');
const html = document.documentElement;

// Default to dark theme if no preference is saved
const currentTheme = localStorage.getItem('theme') || 'dark';
html.setAttribute('data-theme', currentTheme);

themeToggle.addEventListener('click', () => {
    const theme = html.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    html.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
});

// Game state
let currentPaper = null;
let roundNumber = 1;
let roundsPlayed = 0;
let isLoading = false;

// DOM elements
const loading = document.getElementById('loading');
const gameContainer = document.getElementById('game-container');
const paperImage = document.getElementById('paper-image');
const yearGuess = document.getElementById('year-guess');
const citeGuess = document.getElementById('cite-guess');
const submitBtn = document.getElementById('submit-btn');
const guessCard = document.getElementById('guess-card');
const resultsCard = document.getElementById('results-card');
const nextBtn = document.getElementById('next-btn');
const cacheBadge = document.getElementById('cache-badge');
const cacheCount = document.getElementById('cache-count');

const roundNumberDisplay = document.getElementById('round-number');
const roundsPlayedDisplay = document.getElementById('rounds-played');
const resultTitle = document.getElementById('result-title');
const resultYear = document.getElementById('result-year');
const resultCites = document.getElementById('result-cites');
const yearFeedback = document.getElementById('year-feedback');
const citeFeedback = document.getElementById('cite-feedback');
const paperLink = document.getElementById('paper-link');

// Update cache stats
async function updateCacheStats() {
    try {
        const response = await fetch('/api/cache-stats');
        const data = await response.json();
        cacheCount.textContent = data.cached_papers;
        if (data.cached_papers > 0) {
            cacheBadge.style.display = 'block';
        }
    } catch (e) {
        // Ignore errors
    }
}

async function loadNewPaper() {
    if (isLoading) {
        console.log('Already loading, ignoring request');
        return;
    }
    
    isLoading = true;
    console.log('Loading new paper...');
    
    loading.style.display = 'block';
    gameContainer.style.display = 'none';
    
    // Reset form
    yearGuess.value = '';
    citeGuess.value = '';
    guessCard.style.display = 'block';
    resultsCard.style.display = 'none';
    currentPaper = null;
    
    const maxRetries = 3;
    
    for (let retry = 0; retry < maxRetries; retry++) {
        try {
            console.log(`Attempt ${retry + 1}/${maxRetries}`);
            
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 30000);
            
            const response = await fetch('/api/random-paper', {
                signal: controller.signal,
                method: 'GET',
                cache: 'no-cache'
            });
            clearTimeout(timeoutId);
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            console.log('Received data:', data.success ? 'success' : 'failed');
            
            if (data.success) {
                currentPaper = data;
                paperImage.src = data.image;
                
                // Wait for image to load
                await new Promise((resolve) => {
                    paperImage.onload = resolve;
                    paperImage.onerror = resolve;
                });
                
                loading.style.display = 'none';
                gameContainer.style.display = 'grid';
                roundNumberDisplay.textContent = roundNumber;
                roundsPlayedDisplay.textContent = roundsPlayed;
                
                // Update cache stats
                updateCacheStats();
                
                isLoading = false;
                console.log('Paper loaded successfully');
                return;
            } else {
                if (retry < maxRetries - 1) {
                    console.log('Failed, retrying...');
                    await new Promise(resolve => setTimeout(resolve, 1000));
                    continue;
                }
                alert('Error loading paper. Please refresh the page.');
                isLoading = false;
                return;
            }
        } catch (error) {
            console.error('Error:', error);
            if (retry < maxRetries - 1) {
                console.log('Error occurred, retrying...');
                await new Promise(resolve => setTimeout(resolve, 1000));
                continue;
            }
            alert('Network error. Please refresh the page and try again.');
            isLoading = false;
            return;
        }
    }
    
    isLoading = false;
}

function getYearFeedback(guess, actual) {
    const diff = guess - actual;
    const absDiff = Math.abs(diff);
    
    if (diff === 0) return '🎯 Perfect! Spot on!';
    else if (absDiff === 1) return diff > 0 ? '📅 1 year too recent' : '📅 1 year too old';
    else if (absDiff <= 3) return diff > 0 ? `📅 ${absDiff} years too recent` : `📅 ${absDiff} years too old`;
    else if (absDiff <= 5) return diff > 0 ? `📅 ${absDiff} years too recent (getting warm)` : `📅 ${absDiff} years too old (close!)`;
    else if (absDiff <= 10) return diff > 0 ? `📅 ${absDiff} years too recent` : `📅 ${absDiff} years too old`;
    else return diff > 0 ? `📅 Way too recent (${absDiff} years off)` : `📅 Way too old (${absDiff} years off)`;
}

function getCitationFeedback(guess, actual) {
    const diff = guess - actual;
    const absDiff = Math.abs(diff);
    const percentDiff = actual === 0 ? 100 : (absDiff / actual) * 100;
    
    if (diff === 0) return '🎯 Exactly right!';
    
    if (actual < 50) {
        if (absDiff <= 5) return diff > 0 ? `📚 ${absDiff} citations too high (very close!)` : `📚 ${absDiff} citations too low (very close!)`;
        else if (absDiff <= 20) return diff > 0 ? `📚 ${absDiff} citations too high` : `📚 ${absDiff} citations too low`;
        else return diff > 0 ? `📚 Overestimated by ${absDiff} citations` : `📚 Underestimated by ${absDiff} citations`;
    }
    
    if (percentDiff <= 10) return diff > 0 ? `📚 Slightly overestimated (${absDiff} citations, ${percentDiff.toFixed(0)}% off)` : `📚 Slightly underestimated (${absDiff} citations, ${percentDiff.toFixed(0)}% off)`;
    else if (percentDiff <= 25) return diff > 0 ? `📚 Overestimated by ${percentDiff.toFixed(0)}%` : `📚 Underestimated by ${percentDiff.toFixed(0)}%`;
    else if (percentDiff <= 50) return diff > 0 ? `📚 Significantly overestimated (${percentDiff.toFixed(0)}% too high)` : `📚 Significantly underestimated (${percentDiff.toFixed(0)}% too low)`;
    else return diff > 0 ? `📚 Way overestimated (${absDiff.toLocaleString()} citations off)` : `📚 Way underestimated (${absDiff.toLocaleString()} citations off)`;
}

async function submitGuess() {
    if (!currentPaper) {
        alert('No paper loaded. Please wait for a paper to load.');
        return;
    }
    
    const yearGuessValue = parseInt(yearGuess.value);
    const citeGuessValue = parseInt(citeGuess.value);
    
    if (isNaN(yearGuessValue) || yearGuessValue < 2000 || yearGuessValue > 2024) {
        alert('Please enter a valid year between 2000 and 2024');
        return;
    }
    
    if (isNaN(citeGuessValue) || citeGuessValue < 0) {
        alert('Please enter a valid number of citations (0 or more)');
        return;
    }
    
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span>Evaluating...</span>';
    
    try {
        const yearFeedbackText = getYearFeedback(yearGuessValue, currentPaper.year);
        const citeFeedbackText = getCitationFeedback(citeGuessValue, currentPaper.cites);
        
        resultTitle.textContent = currentPaper.title;
        resultYear.textContent = currentPaper.year;
        resultCites.textContent = currentPaper.cites.toLocaleString();
        yearFeedback.textContent = yearFeedbackText;
        citeFeedback.textContent = citeFeedbackText;
        paperLink.href = `https://eprint.iacr.org/${currentPaper.year}/${String(currentPaper.id).padStart(4, '0')}`;
        
        roundsPlayed++;
        roundsPlayedDisplay.textContent = roundsPlayed;
        
        guessCard.style.display = 'none';
        resultsCard.style.display = 'block';
        
        if (window.innerWidth <= 1200) {
            resultsCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
        
    } catch (error) {
        console.error('Error:', error);
        alert('Error calculating feedback. Please try again.');
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<span>Submit Your Guess</span><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>';
    }
}

function nextRound() {
    console.log('Next round clicked');
    roundNumber++;
    loadNewPaper();
}

// Event listeners
submitBtn.addEventListener('click', submitGuess);
nextBtn.addEventListener('click', nextRound);

yearGuess.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') citeGuess.focus();
});

citeGuess.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') submitGuess();
});

// Initial load
console.log('Starting initial load...');
loadNewPaper();

// Update cache stats periodically
setInterval(updateCacheStats, 10000);
