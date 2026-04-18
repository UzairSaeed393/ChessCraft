document.addEventListener('DOMContentLoaded', function() {
    const fetchForm = document.getElementById('fetchForm');
    const fetchBtn = document.getElementById('fetchBtn');
    
    if (fetchForm && fetchBtn) {
        const btnText = fetchBtn.querySelector('.btn-text');
        const loader = fetchBtn.querySelector('.loader');

        fetchForm.addEventListener('submit', function() {
            // 1. UI Feedback: Disable button
            fetchBtn.disabled = true;
            fetchBtn.style.cursor = 'not-allowed';
            fetchBtn.style.opacity = '0.8';

            // 2. Toggle Visibility: Hide text, show loader
            if (btnText) btnText.style.display = 'none';
            if (loader) loader.style.display = 'block';
        });
    }

    // Player selector buttons (if present on page)
    document.querySelectorAll('.player-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const uname = btn.dataset.username || '';
            const params = new URLSearchParams(window.location.search);
            if (uname) params.set('username', uname);
            else params.delete('username');
            // Preserve opening filter and page
            window.location.search = params.toString();
        });
    });
});