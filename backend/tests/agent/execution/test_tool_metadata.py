"""Per-invocation effects stay distinct from conservative capability exposure."""

from types import SimpleNamespace

import pytest

from magi.agent.execution.completion_gate import CompletionGate
from magi.agent.execution.completion_policy import CompletionPolicy
from magi.agent.execution.evidence import ToolExecutionEvidence
from magi.agent.execution.tool_metadata import resolve_tool_capability_metadata
from magi.tools.builtin.chat_stickers_tool import ChatStickersTool
from magi.tools.builtin.schedule_tool import ScheduleTool
from magi.tools.builtin.system_settings_tool import SystemSettingsTool
from magi.tools.schema import ToolExecutionContext


@pytest.mark.parametrize("tool_type,reads,writes", [
    (SystemSettingsTool, ["list", "get"], ["set"]),
    (ChatStickersTool, ["list"], ["save", "remove"]),
    (ScheduleTool, ["list", "get", "activity"], ["add", "update", "remove", "run"]),
])
def test_only_declared_read_actions_narrow_effects(tool_type, reads, writes):
    tool = tool_type()
    registry = SimpleNamespace(get_tool=lambda name: tool)
    name = tool.get_schema().name
    capability = resolve_tool_capability_metadata(registry, name)
    for action in reads:
        metadata = resolve_tool_capability_metadata(registry, name, arguments={"action": action})
        assert metadata.effect_class.value == metadata.replay_policy.value == "read_only"
    for arguments in [{}, {"action": []}, {"action": "unknown"}, *({"action": action} for action in writes)]:
        assert resolve_tool_capability_metadata(registry, name, arguments=arguments) == capability
    assert capability.effect_class.value != "read_only"
    assert capability.replay_policy.value == "reconcilable"


@pytest.mark.asyncio
async def test_listing_real_settings_does_not_create_a_validation_requirement():
    tool = SystemSettingsTool()
    arguments = {"action": "list"}
    result = await tool.execute(arguments, ToolExecutionContext(agent_id="test"))
    assert result.success
    metadata = resolve_tool_capability_metadata(
        SimpleNamespace(get_tool=lambda name: tool), "system-settings", arguments=arguments,
    )
    evidence = ToolExecutionEvidence(
        tool_name="system-settings", success=True, result=result.data,
        effect_class=metadata.effect_class.value, replay_policy=metadata.replay_policy.value,
    )
    decision = CompletionGate().evaluate(
        policy=CompletionPolicy(), evidence=[evidence], repair_iterations=0,
    )
    assert decision.outcome.value == "complete"
