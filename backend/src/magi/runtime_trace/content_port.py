"""Trace-owner deletion boundary used by cross-domain forgetting workflows."""

from typing import Protocol


class TraceContentRepository(Protocol):
    def delete_session(self, *, user_id: str, session_id: str) -> None: ...

    def delete_turn(self, *, user_id: str, session_id: str, turn_id: str) -> None: ...

    def clear_all(self) -> None: ...
