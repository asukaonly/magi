"""Transport-independent failures from memory application workflows."""

from typing import Any, Literal

MemoryFailure = Literal[
    "invalid_request", "not_found", "conflict", "precondition_required", "unavailable", "internal"
]


class MemoryApplicationError(RuntimeError):
    def __init__(self, *, reason: MemoryFailure, detail: Any) -> None:
        super().__init__(str(detail))
        self.reason = reason
        self.detail = detail
