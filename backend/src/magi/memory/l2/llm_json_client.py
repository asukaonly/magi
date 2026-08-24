"""JSON-mode LLM client helpers for L2 prompt services."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Optional, Protocol, cast

from ...core.logger import get_logger
from ...llm import (
    LLMProviderBridge,
    LLMRequestPriority,
    LLMScenario,
    ProviderResponse,
    ScenarioLLMPool,
)
from ...llm.error_classifier import is_rate_limit_exception

logger = get_logger("magi.memory.l2.llm_service")
_RATE_LIMIT_BACKOFF_SECONDS = (1.0, 2.0, 4.0)
_JSON_FORMAT_RETRY_SUFFIX = """

## Output correction
Your previous response was not a valid JSON object. Return exactly one valid JSON object that matches the requested schema. Do not use Markdown fences, prose, comments, or trailing text.
"""


class L2LLMJsonError(RuntimeError):
    """Base error for L2 JSON-mode model calls."""


class L2LLMUnavailableError(L2LLMJsonError):
    """Raised when an L2 model call has no configured adapter."""


class L2LLMCallError(L2LLMJsonError):
    """Raised when the provider call fails after transport retries."""


class L2InvalidJsonResponseError(L2LLMJsonError):
    """Raised when the provider repeatedly returns an invalid JSON object."""

    def __init__(self, message: str, *, issues: list[str] | None = None) -> None:
        super().__init__(message)
        self.issues = list(issues or [])


@dataclass(slots=True)
class _L2JsonCall:
    system_prompt: str
    prompt: str
    request_kind: str
    turn_id: str | None
    session_id: str | None
    scenario: LLMScenario
    disable_thinking: bool
    priority: LLMRequestPriority


@dataclass(slots=True)
class _L2JsonTarget:
    adapter: Any
    provider_bridge: LLMProviderBridge


class _L2LLMJsonClientHostProtocol(Protocol):
    _scenario_llm_pool: ScenarioLLMPool | None


class L2LLMJsonClientMixin:
    """Shared JSON-mode LLM execution and retry helpers."""

    async def _generate_json(
        self,
        *,
        system_prompt: str,
        prompt: str,
        request_kind: str,
        turn_id: str | None = None,
        session_id: str | None = None,
        log_context: dict[str, Any] | None = None,
        scenario: LLMScenario = LLMScenario.AUXILIARY,
        disable_thinking: bool = True,
        priority: LLMRequestPriority | str | int | None = None,
        required_fields: dict[str, type] | None = None,
        contract_normalizer: Callable[[dict[str, Any]], list[str]] | None = None,
        contract_validator: Callable[[dict[str, Any]], list[str]] | None = None,
    ) -> dict[str, Any]:
        call = _L2JsonCall(
            system_prompt=system_prompt,
            prompt=prompt,
            request_kind=request_kind,
            turn_id=turn_id,
            session_id=session_id,
            scenario=scenario,
            disable_thinking=disable_thinking,
            priority=(
                LLMRequestPriority.coerce(priority)
                if priority is not None
                else LLMRequestPriority.LOW
            ),
        )
        target = self._get_json_target(call)
        if target is None:
            raise L2LLMUnavailableError(
                f"No L2 LLM adapter is available for {call.request_kind}"
            )
        context = self._json_log_context(call, target=target, log_context=log_context)
        started_at = time.perf_counter()
        response = await self._call_json_with_retries(
            call=call,
            target=target,
            context=context,
            started_at=started_at,
        )
        completion_context = self._log_json_completion(context, response, started_at)
        validation_issues: list[str] = []
        try:
            return self._parse_json_response(
                response.content,
                completion_context,
                required_fields=required_fields,
                contract_normalizer=contract_normalizer,
                contract_validator=contract_validator,
            )
        except L2InvalidJsonResponseError as exc:
            validation_issues = exc.issues
            logger.info("L2 LLM JSON format retry scheduled", **completion_context)

        correction_suffix = _JSON_FORMAT_RETRY_SUFFIX
        if validation_issues:
            correction_suffix += "\nValidation problems:\n" + "\n".join(
                f"- {issue}" for issue in validation_issues[:20]
            )
        retry_call = replace(
            call,
            system_prompt=f"{call.system_prompt}{correction_suffix}",
        )
        retry_context = dict(context)
        retry_context.update(
            {
                "json_format_retry": True,
                "system_prompt_char_count": len(retry_call.system_prompt),
            }
        )
        retry_started_at = time.perf_counter()
        retry_response = await self._call_json_with_retries(
            call=retry_call,
            target=target,
            context=retry_context,
            started_at=retry_started_at,
        )
        retry_completion_context = self._log_json_completion(
            retry_context,
            retry_response,
            retry_started_at,
        )
        return self._parse_json_response(
            retry_response.content,
            retry_completion_context,
            required_fields=required_fields,
            contract_normalizer=contract_normalizer,
            contract_validator=contract_validator,
        )

    def _get_json_target(self, call: _L2JsonCall) -> _L2JsonTarget | None:
        llm_target = self._get_llm_target(scenario=call.scenario)
        if llm_target is None:
            logger.warning(
                "L2 LLM call skipped: no adapter available",
                request_kind=call.request_kind,
                scenario=call.scenario.value,
            )
            return None
        adapter, provider_bridge = llm_target
        return _L2JsonTarget(adapter=adapter, provider_bridge=provider_bridge)

    def _json_log_context(
        self,
        call: _L2JsonCall,
        *,
        target: _L2JsonTarget,
        log_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        provider = str(getattr(target.adapter, "provider_name", "unknown") or "unknown")
        model = str(getattr(target.adapter, "model_name", "unknown") or "unknown")
        context = dict(log_context or {})
        context.update(
            {
                "request_kind": call.request_kind,
                "provider": provider,
                "model": model,
                "disable_thinking": call.disable_thinking,
                "json_mode": True,
                "prompt_char_count": len(call.prompt),
                "system_prompt_char_count": len(call.system_prompt),
            }
        )
        return context

    async def _call_json_with_retries(
        self,
        *,
        call: _L2JsonCall,
        target: _L2JsonTarget,
        context: dict[str, Any],
        started_at: float,
    ) -> ProviderResponse:
        max_output_tokens = self._resolve_max_output_tokens(scenario=call.scenario)
        for attempt_index in range(len(_RATE_LIMIT_BACKOFF_SECONDS) + 1):
            try:
                return await self._call_json_once(
                    call=call,
                    provider_bridge=target.provider_bridge,
                    max_output_tokens=max_output_tokens,
                )
            except Exception as exc:
                if await self._handle_json_call_failure(
                    exc=exc,
                    attempt_index=attempt_index,
                    context=context,
                    started_at=started_at,
                ):
                    continue
                raise L2LLMCallError(
                    f"L2 LLM call failed for {call.request_kind}"
                ) from exc
        raise L2LLMCallError(f"L2 LLM call failed for {call.request_kind}")

    async def _call_json_once(
        self,
        *,
        call: _L2JsonCall,
        provider_bridge: LLMProviderBridge,
        max_output_tokens: int,
    ) -> ProviderResponse:
        return await provider_bridge.chat_response(
            system_prompt=call.system_prompt,
            messages=[{"role": "user", "content": call.prompt}],
            max_tokens=max_output_tokens,
            temperature=0.0,
            json_mode=True,
            disable_thinking=call.disable_thinking,
            # L2 extraction system prompts are constants (dynamic entities
            # ride in the user message) — cache them (marker vendors).
            cache_system=True,
            event_context={
                "request_kind": call.request_kind,
                "turn_id": call.turn_id,
                "session_id": call.session_id,
                "agent_id": "memory:l2",
            },
            priority=call.priority,
        )

    async def _handle_json_call_failure(
        self,
        *,
        exc: Exception,
        attempt_index: int,
        context: dict[str, Any],
        started_at: float,
    ) -> bool:
        failure_context = self._json_failure_context(
            exc=exc,
            attempt_index=attempt_index,
            context=context,
            started_at=started_at,
        )
        if self._is_rate_limit_error(exc) and attempt_index < len(_RATE_LIMIT_BACKOFF_SECONDS):
            backoff_seconds = _RATE_LIMIT_BACKOFF_SECONDS[attempt_index]
            failure_context["backoff_seconds"] = backoff_seconds
            logger.warning("L2 LLM rate limited", **failure_context)
            logger.info("L2 LLM retry scheduled", **failure_context)
            await asyncio.sleep(backoff_seconds)
            return True
        logger.warning("L2 LLM call failed", **failure_context)
        return False

    def _json_failure_context(
        self,
        *,
        exc: Exception,
        attempt_index: int,
        context: dict[str, Any],
        started_at: float,
    ) -> dict[str, Any]:
        failure_context = dict(context)
        failure_context["duration_ms"] = round((time.perf_counter() - started_at) * 1000.0, 2)
        failure_context["error"] = str(exc)
        failure_context["attempt_index"] = attempt_index + 1
        return failure_context

    def _log_json_completion(
        self,
        context: dict[str, Any],
        response: ProviderResponse,
        started_at: float,
    ) -> dict[str, Any]:
        completion_context = dict(context)
        completion_context.update(self._usage_log_fields(response))
        completion_context["duration_ms"] = round(
            (time.perf_counter() - started_at) * 1000.0,
            2,
        )
        logger.info("L2 LLM call completed", **completion_context)
        return completion_context

    def _parse_json_response(
        self,
        raw: str,
        completion_context: dict[str, Any],
        *,
        required_fields: dict[str, type] | None = None,
        contract_normalizer: Callable[[dict[str, Any]], list[str]] | None = None,
        contract_validator: Callable[[dict[str, Any]], list[str]] | None = None,
    ) -> dict[str, Any]:
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            invalid_context = dict(completion_context)
            invalid_context["response_char_count"] = len(raw or "")
            logger.warning("L2 LLM returned invalid JSON", **invalid_context)
            raise L2InvalidJsonResponseError("L2 LLM response is not valid JSON") from exc
        if not isinstance(parsed, dict):
            invalid_context = dict(completion_context)
            invalid_context["response_char_count"] = len(raw or "")
            invalid_context["response_json_type"] = type(parsed).__name__
            logger.warning("L2 LLM returned non-object JSON", **invalid_context)
            raise L2InvalidJsonResponseError("L2 LLM response is not a JSON object")
        normalizations = contract_normalizer(parsed) if contract_normalizer is not None else []
        if normalizations:
            normalized_context = dict(completion_context)
            normalized_context["contract_normalizations"] = normalizations
            logger.info("L2 LLM JSON contract normalized", **normalized_context)
        self._validate_json_contract(
            parsed,
            completion_context=completion_context,
            required_fields=required_fields,
            contract_validator=contract_validator,
        )
        return cast(dict[str, Any], parsed)

    @staticmethod
    def _validate_json_contract(
        parsed: dict[str, Any],
        *,
        completion_context: dict[str, Any],
        required_fields: dict[str, type] | None,
        contract_validator: Callable[[dict[str, Any]], list[str]] | None,
    ) -> None:
        required = required_fields or {}
        missing_fields = [field for field in required if field not in parsed]
        invalid_fields = [
            field
            for field, expected_type in required.items()
            if field in parsed and not isinstance(parsed[field], expected_type)
        ]
        contract_issues = contract_validator(parsed) if contract_validator is not None else []
        if not missing_fields and not invalid_fields and not contract_issues:
            return
        invalid_context = dict(completion_context)
        invalid_context["missing_fields"] = missing_fields
        invalid_context["invalid_field_types"] = invalid_fields
        invalid_context["contract_issues"] = contract_issues
        logger.warning("L2 LLM returned invalid JSON contract", **invalid_context)
        issues = [f"missing field: {field}" for field in missing_fields]
        issues.extend(f"invalid field type: {field}" for field in invalid_fields)
        issues.extend(contract_issues)
        raise L2InvalidJsonResponseError(
            "L2 LLM response does not match the JSON contract",
            issues=issues,
        )

    def _is_rate_limit_error(self, exc: Exception) -> bool:
        return bool(is_rate_limit_exception(exc))

    def _get_adapter(self, scenario: LLMScenario = LLMScenario.AUXILIARY) -> Optional[Any]:
        host = self._llm_json_client_host()
        if host._scenario_llm_pool is None:
            logger.warning("L2 LLM adapter unavailable: scenario_llm_pool is None")
            return None
        try:
            return host._scenario_llm_pool.get(scenario)
        except Exception as exc:
            logger.warning("L2 LLM adapter unavailable", error=str(exc), scenario=scenario.value)
            return None

    def _get_llm_target(
        self, *, scenario: LLMScenario = LLMScenario.AUXILIARY
    ) -> Optional[tuple[Any, LLMProviderBridge]]:
        adapter = self._get_adapter(scenario=scenario)
        if adapter is None:
            return None
        return adapter, LLMProviderBridge(adapter)

    def _resolve_max_output_tokens(self, *, scenario: LLMScenario) -> int:
        default_limit = 4096
        host = self._llm_json_client_host()
        pool = host._scenario_llm_pool
        if pool is None:
            return default_limit

        selection = None
        get_selection = getattr(pool, "get_selection", None)
        if callable(get_selection):
            try:
                selection = get_selection(scenario)
            except Exception:
                selection = None
        if selection is None:
            config = getattr(pool, "_config", None)
            llm_config = getattr(config, "llm", None)
            selections = getattr(llm_config, "selections", None)
            if isinstance(selections, dict):
                selection = selections.get(scenario.value)

        limits = getattr(selection, "limits", None)
        max_output_tokens = getattr(limits, "max_output_tokens", None)
        if max_output_tokens is None:
            return default_limit
        try:
            resolved = int(max_output_tokens)
        except (TypeError, ValueError):
            return default_limit
        return resolved if resolved > 0 else default_limit

    def _usage_log_fields(self, response: ProviderResponse) -> dict[str, Any]:
        usage = response.usage
        if usage is None:
            return {
                "usage_available": False,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
        return {
            "usage_available": True,
            "prompt_tokens": int(usage.prompt_tokens or 0),
            "completion_tokens": int(usage.completion_tokens or 0),
            "total_tokens": int(usage.total_tokens or 0),
        }

    def _llm_json_client_host(self) -> _L2LLMJsonClientHostProtocol:
        return cast(_L2LLMJsonClientHostProtocol, self)


__all__ = [
    "L2InvalidJsonResponseError",
    "L2LLMCallError",
    "L2LLMJsonClientMixin",
    "L2LLMJsonError",
    "L2LLMUnavailableError",
]
