function togglePassword(fieldId, triggerElement) {
    const field = document.getElementById(fieldId);
    if (!field) return;

    const nextIsText = field.type === "password";
    field.type = nextIsText ? "text" : "password";

    if (triggerElement) {
        triggerElement.setAttribute(
            "aria-label",
            nextIsText ? "Hide password" : "Show password"
        );
        triggerElement.setAttribute("aria-pressed", nextIsText ? "true" : "false");
    }

    const icon = triggerElement?.querySelector?.("i");
    if (icon && icon.classList) {
        icon.classList.toggle("bi-eye", !nextIsText);
        icon.classList.toggle("bi-eye-slash", nextIsText);
    }
}
