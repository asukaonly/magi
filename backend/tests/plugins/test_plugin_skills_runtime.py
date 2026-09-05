from pathlib import Path

import pytest

from magi.plugins.skills import PluginSkillRegistry
from magi.skills.indexer import SkillIndexer
from magi.skills.loader import SkillLoader
from magi.tools.registry import ToolRegistry
from magi.agent.execution.function_calling.tools import build_tools_parameter


def test_packaged_skill_load_refresh_unload_and_owner_isolation(tmp_path):
    root = tmp_path / "plugin"
    skill = root / "skills" / "summarize"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: summarize\ndescription: Summarize notes\n---\nSummarize $ARGUMENTS.\n"
    )
    indexer = SkillIndexer(skill_locations=[tmp_path / "empty"])
    loader = SkillLoader(indexer)
    tools = ToolRegistry(skill_indexer=indexer)
    registry = PluginSkillRegistry(tools, indexer, loader)
    old = registry.register(
        "package",
        "summarize",
        Path("skills/summarize"),
        plugin_dir=root,
        connection_id="conn_a",
    )
    assert tools.is_skill("conn_a:summarize")
    assert "Summarize" in loader.load_skill("conn_a:summarize").prompt_template
    alias = build_tools_parameter(tools, ["/conn_a:summarize"])[0]["function"]["name"]
    assert ":" not in alias and len(alias) <= 64
    assert tools.resolve_tool_name(alias) == "skill_conn_a:summarize"
    tools.refresh_skills()
    assert tools.is_skill("conn_a:summarize")
    with pytest.raises(ValueError):
        registry.register("package", "summarize", skill, plugin_dir=root, connection_id="conn_a")
    old()
    assert loader.load_skill("conn_a:summarize") is None
    assert tools.resolve_tool_name(alias) == alias
    registry.register("package", "summarize", skill, plugin_dir=root, connection_id="conn_a")
    old()
    assert loader.load_skill("conn_a:summarize") is not None
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text((skill / "SKILL.md").read_text())
    with pytest.raises(ValueError, match="inside its package"):
        registry.register("package", "summarize", outside, plugin_dir=root)
