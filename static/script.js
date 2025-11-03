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


function sliderToCitations(sliderValue) {
    const citations = Math.round((Math.exp(sliderValue / 20) - 1) * 10);
    return Math.min(citations, 10000); // Cap at 10k
}

function citationsToSlider(citations) {
    // Inverse: sliderValue = 20 * ln((citations/10) + 1)
    return Math.round(20 * Math.log((citations / 10) + 1));
}

// Game state
let currentPaper = null;
let roundNumber = 1;
let roundsPlayed = 0;
let totalScore = 0;
let roundScores = []; // Track individual round scores
let isLoading = false;

// DOM elements
const loading = document.getElementById('loading');
const gameContainer = document.getElementById('game-container');
const paperImage = document.getElementById('paper-image');
const yearGuess = document.getElementById('year-guess');
const citeGuess = document.getElementById('cite-guess');
const yearValue = document.getElementById('year-value');
const citeValue = document.getElementById('cite-value');
const submitBtn = document.getElementById('submit-btn');
const guessCard = document.getElementById('guess-card');
const resultsCard = document.getElementById('results-card');
const nextBtn = document.getElementById('next-btn');
const cacheBadge = document.getElementById('cache-badge');
const cacheCount = document.getElementById('cache-count');

const roundNumberDisplay = document.getElementById('round-number');
const roundsPlayedDisplay = document.getElementById('rounds-played');
const totalScoreDisplay = document.getElementById('total-score');
const resultTitle = document.getElementById('result-title');
const resultYear = document.getElementById('result-year');
const resultCites = document.getElementById('result-cites');
const yearFeedback = document.getElementById('year-feedback');
const citeFeedback = document.getElementById('cite-feedback');
const yearScoreDisplay = document.getElementById('year-score');
const citeScoreDisplay = document.getElementById('cite-score');
const roundScoreDisplay = document.getElementById('round-score');
const paperLink = document.getElementById('paper-link');

// Slider value update handlers with gradient background
function updateSliderBackground(slider) {
    const min = parseFloat(slider.min);
    const max = parseFloat(slider.max);
    const value = parseFloat(slider.value);
    const percentage = ((value - min) / (max - min)) * 100;
    
    slider.style.background = `linear-gradient(to right, 
        var(--accent-color) 0%, 
        var(--accent-color) ${percentage}%, 
        var(--border-color) ${percentage}%, 
        var(--border-color) 100%)`;
}

yearGuess.addEventListener('input', (e) => {
    yearValue.textContent = e.target.value;
    updateSliderBackground(e.target);
});

citeGuess.addEventListener('input', (e) => {
    const sliderValue = parseInt(e.target.value);
    const citations = sliderToCitations(sliderValue);
    citeValue.textContent = citations >= 1000 ? `${(citations / 1000).toFixed(1)}k` : citations;
    updateSliderBackground(e.target);
});

// Initialize slider backgrounds on load
updateSliderBackground(yearGuess);
updateSliderBackground(citeGuess);

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
    
    // Reset sliders to middle values
    yearGuess.value = 2012;
    citeGuess.value = 50; // Slider value (maps to ~20 citations)
    yearValue.textContent = '2012';
    const defaultCitations = sliderToCitations(50);
    citeValue.textContent = defaultCitations;
    updateSliderBackground(yearGuess);
    updateSliderBackground(citeGuess);
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
                totalScoreDisplay.textContent = totalScore.toLocaleString();
                
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
    const citeSliderValue = parseInt(citeGuess.value);
    const citeGuessValue = sliderToCitations(citeSliderValue); // Convert slider to actual citations
    
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span>Calculating Score...</span>';
    
    try {
        // Get scores from backend
        const response = await fetch('/api/submit-guess', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                year_guess: yearGuessValue,
                cite_guess: citeGuessValue,
                actual_year: currentPaper.year,
                actual_cites: currentPaper.cites
            })
        });
        
        if (!response.ok) {
            throw new Error('Failed to calculate score');
        }
        
        const scoreData = await response.json();
        const yearScore = scoreData.year_score;
        const citeScore = scoreData.cite_score;
        const roundScore = scoreData.total_score;
        
        // Update cumulative score
        totalScore += roundScore;
        roundScores.push({
            round: roundNumber,
            yearScore: yearScore,
            citeScore: citeScore,
            totalScore: roundScore,
            paper: currentPaper.title
        });
        
        // Get feedback text
        const yearFeedbackText = getYearFeedback(yearGuessValue, currentPaper.year);
        const citeFeedbackText = getCitationFeedback(citeGuessValue, currentPaper.cites);
        
        // Display results
        resultTitle.textContent = currentPaper.title;
        resultYear.textContent = currentPaper.year;
        resultCites.textContent = currentPaper.cites.toLocaleString();
        yearFeedback.textContent = yearFeedbackText;
        citeFeedback.textContent = citeFeedbackText;
        
        // Display scores
        yearScoreDisplay.textContent = yearScore.toLocaleString();
        citeScoreDisplay.textContent = citeScore.toLocaleString();
        roundScoreDisplay.textContent = roundScore.toLocaleString();
        
        paperLink.href = `https://eprint.iacr.org/${currentPaper.year}/${String(currentPaper.id).padStart(4, '0')}`;
        
        roundsPlayed++;
        roundsPlayedDisplay.textContent = roundsPlayed;
        totalScoreDisplay.textContent = totalScore.toLocaleString();
        
        guessCard.style.display = 'none';
        resultsCard.style.display = 'block';
        
        if (window.innerWidth <= 1200) {
            resultsCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
        
    } catch (error) {
        console.error('Error:', error);
        alert('Error calculating score. Please try again.');
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

function resetGame() {
    if (confirm('Are you sure you want to reset your score and start over?')) {
        roundNumber = 1;
        roundsPlayed = 0;
        totalScore = 0;
        roundScores = [];
        loadNewPaper();
    }
}

// Event listeners
submitBtn.addEventListener('click', submitGuess);
nextBtn.addEventListener('click', nextRound);

// Allow Enter key on sliders to submit
yearGuess.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') submitGuess();
});

citeGuess.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') submitGuess();
});

// Initial load
console.log('Starting initial load...');
loadNewPaper();

// Update cache stats periodically
setInterval(updateCacheStats, 10000);