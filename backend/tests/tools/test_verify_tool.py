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
async def test_verify_paths_passes_for_valid_python(tmp_path: Path) -> None:
    target = tmp_path / "ok.py"
    target.write_text("x = 1\n")
    res = await VerifyTool().execute({"mode": "paths", "paths": [str(target)]}, _ctx(tmp_path))
    assert res.success, res.error
    assert len(res.data["results"]) == 1
    assert res.data["results"][0]["status"] == "pass"
    assert res.data["summary"]["pass"] == 1
    assert res.data["summary"]["fail"] == 0
    assert (
        res.data["results"][0]["content_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    )


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
async def test_verify_changed_dedupes_paths(tmp_path: Path) -> None:
    target = tmp_path / "m.py"
    target.write_text("x = 1\n")
    ctx = _ctx(tmp_path)
    await FileReadTool().execute({"path": str(target)}, ctx)
    await FileEditTool().execute(
        {"path": str(target), "old_string": "x = 1", "new_string": "x = 2"}, ctx
    )
    await FileEditTool().execute(
        {"path": str(target), "old_string": "x = 2", "new_string": "x = 3"}, ctx
    )
    res = await VerifyTool().execute({"mode": "changed"}, ctx)
    assert res.success, res.error
    relevant = [r for r in res.data["results"] if r["path"].endswith("m.py")]
    assert len(relevant) == 1


@pytest.mark.asyncio
async def test_verify_appends_to_session_log(tmp_path: Path) -> None:
    target = tmp_path / "ok.py"
    target.write_text("x = 1\n")
    ctx = _ctx(tmp_path)
    await VerifyTool().execute({"mode": "paths", "paths": [str(target)]}, ctx)
    log = tmp_path / ".magi" / "sessions" / "s1" / "verify.jsonl"
    assert log.exists()
    assert log.read_text().strip()


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
async def test_verify_unknown_extension_skipped(tmp_path: Path) -> None:
    target = tmp_path / "thing.xyz"
    target.write_text("hello")
    res = await VerifyTool().execute({"mode": "paths", "paths": [str(target)]}, _ctx(tmp_path))
    assert res.success
    assert res.data["results"][0]["status"] == "skipped"


@pytest.mark.asyncio
async def test_verify_changed_empty_session_returns_empty(tmp_path: Path) -> None:
    res = await VerifyTool().execute({"mode": "changed"}, _ctx(tmp_path))
    assert res.success, res.error
    assert res.data["results"] == []
    assert res.data["summary"]["pass"] == 0
    assert res.data["validation_status"] == "inconclusive"


@pytest.mark.asyncio
async def test_verification_identifies_the_written_content_version(tmp_path: Path) -> None:
    target = tmp_path / "created.json"
    write = await FileWriteTool().execute(
        {"path": str(target), "content": '{"ok": true}'}, _ctx(tmp_path)
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
async def test_file_changed_during_verification_is_inconclusive(
    tmp_path: Path, monkeypatch
) -> None:
    from magi.tools.builtin._verifiers import verify_file

    target = tmp_path / "changing.json"
    target.write_text('{"before": true}')

    async def changing_verifier(path, *, timeout_s):
        outcome = await verify_file(path, timeout_s=timeout_s)
        path.write_text("invalid JSON")
        return replace(outcome, status="pass")

    monkeypatch.setattr("magi.tools.builtin.verify_tool.verify_file", changing_verifier)
    result = await VerifyTool().execute({"mode": "paths", "paths": [str(target)]}, _ctx(tmp_path))
    assert result.data["results"][0]["status"] == "skipped"
    assert result.data["results"][0]["content_sha256"] is None


@pytest.mark.asyncio
async def test_verify_rejects_unknown_mode(tmp_path: Path) -> None:
    res = await VerifyTool().execute({"mode": "wat"}, _ctx(tmp_path))
    assert not res.success
    assert "mode" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_verify_paths_mode_requires_paths(tmp_path: Path) -> None:
    res = await VerifyTool().execute({"mode": "paths"}, _ctx(tmp_path))
    assert not res.success
    assert "paths" in (res.error or "").lower()


def test_verify_tool_is_registered() -> None:
    from magi.tools.builtin.verify_tool import VerifyTool as Canonical
    from magi.tools.builtin import VerifyTool as FromBuiltin
    from magi.tools import VerifyTool as FromTools
    from magi.tools.core_tools import CORE_TOOL_CLASSES

    assert FromBuiltin is Canonical
    assert FromTools is Canonical
    assert Canonical in CORE_TOOL_CLASSES
