"""Tests for SourceIngestionGateway as a thin publisher.

Phase 9: Gateway no longer writes to memory/timeline/state directly.
It builds a SourceEventEmitted payload and publishes to the event bus.
Side effects are tested through their respective subscribers.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.awareness.ingestion_gateway import SourceIngestionGateway, SourceIngestionResult
from magi.awareness.source_base import L2BatchPolicy, Source
from magi.awareness.source_output import (
    ActivityFacet,
    ContentBlock,
    SourceActivity,
    SourceMemoryPolicy,
    SourceNarration,
    SourceOutput,
    SourceOutputMetadata,
)
from magi.events.domain_payloads import SourceEventEmitted
from magi.events.events import EventTypes
from magi.memory.source_ingestion import (
    SourceCommitOutcome,
    SourceCommitReceipt,
    SourceEventCommitter,
    SourceIngestionBoundary,
)


class _FakeSource(Source):
    source_id = "test.fake"
    source_type = "fake_source"
    memory_event_type = "FAKE_EVENT"
    update_key_fields = ("id",)
    memory_policy = SourceMemoryPolicy(
        memory_domain="external_activity",
        ingest_target="l1_only",
        cognition_eligible=True,
        retention_class="permanent",
        importance_bias=0.7,
        author_type="external",
        content_type="observation",
    )

    async def build_output(self, item: dict[str, Any]) -> SourceOutput:
        return self._build_output(
            source_item_id=str(item["id"]),
            activity=self._build_activity(
                source=self._build_activity_facet(
                    code="fake_source",
                    i18n_key="activity.source.fake_source",
                    fallback="Fake Source",
                ),
                action=self._build_activity_facet(
                    code="observe",
                    i18n_key="activity.action.observe",
                    fallback="Observed",
                ),
            ),
            narration=self._build_narration(title="Fake title", body="Fake summary"),
        )


class _FakeBatchingSource(_FakeSource):
    def l2_batch_policy(self, output: SourceOutput) -> L2BatchPolicy | None:
        return L2BatchPolicy(
            owner=f"{output.source_type}:default",
            max_events=20,
            max_estimated_tokens=3200,
            max_wait_seconds=180,
        )


def _make_output(**overrides: Any) -> SourceOutput:
    defaults = dict(
        source_type="fake_source",
        source_item_id="item-1",
        occurred_at=1700000000.0,
        captured_at=1700000001.0,
        activity=SourceActivity(
            source=ActivityFacet(
                code="fake_source",
                i18n_key="activity.source.fake_source",
                fallback="Fake Source",
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
    )
    defaults.update(overrides)
    return SourceOutput(**defaults)


def _make_bus() -> MagicMock:
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=True)
    return bus


def _make_committer() -> MagicMock:
    committer = MagicMock()
    committer.capture_ingestion_boundary = AsyncMock(
        return_value=SourceIngestionBoundary(
            expected_epoch=0,
            clear_generation=0,
            clear_cutoff_at=0.0,
        )
    )

    async def _commit(
        event,
        *,
        expected_epoch,
        clear_generation,
        clear_cutoff_at,
        allow_pre_clear_events,
    ):
        return SourceCommitReceipt(
            event_id=event.event_id,
            outcome=SourceCommitOutcome.PERSISTED,
        )

    committer.commit = AsyncMock(side_effect=_commit)
    return committer


class TestSourceIngestionGatewayPublishes:
    @pytest.mark.asyncio
    async def test_ingest_publishes_source_event_emitted(self):
        bus = _make_bus()
        committer = _make_committer()
        gateway = SourceIngestionGateway(event_bus=bus, memory_committer=committer)
        source = _FakeSource()
        output = _make_output()

        result = await gateway.ingest(source, output)

        assert isinstance(result, SourceIngestionResult)
        assert result.ingested is True
        assert result.event_id  # ULID assigned
        assert result.stats == {
            "memory_outcome": "persisted",
            "projection_published": True,
            "projection_skipped": False,
        }
        committer.commit.assert_awaited_once()
        bus.publish.assert_awaited_once()

        event = bus.publish.await_args.args[0]
        assert event.type == EventTypes.SOURCE_EVENT_EMITTED
        assert event.event_id == result.event_id
        assert event.source == "source_ingestion_gateway"
        payload = event.data
        assert isinstance(payload, SourceEventEmitted)
        assert payload.source_id == "test.fake"
        assert payload.source_name == "test.fake"
        assert payload.memory_event_type == "FAKE_EVENT"
        assert payload.idempotency_key == "item-1"
        assert payload.occurred_at == 1700000000.0
        assert payload.owner_user_id == "local_user"
        assert committer.commit.await_args.kwargs["expected_epoch"] == 0

    @pytest.mark.asyncio
    async def test_ingest_preserves_explicit_clear_boundary(self):
        bus = _make_bus()
        committer = _make_committer()
        gateway = SourceIngestionGateway(event_bus=bus, memory_committer=committer)
        boundary = SourceIngestionBoundary(
            expected_epoch=17,
            clear_generation=4,
            clear_cutoff_at=1_700_000_010.0,
        )

        await gateway.ingest(
            _FakeSource(),
            _make_output(),
            boundary=boundary,
            allow_pre_clear_events=True,
        )

        assert committer.commit.await_args.kwargs["expected_epoch"] == 17
        assert committer.commit.await_args.kwargs["clear_generation"] == 4
        assert committer.commit.await_args.kwargs["clear_cutoff_at"] == 1_700_000_010.0
        assert committer.commit.await_args.kwargs["allow_pre_clear_events"] is True
        committer.capture_ingestion_boundary.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_payload_carries_policy_dict(self):
        bus = _make_bus()
        gateway = SourceIngestionGateway(event_bus=bus, memory_committer=_make_committer())
        source = _FakeSource()

        await gateway.ingest(source, _make_output())

        payload = bus.publish.await_args.args[0].data
        assert payload.policy_dict["memory_domain"] == "external_activity"
        assert payload.policy_dict["ingest_target"] == "l1_only"
        assert payload.policy_dict["retention_class"] == "permanent"
        assert payload.policy_dict["importance_bias"] == 0.7

    @pytest.mark.asyncio
    async def test_payload_carries_projection_dict(self):
        bus = _make_bus()
        gateway = SourceIngestionGateway(event_bus=bus, memory_committer=_make_committer())
        source = _FakeSource()

        await gateway.ingest(source, _make_output())

        payload = bus.publish.await_args.args[0].data
        assert payload.projection_dict.get("embedding_head") == "Fake Source Observed"
        assert (
            payload.projection_dict.get("metadata", {})
            .get("projection", {})
            .get("renderer_version")
            == "source_activity_v1"
        )

    @pytest.mark.asyncio
    async def test_payload_carries_owner_from_provenance(self):
        bus = _make_bus()
        gateway = SourceIngestionGateway(event_bus=bus, memory_committer=_make_committer())
        source = _FakeSource()
        output = _make_output(provenance={"user_id": "owner-42"})

        await gateway.ingest(source, output)

        payload = bus.publish.await_args.args[0].data
        assert payload.owner_user_id == "owner-42"
        assert payload.context.user_id == "owner-42"

    @pytest.mark.asyncio
    async def test_payload_carries_metadata_dict(self):
        bus = _make_bus()
        gateway = SourceIngestionGateway(event_bus=bus, memory_committer=_make_committer())
        source = _FakeSource()
        metadata = SourceOutputMetadata(
            tags=["j-pop", "electropop"],
            entities=[{"id": "entity-1"}],
            fact_hints=[{"subject_ref": "user:self"}],
        )

        await gateway.ingest(source, _make_output(), metadata)

        payload = bus.publish.await_args.args[0].data
        assert payload.metadata_dict is not None
        assert payload.metadata_dict["tags"] == ["j-pop", "electropop"]
        assert payload.metadata_dict["entities"] == [{"id": "entity-1"}]
        assert payload.metadata_dict["fact_hints"] == [{"subject_ref": "user:self"}]

    @pytest.mark.asyncio
    async def test_payload_metadata_dict_none_when_no_metadata(self):
        bus = _make_bus()
        gateway = SourceIngestionGateway(event_bus=bus, memory_committer=_make_committer())
        source = _FakeSource()

        await gateway.ingest(source, _make_output())

        payload = bus.publish.await_args.args[0].data
        assert payload.metadata_dict is None

    @pytest.mark.asyncio
    async def test_payload_carries_relation_candidates_and_whitelist(self):
        bus = _make_bus()
        gateway = SourceIngestionGateway(event_bus=bus, memory_committer=_make_committer())
        source = _FakeSource()
        metadata = SourceOutputMetadata(
            relation_candidates=[
                {"predicate": "LIKES", "object_id": "topic:test", "confidence": 0.9},
            ],
        )

        await gateway.ingest(
            source,
            _make_output(),
            metadata,
            allowed_edge_whitelist=["LIKES"],
        )

        payload = bus.publish.await_args.args[0].data
        assert payload.relation_candidates == (
            {"predicate": "LIKES", "object_id": "topic:test", "confidence": 0.9},
        )
        assert payload.allowed_edge_whitelist == ("LIKES",)

    @pytest.mark.asyncio
    async def test_payload_relation_candidates_default_empty(self):
        bus = _make_bus()
        gateway = SourceIngestionGateway(event_bus=bus, memory_committer=_make_committer())
        source = _FakeSource()

        await gateway.ingest(source, _make_output())

        payload = bus.publish.await_args.args[0].data
        assert payload.relation_candidates == ()
        assert payload.allowed_edge_whitelist == ()

    @pytest.mark.asyncio
    async def test_payload_carries_l2_batch_policy_dict(self):
        bus = _make_bus()
        gateway = SourceIngestionGateway(event_bus=bus, memory_committer=_make_committer())
        source = _FakeBatchingSource()

        await gateway.ingest(source, _make_output())

        payload = bus.publish.await_args.args[0].data
        assert payload.l2_batch_policy_dict is not None
        assert payload.l2_batch_policy_dict["owner"] == "fake_source:default"
        assert payload.l2_batch_policy_dict["max_events"] == 20
        assert payload.l2_batch_policy_dict["max_estimated_tokens"] == 3200
        assert payload.l2_batch_policy_dict["max_wait_seconds"] == 180

    @pytest.mark.asyncio
    async def test_payload_l2_batch_policy_dict_none_when_no_policy(self):
        bus = _make_bus()
        gateway = SourceIngestionGateway(event_bus=bus, memory_committer=_make_committer())
        source = _FakeSource()

        await gateway.ingest(source, _make_output())

        payload = bus.publish.await_args.args[0].data
        assert payload.l2_batch_policy_dict is None

    @pytest.mark.asyncio
    async def test_payload_carries_fingerprint_and_idempotency_key(self):
        bus = _make_bus()
        gateway = SourceIngestionGateway(event_bus=bus, memory_committer=_make_committer())
        source = _FakeSource()

        await gateway.ingest(source, _make_output())

        payload = bus.publish.await_args.args[0].data
        assert payload.idempotency_key == "item-1"
        assert payload.source_fingerprint  # non-empty string

    @pytest.mark.asyncio
    async def test_projection_publish_failure_keeps_confirmed_memory_success(self):
        """Derived projection failure cannot erase an already confirmed L1 commit."""
        bus = _make_bus()
        bus.publish = AsyncMock(side_effect=RuntimeError("boom"))
        gateway = SourceIngestionGateway(event_bus=bus, memory_committer=_make_committer())
        source = _FakeSource()

        result = await gateway.ingest(source, _make_output())
        assert result.ingested is True
        assert result.stats["projection_published"] is False

    @pytest.mark.asyncio
    async def test_memory_commit_failure_raises_without_publishing(self):
        bus = _make_bus()
        committer = _make_committer()
        committer.commit = AsyncMock(side_effect=RuntimeError("l1 unavailable"))
        gateway = SourceIngestionGateway(event_bus=bus, memory_committer=committer)

        with pytest.raises(RuntimeError, match="l1 unavailable"):
            await gateway.ingest(_FakeSource(), _make_output())

        bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_governed_skip_does_not_recreate_downstream_projection(self):
        bus = _make_bus()
        committer = _make_committer()
        committer.commit = AsyncMock(
            return_value=SourceCommitReceipt(
                event_id="forgotten-event",
                outcome=SourceCommitOutcome.GOVERNED_SKIP,
            )
        )
        gateway = SourceIngestionGateway(event_bus=bus, memory_committer=committer)

        result = await gateway.ingest(_FakeSource(), _make_output())

        assert result.ingested is True
        assert result.stats == {
            "memory_outcome": "governed_skip",
            "projection_published": False,
            "projection_skipped": True,
        }
        bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stale_batch_epoch_is_terminal_without_projection_publish(self):
        class _EpochMemory:
            def __init__(self) -> None:
                self.epoch = 23
                self.expected_epochs: list[int] = []

            async def ingest_event(self, event, *, expected_epoch):  # type: ignore[no-untyped-def]
                self.expected_epochs.append(int(expected_epoch))
                if int(expected_epoch) != self.epoch:
                    return {
                        "event_id": event.event_id,
                        "l1_written": False,
                        "l1_confirmed": False,
                        "skipped": True,
                        "skip_reason": "memory_clear_epoch_changed",
                    }
                return {
                    "event_id": event.event_id,
                    "l1_written": True,
                    "l1_confirmed": True,
                }

        bus = _make_bus()
        memory = _EpochMemory()
        gateway = SourceIngestionGateway(
            event_bus=bus,
            memory_committer=SourceEventCommitter(unified_memory=memory),
        )
        batch_epoch = memory.epoch
        boundary = SourceIngestionBoundary(
            expected_epoch=batch_epoch,
            clear_generation=0,
            clear_cutoff_at=0.0,
        )
        memory.epoch += 1

        result = await gateway.ingest(
            _FakeSource(),
            _make_output(),
            boundary=boundary,
        )

        assert memory.expected_epochs == [batch_epoch]
        assert result.ingested is True
        assert result.stats == {
            "memory_outcome": "governed_skip",
            "projection_published": False,
            "projection_skipped": True,
            "skip_reason": "memory_clear_epoch_changed",
        }
        bus.publish.assert_not_awaited()
