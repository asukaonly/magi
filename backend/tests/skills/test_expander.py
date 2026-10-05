"""Tests for skill expander."""

from pathlib import Path
from unittest.mock import MagicMock

from magi.skills.expander import expand_skill
from magi.skills.schema import SkillContent, SkillFrontmatter


def _fake_skill(prompt: str, **fm_overrides) -> SkillContent:
    fm_kwargs = {"name": "demo", "description": "Demo skill"}
    fm_kwargs.update(fm_overrides)
    fm = SkillFrontmatter(**fm_kwargs)
    return SkillContent(
        name=fm.name,
        frontmatter=fm,
        prompt_template=prompt,
        supporting_data={},
        source_file=Path("/tmp/skill.md"),
    )


def _loader_returning(skill: SkillContent | None) -> MagicMock:
    loader = MagicMock()
    loader.load_skill.return_value = skill
    return loader


def test_returns_none_when_skill_not_found():
    loader = _loader_returning(None)
    assert expand_skill(skill_name="missing", loader=loader) is None


def test_argument_substitution_and_invocation_matrix():
    for template, arguments, rendered, invocation in [
        ("Hello $0, you ran $@.", ["world"], "Hello world, you ran world.", "/demo world"),
        ("hi", [], "hi", "/demo"),
        ("got $argumentS", ["a", "b"], "got a b", "/demo a b"),
        ("count=$#", ["a", "b", "c"], "count=3", "/demo a b c"),
    ]:
        loader = _loader_returning(_fake_skill(template))
        out = expand_skill(skill_name="demo", arguments=arguments, loader=loader)
        assert out is not None
        assert (out.rendered_prompt, out.invocation_text) == (rendered, invocation)
        loader.load_skill.assert_called_once_with("demo")


def test_user_session_id_substitution():
    loader = _loader_returning(_fake_skill("user=${user_id} session=${CLAUDE_session_id}"))
    out = expand_skill(
        skill_name="demo",
        loader=loader,
        user_id="alice",
        session_id="s1",
    )
    assert out.rendered_prompt == "user=alice session=s1"


def test_propagates_metadata():
    loader = _loader_returning(
        _fake_skill(
            "x",
            argument_hint="<file>",
            allowed_tools=["read_file", "list_files"],
            context="fork",
        )
    )
    out = expand_skill(skill_name="demo", loader=loader)
    assert out.argument_hint == "<file>"
    assert out.allowed_tools == ["read_file", "list_files"]
    assert out.context_mode == "fork"
    assert out.user_invocable is True
