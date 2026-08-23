"""Tests for the Coding subagent type."""

from __future__ import annotations

import json

import pytest

# Import order matters: agent_tool transitively imports workers; importing
# AgentTool first lets the workers module finish initializing.
from magi.agent.runtime_tools import AgentTool
from magi.agent.workers import WorkerAgentManager
from magi.tools.platform_tools import native_shell_tool_name


class _FakeRegistry:
    """Mirrors the fake registry pattern in tests/tools/test_agent_tool.py."""

    def __init__(self, tools: list[str]) -> None:
        self._tools = list(tools)

    def list_tools(self) -> list[str]:
        return list(self._tools)


_CODING_REGISTRY_TOOLS = [
    "file_read",
    "file_edit",
    "file_write",
    "file_rollback",
    "file_diff",
    "verify",
    "glob",
    "grep",
    "file_list",
    "file_info",
    native_shell_tool_name(),
    "find-relevant-tools",
    "todo_write",
    "agent",
    "memory_query",
    "web_search",
    "web_fetch",  # not in whitelist
]


def _coding_manager() -> WorkerAgentManager:
    mgr = WorkerAgentManager()
    mgr._tool_registry = _FakeRegistry(_CODING_REGISTRY_TOOLS)  # type: ignore[assignment]
    return mgr


def test_worker_manager_exposes_coding_type() -> None:
    assert WorkerAgentManager.TYPE_CODING == "Coding"


@pytest.mark.parametrize("alias", ["coding", "Coding", "code"])
def test_worker_manager_alias_normalizes_to_coding(alias: str) -> None:
    mgr = WorkerAgentManager()
    assert mgr._normalize_subagent_type(alias) == WorkerAgentManager.TYPE_CODING


def test_agent_tool_advertises_coding_in_enum() -> None:
    tool = AgentTool()
    subagent_param = next(p for p in tool.schema.parameters if p.name == "subagent_type")
    assert "Coding" in (subagent_param.enum or [])
    assert "coding" in (subagent_param.enum or [])


def test_agent_tool_constants_match_manager() -> None:
    tool = AgentTool()
    assert tool.TYPE_CODING == WorkerAgentManager.TYPE_CODING
    assert tool._WORKER_TYPE_MAP["coding"] == tool.TYPE_CODING
    assert tool._WORKER_TYPE_MAP["code"] == tool.TYPE_CODING


def test_coding_tool_whitelist_filters_against_registry() -> None:
    mgr = _coding_manager()
    tools = mgr._resolve_tools_for_type(WorkerAgentManager.TYPE_CODING)
    expected_present = {
        "file_read",
        "file_edit",
        "file_write",
        "file_rollback",
        "file_diff",
        "verify",
        "glob",
        "grep",
        native_shell_tool_name(),
        "find-relevant-tools",
    }
    assert expected_present.issubset(set(tools)), (
        f"Coding whitelist missing: {expected_present - set(tools)}"
    )
    excluded = {"agent", "memory_query", "web_search", "web_fetch"}
    assert excluded.isdisjoint(set(tools)), (
        f"Coding whitelist must not include {excluded & set(tools)}"
    )


def test_coding_system_prompt_mentions_role_and_workspace(tmp_path) -> None:
    mgr = _coding_manager()
    tools = mgr._resolve_tools_for_type(WorkerAgentManager.TYPE_CODING)
    prompt = mgr._build_worker_system_prompt(
        worker_id="w1",
        subagent_type=WorkerAgentManager.TYPE_CODING,
        description="Add a max_retries argument to the connect() helper",
        selected_tools=tools,
        execution_workspace=str(tmp_path),
    )
    assert "coding worker" in prompt.lower()
    assert "Add a max_retries argument" in prompt
    assert "file_read" in prompt
    assert "verify" in prompt
    assert str(tmp_path) in prompt
    assert "confirm_destructive" in prompt
    assert "ONLY valid JSON" in prompt
    assert '"result_status"' in prompt
    assert '"artifacts"' in prompt
    assert '"verification"' in prompt


def test_coding_system_prompt_lists_only_whitelisted_tools() -> None:
    mgr = _coding_manager()
    tools = mgr._resolve_tools_for_type(WorkerAgentManager.TYPE_CODING)
    prompt = mgr._build_worker_system_prompt(
        worker_id="w2",
        subagent_type=WorkerAgentManager.TYPE_CODING,
        description="trivial",
        selected_tools=tools,
        execution_workspace=None,
    )
    assert "Only use these tools:" in prompt
    rules_line = next(
        line for line in prompt.splitlines() if line.startswith("Only use these tools:")
    )
    for t in tools:
        assert t in rules_line


def test_coding_validator_rejects_plaintext() -> None:
    mgr = WorkerAgentManager()
    plaintext = (
        "Changed: src/config.py - added max_retries argument to connect().\n"
        "verify: pass.\n"
        "Did not touch tests."
    )
    with pytest.raises(ValueError, match="valid JSON"):
        mgr._validate_worker_result(
            subagent_type=WorkerAgentManager.TYPE_CODING,
            content=plaintext,
        )


def test_coding_validator_rejects_empty() -> None:
    mgr = WorkerAgentManager()
    with pytest.raises(ValueError):
        mgr._validate_worker_result(
            subagent_type=WorkerAgentManager.TYPE_CODING,
            content="   ",
        )


def test_non_coding_validators_unchanged() -> None:
    """Plaintext to a non-Coding subagent must still be rejected as non-JSON."""
    mgr = WorkerAgentManager()
    with pytest.raises(ValueError):
        mgr._validate_worker_result(
            subagent_type=WorkerAgentManager.TYPE_GENERAL,
            content="not json",
        )


def test_general_purpose_validator_accepts_external_findings_without_path() -> None:
    mgr = WorkerAgentManager()
    result = mgr._validate_worker_result(
        subagent_type=WorkerAgentManager.TYPE_GENERAL,
        content=(
            '{"result_status":"success","summary":"ok",'
            '"findings":[{"title":"Transit option","detail":"Metro plus short walk"}],'
            '"evidence":[{"path":"https://example.com/route","detail":"route source"}],'
            '"records":[],"gaps":[],"next_steps":[],"failure_reason":null}'
        ),
    )
    assert result.findings[0].path is None


def test_general_purpose_validator_preserves_structured_records() -> None:
    mgr = WorkerAgentManager()
    result = mgr._validate_worker_result(
        subagent_type=WorkerAgentManager.TYPE_GENERAL,
        content=(
            '{"result_status":"success","summary":"inventory ready",'
            '"findings":[],"evidence":[],'
            '"records":[{"path":"C:/Inbox/a.pdf","category":"documents"}],'
            '"gaps":[],"next_steps":[],"failure_reason":null}'
        ),
    )

    assert result.records == [{"path": "C:/Inbox/a.pdf", "category": "documents"}]
    assert result.to_dict()["records"] == result.records


def test_general_purpose_validator_requires_records_field() -> None:
    mgr = WorkerAgentManager()

    with pytest.raises(ValueError, match="missing required fields"):
        mgr._validate_worker_result(
            subagent_type=WorkerAgentManager.TYPE_GENERAL,
            content=(
                '{"result_status":"success","summary":"inventory ready",'
                '"findings":[],"evidence":[],"gaps":[],"next_steps":[],'
                '"failure_reason":null}'
            ),
        )


@pytest.mark.parametrize(
    ("field_name", "value", "error_match"),
    [
        ("result_status", 1, "result_status"),
        ("summary", {"text": "inventory ready"}, "non-empty string summary"),
        ("summary", "   ", "non-empty string summary"),
    ],
)
def test_general_purpose_validator_rejects_non_string_or_empty_required_text(
    field_name: str,
    value: object,
    error_match: str,
) -> None:
    mgr = WorkerAgentManager()
    payload = {
        "result_status": "success",
        "summary": "inventory ready",
        "findings": [],
        "evidence": [],
        "records": [],
        "gaps": [],
        "next_steps": [],
        "failure_reason": None,
    }
    payload[field_name] = value

    with pytest.raises(ValueError, match=error_match):
        mgr._validate_worker_result(
            subagent_type=WorkerAgentManager.TYPE_GENERAL,
            content=json.dumps(payload),
        )


@pytest.mark.parametrize(
    ("field_name", "invalid_item", "error_match"),
    [
        ("findings", {"title": 42, "detail": "not a string title"}, "Worker finding 1"),
        ("evidence", {"path": "/tmp/a.py", "detail": True}, "Worker evidence 1"),
    ],
)
def test_general_purpose_validator_rejects_mixed_malformed_common_entries(
    field_name: str,
    invalid_item: object,
    error_match: str,
) -> None:
    mgr = WorkerAgentManager()
    payload = {
        "result_status": "success",
        "summary": "inventory ready",
        "findings": [{"title": "Inventory", "detail": "Scanned the folder"}],
        "evidence": [{"path": "/tmp", "detail": "Folder exists"}],
        "records": [],
        "gaps": [],
        "next_steps": [],
        "failure_reason": None,
    }
    assert isinstance(payload[field_name], list)
    payload[field_name].append(invalid_item)

    with pytest.raises(ValueError, match=error_match):
        mgr._validate_worker_result(
            subagent_type=WorkerAgentManager.TYPE_GENERAL,
            content=json.dumps(payload),
        )


def test_general_purpose_validator_rejects_top_level_array() -> None:
    mgr = WorkerAgentManager()

    with pytest.raises(ValueError, match="JSON object"):
        mgr._validate_worker_result(
            subagent_type=WorkerAgentManager.TYPE_GENERAL,
            content='[{"path":"C:/Inbox/a.pdf","category":"documents"}]',
        )


def test_general_purpose_validator_rejects_non_object_record() -> None:
    mgr = WorkerAgentManager()

    with pytest.raises(ValueError, match=r"records\[0\].*JSON object"):
        mgr._validate_worker_result(
            subagent_type=WorkerAgentManager.TYPE_GENERAL,
            content=(
                '{"result_status":"success","summary":"inventory ready",'
                '"findings":[],"evidence":[],"records":["a.pdf"],'
                '"gaps":[],"next_steps":[],"failure_reason":null}'
            ),
        )


def test_code_explore_validator_still_requires_path_and_reason() -> None:
    mgr = WorkerAgentManager()
    with pytest.raises(ValueError, match="CodeExplore worker finding"):
        mgr._validate_worker_result(
            subagent_type=WorkerAgentManager.TYPE_EXPLORE,
            content=(
                '{"result_status":"success","summary":"ok",'
                '"findings":[{"title":"Source fact","detail":"Needs a file path"}],'
                '"evidence":[{"path":"/tmp/source.py","detail":"source"}],'
                '"records":[],"gaps":[],"next_steps":[],"failure_reason":null}'
            ),
        )


@pytest.mark.asyncio
async def test_agent_tool_validation_accepts_coding_launch_args() -> None:
    """Public validate_parameters must accept subagent_type=Coding."""
    tool = AgentTool()
    ok, err = await tool.validate_parameters(
        {
            "action": "launch",
            "subagent_type": "Coding",
            "description": "Add max_retries arg",
            "prompt": "Edit src/config.py to add a max_retries parameter, default 3.",
        }
    )
    assert ok, f"validation rejected Coding launch: {err}"


def test_agent_tool_resolve_tools_for_coding() -> None:
    tool = AgentTool()
    tool._manager._tool_registry = _FakeRegistry(_CODING_REGISTRY_TOOLS)  # type: ignore[assignment]
    tools = tool._resolve_tools_for_type(tool.TYPE_CODING)
    assert "file_edit" in tools
    assert "verify" in tools
    assert "agent" not in tools
