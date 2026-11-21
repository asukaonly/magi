"""Tests for cross-process plugin i18n propagation and localized timeline/manual-entry labels."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from magi import i18n as core_i18n
from magi.memory.manual_entries.l1_projector import _build_memory_event
from magi.memory.manual_entries.models import ManualEntry
from magi.plugins.i18n import set_current_language as set_plugin_current_language
from magi.plugins.process_proxies import SourceProxy
from magi.timeline.service import _synthesize_standout_title
from magi_plugin_sdk.i18n import get_current_language as get_sdk_language
from magi_plugin_sdk.worker import WorkerServer


def test_source_proxy_t_forwards_host_language():
    owner = MagicMock()
    owner.plugin_id = "chrome-history"
    owner.manifest.plugin_dir = None
    owner.connection = MagicMock()
    owner.connection.plugin_id = "chrome-history"
    owner.context = MagicMock()
    owner.context.connection = owner.connection
    owner.invoke_sync.return_value = "translated"
    proxy = SourceProxy(
        owner,
        {
            "id": "chrome_history",
            "target": "source:0",
            "methods": ["t"],
            "attributes": {
                "display_name": "Chrome",
                "domain": "browsing",
                "polling_mode": "pull",
            },
        },
    )

    set_plugin_current_language("zh-CN")
    try:
        proxy.t("summary.visited_page", title="Docs")
        assert owner.invoke_sync.call_args.kwargs["language"] == "zh-CN"

        proxy.t("summary.visited_page", language="en", title="Docs")
        assert owner.invoke_sync.call_args.kwargs["language"] == "en"
    finally:
        set_plugin_current_language(None)


@pytest.mark.asyncio
async def test_worker_execute_applies_and_resets_invocation_language():
    observed_languages: list[str] = []

    def handler() -> str:
        observed_languages.append(get_sdk_language())
        return get_sdk_language()

    server = WorkerServer.__new__(WorkerServer)
    server.tasks = {}
    server.source_watches = {}
    server.streams = {}
    server.stream_busy = set()
    server.channel_boundaries = {}
    server.stopping = False
    server.max_inflight = 4
    sent: list[dict[str, object]] = []
    server.send = sent.append
    server.catalog = MagicMock()
    server.catalog.method.return_value = handler

    for lang in ("zh-CN", "en"):
        await server._execute(
            f"req-{lang}",
            {
                "method": "invoke",
                "payload": {
                    "target": "source:0",
                    "method": "build_output",
                    "args": (),
                    "kwargs": {},
                    "language": lang,
                },
            },
        )

    assert observed_languages == ["zh-CN", "en"]
    assert [msg["result"] for msg in sent] == ["zh-CN", "en"]
    # Context resets cleanly back to default after invocation finishes.
    assert get_sdk_language() == "en"


def test_manual_entry_projection_title_follows_active_language():
    entry = ManualEntry(
        entry_id="me-i18n-1",
        created_at=1000.0,
        event_at=1000.0,
        kind="quick",
        body="Walked by the lake",
    )

    with core_i18n.language_context("en"):
        en_event = _build_memory_event(entry, predecessor_event_id=None)
    with core_i18n.language_context("zh-CN"):
        zh_event = _build_memory_event(entry, predecessor_event_id=None)

    assert en_event.metadata_json["activity_snapshot"]["title"] == "Your note"
    assert zh_event.metadata_json["activity_snapshot"]["title"] == "你写下的"


def test_standout_fallback_title_follows_locale_and_timezone():
    # 2026-10-18 is a Sunday.
    start = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc).timestamp()

    assert _synthesize_standout_title(
        start, start + 3 * 3600, locale="en", timezone_name="UTC"
    ) == "Sun 14:00 · 3h"
    assert _synthesize_standout_title(
        start, start + 30, locale="en", timezone_name="UTC"
    ) == "Sun 14:00 · <1m"
    assert _synthesize_standout_title(
        start, start + 3 * 3600, locale="zh-CN", timezone_name="UTC"
    ) == "周日 14:00 · 3h"
    assert _synthesize_standout_title(
        start, start + 30, locale="zh-CN", timezone_name="UTC"
    ) == "周日 14:00 · 短"
