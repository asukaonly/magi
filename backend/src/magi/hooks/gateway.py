"""Hook dispatch gateway: collect handler decisions and fold to one outcome."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import List, Optional

from .contracts import HookContext, HookDecision, HookOutcome
from .registry import HookRegistry

logger = logging.getLogger(__name__)


class HookGateway:
    """Dispatch hooks for an event and fold handler results.

    Folding rules (locked-in semantics, not handler-configurable):

    1. Any ``DENY`` short-circuits — the first ``DENY`` wins, remaining
       handlers are still awaited but their decisions are discarded so
       handlers cannot silently override a denial.
    2. ``MODIFY`` results apply in registration order — each handler sees
       the modifications applied by the previous one (via context rebuild).
    3. ``INJECT_CONTEXT`` concatenates with newlines.
    4. All ``CONTINUE`` → outcome ``CONTINUE``.

    Handler exceptions are treated as ``CONTINUE`` and logged so a broken
    user hook cannot brick the runtime.
    """

    def __init__(self, registry: HookRegistry, *, default_timeout_s: float = 60.0) -> None:
        self._registry = registry
        self._default_timeout_s = default_timeout_s

    async def dispatch(
        self,
        ctx: HookContext,
        *,
        timeout_s: Optional[float] = None,
    ) -> HookDecision:
        handlers = self._registry.handlers_for(ctx.event_type, ctx.matcher_key)
        if not handlers:
            return HookDecision.cont()

        effective_timeout = timeout_s if timeout_s is not None else self._default_timeout_s
        current_ctx = ctx
        merged_arguments = (
            dict(ctx.arguments) if ctx.arguments is not None else None
        )
        merged_user_message: Optional[str] = ctx.user_message
        injected_blocks: List[str] = []
        any_modify = False

        for handler in handlers:
            decision = await self._run_one(handler, current_ctx, effective_timeout)
            if decision.outcome == HookOutcome.DENY:
                # Drain remaining handlers but discard their decisions —
                # someone said no, the answer is no.
                for remaining in handlers[handlers.index(handler) + 1:]:
                    try:
                        await self._run_one(remaining, current_ctx, effective_timeout)
                    except Exception:
                        pass
                return decision

            if decision.outcome == HookOutcome.MODIFY:
                any_modify = True
                if decision.modified_arguments is not None:
                    if merged_arguments is None:
                        merged_arguments = {}
                    merged_arguments.update(decision.modified_arguments)
                if decision.modified_user_message is not None:
                    merged_user_message = decision.modified_user_message
                current_ctx = replace(
                    current_ctx,
                    arguments=merged_arguments,
                    user_message=merged_user_message,
                )
            elif decision.outcome == HookOutcome.INJECT_CONTEXT:
                if decision.additional_context:
                    injected_blocks.append(decision.additional_context)
            # CONTINUE: nothing to merge.

        if injected_blocks:
            combined = "\n\n".join(injected_blocks)
            return HookDecision(
                outcome=HookOutcome.INJECT_CONTEXT,
                additional_context=combined,
                modified_arguments=merged_arguments if any_modify else None,
                modified_user_message=merged_user_message if any_modify else None,
            )
        if any_modify:
            return HookDecision(
                outcome=HookOutcome.MODIFY,
                modified_arguments=merged_arguments,
                modified_user_message=merged_user_message,
            )
        return HookDecision.cont()

    async def _run_one(
        self,
        handler,
        ctx: HookContext,
        timeout_s: float,
    ) -> HookDecision:
        source = self._registry.source_of(handler)
        try:
            return await asyncio.wait_for(handler(ctx), timeout=timeout_s)
        except asyncio.TimeoutError:
            logger.warning(
                "hook handler timed out event=%s source=%s timeout=%.1fs",
                ctx.event_type.value,
                source,
                timeout_s,
            )
            return HookDecision.cont(source=source)
        except Exception:
            logger.exception(
                "hook handler raised event=%s source=%s",
                ctx.event_type.value,
                source,
            )
            return HookDecision.cont(source=source)

    @property
    def registry(self) -> HookRegistry:
        return self._registry


__all__ = ["HookGateway"]
