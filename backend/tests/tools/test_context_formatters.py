from __future__ import annotations

from magi.agent.execution.tool_context_formatters import (
    compact_glob_tool_data,
    compact_read_chat_attachment_tool_data,
    compact_shell_tool_data,
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


def test_agent_formatter_preserves_actionable_worker_states_and_bounds_batch_size():
    from magi.agent.execution.tool_context_formatters import ToolContextFormatterRegistry

    registry = ToolContextFormatterRegistry.build_default(
        max_items=3, max_text_chars=80, memory_formatter=lambda data: data
    )
    formatter = registry.get("agent")
    workers = [
        {
            "worker_id": "complete",
            "child_run_id": "child-1",
            "status": "completed",
            "preset": "read_only",
            "result": {
                "summary": "backend analyzed",
                "findings": [{"title": "backend", "detail": "runtime path"}],
            },
        },
        {"worker_id": "pending", "status": "running"},
        {
            "worker_id": "failed",
            "status": "failed",
            "error": "Repository unavailable",
            "failure_reason": "workspace_missing",
        },
        {"worker_id": "outside-limit", "status": "running"},
    ]
    compact = formatter({"workers": workers, "parent_run_id": "parent-1", "parallel": True})
    assert compact["worker_count"] == 4
    assert compact["parent_run_id"] == "parent-1"
    assert compact["parallel"] is True
    assert [row["worker_id"] for row in compact["workers"]] == ["complete", "pending", "failed"]
    complete, pending, failed = compact["workers"]
    assert complete["child_result"] == workers[0]["result"]
    assert complete["child_run_id"] == "child-1" and complete["preset"] == "read_only"
    assert [row["needs_await"] for row in compact["workers"]] == [False, True, False]
    assert pending["child_result"] is None
    assert (failed["error"], failed["failure_reason"]) == (
        "Repository unavailable",
        "workspace_missing",
    )


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


def test_memory_compaction_renders_evidence_from_all_layers():
    results = {
        "l1_timeline_summary": [
            {
                "session_id": "s1",
                "turn_id": "t1",
                "author_type": "user",
                "timestamp": "2026-01-01T00:00:00Z",
                "summary": "planned a trip",
            }
        ],
        "l1_events": [
            {
                "session_id": "s1",
                "turn_id": "t2",
                "author_type": "assistant",
                "score": 0.9,
                "content": "shared route options",
            }
        ],
        "l2_entity_cards": [{"name": "Tokyo", "entity_type": "place", "summary": "favorite stop"}],
        "l2_relationships": [
            {
                "subject": "user",
                "predicate": "LIKES",
                "object": "Tokyo",
                "confidence": 0.8,
                "evidence_text": "repeat mentions",
            }
        ],
        "l2_assertions": [
            {"subject": "user", "predicate": "prefers", "confidence": 0.7, "claim": "quiet routes"}
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
                "summary": "kept refining the route",
            }
        ],
        "l4_procedures": [
            {
                "skill_name": "route-search",
                "skill_category": "tool",
                "success_rate": 0.75,
                "total_attempts": 4,
                "description": "use when travel dates are known",
                "circuit_breaker_state": "half_open",
            }
        ],
        "trace": {"l2_experience_count": 1},
    }
    compact = compact_memory_tool_data({"results": results}, max_items=5, max_text_chars=80)
    sections = dict(section.split(":\n", 1) for section in compact["memory_context"].split("\n\n"))
    expected = {
        "Timeline Summary": ["session=s1", "turn=t1", "role=user", "planned a trip"],
        "Key Events": ["turn=t2", "role=assistant", "score=0.9", "shared route options"],
        "Entity Cards": ["Tokyo", "place", "favorite stop"],
        "Relationships": ["user LIKES Tokyo", "confidence=0.8", "repeat mentions"],
        "Assertions": ["user prefers", "quiet routes", "confidence=0.7"],
        "Experiences": ["Japan planning", "balancing city hops", "events=3"],
        "Reflections": ["temporal/travel", "kept refining the route"],
        "Execution Experience": [
            "route-search",
            "75% success over 4 uses",
            "recovering",
            "use when travel dates are known",
        ],
    }
    assert sections.keys() == expected.keys()
    for section, facts in expected.items():
        for fact in facts:
            assert fact in sections[section], (section, fact)
    assert compact["meta"]["l2_experience_count"] == 1
