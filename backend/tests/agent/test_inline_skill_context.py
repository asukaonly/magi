from types import SimpleNamespace

import pytest

from magi.agent.task_agents.handlers.handlers import (
    _build_inline_skill_prompt,
    _inline_skill_preapproval_rules,
)
from magi.chat.task_agent.coordinator import _inline_skill_tools


def test_inline_skill_prompt_is_structured_and_hash_bound() -> None:
    request = SimpleNamespace(
        context=SimpleNamespace(
            latest_payload=SimpleNamespace(
                skill_invocation={
                    "name": "review",
                    "rendered_prompt": "Inspect the change.",
                    "content_hash": "abc123",
                }
            )
        )
    )

    prompt = _build_inline_skill_prompt(request)

    assert "Explicit Skill Context" in prompt
    assert '<skill name="review" sha256="abc123">' in prompt
    assert "Inspect the change." in prompt


def test_inline_skill_prompt_rejects_incomplete_context() -> None:
    request = SimpleNamespace(
        context=SimpleNamespace(
            latest_payload=SimpleNamespace(
                skill_invocation={"name": "review", "rendered_prompt": ""}
            )
        )
    )

    with pytest.raises(ValueError, match="incomplete"):
        _build_inline_skill_prompt(request)


def test_inline_skill_rules_separate_capability_names_from_argument_patterns() -> None:
    context = SimpleNamespace(
        latest_payload=SimpleNamespace(
            skill_invocation={
                "name": "review",
                "allowed_tools": ["read_file", "bash(git diff *)"],
            }
        )
    )
    request = SimpleNamespace(context=context)

    assert _inline_skill_tools(context) == ["read_file", "bash"]
    assert [rule.display for rule in _inline_skill_preapproval_rules(request)] == [
        "read_file",
        "bash(git diff *)",
    ]
