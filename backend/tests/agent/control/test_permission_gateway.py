"""Gateway three-tier × four-risk decision matrix plus rule flow."""

from __future__ import annotations

from typing import Any

import pytest

from magi.control.common import InteractionBroker
from magi.control.permission.classifier import RiskClassifier
from magi.control.permission.contracts import (
    PermissionOutcome,
    PermissionRule,
    PermissionScope,
    ToolOrigin,
)
from magi.control.permission.gateway import (
    PermissionGateway,
    UserPromptResponse,
)
from magi.control.permission.rules import PermissionRuleStore
from magi.control.settings import (
    ControlSettings,
    PermissionMode,
    SessionControlOverride,
)


class _StubPrompter:
    """Deterministic prompter for gateway tests."""

    def __init__(self, response: UserPromptResponse) -> None:
        self._response = response
        self.calls: list[Any] = []

    async def __call__(self, request, *, timeout_seconds):
        self.calls.append(request)
        return self._response


async def _make_gateway(
    *,
    mode: PermissionMode = PermissionMode.HIGH_ONLY,
    prompter: _StubPrompter | None = None,
    db_path: str | None = None,
) -> tuple[PermissionGateway, PermissionRuleStore]:
    rules = PermissionRuleStore(db_path=db_path)
    await rules.initialize()
    settings = ControlSettings(permission_mode=mode)
    gateway = PermissionGateway(
        classifier=RiskClassifier(),
        rules=rules,
        broker=InteractionBroker(),
        settings_provider=lambda: settings,
        session_override_provider=lambda _sid: None,
        prompter=prompter,
        prompt_timeout_seconds=5.0,
    )
    return gateway, rules


# ---------------------------------------------------------------------------
# Mode × risk matrix — no user prompter; auto-allowed cases.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_off_mode_allows_destructive_without_prompt() -> None:
    prompter = _StubPrompter(UserPromptResponse(allow=False))
    gateway, _ = await _make_gateway(mode=PermissionMode.OFF, prompter=prompter)
    decision = await gateway.gate(
        tool_name="bash",
        arguments={"command": "rm -rf ./build"},
        agent_id="a1",
    )
    assert decision.outcome is PermissionOutcome.ALLOWED
    assert decision.source == "auto"
    assert prompter.calls == []


@pytest.mark.asyncio
async def test_off_mode_still_blocks_kill_list() -> None:
    prompter = _StubPrompter(UserPromptResponse(allow=True))
    gateway, _ = await _make_gateway(mode=PermissionMode.OFF, prompter=prompter)
    decision = await gateway.gate(
        tool_name="bash",
        arguments={"command": "rm -rf /"},
        agent_id="a1",
    )
    assert decision.outcome is PermissionOutcome.KILL_LISTED
    assert decision.source.startswith("kill_list:")
    assert prompter.calls == []


@pytest.mark.asyncio
async def test_off_mode_blocks_powershell_root_alias_bypass() -> None:
    prompter = _StubPrompter(UserPromptResponse(allow=True))
    gateway, _ = await _make_gateway(mode=PermissionMode.OFF, prompter=prompter)

    decision = await gateway.gate(
        tool_name="powershell",
        arguments={"command": "ri C:\\* -r -fo"},
        agent_id="a1",
    )

    assert decision.outcome is PermissionOutcome.KILL_LISTED
    assert decision.source == "kill_list:remove_item_root"
    assert prompter.calls == []


@pytest.mark.asyncio
async def test_high_only_lets_low_risk_through_silently() -> None:
    prompter = _StubPrompter(UserPromptResponse(allow=False))
    gateway, _ = await _make_gateway(mode=PermissionMode.HIGH_ONLY, prompter=prompter)
    decision = await gateway.gate(
        tool_name="bash",
        arguments={"command": "ls -la"},
        agent_id="a1",
    )
    assert decision.outcome is PermissionOutcome.ALLOWED
    assert decision.source == "auto"
    assert prompter.calls == []


@pytest.mark.asyncio
async def test_high_only_prompts_on_high_risk() -> None:
    prompter = _StubPrompter(UserPromptResponse(allow=True))
    gateway, _ = await _make_gateway(mode=PermissionMode.HIGH_ONLY, prompter=prompter)
    decision = await gateway.gate(
        tool_name="bash",
        arguments={"command": "npm install react"},
        agent_id="a1",
    )
    assert decision.outcome is PermissionOutcome.ALLOWED
    assert decision.source == "user"
    assert len(prompter.calls) == 1


@pytest.mark.asyncio
async def test_high_only_prompts_for_unknown_powershell_command() -> None:
    prompter = _StubPrompter(UserPromptResponse(allow=True))
    gateway, _ = await _make_gateway(mode=PermissionMode.HIGH_ONLY, prompter=prompter)

    decision = await gateway.gate(
        tool_name="powershell",
        arguments={"command": "Some-CustomCommand -DoSomething"},
        agent_id="a1",
    )

    assert decision.outcome is PermissionOutcome.ALLOWED
    assert decision.source == "user"
    assert len(prompter.calls) == 1
    assert prompter.calls[0].risk_level.value == "high"


@pytest.mark.asyncio
async def test_high_only_prompts_for_file_read_outside_workspace(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    prompter = _StubPrompter(UserPromptResponse(allow=True))
    gateway, _ = await _make_gateway(mode=PermissionMode.HIGH_ONLY, prompter=prompter)

    decision = await gateway.gate(
        tool_name="file_read",
        arguments={"path": str(outside)},
        agent_id="a1",
        workspace=str(workspace),
    )

    assert decision.outcome is PermissionOutcome.ALLOWED
    assert decision.source == "user"
    assert len(prompter.calls) == 1
    assert prompter.calls[0].risk_level.value == "high"
    assert "outside_workspace" in prompter.calls[0].signals


@pytest.mark.asyncio
async def test_high_only_skips_medium_risk() -> None:
    prompter = _StubPrompter(UserPromptResponse(allow=False))
    gateway, _ = await _make_gateway(mode=PermissionMode.HIGH_ONLY, prompter=prompter)
    decision = await gateway.gate(
        tool_name="web_fetch",
        arguments={"url": "https://example.com"},
        agent_id="a1",
    )
    assert decision.outcome is PermissionOutcome.ALLOWED
    assert decision.source == "auto"


@pytest.mark.asyncio
async def test_all_mode_prompts_on_medium_risk() -> None:
    prompter = _StubPrompter(UserPromptResponse(allow=True))
    gateway, _ = await _make_gateway(mode=PermissionMode.ALL, prompter=prompter)
    decision = await gateway.gate(
        tool_name="web_fetch",
        arguments={"url": "https://example.com"},
        agent_id="a1",
    )
    assert decision.outcome is PermissionOutcome.ALLOWED
    assert decision.source == "user"


@pytest.mark.asyncio
async def test_all_mode_does_not_prompt_low_risk() -> None:
    prompter = _StubPrompter(UserPromptResponse(allow=False))
    gateway, _ = await _make_gateway(mode=PermissionMode.ALL, prompter=prompter)
    decision = await gateway.gate(
        tool_name="bash",
        arguments={"command": "echo hi"},
        agent_id="a1",
    )
    assert decision.outcome is PermissionOutcome.ALLOWED
    assert decision.source == "auto"
    assert prompter.calls == []


@pytest.mark.asyncio
async def test_missing_prompter_fails_closed() -> None:
    gateway, _ = await _make_gateway(
        mode=PermissionMode.HIGH_ONLY, prompter=None
    )
    decision = await gateway.gate(
        tool_name="bash",
        arguments={"command": "rm -rf ./build"},
        agent_id="a1",
    )
    assert decision.outcome is PermissionOutcome.DENIED
    assert decision.source == "no_prompter"


# ---------------------------------------------------------------------------
# Rule flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_rule_short_circuits_future_calls() -> None:
    prompter = _StubPrompter(
        UserPromptResponse(
            allow=True,
            scope=PermissionScope.SESSION,
        )
    )
    gateway, rules = await _make_gateway(
        mode=PermissionMode.HIGH_ONLY, prompter=prompter
    )
    first = await gateway.gate(
        tool_name="bash",
        arguments={"command": "npm install react"},
        agent_id="a1",
        session_id="s1",
    )
    assert first.outcome is PermissionOutcome.ALLOWED
    assert first.recorded_rule is not None

    second = await gateway.gate(
        tool_name="bash",
        arguments={"command": "npm install react"},
        agent_id="a1",
        session_id="s1",
    )
    assert second.outcome is PermissionOutcome.ALLOWED
    assert second.source.startswith("rule:")
    # Only the first call prompted the user.
    assert len(prompter.calls) == 1
    assert rules.list_rules(session_id="s1")


@pytest.mark.asyncio
async def test_persistent_pattern_rule_matches_glob() -> None:
    prompter = _StubPrompter(UserPromptResponse(allow=False))
    gateway, rules = await _make_gateway(
        mode=PermissionMode.HIGH_ONLY, prompter=prompter
    )
    await rules.add(
        PermissionRule(
            rule_id="r-npm",
            tool_name="bash",
            scope=PermissionScope.PERSISTENT_PATTERN,
            matcher={"command": "npm install *"},
            allow=True,
            note="auto-approve npm install",
        )
    )
    decision = await gateway.gate(
        tool_name="bash",
        arguments={"command": "npm install typescript"},
        agent_id="a1",
    )
    assert decision.outcome is PermissionOutcome.ALLOWED
    assert decision.source == "rule:r-npm"
    assert prompter.calls == []


@pytest.mark.asyncio
async def test_session_override_can_promote_to_off() -> None:
    rules = PermissionRuleStore(db_path=None)
    await rules.initialize()
    base = ControlSettings(permission_mode=PermissionMode.HIGH_ONLY)
    override = SessionControlOverride(permission_mode=PermissionMode.OFF)
    gateway = PermissionGateway(
        classifier=RiskClassifier(),
        rules=rules,
        broker=InteractionBroker(),
        settings_provider=lambda: base,
        session_override_provider=lambda sid: override if sid == "yolo" else None,
        prompter=_StubPrompter(UserPromptResponse(allow=False)),
        prompt_timeout_seconds=1.0,
    )
    decision = await gateway.gate(
        tool_name="bash",
        arguments={"command": "rm -rf ./build"},
        agent_id="a1",
        session_id="yolo",
    )
    assert decision.outcome is PermissionOutcome.ALLOWED
    assert decision.source == "auto"


@pytest.mark.asyncio
async def test_timeout_denies() -> None:
    class _TimeoutPrompter:
        async def __call__(self, request, *, timeout_seconds):
            from magi.control.common import InteractionTimeoutError
            raise InteractionTimeoutError(request.request_id, kind="permission")

    rules = PermissionRuleStore(db_path=None)
    await rules.initialize()
    gateway = PermissionGateway(
        classifier=RiskClassifier(),
        rules=rules,
        broker=InteractionBroker(),
        settings_provider=lambda: ControlSettings(
            permission_mode=PermissionMode.HIGH_ONLY
        ),
        prompter=_TimeoutPrompter(),
        prompt_timeout_seconds=0.5,
    )
    decision = await gateway.gate(
        tool_name="bash",
        arguments={"command": "rm -rf ./x"},
        agent_id="a1",
    )
    assert decision.outcome is PermissionOutcome.TIMED_OUT
    assert decision.source == "timeout"


@pytest.mark.asyncio
async def test_origin_passthrough_tagged_on_request() -> None:
    captured: list = []

    class _Capture:
        async def __call__(self, request, *, timeout_seconds):
            captured.append(request)
            return UserPromptResponse(allow=True)

    rules = PermissionRuleStore(db_path=None)
    await rules.initialize()
    gateway = PermissionGateway(
        classifier=RiskClassifier(),
        rules=rules,
        broker=InteractionBroker(),
        settings_provider=lambda: ControlSettings(
            permission_mode=PermissionMode.HIGH_ONLY
        ),
        prompter=_Capture(),
    )
    await gateway.gate(
        tool_name="bash",
        arguments={"command": "npm install x"},
        agent_id="a1",
        origin=ToolOrigin.SUBAGENT,
    )
    assert captured
    assert captured[0].origin is ToolOrigin.SUBAGENT
