from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from magi.memory.history_imports.markdown_parser import (
    DOCUMENT_AUTHOR,
    parse_markdown,
)

_TEST_TIMEZONE_ID = "Asia/Shanghai"


def test_parses_inline_chat_in_source_order() -> None:
    parsed = parse_markdown(
        source_name="alice.md",
        file_mtime=1_800_000_000,
        calendar_timezone_id=_TEST_TIMEZONE_ID,
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
    assert all(
        item["timestamp_anchor_source"] == "message_timestamp"
        for item in parsed.records
    )
    assert all(
        item["calendar_timezone_id"] == _TEST_TIMEZONE_ID
        for item in parsed.records
    )
    assert datetime.fromtimestamp(
        parsed.records[0]["event_at"],
        tz=ZoneInfo(_TEST_TIMEZONE_ID),
    ).isoformat() == "2026-07-01T09:00:00+08:00"


def test_parses_role_heading_chat_without_fabricating_timestamps() -> None:
    parsed = parse_markdown(
        source_name="assistant.md",
        file_mtime=1_800_000_000,
        calendar_timezone_id=_TEST_TIMEZONE_ID,
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
    assert all(item["timestamp_confidence"] == "file_order" for item in parsed.records)
    assert all(item["timestamp_anchor_source"] == "file_order" for item in parsed.records)


def test_falls_back_to_one_personal_document() -> None:
    parsed = parse_markdown(
        source_name="journal.md",
        file_mtime=1_800_000_000,
        calendar_timezone_id=_TEST_TIMEZONE_ID,
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
    assert len(parsed.records) == 1
    assert {item["speaker_name"] for item in parsed.records} == {DOCUMENT_AUTHOR}
    assert parsed.records[0]["content"] == (
        "# 七月\n\n"
        "最近重新开始跑步。\n\n"
        "## 想继续做的事\n\n"
        "每周至少去两次公园。\n\n"
        "## 关于音乐\n\n"
        "最近反复在听同一张专辑。"
    )
    assert "document_author_confirmation_required" in parsed.warnings


def test_distinct_document_headings_are_not_misread_as_speakers() -> None:
    parsed = parse_markdown(
        source_name="notes.md",
        file_mtime=1_800_000_000,
        calendar_timezone_id=_TEST_TIMEZONE_ID,
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


def test_uses_frontmatter_date_for_personal_writing() -> None:
    parsed = parse_markdown(
        source_name="journal.md",
        file_mtime=1_900_000_000,
        calendar_timezone_id=_TEST_TIMEZONE_ID,
        text="""
---
date: 2024-03-16
tags: [daily]
---
# 周六

今天重新开始跑步，傍晚去了河边。
""",
    )

    assert parsed.detected_kind == "document"
    assert parsed.records[0]["timestamp_confidence"] == "frontmatter"
    assert parsed.records[0]["timestamp_anchor_source"] == "frontmatter"
    assert "timestamps_from_file_mtime" not in parsed.warnings


def test_uses_date_from_daily_note_filename() -> None:
    parsed = parse_markdown(
        source_name="日记/2025-11-02.md",
        file_mtime=1_900_000_000,
        calendar_timezone_id=_TEST_TIMEZONE_ID,
        text="# 今天\n\n和朋友去看了电影。",
    )

    assert parsed.detected_kind == "document"
    assert parsed.records[0]["timestamp_confidence"] == "source_name"
    assert parsed.records[0]["timestamp_anchor_source"] == "source_name"
    assert "timestamps_from_file_mtime" not in parsed.warnings


def test_preserves_multiple_dated_sections_inside_one_document() -> None:
    parsed = parse_markdown(
        source_name="weekly.md",
        file_mtime=1_900_000_000,
        calendar_timezone_id=_TEST_TIMEZONE_ID,
        text="""
## 2025-11-01

第一次去攀岩。

## 2025-11-03

手臂还在酸，但已经想再去了。
""",
    )

    assert len(parsed.records) == 1
    assert parsed.records[0]["timestamp_confidence"] == "file_mtime"
    assert parsed.records[0]["timestamp_anchor_source"] == "file_mtime"
    assert parsed.records[0]["event_at"] == 1_900_000_000
    assert "## 2025-11-01" in parsed.records[0]["content"]
    assert "## 2025-11-03" in parsed.records[0]["content"]


def test_keeps_long_personal_writing_as_one_document() -> None:
    paragraph = "这是很长的一段个人记录。" * 500

    parsed = parse_markdown(
        source_name="long-note.md",
        file_mtime=1_900_000_000,
        calendar_timezone_id=_TEST_TIMEZONE_ID,
        text=f"# 长文\n\n{paragraph}\n\n## 结尾\n\n准备下次继续写。",
    )

    assert parsed.detected_kind == "document"
    assert len(parsed.records) == 1
    assert parsed.records[0]["content"].startswith("# 长文")
    assert parsed.records[0]["content"].endswith("准备下次继续写。")
    assert len(parsed.records[0]["content"]) > 4_000
