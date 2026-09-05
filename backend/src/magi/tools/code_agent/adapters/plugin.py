"""Adapt the SDK external-agent stream to the host delegation runtime."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from magi_plugin_sdk.providers import ExternalAgentEvent, ExternalAgentRequest

from .base import AdapterRunOutcome, CancelToken, OnEvent, wait_for_run_or_cancel
from ..contracts import CostInfo, DelegateRequest, RunEvent


class PluginExternalAgentAdapter:
    def __init__(self, provider: Any, *, connection: Any, valid: Any) -> None:
        self._provider = provider
        self._connection = connection
        self._valid = valid

    async def run(
        self,
        req: DelegateRequest,
        *,
        cwd: Path,
        bundle_dir: Path,
        stdout_path: Path,
        stderr_path: Path,
        on_event: OnEvent,
        cancel_token: CancelToken,
        binary_path: str,
    ) -> AdapterRunOutcome:
        from ....plugins.operation_authorization import build_host_invocation

        if not self._valid():
            raise RuntimeError("External agent provider connection was revoked")
        identity = build_host_invocation(
            self._connection,
            trigger="model",
            task_id=req.delegation_id,
            session_id=req.session_id,
        )
        request = ExternalAgentRequest(
            identity=identity,
            prompt=req.prompt,
            workspace=str(cwd),
            files_hint=req.files_hint,
            constraints=req.constraints.model_dump(mode="json"),
            timeout_seconds=req.timeout_s,
            model=req.model,
        )
        stream = self._provider.stream(request)

        async def consume() -> AdapterRunOutcome:
            completed = None
            count = 0
            try:
                async for raw in stream:
                    count += 1
                    if not self._valid() or count > 100000:
                        raise RuntimeError(
                            "External agent provider revoked or stream limit exceeded"
                        )
                    event = ExternalAgentEvent.model_validate(raw)
                    if completed is not None:
                        raise ValueError("External agent emitted after completion")
                    if event.kind == "completed":
                        if event.result is None:
                            raise ValueError(
                                "External agent completion requires a result"
                            )
                        completed = event.result
                    else:
                        await on_event(
                            RunEvent(
                                kind=event.kind,
                                ts_ms=int(time.time() * 1000),
                                payload=dict(event.payload),
                            )
                        )
                if completed is None:
                    raise ValueError("External agent stream ended without a result")
                return AdapterRunOutcome(
                    exit_code=(
                        completed.exit_code
                        if completed.status == "succeeded"
                        else (completed.exit_code or 1)
                    ),
                    summary=completed.summary,
                    error=completed.error
                    or (None if completed.status == "succeeded" else completed.status),
                    cancelled=completed.status == "cancelled",
                    cost=CostInfo(
                        usd=completed.cost_usd,
                        input_tokens=completed.usage.input_tokens,
                        output_tokens=completed.usage.output_tokens,
                    ),
                )
            finally:
                await stream.aclose()

        async def terminate() -> None:
            # Cancelling the consumer closes the bounded worker stream in finally.
            return None

        outcome, cancelled = await asyncio.wait_for(
            wait_for_run_or_cancel(
                consume(), cancel_token=cancel_token, terminate=terminate
            ),
            req.timeout_s,
        )
        return outcome or AdapterRunOutcome(
            exit_code=1, summary=None, cost=None, error="cancelled", cancelled=cancelled
        )
