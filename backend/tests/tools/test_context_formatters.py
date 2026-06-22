from __future__ import annotations

from magi.agent.execution.tool_context_formatters import (
    compact_agent_tool_data,
    compact_glob_tool_data,
    compact_read_chat_attachment_tool_data,
)
from magi.memory.tool_context_formatter import compact_memory_tool_data


def test_compact_glob_tool_data_trims_matches() -> None:
    matches = [
        {
            "path": f"/tmp/file_{i}.py",
            "name": f"file_{i}.py",
            "is_file": True,
            "is_dir": False,
            "size": i,
        }
        for i in range(45)
    ]

    compact = compact_glob_tool_data(
        {"pattern": "**/*.py", "base_path": "/tmp", "matches": matches, "count": 45}, max_items=40
    )

    assert compact["count"] == 45
    assert compact["omitted_matches"] == 5
    assert len(compact["matches"]) == 40
    assert compact["matches"][0]["path"] == "/tmp/file_0.py"
    assert "size" not in compact["matches"][0]


def test_compact_agent_tool_data_keeps_worker_summary() -> None:
    compact = compact_agent_tool_data(
        {
            "worker_id": "worker_1",
            "status": "completed",
            "subagent_type": "CodeExplore",
            "description": "scan backend",
            "result": {
                "summary": "backend analyzed",
                "findings": [{"title": "backend", "detail": "runtime path"}],
            },
        },
        max_items=40,
    )

    assert compact["worker_id"] == "worker_1"
    assert compact["worker_result"]["summary"] == "backend analyzed"


def test_compact_read_chat_attachment_tool_data_trims_text() -> None:
    compact = compact_read_chat_attachment_tool_data(
        {
            "attachment": {"attachment_id": "att-1", "original_name": "report.pdf"},
            "content_kind": "text",
            "text": "abcdef",
            "offset": 0,
            "returned_chars": 6,
            "total_chars": 6,
            "is_complete": True,
            "summary": "Read report",
        },
        max_text_chars=3,
    )

    assert compact["attachment"]["attachment_id"] == "att-1"
    assert compact["text_preview"] == "abc"
    assert compact["text_truncated"] is True
    assert compact["summary"] == "Read report"


def test_compact_memory_tool_data_renders_l2_experiences() -> None:
    compact = compact_memory_tool_data(
        {
            "results": {
                "l2_experiences": [
                    {
                        "experience_id": "exp-japan",
                        "title": "日本旅行",
                        "magi_interpretation": "在路线、车票和城市切换之间整理旅行节奏。",
                        "source_event_count": 18,
                    }
                ],
                "trace": {"l2_experience_count": 1},
            }
        },
        max_items=5,
        max_text_chars=80,
    )

    assert "Experiences:" in compact["memory_context"]
    assert "日本旅行" in compact["memory_context"]
    assert compact["meta"]["l2_experience_count"] == 1
