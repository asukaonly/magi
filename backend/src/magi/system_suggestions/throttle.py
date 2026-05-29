"""Per-session throttle: avoid re-running the LLM classifier on every /check.

Re-classify only when the keyword-gate candidate set changes, or after N
checks have elapsed since the last classification. State is in-process
(single-user desktop app); it resets on worker restart.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class _SessionState:
    candidates: frozenset[str] = field(default_factory=frozenset)
    cached: list[Any] = field(default_factory=list)
    checks_since_classify: int = 0
    classified: bool = False


class SuggestionThrottle:
    def __init__(self, reclassify_after: int = 3) -> None:
        self._reclassify_after = reclassify_after
        self._by_session: dict[str, _SessionState] = {}

    def should_classify(self, session_id: str, candidates: frozenset[str]) -> bool:
        st = self._by_session.get(session_id)
        if st is None or not st.classified:
            return True
        if candidates != st.candidates:
            return True
        st.checks_since_classify += 1
        return st.checks_since_classify >= self._reclassify_after

    def store(self, session_id: str, candidates: frozenset[str], proposals: list[Any]) -> None:
        self._by_session[session_id] = _SessionState(
            candidates=candidates, cached=list(proposals),
            checks_since_classify=0, classified=True,
        )

    def get_cached(self, session_id: str) -> list[Any]:
        st = self._by_session.get(session_id)
        return list(st.cached) if st else []
