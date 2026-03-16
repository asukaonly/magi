from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from dependency_injector import providers

from magi.api.routers import skills as skills_router_module
from magi.core.container import get_container
from magi.skills import service_access as skills_runtime_service
from magi.tools.context_decider import ContextDecider
from magi.tools.registry import tool_registry


def _write_skill(skill_root: Path, name: str, description: str) -> None:
    skill_dir = skill_root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "---",
                "",
                f"# {name}",
                "",
                "Do the thing.",
            ]
        ),
        encoding="utf-8",
    )


@pytest.fixture
def isolated_skills_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    container = get_container()
    original_registry_skills = dict(tool_registry._skills)
    original_registry_indexer = tool_registry._skill_indexer

    skill_root = tmp_path / "skills"
    skill_root.mkdir(parents=True, exist_ok=True)
    _write_skill(skill_root, "enabled-skill", "Enabled skill description")
    _write_skill(skill_root, "disabled-skill", "Disabled skill description")

    config_path = tmp_path / "agent.yaml"
    config_path.write_text(
        "tools:\n"
        "  skills:\n"
        "    - enabled-skill\n",
        encoding="utf-8",
    )

    from magi.skills.indexer import SkillIndexer

    monkeypatch.setattr(SkillIndexer, "SKILL_LOCATIONS", [skill_root])
    monkeypatch.setattr(skills_runtime_service, "get_config_file_path", lambda: config_path)

    tool_registry._skills = {}
    tool_registry._skill_indexer = None
    container.skill_indexer.reset_override()
    container.skill_loader.reset_override()
    container.skill_executor.reset_override()

    yield config_path, container

    tool_registry._skills = original_registry_skills
    tool_registry._skill_indexer = original_registry_indexer
    container.skill_indexer.reset_override()
    container.skill_loader.reset_override()
    container.skill_executor.reset_override()


def _bind_skills_runtime(container, bindings) -> None:
    container.skill_indexer.override(providers.Object(bindings.skill_indexer))
    container.skill_loader.override(providers.Object(bindings.skill_loader))
    container.skill_executor.override(providers.Object(bindings.skill_executor))


def test_build_skills_runtime_registers_only_enabled_skills(isolated_skills_state) -> None:
    _, container = isolated_skills_state

    bindings = skills_runtime_service.build_skills_runtime(llm_adapter=None)
    _bind_skills_runtime(container, bindings)

    assert set(tool_registry.get_skill_names()) == {"enabled-skill"}

    decider = ContextDecider(tool_registry=tool_registry, llm_adapter=None)
    prompt = decider._build_prompt(  # noqa: SLF001 - direct contract verification for routing prompt
        user_message="Use a skill",
        available_tools=decider._get_available_tools(),  # noqa: SLF001
        context={"os": "Darwin"},
    )

    assert "## Available Skills" in prompt
    assert "/enabled-skill" in prompt
    assert "/disabled-skill" not in prompt


@pytest.mark.asyncio
async def test_refresh_skills_syncs_enabled_subset_to_tool_registry(
    isolated_skills_state,
) -> None:
    config_path, container = isolated_skills_state
    bindings = skills_runtime_service.build_skills_runtime(llm_adapter=None)
    _bind_skills_runtime(container, bindings)
    assert set(tool_registry.get_skill_names()) == {"enabled-skill"}

    config_path.write_text(
        "tools:\n"
        "  skills:\n"
        "    - disabled-skill\n",
        encoding="utf-8",
    )

    await skills_router_module.refresh_skills()

    assert set(tool_registry.get_skill_names()) == {"disabled-skill"}


@pytest.mark.asyncio
async def test_list_skills_returns_503_when_module_uninitialized(monkeypatch: pytest.MonkeyPatch) -> None:
    container = get_container()
    container.skill_indexer.reset_override()

    with pytest.raises(HTTPException) as exc_info:
        await skills_router_module.list_skills()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Skills module not initialized"
