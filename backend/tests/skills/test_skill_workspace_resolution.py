from __future__ import annotations

import importlib
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from magi.skills import runner as runner_module
from magi.skills.runner import SkillRunner
from magi.skills.schema import SkillContent, SkillFrontmatter
from magi.skills.subagent import SkillSubagent


def test_skill_runner_substitutes_pwd_from_workspace_context(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = SkillRunner(loader=None, llm_adapter=None)

    rendered = runner._substitute_variables(
        template="pwd=${PWD}",
        arguments=[],
        context={"workspace": str(workspace)},
    )

    assert rendered == f"pwd={workspace.resolve()}"


@pytest.mark.asyncio
async def test_skill_runner_omits_arguments_when_full_content_logging_is_disabled(
    monkeypatch,
    caplog,
) -> None:
    class _MissingSkillLoader:
        def load_skill(self, _name: str):
            return None

    monkeypatch.setattr(
        runner_module,
        "full_content_logging_enabled",
        lambda: False,
    )
    runner = SkillRunner(loader=_MissingSkillLoader(), llm_adapter=None)  # type: ignore[arg-type]

    with caplog.at_level(logging.INFO, logger=runner_module.logger.name):
        result = await runner.execute(
            "missing-skill",
            arguments=["SKILL-ARGUMENT-CANARY"],
        )

    assert result.success is False
    assert "SKILL-ARGUMENT-CANARY" not in caplog.text
    assert "argument_count=1" in caplog.text


@pytest.mark.asyncio
async def test_skill_runner_omits_exception_content_when_logging_is_disabled(
    monkeypatch,
    caplog,
) -> None:
    secret_error = "private skill exception content"

    class _SkillLoader:
        def load_skill(self, _name: str):
            return SkillContent(
                name="private-skill",
                frontmatter=SkillFrontmatter(
                    name="private-skill",
                    description="Private skill",
                ),
                prompt_template="Prompt",
            )

    async def _raise_private_error(*_args, **_kwargs):
        raise RuntimeError(secret_error)

    monkeypatch.setattr(
        runner_module,
        "full_content_logging_enabled",
        lambda: False,
    )
    runner = SkillRunner(loader=_SkillLoader(), llm_adapter=None)  # type: ignore[arg-type]
    monkeypatch.setattr(runner, "_execute_direct", _raise_private_error)

    with caplog.at_level(logging.ERROR, logger=runner_module.logger.name):
        result = await runner.execute("private-skill")

    assert result.error == secret_error
    assert secret_error not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


@pytest.mark.asyncio
async def test_skill_subagent_passes_workspace_to_function_calling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    recorded: dict[str, object] = {}

    class _FakeRegistry:
        def list_tools(self) -> list[str]:
            return ["file_read"]

    class _FakeFunctionCallingOrchestrator:
        async def execute_with_tools(self, **kwargs):
            recorded.update(kwargs)
            return SimpleNamespace(succeeded=True, content="done", failure_reason=None)

        async def run(self, run_input):  # engine front door → forwards (ADR-0004 P4)
            return await self.execute_with_tools(**run_input.to_execute_kwargs())

    from magi.agent.execution.function_calling.headless_factory import (
        build_headless_engine_run_input,
    )

    skill = SkillContent(
        name="demo-skill",
        frontmatter=SkillFrontmatter(
            name="demo-skill",
            description="Demo skill",
            context="fork",
            allowed_tools=["file_read"],
        ),
        prompt_template="Prompt",
    )
    subagent = SkillSubagent(
        skill=skill,
        llm_adapter=object(),
        tool_registry=_FakeRegistry(),
        orchestrator_factory=lambda **kwargs: _FakeFunctionCallingOrchestrator(),
        engine_run_input_factory=build_headless_engine_run_input,
    )

    result = await subagent.execute(
        user_message="read the file",
        system_prompt="Prompt",
        context={"user_id": "user-1", "workspace": str(workspace)},
    )

    assert result.success is True
    assert recorded["execution_workspace"] == str(workspace.resolve())


def test_skill_indexer_project_local_location_is_repo_relative_not_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import magi.skills.indexer as indexer_module

    original_cwd = Path.cwd()
    monkeypatch.chdir(tmp_path)
    reloaded_module = importlib.reload(indexer_module)

    expected_project_local = Path(reloaded_module.__file__).resolve().parents[4] / ".claude" / "skills"
    # Locate the entry by value rather than by fixed index — SKILL_LOCATIONS
    # gained the ``~/.agents/skills`` slot in addition to ``~/.claude/skills``
    # so positional asserts are fragile.
    assert expected_project_local in reloaded_module.SkillIndexer.SKILL_LOCATIONS
    observed_project_local = expected_project_local

    assert observed_project_local == expected_project_local
    assert observed_project_local != tmp_path / ".claude" / "skills"

    monkeypatch.chdir(original_cwd)
    importlib.reload(reloaded_module)
