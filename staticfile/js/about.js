// Ensure each offer's details are hidden initially and only the clicked
// offer is toggled. Also sets proper button text.
function initOfferToggles() {
    const offers = document.querySelectorAll('.offer');

    offers.forEach(offer => {
        const btn = offer.querySelector('button');
        const details = offer.querySelector('.expand');

        if (!btn || !details) return;

        // Defensive: ensure details start hidden
        details.classList.remove('show');

        // Set accessible state and initial button text
        btn.setAttribute('aria-expanded', 'false');
        btn.innerText = 'View Details';

        // Remove any inline onclick to avoid duplicate handlers (if present)
        btn.removeAttribute('onclick');

        // Use listener instead of inline onclick; keeps scope local to this card
        btn.addEventListener('click', () => {
            const isShown = details.classList.toggle('show');
            btn.innerText = isShown ? 'Hide Details' : 'View Details';
            btn.setAttribute('aria-expanded', String(isShown));
            if (isShown) details.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        });
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initOfferToggles);
} else {
    initOfferToggles();
}
