from __future__ import annotations

from magi.agent.execution.tool_context_formatters import (
    compact_agent_tool_data,
    compact_glob_tool_data,
    compact_read_chat_attachment_tool_data,
    compact_shell_tool_data,
)
from magi.memory.tool_context_formatter import compact_memory_tool_data
from magi.memory.tool_context_rendering import render_memory_context


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


def test_compact_shell_tool_data_keeps_tail_and_runner_metadata() -> None:
    compact = compact_shell_tool_data(
        {
            "command": "run-check",
            "return_code": 1,
            "stdout": "prefix-final-marker",
            "stderr": "warning-timeout-marker",
            "stdout_total_bytes": 100_000,
            "stderr_total_bytes": 80_000,
            "stdout_truncated": True,
            "stderr_truncated": True,
            "timed_out": True,
        },
        max_text_chars=12,
    )

    assert compact["stdout_preview"] == "final-marker"
    assert compact["stderr_preview"] == "meout-marker"
    assert compact["stdout_preview_truncated"] is True
    assert compact["stderr_preview_truncated"] is True
    assert compact["stdout_total_bytes"] == 100_000
    assert compact["stderr_total_bytes"] == 80_000
    assert compact["stdout_truncated"] is True
    assert compact["stderr_truncated"] is True
    assert compact["timed_out"] is True


def test_compact_agent_tool_data_keeps_child_summary() -> None:
    compact = compact_agent_tool_data(
        {
            "worker_id": "worker_1",
            "child_run_id": "child_1",
            "status": "completed",
            "preset": "read_only",
            "description": "scan backend",
            "result": {
                "summary": "backend analyzed",
                "findings": [{"title": "backend", "detail": "runtime path"}],
            },
        },
        max_items=40,
    )

    assert compact["worker_id"] == "worker_1"
    assert compact["child_run_id"] == "child_1"
    assert compact["preset"] == "read_only"
    assert compact["child_result"]["summary"] == "backend analyzed"


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


def test_render_memory_context_includes_all_supported_sections() -> None:
    rendered = render_memory_context(
        {
            "l1_timeline_summary": [
                {
                    "session_id": "s1",
                    "turn_id": "t1",
                    "author_type": "user",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "summary_preview": "planned a trip",
                }
            ],
            "l1_events": [
                {
                    "session_id": "s1",
                    "turn_id": "t2",
                    "author_type": "assistant",
                    "score": 0.9,
                    "content_preview": "shared route options",
                }
            ],
            "l2_entity_cards": [
                {
                    "name": "Tokyo",
                    "entity_type": "place",
                    "summary_preview": "favorite stop",
                }
            ],
            "l2_relationships": [
                {
                    "subject": "user",
                    "predicate": "LIKES",
                    "object": "Tokyo",
                    "confidence": 0.8,
                    "evidence": "repeat mentions",
                }
            ],
            "l2_assertions": [
                {
                    "subject": "user",
                    "predicate": "prefers",
                    "claim_preview": "quiet routes",
                    "confidence": 0.7,
                }
            ],
            "l2_experiences": [
                {
                    "title": "Japan planning",
                    "magi_interpretation": "balancing city hops",
                    "source_event_count": 3,
                }
            ],
            "l3_reflections": [
                {
                    "summary_type": "temporal",
                    "summary_category": "travel",
                    "summary_preview": "kept refining the route",
                }
            ],
            "l4_procedures": [
                {
                    "skill_name": "route-search",
                    "skill_category": "tool",
                    "success_rate": 0.75,
                    "total_attempts": 4,
                    "breaker_state": "half_open",
                    "description_preview": "use when travel dates are known",
                }
            ],
        }
    )

    assert (
        rendered == "Timeline Summary:\n"
        "- session=s1 turn=t1 role=user t=2026-01-01T00:00:00Z: planned a trip\n\n"
        "Key Events:\n"
        "- session=s1 turn=t2 role=assistant score=0.9: shared route options\n\n"
        "Entity Cards:\n"
        "- Tokyo (place): favorite stop\n\n"
        "Relationships:\n"
        "- user LIKES Tokyo (confidence=0.8) [repeat mentions]\n\n"
        "Assertions:\n"
        "- user prefers: quiet routes (confidence=0.7)\n\n"
        "Experiences:\n"
        "- Japan planning: balancing city hops (events=3)\n\n"
        "Reflections:\n"
        "- temporal/travel: kept refining the route\n\n"
        "Execution Experience:\n"
        "- route-search (tool, 75% success over 4 uses) [recovering]: "
        "use when travel dates are known"
    )
