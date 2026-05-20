"""Dataclasses for the manual_entries table."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(slots=True)
class ManualEntry:
    """A user-authored memory note.

    ``event_at`` is the timestamp the memory itself describes (used for
    timeline placement); ``created_at`` is when the user clicked save.
    They diverge when the user writes about the past ("yesterday's
    meeting was…").

    Attachments are a list of ``manual-entry-asset://<sha>.<ext>`` refs
    pointing at content-addressed image files under
    ``~/.magi/data/media/manual_entries/``.
    """

    entry_id: str
    created_at: float
    event_at: float
    body: str
    kind: str = "quick"
    mood: Optional[str] = None
    location_label: Optional[str] = None
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None
    attachments: list[str] = field(default_factory=list)
    exclude_from_llm: bool = False
    user_pinned: bool = False
    deleted_at: Optional[float] = None
    l1_event_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "created_at": self.created_at,
            "event_at": self.event_at,
            "body": self.body,
            "kind": self.kind,
            "mood": self.mood,
            "location_label": self.location_label,
            "location_lat": self.location_lat,
            "location_lng": self.location_lng,
            "attachments": list(self.attachments),
            "exclude_from_llm": self.exclude_from_llm,
            "user_pinned": self.user_pinned,
            "deleted_at": self.deleted_at,
            "l1_event_id": self.l1_event_id,
        }
