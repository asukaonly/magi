"""Wrap a shell command into a HookHandler matching Claude Code semantics.

Protocol (compatible with Claude Code hooks):

1. The handler spawns ``/bin/sh -c <command>``.
2. stdin: JSON-encoded :class:`HookContext` as a single line.
3. stdout: optional JSON response describing the decision. Recognised
   shapes::

       {"decision": "block", "reason": "..."}
       {"decision": "approve"}
       {"decision": "modify", "modified_arguments": {...}}
       {"decision": "modify", "modified_user_message": "..."}
       {"decision": "inject", "additional_context": "..."}

   If stdout is empty or not JSON, exit code rules apply.
4. Exit code: ``0`` = CONTINUE, ``2`` = DENY (matching Claude Code's
   convention where exit code 2 signals "blocked" while stderr carries the
   reason), anything else = CONTINUE with a logged warning.
5. stderr is captured and surfaced in logs (and used as DENY reason when
   exit code 2 has no JSON).
"""

from __future__ import annotations

from magi_plugin_sdk.subprocess import hidden_process_kwargs

import asyncio
import dataclasses
import json
import logging
from typing import Any, Mapping, Optional

from ..utils.diagnostic_logging import full_content_logging_enabled
from .contracts import HookContext, HookDecision

logger = logging.getLogger(__name__)

DEFAULT_SHELL_TIMEOUT_S = 60.0


def _serialize_context(ctx: HookContext) -> str:
    payload: dict[str, Any] = {
        "event_type": ctx.event_type.value,
        "session_id": ctx.session_id,
        "turn_id": ctx.turn_id,
        "user_id": ctx.user_id,
        "workspace": ctx.workspace,
        "tool_name": ctx.tool_name,
        "arguments": dict(ctx.arguments) if ctx.arguments is not None else None,
        "skill_name": ctx.skill_name,
        "user_message": ctx.user_message,
        "matcher_key": ctx.matcher_key,
        "extra": dict(ctx.extra) if ctx.extra else {},
    }
    try:
        return json.dumps(payload, default=str)
    except Exception:
        # As a last resort fall back to a stringified dataclass dump.
        return json.dumps(dataclasses.asdict(ctx), default=str)


def _parse_decision_payload(
    raw: str,
    *,
    source: Optional[str],
    exit_code: int,
    stderr: str,
) -> HookDecision:
    text = (raw or "").strip()
    parsed: Optional[Mapping[str, Any]] = None
    if text:
        try:
            candidate = json.loads(text)
            if isinstance(candidate, dict):
                parsed = candidate
        except json.JSONDecodeError:
            logger.debug("shell hook stdout was not JSON (source=%s)", source)

    if parsed is not None:
        decision_kind = str(parsed.get("decision") or "").strip().lower()
        if decision_kind in {"block", "deny"}:
            return HookDecision.deny(
                str(parsed.get("reason") or stderr.strip() or "denied by hook"),
                source=source,
            )
        if decision_kind == "modify":
            return HookDecision.modify(
                arguments=parsed.get("modified_arguments") if isinstance(parsed.get("modified_arguments"), dict) else None,
                user_message=str(parsed.get("modified_user_message")) if parsed.get("modified_user_message") is not None else None,
                reason=str(parsed.get("reason")) if parsed.get("reason") else None,
                source=source,
            )
        if decision_kind in {"inject", "inject_context"}:
            content = str(parsed.get("additional_context") or parsed.get("context") or "").strip()
            return HookDecision.inject(content, source=source) if content else HookDecision.cont(source=source)
        if decision_kind in {"approve", "continue", "allow"}:
            return HookDecision.cont(source=source)

    if exit_code == 0:
        return HookDecision.cont(source=source)
    if exit_code == 2:
        return HookDecision.deny(stderr.strip() or "denied by hook", source=source)
    if full_content_logging_enabled():
        logger.warning(
            "shell hook exited with unexpected code=%s source=%s stderr=%s",
            exit_code,
            source,
            stderr.strip()[:200],
        )
    else:
        logger.warning(
            "shell hook exited with unexpected code=%s source=%s stderr_chars=%d",
            exit_code,
            source,
            len(stderr),
        )
    return HookDecision.cont(source=source)


def build_shell_hook_handler(
    *,
    command: str,
    timeout_s: Optional[float] = None,
    source: Optional[str] = None,
):
    """Return an async hook handler that runs ``command`` as a subprocess."""

    effective_timeout = float(timeout_s) if timeout_s is not None else DEFAULT_SHELL_TIMEOUT_S

    async def handler(ctx: HookContext) -> HookDecision:
        proc = None
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **hidden_process_kwargs(),
            )
        except Exception as exc:
            if full_content_logging_enabled():
                logger.exception("failed to spawn shell hook command=%s", command)
            else:
                logger.warning(
                    "failed to spawn shell hook | error_type=%s",
                    type(exc).__name__,
                )
            return HookDecision.cont(source=source)

        try:
            stdin_bytes = _serialize_context(ctx).encode("utf-8")
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=stdin_bytes),
                timeout=effective_timeout,
            )
        except asyncio.TimeoutError:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass
            logger.warning(
                "shell hook timed out source=%s timeout=%.1fs",
                source,
                effective_timeout,
            )
            return HookDecision.cont(source=source)
        except Exception as exc:
            if full_content_logging_enabled():
                logger.exception("shell hook crashed source=%s", source)
            else:
                logger.warning(
                    "shell hook crashed source=%s error_type=%s",
                    source,
                    type(exc).__name__,
                )
            return HookDecision.cont(source=source)

        stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
        stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")
        exit_code = proc.returncode if proc.returncode is not None else 0
        return _parse_decision_payload(
            stdout,
            source=source,
            exit_code=exit_code,
            stderr=stderr,
        )

    return handler


__all__ = ["build_shell_hook_handler", "DEFAULT_SHELL_TIMEOUT_S"]
