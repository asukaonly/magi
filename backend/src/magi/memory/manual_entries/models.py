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
    # ProseMirror JSON document for the rich-text editor (Phase B-2).
    # ``body`` is the canonical plain-text projection: L1, search, diary
    # LLM, and embedding all read it. ``body_doc`` lets the UI restore
    # bold/italic/headings/etc. on display. None → render `body` as a
    # single paragraph.
    body_doc: Optional[dict[str, Any]] = None
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
    # Cross-store projection ownership is recorded before an L1 write.  These
    # fields are deliberately internal: API callers only need the linked
    # projection, while repair/delete flows need the durable in-flight
    # identity when a request stops between the two databases.
    pending_l1_event_id: Optional[str] = None
    pending_l1_predecessor_event_id: Optional[str] = None
    delete_requested_at: Optional[float] = None
    # Ambient weather snapshot resolved against Open-Meteo at the entry's
    # event_at + location. Shape: {"code": int, "temp_c": float,
    # "fetched_at": float}. Null when no lat/lng was resolvable or the
    # fetcher disabled / failed.
    weather: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "created_at": self.created_at,
            "event_at": self.event_at,
            "body": self.body,
            "body_doc": dict(self.body_doc) if self.body_doc else None,
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
            "weather": dict(self.weather) if self.weather else None,
        }
