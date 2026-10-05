"""Source ``output.tags`` must flow into the L1 FTS retrieval terms.

Previously only ``metadata.tags`` (the host-attached enrichment set) was
promoted into ``projection.retrieval_terms``. Plugin-emitted tags such
as the screen-time plugin's ``app_category:gaming`` were silently
dropped, so a BM25 / keyword query for ``gaming`` never matched the
underlying ``APP_USAGE_HOURLY`` event even when the tag was set
correctly. These tests lock in the corrected behavior.
"""
from __future__ import annotations

import pytest

from magi.awareness.source_base import Source
from magi.awareness.source_output import (
    SourceActivity,
    SourceNarration,
    SourceOutput,
    SourceOutputMetadata,
    TimelinePresentation,
)
from magi.awareness.source_projection import build_source_projection
from magi_plugin_sdk.sources import ActivityFacet, ContentBlock


class _FakeSource(Source):
    """Minimal concrete source; build_source_projection only reads metadata."""

    source_id = "test.fake"
    source_type = "fake"
    plugin_id = "test_plugin"
    display_name = "Fake"
    memory_event_type = "FAKE_EVENT"

    async def collect_items(self, context):  # pragma: no cover - unused here
        raise NotImplementedError

    async def build_output(self, item):  # pragma: no cover - unused here
        raise NotImplementedError


def _build_output(*, tags: list[str]) -> SourceOutput:
    return SourceOutput(
        source_type="fake",
        source_item_id="fake-1",
        occurred_at=1000.0,
        captured_at=1001.0,
        activity=SourceActivity(
            source=ActivityFacet(
                code="wuthering_waves",
                i18n_key="apps.wuthering_waves",
                fallback="Wuthering Waves",
            ),
            action=ActivityFacet(
                code="usage",
                i18n_key="activity.action.usage",
                fallback="Usage",
            ),
        ),
        narration=SourceNarration(title="", body="11:00-12:00 · 30 min"),
        content_blocks=[ContentBlock(kind="text", value="Category: gaming")],
        tags=tags,
    )


def _retrieval_terms(projection_metadata: dict) -> list[str]:
    return list(
        projection_metadata.get("projection", {}).get("retrieval_terms") or []
    )


@pytest.mark.parametrize(
    "tags, expected",
    [
        (
            ["screen_time", "app_usage", "app_category:gaming"],
            ["screen_time", "app_usage", "app_category:gaming"],
        ),
        (["Gaming", "gaming", "GAMING"], ["Gaming"]),
        ([], []),
    ],
)
def test_source_tags_project_as_distinct_retrieval_terms(tags, expected):
    projection = build_source_projection(_FakeSource(), _build_output(tags=tags), metadata=None)
    terms = _retrieval_terms(projection.metadata)
    assert [term.casefold() for term in terms] == [term.casefold() for term in expected]
    if not expected:
        assert "retrieval_terms" not in projection.metadata.get("projection", {})


def test_metadata_tags_merge_with_output_tags() -> None:
    """Host-attached tags still contribute, on top of producer tags."""
    output = _build_output(tags=["app_category:gaming"])
    metadata = SourceOutputMetadata(
        entities=[],
        tags=["work_context"],
        relation_candidates=[],
        fact_hints=[],
    )

    projection = build_source_projection(_FakeSource(), output, metadata=metadata)

    terms = _retrieval_terms(projection.metadata)
    assert "app_category:gaming" in terms
    assert "work_context" in terms


def test_timeline_presentation_keeps_evidence_text_out_of_summary() -> None:
    """High-volume evidence sources can keep OCR searchable without flooding timeline."""
    full_ocr_text = (
        "Magi AI Agent Framework 通知 对话 时间线 记忆 任务 设置 后台任务 "
        "调度配置 调度记录 今天 近 24 小时 近 7 天 全部 用户自定义 0 "
        "数据来源同步 5 记忆维护 1 时间线维护 0 状态 全部"
    )
    output = SourceOutput(
        source_type="screenshot_timeline",
        source_item_id="cap-1",
        occurred_at=1000.0,
        captured_at=1001.0,
        activity=SourceActivity(
            source=ActivityFacet(
                code="screenshot_timeline",
                i18n_key="activity.source.screenshot_timeline",
                fallback="Screenshot Timeline",
            ),
            action=ActivityFacet(
                code="screen_capture",
                i18n_key="activity.action.screen_capture",
                fallback="Screen Capture",
            ),
        ),
        narration=SourceNarration(title="Magi: 调度记录", body=full_ocr_text),
        content_blocks=[ContentBlock(kind="text", value=full_ocr_text)],
        timeline_presentation=TimelinePresentation(
            mode="evidence_only",
            title="Magi: 调度记录",
        ),
    )

    projection = build_source_projection(_FakeSource(), output, metadata=None)

    assert "Magi: 调度记录" in projection.summary
    assert full_ocr_text not in projection.summary
    assert full_ocr_text in projection.content
    assert projection.metadata["projection"]["timeline_presentation"]["mode"] == "evidence_only"
