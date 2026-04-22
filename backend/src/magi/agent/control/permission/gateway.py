"""Central permission gateway for tool invocations.

Decision flow for every ``(tool_name, arguments)`` the gateway sees:

1. Kill-list check — if matched, return ``KILL_LISTED`` with no user
   prompt regardless of mode. This is a hardware safety fuse for
   LLM glitches and prompt injection.
2. Cached-rule check — session / persistent rules are consulted next.
3. Mode + risk table — :class:`PermissionMode.OFF` short-circuits to
   allow; :class:`PermissionMode.HIGH_ONLY` only asks when risk
   ``>= HIGH``; :class:`PermissionMode.ALL` asks whenever the tool is
   considered dangerous (risk ``>= MEDIUM`` or the tool schema flags
   it dangerous).
4. Prompt — the request is handed to the :class:`InteractionBroker`.
   The caller of :meth:`PermissionGateway.gate` is responsible for
   surfacing the request payload to the UI / IPC. On response, if the
   user picks a non-``ONE_SHOT`` scope the rule is written to the
   store.
5. Timeout — if the user does not respond within
   ``prompt_timeout_seconds`` the request is denied (``TIMED_OUT``).

The gateway does *not* execute the tool. It returns a
:class:`PermissionDecision`; the step executor then either calls the
registry or synthesises a tool-level error message for the LLM.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

from ....core.logger import get_logger
from ..common import InteractionBroker, InteractionTimeoutError
from ..settings import (
    ControlSettings,
    PermissionMode,
    SessionControlOverride,
    resolve_effective_settings,
)
from .classifier import ClassificationResult, RiskClassifier
from .contracts import (
    PermissionDecision,
    PermissionOutcome,
    PermissionRequest,
    PermissionRule,
    PermissionScope,
    RiskLevel,
    ToolOrigin,
)
from .kill_list import check_kill_list
from .rules import PermissionRuleStore

__all__ = [
    "PermissionGateway",
    "PermissionPrompter",
    "UserPromptResponse",
]


logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Prompt protocol
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class UserPromptResponse:
    """Shape of a response delivered through the prompter / broker."""

    allow: bool
    scope: PermissionScope = PermissionScope.ONE_SHOT
    matcher: dict[str, Any] | None = None
    note: str | None = None


class PermissionPrompter(Protocol):
    """Callable that publishes a permission prompt and awaits the user.

    Implementations typically:

    1. Emit an IPC event (``control.permission.requested``) carrying
       ``request.to_dict()``.
    2. ``await broker.wait(interaction_id=request.request_id, kind="permission", ...)``.
    3. Return the :class:`UserPromptResponse` materialised from the
       inbound ``control.permission.respond`` IPC call.
    """

    async def __call__(
        self,
        request: PermissionRequest,
        *,
        timeout_seconds: float,
    ) -> UserPromptResponse:
        ...


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------


class PermissionGateway:
    """Resolve a :class:`PermissionDecision` for a tool invocation.

    Args:
        classifier: The :class:`RiskClassifier` (injectable for tests).
        rules: Persistent + session rule cache.
        broker: Async broker shared with ask/plan for suspend/resume.
        settings_provider: Returns the current global
            :class:`ControlSettings`; re-invoked on every call so
            runtime updates take effect without restart.
        session_override_provider: Returns an optional session
            override keyed by ``session_id``. May be ``None`` if no
            session is in play.
        prompter: Callable that handles UI side of a user prompt.
        prompt_timeout_seconds: Seconds to wait for the user before
            denying via timeout. Defaults to 120.
    """

    def __init__(
        self,
        *,
        classifier: RiskClassifier,
        rules: PermissionRuleStore,
        broker: InteractionBroker,
        settings_provider: Callable[[], ControlSettings],
        session_override_provider: Callable[
            [str | None], SessionControlOverride | None
        ]
        | None = None,
        prompter: PermissionPrompter | None = None,
        prompt_timeout_seconds: float = 120.0,
        plan_mode_guard: Callable[[str | None, str], bool] | None = None,
    ) -> None:
        self._classifier = classifier
        self._rules = rules
        self._broker = broker
        self._settings_provider = settings_provider
        self._session_override_provider = session_override_provider
        self._prompter = prompter
        self._prompt_timeout_seconds = float(prompt_timeout_seconds)
        self._plan_mode_guard = plan_mode_guard

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def gate(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        agent_id: str,
        origin: ToolOrigin = ToolOrigin.CHAT,
        session_id: str | None = None,
        task_id: str | None = None,
        workspace: str | None = None,
        tool_is_dangerous: bool = False,
    ) -> PermissionDecision:
        """Evaluate a single tool invocation."""
        started = time.time()
        decision = await self._gate_impl(
            tool_name=tool_name,
            arguments=arguments,
            agent_id=agent_id,
            origin=origin,
            session_id=session_id,
            task_id=task_id,
            workspace=workspace,
            tool_is_dangerous=tool_is_dangerous,
        )
        logger.info(
            "permission.decision",
            tool=tool_name,
            agent_id=agent_id,
            origin=origin.value,
            session_id=session_id,
            task_id=task_id,
            outcome=decision.outcome.value,
            source=decision.source,
            reason=decision.reason,
            request_id=decision.request_id,
            rule_recorded=(
                decision.recorded_rule.rule_id if decision.recorded_rule else None
            ),
            elapsed_ms=int((time.time() - started) * 1000),
        )
        return decision

    async def _gate_impl(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        agent_id: str,
        origin: ToolOrigin,
        session_id: str | None,
        task_id: str | None,
        workspace: str | None,
        tool_is_dangerous: bool,
    ) -> PermissionDecision:

        # 1) Kill-list — hard refusal regardless of mode or rules.
        kill_match = check_kill_list(tool_name=tool_name, arguments=arguments)
        if kill_match is not None:
            request_id = PermissionRequest.new_id()
            logger.warning(
                "permission.kill_listed",
                tool=tool_name,
                key=kill_match.entry.key,
                reason=kill_match.reason,
            )
            return PermissionDecision(
                request_id=request_id,
                outcome=PermissionOutcome.KILL_LISTED,
                source=f"kill_list:{kill_match.entry.key}",
                reason=kill_match.reason,
            )

        # 1b) Plan-mode guard — while plan mode is active only read-only
        # tools are allowed. This is structural (cannot be rule-overridden)
        # and lives alongside the kill-list conceptually: a refusal here
        # is surfaced as ``DENIED`` with ``source=plan_mode`` so the LLM
        # sees a distinct reason.
        if self._plan_mode_guard is not None and not self._plan_mode_guard(
            session_id, tool_name
        ):
            return PermissionDecision(
                request_id=PermissionRequest.new_id(),
                outcome=PermissionOutcome.DENIED,
                source="plan_mode",
                reason=(
                    "plan mode is active: only read-only tools and the "
                    "plan-mode tools themselves may run. Call "
                    "exit_plan_mode once the plan is ready."
                ),
            )

        # Classify up front — signals are surfaced to the user prompt
        # and are used downstream by the trace UI.
        classification: ClassificationResult = self._classifier.classify(
            tool_name=tool_name,
            arguments=arguments,
            tool_is_dangerous=tool_is_dangerous,
        )

        # 2) Cached-rule lookup.
        matched_rule = self._rules.find_match(
            tool_name=tool_name, arguments=arguments, session_id=session_id
        )
        if matched_rule is not None:
            outcome = (
                PermissionOutcome.ALLOWED
                if matched_rule.allow
                else PermissionOutcome.DENIED
            )
            return PermissionDecision(
                request_id=PermissionRequest.new_id(),
                outcome=outcome,
                source=f"rule:{matched_rule.rule_id}",
                reason=matched_rule.note
                or f"matched {matched_rule.scope.value} rule",
            )

        # 3) Resolve effective mode + risk table.
        override = (
            self._session_override_provider(session_id)
            if self._session_override_provider
            else None
        )
        effective = resolve_effective_settings(
            base=self._settings_provider(), override=override
        )

        if not self._needs_prompt(
            mode=effective.permission_mode,
            risk=classification.level,
            tool_is_dangerous=tool_is_dangerous,
        ):
            return PermissionDecision(
                request_id=PermissionRequest.new_id(),
                outcome=PermissionOutcome.ALLOWED,
                source="auto",
                reason=f"mode={effective.permission_mode.value} risk={classification.level.value}",
            )

        # 4) Prompt the user.
        if self._prompter is None:
            # Fail-closed: no UI wired yet, but the classifier says we
            # should have asked. Deny the call with a descriptive
            # source so the user sees why in the trace.
            return PermissionDecision(
                request_id=PermissionRequest.new_id(),
                outcome=PermissionOutcome.DENIED,
                source="no_prompter",
                reason="permission prompt requested but no prompter is configured",
            )

        request = PermissionRequest(
            request_id=PermissionRequest.new_id(),
            tool_name=tool_name,
            arguments=arguments,
            risk_level=classification.level,
            origin=origin,
            agent_id=agent_id,
            session_id=session_id,
            task_id=task_id,
            workspace=workspace,
            preview=classification.preview,
            signals=[signal.key for signal in classification.signals],
            created_at=time.time(),
        )

        try:
            response = await self._prompter(
                request, timeout_seconds=self._prompt_timeout_seconds
            )
        except InteractionTimeoutError:
            logger.info(
                "permission.timed_out",
                tool=tool_name,
                request_id=request.request_id,
            )
            return PermissionDecision(
                request_id=request.request_id,
                outcome=PermissionOutcome.TIMED_OUT,
                source="timeout",
                reason=f"no response within {self._prompt_timeout_seconds:.0f}s",
            )

        return await self._finalise_user_response(request, response, session_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _needs_prompt(
        *, mode: PermissionMode, risk: RiskLevel, tool_is_dangerous: bool
    ) -> bool:
        if mode is PermissionMode.OFF:
            return False
        if mode is PermissionMode.HIGH_ONLY:
            return risk >= RiskLevel.HIGH
        # ALL — ask whenever there's *any* reason to believe this is dangerous.
        if risk >= RiskLevel.MEDIUM:
            return True
        return bool(tool_is_dangerous)

    async def _finalise_user_response(
        self,
        request: PermissionRequest,
        response: UserPromptResponse,
        session_id: str | None,
    ) -> PermissionDecision:
        recorded_rule: PermissionRule | None = None
        if response.scope is not PermissionScope.ONE_SHOT:
            matcher = response.matcher
            if matcher is None:
                matcher = _default_matcher(request, response.scope)
            rule = PermissionRule(
                rule_id=PermissionRule.new_id(),
                tool_name=request.tool_name,
                scope=response.scope,
                matcher=matcher,
                allow=response.allow,
                note=response.note,
            )
            try:
                recorded_rule = await self._rules.add(rule, session_id=session_id)
            except Exception as exc:
                logger.warning(
                    "permission.rule_save_failed",
                    tool=request.tool_name,
                    scope=response.scope.value,
                    error=str(exc),
                )
                recorded_rule = rule

        outcome = (
            PermissionOutcome.ALLOWED if response.allow else PermissionOutcome.DENIED
        )
        return PermissionDecision(
            request_id=request.request_id,
            outcome=outcome,
            source="user",
            reason=response.note,
            recorded_rule=recorded_rule,
        )


def _default_matcher(
    request: PermissionRequest, scope: PermissionScope
) -> dict[str, Any]:
    """Best-effort matcher when the UI did not supply one explicitly."""
    # Default: match the full argument set exactly.
    if scope is PermissionScope.PERSISTENT_PATTERN:
        # Pattern scope defaulted to "any argument shape" is dangerous;
        # fall back to the exact match to be safe. UIs should always
        # provide an explicit pattern matcher.
        return dict(request.arguments)
    return dict(request.arguments)
