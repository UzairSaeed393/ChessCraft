(function () {
    function ready(fn) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", fn);
        } else {
            fn();
        }
    }

    ready(function () {
        // Auto-dismiss flash messages
        const alerts = document.querySelectorAll('.alert.auto-dismiss');
        if (alerts && alerts.length) {
            window.setTimeout(function () {
                alerts.forEach(function (el) {
                    if (!el || !el.isConnected) return;
                    el.style.transition = 'opacity 0.45s ease';
                    el.style.opacity = '0';
                    window.setTimeout(function () {
                        if (el.isConnected) el.remove();
                    }, 500);
                });
            }, 5000);
        }

        const menuToggle = document.getElementById("menuToggle");
        const sidebar = document.getElementById("sidebar");
        const closeSidebar = document.getElementById("closeSidebar");

        if (!sidebar) return;

        function open() {
            sidebar.classList.add("active");
            document.body.style.overflow = "hidden";
        }

        function close() {
            sidebar.classList.remove("active");
            document.body.style.overflow = "";
        }

        function toggle() {
            if (sidebar.classList.contains("active")) {
                close();
            } else {
                open();
            }
        }

        if (menuToggle) {
            menuToggle.addEventListener("click", function (e) {
                e.preventDefault();
                toggle();
            });
        }

        if (closeSidebar) {
            closeSidebar.addEventListener("click", function (e) {
                e.preventDefault();
                close();
            });
        }

        // Close when clicking outside the sidebar
        document.addEventListener("click", function (e) {
            if (!sidebar.classList.contains("active")) return;

            const clickInsideSidebar = sidebar.contains(e.target);
            const clickOnMenuToggle = menuToggle && menuToggle.contains(e.target);

            if (!clickInsideSidebar && !clickOnMenuToggle) {
                close();
            }
        });

        // Close when pressing Escape
        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape" && sidebar.classList.contains("active")) {
                close();
            }
        });

        // Close after selecting a link (mobile nav)
        sidebar.addEventListener("click", function (e) {
            const target = e.target;
            if (target && target.tagName === "A") {
                close();
            }
        });
    });
})();
