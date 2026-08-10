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

from ...core.logger import get_logger
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


@dataclass(slots=True)
class _GateContext:
    tool_name: str
    arguments: dict[str, Any]
    agent_id: str
    origin: ToolOrigin
    session_id: str | None
    turn_id: str | None
    workspace: str | None
    tool_is_dangerous: bool
    tool_risk_level: RiskLevel | str | None
    tool_risk_authoritative: bool


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
    ) -> UserPromptResponse: ...


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
        session_override_provider: (
            Callable[[str | None], SessionControlOverride | None] | None
        ) = None,
        prompter: PermissionPrompter | None = None,
        # Phase H+2: default bumped 120 → 300 to accommodate external
        # channel response latency. WeChat / Telegram users may be away
        # from their device for minutes; 5 min keeps the prompt
        # reachable without hanging the run indefinitely. Desktop users
        # were never near the 120s ceiling either, so this is strictly
        # a wider window with no regression.
        prompt_timeout_seconds: float = 300.0,
        plan_mode_guard: Callable[[str | None, str], bool] | None = None,
        # Phase H+2: per-binding auto-approve bypass. Both must be wired
        # for the bypass to fire — when either is None (the default,
        # also the partial-bootstrap state) the bypass is silently
        # disabled and all prompts go through the normal flow.
        # ``binding_settings_store`` is the SQLite-backed
        # ``ChannelBindingSettingsStore`` (CF-7).
        # ``binding_origin_resolver`` is an async callable
        # ``session_id -> (channel_type, external_user_id) | None``
        # that the bootstrap wires to a function reading the active
        # run's ``RunTrigger.source_channel`` from the appropriate
        # SessionRunStore (channels-side wire-up in CF-9/CF-10).
        binding_settings_store: Any | None = None,
        binding_origin_resolver: (
            Callable[[str | None], "Awaitable[tuple[str, str] | None]"] | None
        ) = None,
    ) -> None:
        self._classifier = classifier
        self._rules = rules
        self._broker = broker
        self._settings_provider = settings_provider
        self._session_override_provider = session_override_provider
        self._prompter = prompter
        self._prompt_timeout_seconds = float(prompt_timeout_seconds)
        self._plan_mode_guard = plan_mode_guard
        self._binding_settings_store = binding_settings_store
        self._binding_origin_resolver = binding_origin_resolver

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
        turn_id: str | None = None,
        workspace: str | None = None,
        tool_is_dangerous: bool = False,
        tool_risk_level: RiskLevel | str | None = None,
        tool_risk_authoritative: bool = False,
    ) -> PermissionDecision:
        """Evaluate a single tool invocation."""
        started = time.time()
        decision = await self._gate_impl(
            tool_name=tool_name,
            arguments=arguments,
            agent_id=agent_id,
            origin=origin,
            session_id=session_id,
            turn_id=turn_id,
            workspace=workspace,
            tool_is_dangerous=tool_is_dangerous,
            tool_risk_level=tool_risk_level,
            tool_risk_authoritative=tool_risk_authoritative,
        )
        logger.info(
            "permission.decision",
            tool=tool_name,
            agent_id=agent_id,
            origin=origin.value,
            session_id=session_id,
            turn_id=turn_id,
            outcome=decision.outcome.value,
            source=decision.source,
            reason=decision.reason,
            request_id=decision.request_id,
            rule_recorded=(decision.recorded_rule.rule_id if decision.recorded_rule else None),
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
        turn_id: str | None,
        workspace: str | None,
        tool_is_dangerous: bool,
        tool_risk_level: RiskLevel | str | None,
        tool_risk_authoritative: bool,
    ) -> PermissionDecision:
        context = _GateContext(
            tool_name=tool_name,
            arguments=arguments,
            agent_id=agent_id,
            origin=origin,
            session_id=session_id,
            turn_id=turn_id,
            workspace=workspace,
            tool_is_dangerous=tool_is_dangerous,
            tool_risk_level=tool_risk_level,
            tool_risk_authoritative=tool_risk_authoritative,
        )
        for decision in (
            self._kill_list_decision(context),
            self._plan_mode_decision(context),
        ):
            if decision is not None:
                return decision

        classification = self._classify_invocation(context)
        matched_decision = self._matched_rule_decision(context)
        if matched_decision is not None:
            return matched_decision

        effective = self._effective_control_settings(context.session_id)
        auto_decision = self._auto_decision_if_prompt_not_needed(
            context,
            classification=classification,
            permission_mode=effective.permission_mode,
        )
        if auto_decision is not None:
            return auto_decision

        auto_approve_decision = await self._auto_approve_binding_decision(context.session_id)
        if auto_approve_decision is not None:
            return auto_approve_decision

        no_prompter_decision = self._no_prompter_decision()
        if no_prompter_decision is not None:
            return no_prompter_decision

        request = self._build_permission_request(context, classification)
        return await self._prompt_for_decision(request, context.session_id)

    def _kill_list_decision(self, context: _GateContext) -> PermissionDecision | None:
        kill_match = check_kill_list(
            tool_name=context.tool_name,
            arguments=context.arguments,
        )
        if kill_match is None:
            return None
        logger.warning(
            "permission.kill_listed",
            tool=context.tool_name,
            key=kill_match.entry.key,
            reason=kill_match.reason,
        )
        return PermissionDecision(
            request_id=PermissionRequest.new_id(),
            outcome=PermissionOutcome.KILL_LISTED,
            source=f"kill_list:{kill_match.entry.key}",
            reason=kill_match.reason,
        )

    def _plan_mode_decision(self, context: _GateContext) -> PermissionDecision | None:
        if self._plan_mode_guard is None:
            return None
        if self._plan_mode_guard(context.session_id, context.tool_name):
            return None
        return PermissionDecision(
            request_id=PermissionRequest.new_id(),
            outcome=PermissionOutcome.DENIED,
            source="plan_mode",
            reason=(
                "plan mode is active: only read-only tools and the "
                "plan-mode tools themselves may run. Call exit_plan_mode "
                "once the plan is ready."
            ),
        )

    def _classify_invocation(self, context: _GateContext) -> ClassificationResult:
        return self._classifier.classify(
            tool_name=context.tool_name,
            arguments=context.arguments,
            workspace=context.workspace,
            tool_is_dangerous=context.tool_is_dangerous,
            tool_risk_level=context.tool_risk_level,
            tool_risk_authoritative=context.tool_risk_authoritative,
        )

    def _matched_rule_decision(self, context: _GateContext) -> PermissionDecision | None:
        matched_rule = self._rules.find_match(
            tool_name=context.tool_name,
            arguments=context.arguments,
            session_id=context.session_id,
        )
        if matched_rule is None:
            return None
        outcome = PermissionOutcome.ALLOWED if matched_rule.allow else PermissionOutcome.DENIED
        return PermissionDecision(
            request_id=PermissionRequest.new_id(),
            outcome=outcome,
            source=f"rule:{matched_rule.rule_id}",
            reason=matched_rule.note or f"matched {matched_rule.scope.value} rule",
        )

    def _effective_control_settings(self, session_id: str | None) -> ControlSettings:
        override = (
            self._session_override_provider(session_id) if self._session_override_provider else None
        )
        return resolve_effective_settings(base=self._settings_provider(), override=override)

    def _auto_decision_if_prompt_not_needed(
        self,
        context: _GateContext,
        *,
        classification: ClassificationResult,
        permission_mode: PermissionMode,
    ) -> PermissionDecision | None:
        if self._needs_prompt(
            mode=permission_mode,
            risk=classification.level,
            tool_is_dangerous=context.tool_is_dangerous,
        ):
            return None
        return PermissionDecision(
            request_id=PermissionRequest.new_id(),
            outcome=PermissionOutcome.ALLOWED,
            source="auto",
            reason=f"mode={permission_mode.value} risk={classification.level.value}",
        )

    async def _auto_approve_binding_decision(
        self,
        session_id: str | None,
    ) -> PermissionDecision | None:
        if not await self._is_auto_approved_binding(session_id):
            return None
        return PermissionDecision(
            request_id=PermissionRequest.new_id(),
            outcome=PermissionOutcome.ALLOWED,
            source="auto_approve_binding",
            reason="binding auto-approve enabled — prompt suppressed per user toggle",
        )

    def _no_prompter_decision(self) -> PermissionDecision | None:
        if self._prompter is not None:
            return None
        return PermissionDecision(
            request_id=PermissionRequest.new_id(),
            outcome=PermissionOutcome.DENIED,
            source="no_prompter",
            reason="permission prompt requested but no prompter is configured",
        )

    def _build_permission_request(
        self,
        context: _GateContext,
        classification: ClassificationResult,
    ) -> PermissionRequest:
        created_at = time.time()
        prompt_timeout_seconds = max(0.0, self._prompt_timeout_seconds)
        return PermissionRequest(
            request_id=PermissionRequest.new_id(),
            tool_name=context.tool_name,
            arguments=context.arguments,
            risk_level=classification.level,
            origin=context.origin,
            agent_id=context.agent_id,
            session_id=context.session_id,
            turn_id=context.turn_id,
            workspace=context.workspace,
            preview=classification.preview,
            signals=[signal.key for signal in classification.signals],
            created_at=created_at,
            timeout_seconds=prompt_timeout_seconds,
            expires_at=(
                created_at + prompt_timeout_seconds if prompt_timeout_seconds > 0 else None
            ),
        )

    async def _prompt_for_decision(
        self,
        request: PermissionRequest,
        session_id: str | None,
    ) -> PermissionDecision:
        prompt_timeout_seconds = max(0.0, self._prompt_timeout_seconds)
        assert self._prompter is not None
        try:
            response = await self._prompter(request, timeout_seconds=prompt_timeout_seconds)
        except InteractionTimeoutError:
            logger.info(
                "permission.timed_out",
                tool=request.tool_name,
                request_id=request.request_id,
            )
            return PermissionDecision(
                request_id=request.request_id,
                outcome=PermissionOutcome.TIMED_OUT,
                source="timeout",
                reason=f"no response within {prompt_timeout_seconds:.0f}s",
            )

        return await self._finalise_user_response(request, response, session_id)

    def bind_auto_approve(
        self,
        *,
        binding_settings_store: Any,
        binding_origin_resolver: Callable[[str | None], "Awaitable[tuple[str, str] | None]"],
    ) -> None:
        """Late-bind the auto-approve dependencies after construction.

        Used by ChannelsModule which runs AFTER ControlPlaneModule
        (so the gateway exists) and after the channel session_mapper
        is built (so we can wire a real origin resolver). Either dep
        can be None to disable the bypass without touching the
        constructor. Idempotent — overwrites any prior binding."""
        self._binding_settings_store = binding_settings_store
        self._binding_origin_resolver = binding_origin_resolver

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _is_auto_approved_binding(self, session_id: str | None) -> bool:
        """Check whether the originating channel binding has its
        auto-approve toggle on. Returns False if either dependency
        is unwired (partial bootstrap / tests), if session_id is
        None, if the resolver can't identify an origin binding, or
        if either lookup raises — fail-closed in every degenerate
        case so the toggle never accidentally suppresses a prompt
        the user would have wanted to see.
        """
        if self._binding_settings_store is None:
            return False
        if self._binding_origin_resolver is None:
            return False
        if not session_id:
            return False
        try:
            binding = await self._binding_origin_resolver(session_id)
        except Exception:
            logger.warning(
                "permission.binding_origin_resolver_failed " "session_id=%s",
                session_id,
                exc_info=True,
            )
            return False
        if binding is None:
            return False
        channel_type, external_user_id = binding
        try:
            settings = await self._binding_settings_store.get(
                channel_type=channel_type,
                external_user_id=external_user_id,
            )
        except Exception:
            logger.warning(
                "permission.binding_settings_lookup_failed " "channel_type=%s external_user_id=%s",
                channel_type,
                external_user_id,
                exc_info=True,
            )
            return False
        return bool(getattr(settings, "auto_approve", False))

    @staticmethod
    def _needs_prompt(*, mode: PermissionMode, risk: RiskLevel, tool_is_dangerous: bool) -> bool:
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

        outcome = PermissionOutcome.ALLOWED if response.allow else PermissionOutcome.DENIED
        return PermissionDecision(
            request_id=request.request_id,
            outcome=outcome,
            source="user",
            reason=response.note,
            recorded_rule=recorded_rule,
        )


def _default_matcher(request: PermissionRequest, scope: PermissionScope) -> dict[str, Any]:
    """Best-effort matcher when the UI did not supply one explicitly."""
    # Default: match the full argument set exactly.
    if scope is PermissionScope.PERSISTENT_PATTERN:
        # Pattern scope defaulted to "any argument shape" is dangerous;
        # fall back to the exact match to be safe. UIs should always
        # provide an explicit pattern matcher.
        return dict(request.arguments)
    return dict(request.arguments)
