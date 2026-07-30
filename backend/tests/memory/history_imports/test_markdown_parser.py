from __future__ import annotations

from magi.memory.history_imports.markdown_parser import (
    DOCUMENT_AUTHOR,
    parse_markdown,
)


def test_parses_inline_chat_in_source_order() -> None:
    parsed = parse_markdown(
        source_name="alice.md",
        file_mtime=1_800_000_000,
        text="""
# 和 Alice 的聊天
## 2026-07-01
- [09:00] 我：最近一直在听这张专辑。
- [09:01] Alice：哪一张？
- [09:02] 我：Oshin，越听越喜欢。
""",
    )

    assert parsed.detected_kind == "chat"
    assert [item["speaker_name"] for item in parsed.records] == ["我", "Alice", "我"]
    assert [item["content"] for item in parsed.records] == [
        "最近一直在听这张专辑。",
        "哪一张？",
        "Oshin，越听越喜欢。",
    ]
    assert [item["event_at"] for item in parsed.records] == sorted(
        item["event_at"] for item in parsed.records
    )
    assert parsed.warnings == []


def test_parses_role_heading_chat_without_fabricating_timestamps() -> None:
    parsed = parse_markdown(
        source_name="assistant.md",
        file_mtime=1_800_000_000,
        text="""
## User
I have been learning pottery lately.

## Assistant
What do you enjoy about it?

## User
It makes me slow down.
""",
    )

    assert parsed.detected_kind == "chat"
    assert [item["speaker_name"] for item in parsed.records] == [
        "User",
        "Assistant",
        "User",
    ]
    assert parsed.warnings == ["timestamps_from_file_order"]
    assert all(
        item["timestamp_confidence"] == "file_order"
        for item in parsed.records
    )


def test_falls_back_to_personal_document_sections() -> None:
    parsed = parse_markdown(
        source_name="journal.md",
        file_mtime=1_800_000_000,
        text="""
# 七月

最近重新开始跑步。

## 想继续做的事

每周至少去两次公园。

## 关于音乐

最近反复在听同一张专辑。
""",
    )

    assert parsed.detected_kind == "document"
    assert len(parsed.records) == 3
    assert {item["speaker_name"] for item in parsed.records} == {DOCUMENT_AUTHOR}
    assert "document_author_confirmation_required" in parsed.warnings


def test_distinct_document_headings_are_not_misread_as_speakers() -> None:
    parsed = parse_markdown(
        source_name="notes.md",
        file_mtime=1_800_000_000,
        text="""
## 背景
这是项目的背景。

## 结论
这是最终结论。

## 下一步
准备继续验证。
""",
    )

    assert parsed.detected_kind == "document"
