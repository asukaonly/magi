"""Domain state for user questions; authorization prompts remain transient."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

@dataclass(slots=True)
class AskState:
    request_id: str
    question: str
    options: tuple[str, ...] = ()
    allow_free_text: bool = True
    asked_at: float = field(default_factory=time.time)
    timeout_seconds: float | None = None
    expires_at: float | None = None
    answered_at: float | None = None
    answer: str | None = None
    #: ``"user"`` | ``"cancelled"`` | ``"timeout"`` | ``None`` while pending.
    resolution: str | None = None
    clear_generation: int = field(default=0, repr=False)

    @property
    def status(self) -> str:
        if self.resolution == "user":
            return "answered"
        if self.resolution in {"timeout", "cancelled"}:
            return self.resolution
        return "pending"

    def to_dict(self) -> dict[str, Any]:
        created_at_ms = int(self.asked_at * 1000)
        answered_at_ms = int(self.answered_at * 1000) if self.answered_at else None
        expires_at_ms = int(self.expires_at * 1000) if self.expires_at else None
        return {
            "request_id": self.request_id,
            "question": self.question,
            "options": list(self.options),
            "allow_free_text": self.allow_free_text,
            "status": self.status,
            "asked_at": self.asked_at,
            "created_at_ms": created_at_ms,
            "timeout_seconds": self.timeout_seconds,
            "expires_at": self.expires_at,
            "expires_at_ms": expires_at_ms,
            "answered_at": self.answered_at,
            "answered_at_ms": answered_at_ms,
            "answer": self.answer,
            "resolution": self.resolution,
        }
