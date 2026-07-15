"""Process-local invalidation signals for correction-sensitive read caches."""

from __future__ import annotations

from collections import defaultdict

_SUBJECT_SIGNALS: defaultdict[tuple[str, str], int] = defaultdict(int)
_GLOBAL_SIGNALS: defaultdict[str, int] = defaultdict(int)


def mark_subject_changed(db_path: str, subject_key: str) -> int:
    """Advance the signal observed by caches for one corrected subject."""
    key = (str(db_path), str(subject_key))
    _SUBJECT_SIGNALS[key] += 1
    return _SUBJECT_SIGNALS[key]


def subject_change_signal(db_path: str, subject_key: str) -> int:
    """Return the current process-local signal for one subject."""
    normalized_db_path = str(db_path)
    return (
        _GLOBAL_SIGNALS[normalized_db_path]
        + _SUBJECT_SIGNALS[(normalized_db_path, str(subject_key))]
    )


def mark_all_subjects_changed(db_path: str) -> int:
    """Advance the signal observed by every cache for one memory database."""
    normalized_db_path = str(db_path)
    _GLOBAL_SIGNALS[normalized_db_path] += 1
    return _GLOBAL_SIGNALS[normalized_db_path]


__all__ = [
    "mark_all_subjects_changed",
    "mark_subject_changed",
    "subject_change_signal",
]
