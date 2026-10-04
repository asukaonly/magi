from __future__ import annotations

import pytest

from magi.memory.history_imports.markdown_parser import (
    DOCUMENT_AUTHOR,
    parse_markdown,
)

_TEST_TIMEZONE_ID = "Asia/Shanghai"
_LONG_DOCUMENT = "# 长文\n\n" + "".join(f"第 {i} 段：这是个人记录。\n" for i in range(500)) + "\n## 结尾\n\n准备下次继续写。"


@pytest.mark.parametrize(
    "source_name,body",
    [
        (
            "alice.md",
            "# 和 Alice 的聊天\n## 2026-07-01\n- [09:00] 我：最近一直在听这张专辑。\n- [09:01] Alice：哪一张？\n- [09:02] 我：Oshin，越听越喜欢。",
        ),
        (
            "assistant.md",
            "## User\nI have been learning pottery lately.\n\n## Assistant\nWhat do you enjoy about it?\n\n## User\nIt makes me slow down.",
        ),
        (
            "journal.md",
            "# 七月\n\n最近重新开始跑步。\n\n## 想继续做的事\n\n每周至少去两次公园。\n\n## 关于音乐\n\n最近反复在听同一张专辑。",
        ),
        (
            "weekly.md",
            "## 2025-11-01\n\n第一次去攀岩。\n\n## 2025-11-03\n\n手臂还在酸，但已经想再去了。",
        ),
        ("long-note.md", _LONG_DOCUMENT),
    ],
    ids=["inline-chat", "role-headings", "ordinary-note", "dated-headings", "long-document"],
)
def test_personal_markdown_preserves_the_entire_document(source_name, body):
    parsed = parse_markdown(
        source_name=source_name,
        file_mtime=1900000000,
        calendar_timezone_id=_TEST_TIMEZONE_ID,
        text="\n" + body + "\n",
    )
    assert parsed.detected_kind == "document"
    assert len(parsed.records) == 1
    assert parsed.records[0]["content"] == body
    assert parsed.records[0]["speaker_name"] == DOCUMENT_AUTHOR
    assert parsed.records[0]["event_at"] == 1900000000
    assert parsed.records[0]["timestamp_confidence"] == "file_mtime"
    assert parsed.records[0]["timestamp_anchor_source"] == "file_mtime"
    assert parsed.warnings == [
        "document_author_confirmation_required",
        "timestamps_from_file_mtime",
    ]


@pytest.mark.parametrize(
    "source_name,frontmatter,day,provenance",
    [
        ("journal.md", "---\ndate: 2024-03-16\ntags: [daily]\n---\n", (2024, 3, 16), "frontmatter"),
        ("日记/2025-11-02.md", "", (2025, 11, 2), "source_name"),
        ("日记/2025-11-02.md", "---\ndate: 2024-03-16\n---\n", (2024, 3, 16), "frontmatter"),
    ],
    ids=["frontmatter", "filename", "frontmatter-precedence"],
)
@pytest.mark.parametrize("zone", ["Asia/Shanghai", "America/New_York"])
def test_document_dates_resolve_local_midnight_with_explicit_precedence(
    source_name, frontmatter, day, provenance, zone
):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    body = "# 今天\n\n和朋友去看了电影。"
    parsed = parse_markdown(
        source_name=source_name,
        file_mtime=1900000000,
        calendar_timezone_id=zone,
        text=frontmatter + body,
    )
    assert len(parsed.records) == 1
    record = parsed.records[0]
    assert record["event_at"] == datetime(*day, tzinfo=ZoneInfo(zone)).timestamp()
    assert record["timestamp_confidence"] == provenance
    assert record["timestamp_anchor_source"] == provenance
    assert record["calendar_timezone_id"] == zone
    assert record["content"] == body
    assert parsed.warnings == ["document_author_confirmation_required"]
