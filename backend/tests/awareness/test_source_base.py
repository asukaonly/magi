"""Tests for awareness layer source contracts and components."""

from __future__ import annotations

from typing import Any

import pytest

from magi.awareness.source_output import (
    ActivityFacet,
    ContentBlock,
    SourceActivity,
    SourceMemoryPolicy,
    SourceNarration,
    SourceOutput,
)
from magi.awareness.source_base import Source


# ── SourceOutput ──

class TestSourceOutput:
    def test_round_trip(self):
        output = SourceOutput(
            source_type="test_source",
            source_item_id="item-1",
            occurred_at=1700000000.0,
            captured_at=1700000001.0,
            activity=SourceActivity(
                source=ActivityFacet(
                    code="test_source",
                    i18n_key="activity.source.test_source",
                    fallback="Test Source",
                ),
                action=ActivityFacet(
                    code="observe",
                    i18n_key="activity.action.observe",
                    fallback="Observed",
                ),
            ),
            narration=SourceNarration(body="Something happened", title="Test Event"),
            content_blocks=[ContentBlock(kind="text", value="hello")],
            tags=["tag1"],
            entities=[{"name": "test"}],
            provenance={"source_id": "test"},
            domain_payload={"custom": True},
        )
        d = output.to_dict()
        restored = SourceOutput.from_dict(d)
        assert restored.source_type == "test_source"
        assert restored.source_item_id == "item-1"
        assert restored.occurred_at == 1700000000.0
        assert restored.activity.source.code == "test_source"
        assert restored.narration.title == "Test Event"
        assert len(restored.content_blocks) == 1
        assert restored.content_blocks[0].kind == "text"
        assert restored.tags == ["tag1"]
        assert restored.domain_payload == {"custom": True}

    def test_from_dict_minimal(self):
        d = {
            "source_type": "s",
            "source_item_id": "id1",
            "occurred_at": 100.0,
            "captured_at": 200.0,
            "activity": {
                "source": {
                    "code": "test_source",
                    "i18n_key": "activity.source.test_source",
                    "fallback": "Test Source",
                },
                "action": {
                    "code": "observe",
                    "i18n_key": "activity.action.observe",
                    "fallback": "Observed",
                },
            },
            "narration": {
                "body": "Observed event",
            },
        }
        output = SourceOutput.from_dict(d)
        assert output.source_type == "s"
        assert output.activity.action.code == "observe"
        assert output.narration.body == "Observed event"
        assert output.content_blocks == []
        assert output.tags == []


# ── Source ──

class _ConcreteSource(Source):
    source_id = "test.concrete"
    source_type = "test_source"
    update_key_fields = ("id", "hash")
    memory_policy = SourceMemoryPolicy(importance_bias=0.7)

    async def build_output(self, item: dict[str, Any]) -> SourceOutput:
        return self._build_output(
            source_item_id=str(item["id"]),
            activity=self._build_activity(
                source=self._build_activity_facet(
                    code="test_source",
                    i18n_key="activity.source.test_source",
                    fallback="Test Source",
                ),
                action=self._build_activity_facet(
                    code="observe",
                    i18n_key="activity.action.observe",
                    fallback="Observed",
                ),
            ),
            narration=self._build_narration(
                title=str(item.get("title", "")),
                body=str(item.get("summary", "")),
            ),
            occurred_at=item.get("occurred_at"),
            tags=item.get("tags", []),
        )


class TestSourceBase:

    def test_fingerprint_dedup(self):
        source = _ConcreteSource()
        item = {"id": "1", "hash": "abc"}
        fp = source.source_item_version_fingerprint(item)
        assert isinstance(fp, str)
        assert len(fp) == 64  # SHA256 hex

        item2 = {"id": "1", "hash": "def"}
        fp2 = source.source_item_version_fingerprint(item2)
        assert fp != fp2

    def test_source_item_identity(self):
        source = _ConcreteSource()
        identity = source.source_item_identity({"id": "x", "hash": "y"})
        assert identity == "d6ea37a8a9eee73bfabc6da5338b8e46378a7d4baaafdc686e22c887d285546c"

    @pytest.mark.asyncio
    async def test_discover_changes(self):
        source = _ConcreteSource()
        items = [{"id": "1", "hash": "a"}, {"id": "2", "hash": "b"}]
        fp = source.source_item_version_fingerprint(items[0])
        changes = await source.discover_changes(items, known_fingerprints={fp})
        assert len(changes) == 1
        assert changes[0]["id"] == "2"
