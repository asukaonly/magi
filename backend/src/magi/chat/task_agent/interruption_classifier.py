"""Deterministic interruption policy for active chat runs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path

import yaml

_STRICT_NORMALIZE_RE = re.compile(
    r"[\s\.,!\?;:\-_\"'`~@#\$%\^&\*\(\)\[\]\{\}<>/\\|"
    "，。！？、；：\"'「」『』【】（）《》…—–～]+"
)
_STRICT_CLAUSE_SPLIT_RE = re.compile(r"[\s]*[\.,!\?;:，。！？、；：]+[\s]*")
_PHRASES_FILE = Path(__file__).with_name("interruption_phrases.yaml")


@lru_cache(maxsize=1)
def _load_strict_interrupt_phrases() -> frozenset[str]:
    try:
        raw = yaml.safe_load(_PHRASES_FILE.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return frozenset()
    phrases: set[str] = set()
    for bucket in raw.values() if isinstance(raw, dict) else ():
        if isinstance(bucket, list):
            phrases.update(str(entry or "").strip() for entry in bucket if str(entry or "").strip())
    return frozenset(phrases)


class InterruptionDisposition(str, Enum):
    """How a new user turn should affect the active run."""

    INTERRUPT = "interrupt"
    AUGMENT = "augment"
    STEER = "steer"
    DEFER = "defer"


@dataclass(slots=True)
class StepState:
    """Execution-step constraints that affect interruption handling."""

    atomic: bool = False
    side_effecting: bool = False


@dataclass(slots=True)
class InterruptionContext:
    """Input to the deterministic interruption policy."""

    user_text: str
    root_user_message: str = ""
    pending_turns: list[str] = field(default_factory=list)
    step_state: StepState = field(default_factory=StepState)


class InterruptionClassifier:
    """Map strict cancel to replacement and ordinary messages to typed steer."""

    def __init__(self, *, llm_adapter=None, llm_pool=None) -> None:
        _ = (llm_adapter, llm_pool)

    def classify(self, context: InterruptionContext) -> InterruptionDisposition:
        if context.step_state.atomic or context.step_state.side_effecting:
            return InterruptionDisposition.DEFER
        if self.looks_like_strict_interrupt(context.user_text):
            return InterruptionDisposition.INTERRUPT
        return InterruptionDisposition.STEER

    async def aclassify(self, context: InterruptionContext) -> InterruptionDisposition:
        """Async facade with no auxiliary model call."""

        return self.classify(context)

    @classmethod
    def _strict_normalize(cls, user_text: str) -> str:
        return _STRICT_NORMALIZE_RE.sub("", user_text.lower())

    def looks_like_strict_interrupt(self, user_text: str) -> bool:
        normalized = self._strict_normalize(user_text)
        phrases = _load_strict_interrupt_phrases()
        if normalized and normalized in phrases:
            return True
        clauses = [
            self._strict_normalize(clause)
            for clause in _STRICT_CLAUSE_SPLIT_RE.split(user_text)
            if self._strict_normalize(clause)
        ]
        return len(clauses) > 1 and all(clause in phrases for clause in clauses)


__all__ = [
    "InterruptionClassifier",
    "InterruptionContext",
    "InterruptionDisposition",
    "StepState",
]
