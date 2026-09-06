"""Bound model-facing text without cutting resource identifiers in half."""

from __future__ import annotations


TRUNCATED = "\n[Content truncated.]"


def clip_text(text: str, limit: int, *, tail: bool = False) -> str:
    if len(text) <= limit:
        return text
    if limit < len(TRUNCATED):
        return TRUNCATED[:max(0, limit)]
    keep = max(0, limit - len(TRUNCATED))
    if tail:
        return TRUNCATED.lstrip() + "\n" + (text[-keep:] if keep else "")
    return text[:keep] + TRUNCATED


def one_line(value: object) -> str:
    return " ".join(str(value or "").split())


class TextBudget:
    """Append whole headers and bounded bodies within one observation budget."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.parts: list[str] = []

    @property
    def remaining(self) -> int:
        return self.limit - sum(len(part) for part in self.parts) - max(0, len(self.parts) - 1) * 2

    def add(self, text: str, *, reserve: int = 0) -> bool:
        cost = len(text) + (2 if self.parts else 0)
        if cost > self.remaining - reserve:
            return False
        self.parts.append(text)
        return True

    def body(self, text: str, *, reserve: int = 0, tail: bool = False) -> bool:
        available = max(0, self.remaining - reserve - (2 if self.parts else 0))
        if available < len(TRUNCATED):
            return not text
        self.add(clip_text(text, available, tail=tail), reserve=reserve)
        return len(text) <= available

    def render(self) -> str:
        return "\n\n".join(self.parts)
