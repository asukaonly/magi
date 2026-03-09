from __future__ import annotations

from pathlib import Path

import pytest

from magi.api.routers import skills as skills_router_module
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
    original_registry_skills = dict(tool_registry._skills)
    original_registry_indexer = tool_registry._skill_indexer
    original_router_indexer = skills_router_module._skill_indexer
    original_router_loader = skills_router_module._skill_loader
    original_router_executor = skills_router_module._skill_executor

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
    monkeypatch.setattr(skills_router_module, "get_config_file_path", lambda: config_path)

    tool_registry._skills = {}
    tool_registry._skill_indexer = None
    skills_router_module._skill_indexer = None
    skills_router_module._skill_loader = None
    skills_router_module._skill_executor = None

    yield config_path

    tool_registry._skills = original_registry_skills
    tool_registry._skill_indexer = original_registry_indexer
    skills_router_module._skill_indexer = original_router_indexer
    skills_router_module._skill_loader = original_router_loader
    skills_router_module._skill_executor = original_router_executor


def test_init_skills_module_registers_only_enabled_skills(isolated_skills_state: Path) -> None:
    _ = isolated_skills_state

    skills_router_module.init_skills_module(llm_adapter=None)

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
    isolated_skills_state: Path,
) -> None:
    config_path = isolated_skills_state
    skills_router_module.init_skills_module(llm_adapter=None)
    assert set(tool_registry.get_skill_names()) == {"enabled-skill"}

    config_path.write_text(
        "tools:\n"
        "  skills:\n"
        "    - disabled-skill\n",
        encoding="utf-8",
    )

    await skills_router_module.refresh_skills()

    assert set(tool_registry.get_skill_names()) == {"disabled-skill"}
