"""L1 projection — exercised via a stub L1 store that records calls."""

from __future__ import annotations

import pytest

from magi.memory.manual_entries import ManualEntry, ManualEntryL1Projector
from magi.memory.manual_entries.l1_projector import (
    ManualEntryProjectionGovernedError,
)


class _StubGovernedMemory:
    """Minimal stand-in for the governed L1 write boundary."""

    def __init__(self) -> None:
        self.stored: list = []
        self._event_ids_by_key: dict[str, str] = {}
        self._next_id_seq = 0
        self.rejection_reason: str | None = None

    async def store_governed_l1_event(self, event):
        if self.rejection_reason is not None:
            return None
        existing = self._event_ids_by_key.get(event.idempotency_key)
        if existing is not None:
            return existing
        self._next_id_seq += 1
        self.stored.append(event)
        self._event_ids_by_key[event.idempotency_key] = event.event_id
        return event.event_id

    async def governed_l1_event_rejection_reason(self, _event):
        return self.rejection_reason


def _entry(**overrides) -> ManualEntry:
    defaults = dict(
        entry_id="me-test-1",
        created_at=1716_000_000.0,
        event_at=1716_000_000.0,
        kind="quick",
        body="hello",
        mood=None,
        attachments=[],
    )
    defaults.update(overrides)
    return ManualEntry(**defaults)


@pytest.mark.asyncio
async def test_project_current_emits_l1_event_with_correct_shape():
    l1 = _StubGovernedMemory()
    projector = ManualEntryL1Projector(memory=l1)
    entry = _entry(
        body="一些想法",
        mood="warm",
        attachments=["manual-entry-asset://aaa.png"],
        location_label="杭州",
    )
    event_id = await projector.project_current(entry, predecessor_event_id=None)

    assert event_id.startswith("me_")
    assert len(l1.stored) == 1
    ev = l1.stored[0]
    assert ev.source == "manual_entry"
    assert ev.content == "一些想法"
    assert ev.timestamp == entry.event_at
    assert ev.idempotency_key.startswith("manual-entry:me-test-1:")
    # Metadata carries the structured manual-entry payload
    assert ev.metadata_json["activity_snapshot"]["source_type"] == "manual_entry"
    assert "timeline" not in ev.metadata_json
    assert ev.metadata_json["manual_entry"]["entry_id"] == "me-test-1"
    assert ev.metadata_json["manual_entry"]["mood"] == "warm"
    assert ev.metadata_json["manual_entry"]["attachments"] == [
        "manual-entry-asset://aaa.png",
    ]


@pytest.mark.asyncio
async def test_project_current_retry_resolves_the_same_event():
    l1 = _StubGovernedMemory()
    projector = ManualEntryL1Projector(memory=l1)
    entry = _entry(l1_event_id="evt-0099")

    first_id = await projector.project_current(entry, predecessor_event_id="evt-0099")
    retry_id = await projector.project_current(entry, predecessor_event_id="evt-0099")

    assert retry_id == first_id
    assert len(l1.stored) == 1


@pytest.mark.asyncio
async def test_project_current_preserves_time_range_rejection_reason():
    memory = _StubGovernedMemory()
    memory.rejection_reason = "time_range"
    projector = ManualEntryL1Projector(memory=memory)

    with pytest.raises(ManualEntryProjectionGovernedError) as error:
        await projector.project_current(
            _entry(),
            predecessor_event_id=None,
        )

    assert getattr(error.value, "reason", None) == "time_range"


@pytest.mark.asyncio
async def test_project_current_changes_identity_for_a_new_predecessor():
    l1 = _StubGovernedMemory()
    projector = ManualEntryL1Projector(memory=l1)
    entry = _entry()

    first_id = await projector.project_current(entry, predecessor_event_id="evt-old-1")
    second_id = await projector.project_current(entry, predecessor_event_id="evt-old-2")

    assert second_id != first_id
    assert len(l1.stored) == 2


@pytest.mark.asyncio
async def test_project_current_changes_identity_when_projected_content_changes():
    l1 = _StubGovernedMemory()
    projector = ManualEntryL1Projector(memory=l1)
    first_id = await projector.project_current(_entry(body="before"), predecessor_event_id="old")
    second_id = await projector.project_current(_entry(body="after"), predecessor_event_id="old")

    assert second_id != first_id
    assert len(l1.stored) == 2


@pytest.mark.asyncio
async def test_project_carries_weather_into_metadata():
    """Weather snapshot should ride along in the manual_entry metadata
    sub-dict so themes/diary can read it without an extra DB hop."""
    l1 = _StubGovernedMemory()
    projector = ManualEntryL1Projector(memory=l1)
    entry = _entry(
        body="下雨天",
        weather={"code": 65, "temp_c": 15.5, "fetched_at": 1716_000_000.0},
    )
    await projector.project_current(entry, predecessor_event_id=None)
    ev = l1.stored[0]
    weather = ev.metadata_json["manual_entry"]["weather"]
    assert weather["code"] == 65
    assert weather["temp_c"] == pytest.approx(15.5)


@pytest.mark.asyncio
async def test_project_weather_absent_keeps_field_null():
    """Without a fetched snapshot, the metadata field is explicitly None
    (not missing) so consumers can rely on the key being present."""
    l1 = _StubGovernedMemory()
    projector = ManualEntryL1Projector(memory=l1)
    await projector.project_current(_entry(weather=None), predecessor_event_id=None)
    ev = l1.stored[0]
    assert ev.metadata_json["manual_entry"]["weather"] is None
