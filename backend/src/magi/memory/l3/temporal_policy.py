"""Period-specific policy for L3 temporal summary generation."""

from __future__ import annotations

LEGACY_FLAT_TIMEOUT_SECONDS = 3.0

_PERIOD_TIMEOUT_SECONDS = {
    "hour": 180.0,
    "day": 300.0,
    "week": 600.0,
    "month": 600.0,
    "quarter": 600.0,
    "year": 600.0,
}
_PERIOD_DISABLE_THINKING = {
    "hour": True,
    "day": False,
    "week": False,
    "month": False,
    "quarter": False,
    "year": False,
}
_PERIOD_FOCUS_INSTRUCTIONS = {
    "hour": "Recall the specific activity or question in this hour. Do not infer a lasting pattern.",
    "day": "Recall the few concrete things that distinguish this day. Keep useful details, merge repetition, and omit routine noise. A sequence is optional.",
    "week": "Connect developments in the same project or life topic across the week. Preserve what changed or was decided; do not repeat a daily diary or give every day a bullet.",
    "month": "Recall meaningful developments across the month, including personal experiences. Group by actual subject when useful; do not concatenate weekly reports.",
    "quarter": "Select lasting developments and memorable experiences from the quarter. Keep concrete anchors and omit routine repetitions.",
    "year": "Select the year's meaningful changes, decisions and experiences. Let the evidence define the subjects; do not impose a growth narrative.",
}


class TemporalSummaryPolicy:
    """Own the generation rules that vary by temporal summary period."""

    def __init__(self, *, timeout_override_seconds: float | None = None) -> None:
        self._timeout_override_seconds = timeout_override_seconds

    def timeout_seconds_for_category(self, category: str) -> float:
        if self._timeout_override_seconds is not None:
            return self._timeout_override_seconds
        return _PERIOD_TIMEOUT_SECONDS.get(str(category), _PERIOD_TIMEOUT_SECONDS["week"])

    def disable_thinking_for_category(self, category: str) -> bool:
        return _PERIOD_DISABLE_THINKING.get(str(category), False)

    def focus_instruction(self, category: str) -> str:
        return _PERIOD_FOCUS_INSTRUCTIONS.get(
            str(category),
            _PERIOD_FOCUS_INSTRUCTIONS["week"],
        )

    def structure_instruction(self, category: str) -> str:
        """Give a reading budget, never a section or minimum-length template."""
        budgets = {
            "hour": "Usually 1-2 sentences about one activity.",
            "day": "Usually 2-5 concrete points, grouped into short paragraphs by subject.",
            "week": "Usually 3-6 concrete developments, grouped by subject only when helpful.",
            "month": "Usually 4-7 concrete developments or experiences.",
            "quarter": "Usually 4-7 lasting developments or memorable experiences.",
            "year": "Usually 5-8 meaningful developments or memorable experiences.",
        }
        return (
            budgets.get(str(category), budgets["week"])
            + " These are upper reading budgets, not quotas or required sections. "
            "Use fewer points when evidence is thin. No mandatory headline, timeline, "
            "decisions, open-threads or comparison sections. Do not state the same fact twice. "
            "Keep one subject per paragraph, usually 1-3 sentences, with a blank line between paragraphs. "
            "Start a new paragraph when the subject changes; never pack unrelated projects, "
            "shopping and entertainment into one block. For independent brief items, bullets are fine. "
            "Preserve these paragraph breaks when repairing factual claims. "
            "A longer period calls for stronger selection, not more filler."
        )


__all__ = [
    "LEGACY_FLAT_TIMEOUT_SECONDS",
    "TemporalSummaryPolicy",
]
