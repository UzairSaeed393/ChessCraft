// ==========================================
// STATE VARIABLES & UI ELEMENTS
// ==========================================
let board = null;
let game = new Chess();
let reviewChart = null;

// Variables to handle PGN playback navigation
let gameHistory = []; 
let currentMoveIndex = 0;

const $evalFill = $('#eval-fill');
const $moveDesc = $('#move-desc');
const $suggestionBox = $('#suggestion-box');

// ==========================================
// 1. BOARD INITIALIZATION & DRAG-DROP LOGIC
// ==========================================
function onDrop(source, target) {
    // Attempt to make the move
    let move = game.move({
        from: source,
        to: target,
        promotion: 'q' // Always promote to Queen for simplicity
    });

    // If the move is illegal, snap the piece back
    if (move === null) return 'snapback';

    // A user made a manual move. Clear the strict mainline history 
    // so they can freely explore this new "What-If" variation.
    gameHistory = [];
    currentMoveIndex = 0;

    // Trigger the Azure Stockfish API for this new position
    updateEngineAnalysis(game.fen());
}

const config = {
    draggable: true,
    position: 'start',
    onDrop: onDrop,
    pieceTheme: '/static/img/chesspieces/wikipedia/{piece}.png'
};

// Mount the chessboard to the HTML div
board = Chessboard('mainBoard', config);


// ==========================================
// 2. LIVE "WHAT-IF" ANALYSIS API CALL
// ==========================================
async function updateEngineAnalysis(fen) {
    $moveDesc.text("Analyzing line...");
    $suggestionBox.text("Thinking...");

    try {
        const response = await fetch('/analysis/api/analyze/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({ fen: fen })
        });

        if (!response.ok) throw new Error("Network response was not ok");
        
        const data = await response.json();

        // 1. Update the Evaluation Bar (Scale +5 to -5)
        // 50% is dead even. +5 is 100% height.
        let heightPercent = 50 + (data.evaluation * 10);
        $evalFill.css('height', Math.max(5, Math.min(95, heightPercent)) + '%');

        // 2. Update the Text UI
        let evalFormatted = data.evaluation > 0 ? `+${data.evaluation}` : data.evaluation;
        $moveDesc.html(`Stockfish Evaluation: <strong class="text-dark">${evalFormatted}</strong> (Depth ${data.depth})`);
        $suggestionBox.html(`Best follow-up: <span class="text-success">${data.best_move}</span>`);

    } catch (error) {
        console.error("Analysis failed:", error);
        $moveDesc.text("Engine connection failed.");
        $suggestionBox.text("");
    }
}


// ==========================================
// 3. FULL GAME REVIEW API CALL
// ==========================================
// Call this function when the user clicks "Start Review" and pass the PGN string
async function runFullGameReview(pgnText) {
    // Show a loading indicator
    $('#reviewChart').parent().append('<div id="loading-spinner" class="text-center mt-4 text-muted small">Generating Game Review...</div>');
    $('#reviewChart').hide();

    try {
        const response = await fetch('/analysis/api/review/', { 
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: new URLSearchParams({ pgn: pgnText })
        });

        const data = await response.json();

        if (data.status === "success") {
            // Render the Evaluation Wave Graph
            initChart(data.eval_history);

            // Load the full game into memory for playback controls
            game.load_pgn(pgnText);
            gameHistory = game.history(); 
            currentMoveIndex = gameHistory.length; 
            board.position(game.fen());

            // Remove loading spinner and show chart
            $('#loading-spinner').remove();
            $('#reviewChart').show();
            
            // Analyze the final position automatically
            updateEngineAnalysis(game.fen());
        }
    } catch (error) {
        console.error("Full review failed:", error);
        $('#loading-spinner').text("Failed to process game review.");
    }
}


// ==========================================
// 4. CHART.JS GRAPH GENERATION
// ==========================================
function initChart(evalData) {
    const ctx = document.getElementById('reviewChart').getContext('2d');
    
    // Destroy the old chart if a new review is run
    if (reviewChart) reviewChart.destroy();

    reviewChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: evalData.map((_, i) => i), // X-Axis Move numbers
            datasets: [{
                data: evalData, // Y-Axis Eval scores
                borderColor: '#0A653A', // Matches your --primary CSS variable
                backgroundColor: 'rgba(10, 101, 58, 0.2)', // Light green fill
                fill: true,
                tension: 0.4, // Smooths the line into a wave
                pointRadius: 0 // Removes dots for a clean look
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { display: false },
                y: { display: false, suggestedMin: -5, suggestedMax: 5 }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: { label: (context) => `Eval: ${context.raw}` }
                }
            }
        }
    });
}


// ==========================================
// 5. NAVIGATION CONTROLS (Playback)
// ==========================================
$('#btnStart').on('click', () => {
    game.reset();
    board.start();
    currentMoveIndex = 0;
    updateEngineAnalysis(game.fen());
});

$('#btnPrev').on('click', () => {
    game.undo();
    board.position(game.fen());
    if (currentMoveIndex > 0) currentMoveIndex--;
    updateEngineAnalysis(game.fen());
});

$('#btnNext').on('click', () => {
    // Only works if we have a game loaded from a PGN
    if (gameHistory.length > 0 && currentMoveIndex < gameHistory.length) {
        // Reconstruct the game state up to the next move
        game.reset();
        currentMoveIndex++;
        for(let i=0; i < currentMoveIndex; i++) {
            game.move(gameHistory[i]);
        }
        board.position(game.fen());
        updateEngineAnalysis(game.fen());
    }
});

$('#btnEnd').on('click', () => {
    if (gameHistory.length > 0) {
        game.reset();
        for(let i=0; i < gameHistory.length; i++) {
            game.move(gameHistory[i]);
        }
        currentMoveIndex = gameHistory.length;
        board.position(game.fen());
        updateEngineAnalysis(game.fen());
    }
});


// ==========================================
// 6. DJANGO CSRF SECURITY HELPER
// ==========================================
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            // Does this cookie string begin with the name we want?
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

let board = null;
let game = new Chess();
let reviewChart = null;

// Tab Switching for Mobile
function switchPane(id, el) {
    $('.pane-content').removeClass('active');
    $(`#${id}`).addClass('active');
    $('.tab-link').removeClass('active');
    $(el).addClass('active');
    if(id === 'pane-board') board.resize();
}

// Live Analysis API
async function updateAnalysis(fen) {
    const response = await fetch('/analysis/api/analyze/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
        body: JSON.stringify({ fen: fen })
    });
    const data = await response.json();
    
    // Update Eval Bar
    let height = 50 + (data.evaluation * 10);
    $('#eval-fill').css('height', Math.max(5, Math.min(95, height)) + '%');
    $('#eval-score').text(data.evaluation);
}

// Chart Initialization
function initChart(dataPoints) {
    const ctx = document.getElementById('reviewChart').getContext('2d');
    if (reviewChart) reviewChart.destroy();
    reviewChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: dataPoints.map((_, i) => i),
            datasets: [{
                data: dataPoints,
                borderColor: '#81b64c',
                fill: true,
                backgroundColor: 'rgba(129, 182, 76, 0.1)',
                tension: 0.4,
                pointRadius: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: { x: { display: false }, y: { display: false, min: -8, max: 8 } },
            plugins: { legend: { display: false } }
        }
    });
}

// Board Config
board = Chessboard('mainBoard', {
    draggable: true,
    position: 'start',
    onDrop: (s, t) => {
        let move = game.move({ from: s, to: t, promotion: 'q' });
        if (move === null) return 'snapback';
        updateAnalysis(game.fen());
    },
    pieceTheme: '/static/img/chesspieces/wikipedia/{piece}.png'
});

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}