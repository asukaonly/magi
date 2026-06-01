"""L1 projection — exercised via a stub L1 store that records calls."""

from __future__ import annotations

import pytest

from magi.memory.manual_entries import ManualEntry, ManualEntryL1Projector


class _StubL1Store:
    """Minimal stand-in for L1EventStore.store / mark_deleted."""

    def __init__(self) -> None:
        self.stored: list = []
        self.deleted: list[str] = []
        self._next_id_seq = 0

    async def store(self, event):
        self._next_id_seq += 1
        event.event_id = f"evt-{self._next_id_seq:04d}"
        self.stored.append(event)
        return event.event_id

    async def mark_deleted(self, event_id: str, *, deleted_at=None) -> bool:
        self.deleted.append(event_id)
        return True


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
async def test_project_on_create_emits_l1_event_with_correct_shape():
    l1 = _StubL1Store()
    projector = ManualEntryL1Projector(l1_store=l1)
    entry = _entry(
        body="一些想法",
        mood="warm",
        attachments=["manual-entry-asset://aaa.png"],
        location_label="杭州",
    )
    event_id = await projector.project_on_create(entry)

    assert event_id == "evt-0001"
    assert len(l1.stored) == 1
    ev = l1.stored[0]
    assert ev.source == "manual_entry"
    assert ev.content == "一些想法"
    assert ev.timestamp == entry.event_at
    assert ev.idempotency_key.startswith("manual-entry:me-test-1:")
    # Metadata carries the structured manual-entry payload
    assert ev.metadata_json["timeline"]["source_type"] == "manual_entry"
    assert ev.metadata_json["manual_entry"]["entry_id"] == "me-test-1"
    assert ev.metadata_json["manual_entry"]["mood"] == "warm"
    assert ev.metadata_json["manual_entry"]["attachments"] == [
        "manual-entry-asset://aaa.png",
    ]


@pytest.mark.asyncio
async def test_project_on_update_tombstones_old_and_stores_new():
    l1 = _StubL1Store()
    projector = ManualEntryL1Projector(l1_store=l1)
    entry = _entry(l1_event_id="evt-0099")  # existing L1 row
    new_id = await projector.project_on_update(entry)
    assert new_id == "evt-0001"
    assert l1.deleted == ["evt-0099"]
    assert len(l1.stored) == 1


@pytest.mark.asyncio
async def test_project_on_update_without_prior_l1_just_stores():
    l1 = _StubL1Store()
    projector = ManualEntryL1Projector(l1_store=l1)
    entry = _entry(l1_event_id=None)
    await projector.project_on_update(entry)
    assert l1.deleted == []
    assert len(l1.stored) == 1


@pytest.mark.asyncio
async def test_project_on_delete_tombstones_when_l1_id_present():
    l1 = _StubL1Store()
    projector = ManualEntryL1Projector(l1_store=l1)
    entry = _entry(l1_event_id="evt-0050")
    await projector.project_on_delete(entry)
    assert l1.deleted == ["evt-0050"]
    assert l1.stored == []


@pytest.mark.asyncio
async def test_project_on_delete_without_l1_id_is_noop():
    l1 = _StubL1Store()
    projector = ManualEntryL1Projector(l1_store=l1)
    entry = _entry(l1_event_id=None)
    await projector.project_on_delete(entry)
    assert l1.deleted == []
    assert l1.stored == []


@pytest.mark.asyncio
async def test_project_carries_weather_into_metadata():
    """Weather snapshot should ride along in the manual_entry metadata
    sub-dict so themes/diary can read it without an extra DB hop."""
    l1 = _StubL1Store()
    projector = ManualEntryL1Projector(l1_store=l1)
    entry = _entry(
        body="下雨天",
        weather={"code": 65, "temp_c": 15.5, "fetched_at": 1716_000_000.0},
    )
    await projector.project_on_create(entry)
    ev = l1.stored[0]
    weather = ev.metadata_json["manual_entry"]["weather"]
    assert weather["code"] == 65
    assert weather["temp_c"] == pytest.approx(15.5)


@pytest.mark.asyncio
async def test_project_weather_absent_keeps_field_null():
    """Without a fetched snapshot, the metadata field is explicitly None
    (not missing) so consumers can rely on the key being present."""
    l1 = _StubL1Store()
    projector = ManualEntryL1Projector(l1_store=l1)
    await projector.project_on_create(_entry(weather=None))
    ev = l1.stored[0]
    assert ev.metadata_json["manual_entry"]["weather"] is None
