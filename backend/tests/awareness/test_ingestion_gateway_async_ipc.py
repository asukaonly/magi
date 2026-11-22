"""Verification tests for P1-C3: zero blocking invoke_sync calls in SourceIngestionGateway."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.awareness.ingestion_gateway import SourceIngestionGateway
from magi.awareness.source_output import (
    ActivityFacet,
    SourceActivity,
    SourceMemoryPolicy,
    SourceNarration,
    SourceOutput,
    SourceOutputMetadata,
)
from magi.memory.source_ingestion import (
    SourceCommitOutcome,
    SourceCommitReceipt,
    SourceIngestionBoundary,
)
from magi.plugins.process_proxies import SourceProxy
from magi.plugins.projections import PluginProjectionService
from magi_plugin_sdk.sources import Source
from magi_plugin_sdk.worker_catalog import SOURCE_METHODS


def _make_output(idx: int) -> SourceOutput:
    return SourceOutput(
        source_type="chrome_history",
        source_item_id=f"visit-{idx}",
        occurred_at=1_760_000_000.0 + idx,
        captured_at=1_760_000_000.0 + idx,
        activity=SourceActivity(
            source=ActivityFacet(code="chrome", i18n_key="source.chrome", fallback="Chrome"),
            action=ActivityFacet(code="visited", i18n_key="action.visited", fallback="visited"),
        ),
        narration=SourceNarration(title=f"Page {idx}", body=f"Read article {idx} about async Rust"),
        tags=["rust", "async"],
    )


def _make_proxy(tmp_path: Path, *, ipc_delay_seconds: float = 0.0) -> tuple[SourceProxy, MagicMock]:
    owner = MagicMock()
    owner.plugin_id = "chrome-history"
    owner.manifest = SimpleNamespace(plugin_dir=tmp_path)
    owner.connection = MagicMock()
    owner.connection.connection_id = "conn-chrome"
    owner.connection.plugin_id = "chrome-history"
    owner.context = MagicMock()
    owner.context.connection = owner.connection

    def _forbidden_invoke_sync(*_args, **_kwargs):
        raise AssertionError("invoke_sync must never be called on the main asyncio loop during ingestion")

    owner.invoke_sync = MagicMock(side_effect=_forbidden_invoke_sync)

    async def _fake_invoke(target: str, method: str, *args, **kwargs):
        if ipc_delay_seconds > 0:
            await asyncio.sleep(ipc_delay_seconds)
        if method == "prepare_ingestion_metadata":
            output = args[0]
            include_idempotency = kwargs.get("include_idempotency_key", True)
            return {
                "source_fingerprint": f"fp:{output.source_item_id}",
                "idempotency_key": f"worker-key:{output.source_item_id}" if include_idempotency else None,
                "l2_batch_policy": None,
                "display_labels": {"source": "Chrome", "action": "visited"},
            }
        raise AssertionError(f"Unexpected IPC method: {method}")

    owner.invoke = AsyncMock(side_effect=_fake_invoke)
    descriptor = {
        "id": "chrome_history",
        "target": "get_sources:0",
        "methods": [
            "collect_items",
            "build_output",
            "extract_metadata",
            "source_item_version_fingerprint",
            "idempotency_key",
            "l2_batch_policy",
            "prepare_ingestion_metadata",
            "t",
        ],
        "attributes": {
            "source_type": "chrome_history",
            "memory_event_type": "SOURCE_EVENT",
            "memory_policy": SourceMemoryPolicy(),
        },
    }
    return SourceProxy(owner, descriptor), owner


class _FakeCommitter:
    async def capture_ingestion_boundary(self) -> SourceIngestionBoundary:
        return SourceIngestionBoundary(expected_epoch=1, clear_generation=0, clear_cutoff_at=0.0)

    async def commit(self, event, **_kwargs) -> SourceCommitReceipt:
        return SourceCommitReceipt(
            event_id=event.event_id,
            outcome=SourceCommitOutcome.PERSISTED,
        )


@pytest.mark.asyncio
async def test_ingesting_50_items_via_source_proxy_makes_zero_invoke_sync_calls(tmp_path: Path):
    """Ingesting 50 items via SourceProxy makes 0 invoke_sync calls and 1 async IPC call/item."""
    proxy, owner = _make_proxy(tmp_path)
    bus = SimpleNamespace(publish=AsyncMock(return_value=True))
    gateway = SourceIngestionGateway(event_bus=bus, memory_committer=_FakeCommitter())
    boundary = await gateway.capture_ingestion_boundary()

    for idx in range(50):
        res = await gateway.ingest(
            proxy,
            _make_output(idx),
            SourceOutputMetadata(tags=["rust"]),
            boundary=boundary,
            host_idempotency_key=f"host-res-{idx}",
        )
        assert res.ingested is True

    assert owner.invoke_sync.call_count == 0
    # Exactly 1 bundled async IPC call per item, and idempotency_key skipped when host supplies one.
    assert owner.invoke.await_count == 50
    for call in owner.invoke.await_args_list:
        assert call.args[1] == "prepare_ingestion_metadata"
        assert call.kwargs["include_idempotency_key"] is False

    # Verify committed payload received host idempotency key and bundled projection labels
    published_event = bus.publish.await_args_list[0].args[0]
    assert published_event.data.idempotency_key == "host-res-0"
    assert published_event.data.source_fingerprint == "fp:visit-0"
    assert published_event.data.projection_dict["title"] == "Chrome visited · Page 0"


@pytest.mark.asyncio
async def test_concurrent_200_item_ingestion_keeps_event_loop_jitter_below_50ms(tmp_path: Path):
    """Ingesting 200 items with simulated async IPC latency must not block foreground ticks."""
    proxy, owner = _make_proxy(tmp_path, ipc_delay_seconds=0.002)
    bus = SimpleNamespace(publish=AsyncMock(return_value=True))
    gateway = SourceIngestionGateway(event_bus=bus, memory_committer=_FakeCommitter())
    boundary = await gateway.capture_ingestion_boundary()

    max_jitter_ms = 0.0
    ticks = 0
    done = asyncio.Event()

    async def _heartbeat_probe() -> None:
        nonlocal max_jitter_ms, ticks
        interval = 0.005
        while not done.is_set():
            t0 = time.perf_counter()
            await asyncio.sleep(interval)
            jitter_ms = max(0.0, (time.perf_counter() - t0 - interval) * 1000.0)
            if jitter_ms > max_jitter_ms:
                max_jitter_ms = jitter_ms
            ticks += 1

    async def _ingest_200() -> None:
        try:
            for idx in range(200):
                await gateway.ingest(
                    proxy,
                    _make_output(idx),
                    boundary=boundary,
                    host_idempotency_key=f"host-{idx}",
                )
        finally:
            done.set()

    await asyncio.gather(_heartbeat_probe(), _ingest_200())
    assert owner.invoke_sync.call_count == 0
    assert ticks >= 5
    assert max_jitter_ms < 50.0, f"Event loop blocked for {max_jitter_ms:.1f}ms (budget < 50ms)"


@pytest.mark.asyncio
async def test_plugin_projection_service_awaits_async_temporal_summary_features():
    """PluginProjectionService.build_temporal_summary_features_async awaits async proxy methods."""
    plugin = SimpleNamespace(
        plugin_id="chrome-history",
        connection=SimpleNamespace(connection_id="conn-1", plugin_id="chrome-history", enabled=True),
        manifest=SimpleNamespace(plugin_id="chrome-history", version="1.0.0", projection_sources=("chrome",)),
        build_temporal_summary_features=AsyncMock(return_value={"summary_lines": ["Read Rust docs"]}),
    )
    service = PluginProjectionService(iter_loaded_plugins=lambda: [plugin])
    event = {
        "event_id": "evt-1",
        "source": "chrome",
        "metadata_json": {
            "source_connection_id": "conn-1",
            "source_plugin_id": "chrome-history",
            "source_object_version": "v1",
            "source_evidence_ref": {
                "connection_id": "conn-1",
                "version": "v1",
                "resource_id": "res-1",
            },
        },
    }
    result = await service.build_temporal_summary_features_async(
        events=[event],
        summary_category="day",
        period_start=100.0,
        period_end=200.0,
    )
    plugin.build_temporal_summary_features.assert_awaited_once()
    assert result["conn-1:chrome"]["summary_lines"] == ["Read Rust docs"]


def test_sdk_source_prepare_ingestion_metadata_is_allowlisted_and_bundled():
    assert "prepare_ingestion_metadata" in SOURCE_METHODS

    class _DummySource(Source):
        source_id = "dummy"
        source_type = "chrome_history"

        async def build_output(self, item):
            return _make_output(0)

    src = _DummySource()
    out = _make_output(7)
    bundled = src.prepare_ingestion_metadata(out, language="en", include_idempotency_key=False)
    assert bundled["idempotency_key"] is None
    assert bundled["source_fingerprint"] == src.source_item_version_fingerprint(out.to_dict())
    assert bundled["display_labels"] == {"source": "Chrome", "action": "visited"}
    assert bundled["l2_batch_policy"] is None
