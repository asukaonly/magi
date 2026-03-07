"""History snapshot handling for ExploreTaskAgent."""
from __future__ import annotations

from typing import Any


class ExploreSessionService:
    """Owns lightweight history snapshots for ExploreTaskAgent runs."""

    def __init__(self) -> None:
        self._request_history: dict[str, list[dict[str, str]]] = {}

    def ingest_history_snapshot(self, history_key: str, history_snapshot: Any) -> None:
        if not isinstance(history_snapshot, list) or not history_snapshot:
            return
        self._request_history[history_key] = [
            {
                "role": str(item.get("role", "user")),
                "content": str(item.get("content", "")),
            }
            for item in history_snapshot
            if isinstance(item, dict) and str(item.get("content", "")).strip()
        ]

    def get_history(self, history_key: str) -> list[dict[str, str]]:
        return list(self._request_history.get(history_key, []))

    def append_request(self, history_key: str, user_message: str) -> None:
        if not user_message:
            return
        history = self._request_history.setdefault(history_key, [])
        if history and history[-1].get("role") == "user" and history[-1].get("content") == user_message:
            return
        history.append({"role": "user", "content": user_message})

    def history_key(self, user_id: str, session_id: str) -> str:
        return f"{user_id}::{session_id}"
