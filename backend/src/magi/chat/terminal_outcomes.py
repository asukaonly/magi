"""Canonical model-context outcomes for terminal chat turns."""

from __future__ import annotations


PRE_SUCCESS_TERMINAL_CHAT_STATUSES = frozenset(
    {"blocked", "cancelled", "failed", "interrupted", "merged"}
)
TERMINAL_CHAT_STATUSES = frozenset({"completed", *PRE_SUCCESS_TERMINAL_CHAT_STATUSES})


def model_context_terminal_outcome(
    *,
    status: str,
    visible_text: str = "",
    error_text: str | None = None,
) -> tuple[str, str]:
    """Return the canonical model-context text and role kind for one terminal turn."""

    normalized_status = str(status or "").strip().lower()
    normalized_visible_text = str(visible_text or "").strip()
    normalized_error_text = str(error_text or "").strip()
    if normalized_status == "completed":
        if normalized_visible_text:
            return normalized_visible_text, "assistant"
        return (
            "[Runtime outcome] The turn completed without a visible assistant message.",
            "runtime",
        )
    if normalized_status == "cancelled":
        return (
            "[Runtime outcome] The turn was cancelled before a final response.",
            "runtime",
        )
    if normalized_status not in PRE_SUCCESS_TERMINAL_CHAT_STATUSES:
        raise ValueError(f"Unsupported terminal chat status: {status}")
    outcome_text = (
        f"[Runtime outcome] The turn ended with status '{normalized_status}' "
        "before a successful final response."
    )
    if normalized_error_text:
        outcome_text = f"{outcome_text} Reason: {normalized_error_text}"
    return outcome_text, "runtime"


__all__ = [
    "PRE_SUCCESS_TERMINAL_CHAT_STATUSES",
    "TERMINAL_CHAT_STATUSES",
    "model_context_terminal_outcome",
]
