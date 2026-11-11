"""Integration tests for the verify tool."""

from __future__ import annotations

from pathlib import Path
import hashlib
from dataclasses import replace

import pytest

from magi.tools.builtin.file_edit_tool import FileEditTool
from magi.tools.builtin.file_read_tool import FileReadTool
from magi.tools.builtin.file_write_tool import FileWriteTool
from magi.tools.builtin.verify_tool import VerifyTool
from magi.tools.schema import ToolExecutionContext
from magi.agent.execution.completion_gate import CompletionGate
from magi.agent.execution.completion_policy import CompletionPolicy
from magi.agent.execution.contracts import CompletionOutcome
from magi.agent.execution.evidence import ToolExecutionEvidence


def _ctx(workspace: Path, session_id: str | None = "s1") -> ToolExecutionContext:
    env_vars = {"session_id": session_id} if session_id else {}
    return ToolExecutionContext(agent_id="a", workspace=str(workspace), env_vars=env_vars)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename,content,status,verifier",
    [
        ("ok.py", "x = 1\n", "pass", "python.compile"),
        ("unknown.xyz", "unrecognized", "skipped", "(none)"),
    ],
)
async def test_verify_dispatch_reports_exact_path_digest_and_summary(
    tmp_path, filename, content, status, verifier
):
    target = tmp_path / filename
    target.write_text(content)
    result = await VerifyTool().execute({"mode": "paths", "paths": [str(target)]}, _ctx(tmp_path))
    assert result.success
    assert len(result.data["results"]) == 1
    outcome = result.data["results"][0]
    assert Path(outcome["path"]) == target
    assert outcome["status"] == status
    assert outcome["verifier"] == verifier
    assert result.data["summary"] == {
        key: int(key == status) for key in ["pass", "fail", "skipped", "timeout"]
    }
    assert outcome["content_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()


@pytest.mark.asyncio
async def test_verify_paths_reports_failure_for_invalid_python(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    target.write_text("def broken(:\n  pass\n")
    res = await VerifyTool().execute({"mode": "paths", "paths": [str(target)]}, _ctx(tmp_path))
    assert res.success
    assert res.data["results"][0]["status"] == "fail"
    assert res.data["summary"]["fail"] == 1


@pytest.mark.asyncio
async def test_verify_changed_picks_up_session_edits(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_text("x = 1\n")
    ctx = _ctx(tmp_path)
    await FileReadTool().execute({"path": str(target)}, ctx)
    await FileEditTool().execute(
        {"path": str(target), "old_string": "x = 1", "new_string": "x = 2"}, ctx
    )
    res = await VerifyTool().execute({"mode": "changed"}, ctx)
    assert res.success, res.error
    paths = [r["path"] for r in res.data["results"]]
    assert any(p.endswith("module.py") for p in paths)
    assert res.data["summary"]["pass"] >= 1


@pytest.mark.asyncio
async def test_verify_changed_deduplicates_multiple_successful_edits(tmp_path):
    from magi_plugin_sdk.workspace_cache import resolve_session_cache

    target = tmp_path / "m.py"
    target.write_text("x = 1\n")
    context = _ctx(tmp_path)
    for before, after in [(1, 2), (2, 3)]:
        assert (await FileReadTool().execute({"path": str(target)}, context)).success
        edited = await FileEditTool().execute(
            {"path": str(target), "old_string": f"x = {before}", "new_string": f"x = {after}"},
            context,
        )
        assert edited.success, edited.error
    assert [row.path for row in resolve_session_cache(tmp_path, "s1").iter_edits()] == [
        "m.py",
        "m.py",
    ]
    assert target.read_text() == "x = 3\n"
    result = await VerifyTool().execute({"mode": "changed"}, context)
    assert result.success
    assert [Path(row["path"]) for row in result.data["results"]] == [target]
    assert result.data["results"][0]["content_sha256"] == hashlib.sha256(b"x = 3\n").hexdigest()


@pytest.mark.asyncio
async def test_verification_log_appends_exact_results_for_each_content_version(tmp_path):
    import json

    target = tmp_path / "content.json"
    context = _ctx(tmp_path)
    expected = []
    for content, status in [('{"ok":true}', "pass"), ("{broken", "fail")]:
        target.write_text(content)
        result = await VerifyTool().execute({"mode": "paths", "paths": [str(target)]}, context)
        assert result.success
        outcome = result.data["results"][0]
        assert Path(outcome["path"]) == target
        assert outcome["status"] == status
        assert outcome["verifier"] == "json.loads"
        assert outcome["content_sha256"] == hashlib.sha256(content.encode()).hexdigest()
        expected.append(outcome)
    log = tmp_path / ".magi" / "sessions" / "s1" / "verify.jsonl"
    assert [json.loads(line) for line in log.read_text().splitlines()] == expected


@pytest.mark.asyncio
async def test_verify_no_session_id_does_not_log(tmp_path: Path) -> None:
    target = tmp_path / "ok.py"
    target.write_text("x = 1\n")
    res = await VerifyTool().execute(
        {"mode": "paths", "paths": [str(target)]},
        _ctx(tmp_path, session_id=None),
    )
    assert res.success, res.error
    assert res.data["results"][0]["status"] == "pass"
    cache_dir = tmp_path / ".magi" / "sessions"
    if cache_dir.exists():
        assert not any((d / "verify.jsonl").exists() for d in cache_dir.iterdir())


@pytest.mark.asyncio
async def test_verify_outside_workspace_skipped(tmp_path: Path) -> None:
    inside = tmp_path / "ws"
    inside.mkdir()
    outside = tmp_path / "other.py"
    outside.write_text("x = 1\n")
    res = await VerifyTool().execute({"mode": "paths", "paths": [str(outside)]}, _ctx(inside))
    assert res.success, res.error
    assert res.data["results"][0]["status"] == "skipped"
    assert "outside" in (res.data["results"][0]["reason"] or "").lower()


@pytest.mark.asyncio
async def test_verify_changed_empty_session_returns_empty(tmp_path: Path) -> None:
    res = await VerifyTool().execute({"mode": "changed"}, _ctx(tmp_path))
    assert res.success, res.error
    assert res.data["results"] == []
    assert res.data["summary"]["pass"] == 0
    assert res.data["validation_status"] == "inconclusive"


@pytest.mark.asyncio
@pytest.mark.parametrize("filename,content", [
    ("created.json", '{"ok": true}'),
    ("draft.md", "# Draft\nComplete text.\n"),
    ("note.txt", "Complete text.\n"),
    ("config.yaml", "enabled: true\n"),
    ("data.csv", "name,value\nexample,1\n"),
])
async def test_verification_identifies_the_written_content_version(tmp_path: Path, filename, content) -> None:
    target = tmp_path / filename
    write = await FileWriteTool().execute(
        {"path": str(target), "content": content}, _ctx(tmp_path)
    )
    verify = await VerifyTool().execute({"mode": "paths", "paths": [str(target)]}, _ctx(tmp_path))
    assert write.success and verify.success
    assert write.data["validation_targets"] == [
        {
            "path": verify.data["results"][0]["path"],
            "content_sha256": verify.data["results"][0]["content_sha256"],
        }
    ]
    evidence = []
    for tool, result in ((FileWriteTool(), write), (VerifyTool(), verify)):
        schema = tool.get_schema()
        evidence.append(
            ToolExecutionEvidence(
                tool_name=schema.name,
                success=result.success,
                effect_class=schema.effect_class,
                replay_policy=schema.effect_replay_policy,
                result=result.data,
            )
        )
    decision = CompletionGate().evaluate(
        policy=CompletionPolicy(), evidence=evidence, repair_iterations=0
    )
    assert decision.outcome is CompletionOutcome.COMPLETE


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["changing.json", "changing.md"])
async def test_file_changed_during_verification_is_inconclusive(
    tmp_path: Path, monkeypatch, filename
) -> None:
    from magi.tools.builtin._verifiers import verify_file

    target = tmp_path / filename
    target.write_text('{"before": true}')

    async def changing_verifier(path, *, timeout_s):
        outcome = await verify_file(path, timeout_s=timeout_s)
        path.write_text("invalid JSON")
        return replace(outcome, status="pass")

    monkeypatch.setattr("magi.tools.builtin.verify_tool.verify_file", changing_verifier)
    result = await VerifyTool().execute({"mode": "paths", "paths": [str(target)]}, _ctx(tmp_path))
    assert result.data["results"][0]["status"] == "skipped"
    assert result.data["results"][0]["content_sha256"] is None


@pytest.mark.parametrize(
    "expected_error_field,mode_value",
    [
        pytest.param("mode", "wat", id="verify_rejects_unknown_mode"),
        pytest.param("paths", "paths", id="verify_paths_mode_requires_paths"),
    ],
)
@pytest.mark.asyncio
async def test_verify_rejects_invalid_mode_or_missing_paths(
    tmp_path: Path, expected_error_field, mode_value
) -> None:
    res = await VerifyTool().execute({"mode": mode_value}, _ctx(tmp_path))
    assert not res.success
    assert expected_error_field in (res.error or "").lower()


def _tool_evidence(tool, result):
    schema = tool.get_schema()
    return ToolExecutionEvidence(
        tool_name=schema.name, success=result.success, effect_class=schema.effect_class,
        replay_policy=schema.effect_replay_policy, result=result.data,
    )


@pytest.mark.asyncio
async def test_explicit_absence_verifies_deletion_and_retires_previous_content(tmp_path):
    path = tmp_path / "draft.json"
    context = _ctx(tmp_path)
    write_tool, verify_tool = FileWriteTool(), VerifyTool()
    write = await write_tool.execute({"path": str(path), "content": "{broken"}, context)
    failed = await verify_tool.execute({"mode": "paths", "paths": [str(path)]}, context)
    path.unlink()
    missing = await verify_tool.execute({"mode": "paths", "paths": [str(path)]}, context)
    absent = await verify_tool.execute(
        {"mode": "paths", "paths": [str(path)], "expected_state": "absent"}, context
    )
    assert missing.data["results"][0]["status"] == "skipped"
    assert absent.data["results"][0]["status"] == "pass"
    evidence = [_tool_evidence(write_tool, write), _tool_evidence(verify_tool, failed)]
    deletion = ToolExecutionEvidence(
        tool_name="bash", success=True, effect_class="unknown", replay_policy="unknown",
        result={"return_code": 0, "command_succeeded": True, "timed_out": False},
    )
    gate = CompletionGate()
    assert gate.evaluate(
        policy=CompletionPolicy(), evidence=[*evidence, _tool_evidence(verify_tool, absent)], repair_iterations=0
    ).reason_code == "validation_required"
    assert gate.evaluate(
        policy=CompletionPolicy(),
        evidence=[*evidence, deletion, _tool_evidence(verify_tool, missing), _tool_evidence(verify_tool, absent)],
        repair_iterations=0,
    ).outcome is CompletionOutcome.COMPLETE
    path.write_text("new content")
    present = await verify_tool.execute(
        {"mode": "paths", "paths": [str(path)], "expected_state": "absent"}, context
    )
    assert present.data["results"][0]["status"] == "fail"


@pytest.mark.asyncio
async def test_absence_requires_explicit_paths_and_does_not_accept_dangling_symlink(tmp_path):
    tool = VerifyTool()
    invalid = await tool.execute({"expected_state": "absent"}, _ctx(tmp_path))
    assert not invalid.success
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "missing")
    result = await tool.execute(
        {"mode": "paths", "paths": [str(link)], "expected_state": "absent"}, _ctx(tmp_path)
    )
    assert result.data["results"][0]["status"] == "fail"
    assert result.data["results"][0]["path"] == str(link)


@pytest.mark.asyncio
async def test_shell_written_invalid_file_remains_blocked_after_successful_command_exit(tmp_path):
    import sys
    from magi.tools.builtin.bash_tool import BashTool

    if sys.platform == "win32":
        pytest.skip("Bash is the native POSIX shell")
    context = _ctx(tmp_path)
    shell, verify = BashTool(), VerifyTool()
    changed = await shell.execute({"command": "printf 'def broken(:\\n' > broken.py"}, context)
    checked = await verify.execute({"mode": "paths", "paths": ["broken.py"]}, context)
    assert changed.success
    assert changed.data["return_code"] == 0
    assert checked.data["summary"]["fail"] == 1
    assert CompletionGate().evaluate(
        policy=CompletionPolicy(), evidence=[_tool_evidence(shell, changed), _tool_evidence(verify, checked)],
        repair_iterations=0,
    ).reason_code == "validation_failed"
