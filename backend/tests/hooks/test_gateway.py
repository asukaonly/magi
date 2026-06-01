"""Unit tests for HookGateway folding semantics."""

from __future__ import annotations

import asyncio

import pytest

from magi.hooks import (
    HookContext,
    HookDecision,
    HookEventType,
    HookGateway,
    HookOutcome,
    HookRegistry,
)


def _ctx(**kwargs) -> HookContext:
    return HookContext(event_type=HookEventType.PRE_TOOL_USE, **kwargs)


@pytest.mark.asyncio
async def test_no_handlers_returns_continue():
    gw = HookGateway(HookRegistry())
    assert (await gw.dispatch(_ctx())).outcome == HookOutcome.CONTINUE


@pytest.mark.asyncio
async def test_single_continue_handler():
    reg = HookRegistry()
    gw = HookGateway(reg)

    async def h(ctx):
        return HookDecision.cont(source="a")

    reg.register(HookEventType.PRE_TOOL_USE, h)
    decision = await gw.dispatch(_ctx())
    assert decision.outcome == HookOutcome.CONTINUE


@pytest.mark.asyncio
async def test_deny_short_circuits_subsequent_modify():
    reg = HookRegistry()
    gw = HookGateway(reg)
    side = []

    async def deny(ctx):
        return HookDecision.deny("nope", source="d")

    async def mod(ctx):
        side.append("ran")
        return HookDecision.modify(arguments={"x": 1}, source="m")

    reg.register(HookEventType.PRE_TOOL_USE, deny)
    reg.register(HookEventType.PRE_TOOL_USE, mod)
    decision = await gw.dispatch(_ctx())
    assert decision.outcome == HookOutcome.DENY
    assert decision.reason == "nope"
    # The follow-up handler is still invoked (so user policies that log
    # everything can observe the call), but its decision is discarded.
    assert side == ["ran"]


@pytest.mark.asyncio
async def test_modify_chain_is_cumulative():
    reg = HookRegistry()
    gw = HookGateway(reg)

    async def a(ctx):
        return HookDecision.modify(arguments={"a": 1})

    async def b(ctx):
        # Should see the merged arguments from the previous handler.
        assert ctx.arguments == {"a": 1}
        return HookDecision.modify(arguments={"b": 2})

    reg.register(HookEventType.PRE_TOOL_USE, a)
    reg.register(HookEventType.PRE_TOOL_USE, b)
    decision = await gw.dispatch(_ctx(arguments={}))
    assert decision.outcome == HookOutcome.MODIFY
    assert decision.modified_arguments == {"a": 1, "b": 2}


@pytest.mark.asyncio
async def test_handler_exception_does_not_crash_dispatch():
    reg = HookRegistry()
    gw = HookGateway(reg)

    async def boom(ctx):
        raise RuntimeError("kaboom")

    async def ok(ctx):
        return HookDecision.cont()

    reg.register(HookEventType.PRE_TOOL_USE, boom)
    reg.register(HookEventType.PRE_TOOL_USE, ok)
    decision = await gw.dispatch(_ctx())
    assert decision.outcome == HookOutcome.CONTINUE


@pytest.mark.asyncio
async def test_handler_timeout_degrades_to_continue():
    reg = HookRegistry()
    gw = HookGateway(reg, default_timeout_s=0.2)

    async def slow(ctx):
        await asyncio.sleep(1.0)
        return HookDecision.deny("would-deny")

    reg.register(HookEventType.PRE_TOOL_USE, slow)
    decision = await gw.dispatch(_ctx())
    assert decision.outcome == HookOutcome.CONTINUE


@pytest.mark.asyncio
async def test_matcher_filters_handlers():
    reg = HookRegistry()
    gw = HookGateway(reg)

    async def only_bash(ctx):
        return HookDecision.deny("bash-blocked")

    reg.register(HookEventType.PRE_TOOL_USE, only_bash, matcher="Bash")
    # matcher does not match -> handler skipped
    decision = await gw.dispatch(_ctx(matcher_key="echo"))
    assert decision.outcome == HookOutcome.CONTINUE
    # matcher matches -> handler runs
    decision = await gw.dispatch(_ctx(matcher_key="Bash"))
    assert decision.outcome == HookOutcome.DENY


def test_registry_rejects_sync_handler():
    reg = HookRegistry()
    with pytest.raises(TypeError):
        reg.register(HookEventType.PRE_TOOL_USE, lambda ctx: None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_inject_context_concatenates():
    reg = HookRegistry()
    gw = HookGateway(reg)

    async def a(ctx):
        return HookDecision.inject("block-A")

    async def b(ctx):
        return HookDecision.inject("block-B")

    reg.register(HookEventType.PRE_TOOL_USE, a)
    reg.register(HookEventType.PRE_TOOL_USE, b)
    decision = await gw.dispatch(_ctx())
    assert decision.outcome == HookOutcome.INJECT_CONTEXT
    assert decision.additional_context == "block-A\n\nblock-B"
