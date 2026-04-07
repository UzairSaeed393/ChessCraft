document.querySelectorAll(".featurecard").forEach(card => {
    card.addEventListener("click", function (e) {
        e.stopPropagation();
        this.classList.toggle("flip");
    });
});

document.addEventListener("click", () => {
    document.querySelectorAll(".featurecard.flip").forEach(card => {
        card.classList.remove("flip");
    });
});
setTimeout(() => {
        document.querySelectorAll('.auto-dismiss').forEach(alert => {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            bsAlert.close();
        });
}, 5000);

// Animated count-up for counter chips
function animateCount(el, duration = 1100) {
    const target = parseInt(el.getAttribute('data-target')) || 0;
    const start = 0;
    const startTime = performance.now();

    function tick(now) {
        const progress = Math.min((now - startTime) / duration, 1);
        const value = Math.floor(progress * (target - start) + start);
        el.textContent = value.toLocaleString();
        if (progress < 1) {
            requestAnimationFrame(tick);
        } else {
            el.textContent = target.toLocaleString();
            // subtle visual feedback
            const chip = el.closest('.countercard');
            if (chip) {
                chip.classList.add('chip-bounce');
                setTimeout(() => chip.classList.remove('chip-bounce'), 520);
            }
        }
    }

    requestAnimationFrame(tick);
}

// observe when counters enter viewport
const counters = document.querySelectorAll('.count-number');
if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver(entries => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                animateCount(entry.target);
                io.unobserve(entry.target);
            }
        });
    }, { threshold: 0.4 });

    counters.forEach(c => io.observe(c));
} else {
    // fallback
    counters.forEach(c => animateCount(c));
}
// Scroll reveal animation
const reveals = document.querySelectorAll('.reveal');

const observer = new IntersectionObserver(
  entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('active');
        observer.unobserve(entry.target);
      }
    });
  },
  { threshold: 0.15 }
);

reveals.forEach(el => observer.observe(el));

// Counter animation (safe)
document.querySelectorAll('.count-number').forEach(counter => {
  const target = +counter.dataset.target;
  let current = 0;
  const step = Math.ceil(target / 60);

  const update = () => {
    current += step;
    if (current >= target) {
      counter.innerText = target;
    } else {
      counter.innerText = current;
      requestAnimationFrame(update);
    }
  };
  update();
});
