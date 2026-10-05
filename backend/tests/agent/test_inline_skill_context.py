from types import SimpleNamespace

import pytest

from magi.agent.task_agents.handlers.handlers import (
    _build_inline_skill_prompt,
    _inline_skill_preapproval_rules,
)
from magi.chat.task_agent.coordinator import _inline_skill_tools


@pytest.mark.asyncio
@pytest.mark.parametrize("template", ["Inspect the change $0.", "Audit the change $0."])
async def test_inline_skill_prompt_renders_trusted_expansion_and_template_digest(
    tmp_path, monkeypatch, template
):
    import hashlib
    from unittest.mock import AsyncMock
    from magi.api.routers import messages_dispatch
    from magi.api.routers.messages_models import UserMessageRequest
    from magi.skills.expander import expand_skill
    from magi.skills.schema import SkillContent, SkillFrontmatter

    skill = SkillContent(
        name="review",
        frontmatter=SkillFrontmatter(name="review", description="Review changes"),
        prompt_template=template,
        supporting_data={},
        source_file=tmp_path / "SKILL.md",
    )
    loader = SimpleNamespace(load_skill=lambda name: skill if name == "review" else None)
    monkeypatch.setattr(
        messages_dispatch, "expand_skill", lambda **kwargs: expand_skill(**kwargs, loader=loader)
    )
    monkeypatch.setattr(messages_dispatch, "get_enabled_skill_names", lambda: {"review"})
    monkeypatch.setattr(
        messages_dispatch, "build_bootstrap_l2_priority_metadata", AsyncMock(return_value={})
    )
    dispatch = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            handled_as="queued",
            session_id="session-1",
            turn_id="turn-1",
            message_id="message-1",
            queue_size=1,
        )
    )
    monkeypatch.setattr(messages_dispatch, "dispatch_user_message", dispatch)
    await messages_dispatch._dispatch_api_user_message(
        UserMessageRequest(
            session_id="session-1",
            message="Untrusted frontend prompt",
            skill_invocation={"name": "review", "arguments": ["123"]},
        )
    )
    dispatch.assert_awaited_once()
    invocation = dispatch.await_args.kwargs["metadata"]["skill_invocation"]
    digest = hashlib.sha256(template.encode()).hexdigest()
    assert invocation["content_hash"] == digest
    assert invocation["rendered_prompt"] == template.replace("$0", "123")
    request = SimpleNamespace(
        context=SimpleNamespace(latest_payload=SimpleNamespace(skill_invocation=invocation))
    )
    prompt = _build_inline_skill_prompt(request)
    assert f'<skill name="review" sha256="{digest}">' in prompt
    assert template.replace("$0", "123") in prompt
    assert "Untrusted frontend prompt" not in prompt


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
