import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from magi.personality import outreach_compose as oc


def _fallback_for(kind: str) -> str:
    return oc._fallback_template(kind=kind, title="Find flights", facts="3 options")


@pytest.mark.asyncio
async def test_fallback_when_persona_missing():
    with patch.object(oc, "resolve_persona_config", AsyncMock(return_value=None)):
        out = await oc.compose_outreach_line(
            kind="task_completed", title="Find flights", facts="3 options", persona_name=None,
        )
    assert out == _fallback_for("task_completed")


@pytest.mark.asyncio
async def test_fallback_when_llm_raises():
    cfg = MagicMock()
    cfg.name = "Magi"; cfg.description = "your agent"
    cfg.identity_core.identity_statement = "I help you."
    with patch.object(oc, "resolve_persona_config", AsyncMock(return_value=cfg)), \
         patch.object(oc, "get_scenario_llm_pool", side_effect=RuntimeError("no pool")):
        out = await oc.compose_outreach_line(
            kind="task_failed", title="Find flights", facts="rate limited", persona_name="Magi",
        )
    assert out == oc._fallback_template(kind="task_failed", title="Find flights", facts="rate limited")


@pytest.mark.asyncio
async def test_uses_llm_output_when_available():
    cfg = MagicMock()
    cfg.name = "Magi"; cfg.description = "your agent"
    cfg.identity_core.identity_statement = "I help you."
    bridge = MagicMock()
    bridge.chat = AsyncMock(return_value="  搞定了你让我查的机票，3 个都在 $400 以内。 ")
    pool = MagicMock()
    pool.get = MagicMock(return_value=MagicMock())
    with patch.object(oc, "resolve_persona_config", AsyncMock(return_value=cfg)), \
         patch.object(oc, "get_scenario_llm_pool", return_value=pool), \
         patch.object(oc, "LLMProviderBridge", return_value=bridge):
        out = await oc.compose_outreach_line(
            kind="task_completed", title="机票", facts="3 个 < $400", persona_name="Magi",
        )
    assert out == "搞定了你让我查的机票，3 个都在 $400 以内。"
    assert bridge.chat.await_count == 1
