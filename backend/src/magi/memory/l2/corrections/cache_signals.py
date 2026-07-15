"""Process-local invalidation signals for correction-sensitive read caches."""

from __future__ import annotations

from collections import defaultdict

_SUBJECT_SIGNALS: defaultdict[tuple[str, str], int] = defaultdict(int)


def mark_subject_changed(db_path: str, subject_key: str) -> int:
    """Advance the signal observed by caches for one corrected subject."""
    key = (str(db_path), str(subject_key))
    _SUBJECT_SIGNALS[key] += 1
    return _SUBJECT_SIGNALS[key]


def subject_change_signal(db_path: str, subject_key: str) -> int:
    """Return the current process-local signal for one subject."""
    return _SUBJECT_SIGNALS[(str(db_path), str(subject_key))]


__all__ = ["mark_subject_changed", "subject_change_signal"]
