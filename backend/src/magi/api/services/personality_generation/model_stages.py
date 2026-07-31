"""Shared LLM and JSON execution for personality generation stages."""

from __future__ import annotations

import json
from typing import Any, Callable, Optional, Sequence, cast

from ....utils.diagnostic_logging import full_content_logging_enabled
from ....config.models import LLMScenario, LLMSettings
from ....llm import LLMProviderBridge
from .constants import (
    JSON_DIAGNOSTIC_CONTRACT_CHARS,
    JSON_DIAGNOSTIC_LINE_CONTEXT,
    JSON_DIAGNOSTIC_OUTPUT_CHARS,
)
from .normalization import _pick_keys
from .runtime import _PERSONALITY_GENERATION_LLM_SEMAPHORE, logger


JSON_REPAIR_SYSTEM_PROMPT = """You repair invalid JSON from a persona-generation stage.
Output ONLY one valid JSON object. Do not add markdown fences, comments, or explanation.
Preserve the original keys and values as much as possible. Only fix syntax and obvious JSON-shape mistakes needed for parsing."""


def _json_candidate_text(response_text: str) -> str:
    """Return the response slice that is parsed as JSON."""
    text = response_text.strip()
    if not text:
        raise ValueError("AI returned empty response")
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1])
    json_start = text.find("{")
    json_end = text.rfind("}")
    if json_start >= 0 and json_end > json_start:
        text = text[json_start : json_end + 1]
    return text


def _extract_json_object(response_text: str) -> dict[str, Any]:
    """Parse the first JSON object from an LLM response."""
    text = _json_candidate_text(response_text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("AI returned JSON that is not an object")
    return data


def _truncate_for_diagnostics(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    half = max_chars // 2
    return f"{value[:half]}\n...[truncated {len(value) - max_chars} chars]...\n" f"{value[-half:]}"


def _expected_output_contract(system_prompt: str) -> str:
    marker = "# Output Contract"
    end_marker = "# Stage Quality Checks"
    start = system_prompt.find(marker)
    if start < 0:
        return _truncate_for_diagnostics(
            system_prompt.strip(),
            JSON_DIAGNOSTIC_CONTRACT_CHARS,
        )
    start += len(marker)
    end = system_prompt.find(end_marker, start)
    contract = system_prompt[start : end if end >= 0 else len(system_prompt)].strip()
    return _truncate_for_diagnostics(
        contract,
        JSON_DIAGNOSTIC_CONTRACT_CHARS,
    )


def _parse_error_summary(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, json.JSONDecodeError):
        return {
            "type": exc.__class__.__name__,
            "message": exc.msg,
            "line": exc.lineno,
            "column": exc.colno,
            "char": exc.pos,
        }
    return {
        "type": exc.__class__.__name__,
        "message": str(exc),
    }


def _line_excerpt_with_caret(
    line: str,
    column: int,
    *,
    radius: int = 180,
) -> tuple[str, str]:
    index = max(column - 1, 0)
    start = max(index - radius, 0)
    end = min(index + radius, len(line))
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(line) else ""
    excerpt = f"{prefix}{line[start:end]}{suffix}"
    caret_index = len(prefix) + max(index - start, 0)
    return excerpt, " " * caret_index + "^"


def _json_output_error_context(
    response_text: str,
    exc: Exception,
) -> str:
    try:
        candidate = _json_candidate_text(response_text)
    except Exception:
        candidate = response_text.strip()
    if not isinstance(exc, json.JSONDecodeError):
        return _truncate_for_diagnostics(
            candidate,
            JSON_DIAGNOSTIC_OUTPUT_CHARS,
        )

    lines = candidate.splitlines() or [candidate]
    line_index = max(min(exc.lineno - 1, len(lines) - 1), 0)
    start = max(line_index - JSON_DIAGNOSTIC_LINE_CONTEXT, 0)
    end = min(
        line_index + JSON_DIAGNOSTIC_LINE_CONTEXT + 1,
        len(lines),
    )
    rendered: list[str] = []
    for current in range(start, end):
        line_no = current + 1
        marker = ">" if current == line_index else " "
        if current == line_index:
            excerpt, caret = _line_excerpt_with_caret(
                lines[current],
                exc.colno,
            )
            rendered.append(f"{marker} {line_no}: {excerpt}")
            rendered.append(f"  {' ' * (len(str(line_no)) + 2)}{caret}")
        else:
            rendered.append(
                f"{marker} {line_no}: " f"{_truncate_for_diagnostics(lines[current], 420)}"
            )
    return "\n".join(rendered)


def _json_output_preview(response_text: str) -> str:
    try:
        candidate = _json_candidate_text(response_text)
    except Exception:
        candidate = response_text.strip()
    return _truncate_for_diagnostics(
        candidate,
        JSON_DIAGNOSTIC_OUTPUT_CHARS,
    )


def _diagnostic_preview(value: str, max_chars: int = 300) -> str:
    if not full_content_logging_enabled():
        return "[content omitted by diagnostics setting]"
    return _truncate_for_diagnostics(value, max_chars)


def _log_invalid_generation_json(
    *,
    event: str,
    stage_id: str,
    system_prompt: str,
    response_text: str,
    parse_error: Exception,
    extra_fields: Optional[dict[str, Any]] = None,
) -> None:
    fields: dict[str, Any] = {
        "stage_id": stage_id,
        "parse_error": _parse_error_summary(parse_error),
        "system_prompt_chars": len(system_prompt),
        "response_chars": len(response_text),
    }
    if full_content_logging_enabled():
        fields.update(
            {
                "expected_output_contract": _expected_output_contract(system_prompt),
                "output_error_context": _json_output_error_context(
                    response_text,
                    parse_error,
                ),
                "output_preview": _json_output_preview(response_text),
            }
        )
    if extra_fields:
        fields.update(extra_fields)
    logger.warning(event, **fields)


def _json_repair_user_prompt(
    stage_id: str,
    response_text: str,
    error: Exception,
) -> str:
    return f"""Repair this invalid JSON from the {stage_id} persona-generation stage.

Parse error:
{error}

Return only the repaired JSON object. Do not summarize or change the content.

# Invalid JSON
{response_text}"""


async def _call_generation_llm(
    *,
    stage_id: str,
    prompt: str,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    llm_override: Optional[LLMSettings],
    adapter_resolver: Callable[..., Any],
    adapter_factory: Callable[..., Any],
    stage_progress_callback: Optional[Callable[[str, str], None]],
    notify_progress: bool = True,
) -> str:
    async with _PERSONALITY_GENERATION_LLM_SEMAPHORE:
        if notify_progress and stage_progress_callback is not None:
            stage_progress_callback(stage_id, "running")
        llm_adapter = adapter_resolver(
            LLMScenario.CORE,
            llm_settings=llm_override,
            adapter_factory=adapter_factory,
        )
        logger.info(
            "[AI Generate Personality] Stage %s using provider=%s model=%s",
            stage_id,
            getattr(llm_adapter, "provider_name", "unknown"),
            getattr(llm_adapter, "model_name", "unknown"),
        )
        bridge = LLMProviderBridge(llm_adapter)
        response = await bridge.chat(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=True,
            disable_thinking=True,
            event_context={
                "request_kind": "personality:generation",
                "agent_id": "personality_generation",
            },
        )
    return cast(str, response).strip()


async def _run_generation_stage(
    *,
    stage_id: str,
    prompt: str,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    llm_override: Optional[LLMSettings],
    adapter_resolver: Callable[..., Any],
    adapter_factory: Callable[..., Any],
    stage_progress_callback: Optional[Callable[[str, str], None]] = None,
    retry_on_json_error: bool = False,
) -> dict[str, Any]:
    """Run one LLM JSON stage behind the shared generation concurrency gate."""
    response_text = await _call_generation_llm(
        stage_id=stage_id,
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        llm_override=llm_override,
        adapter_resolver=adapter_resolver,
        adapter_factory=adapter_factory,
        stage_progress_callback=stage_progress_callback,
    )
    logger.info(
        "[AI Generate Personality] Stage %s raw response preview: %s",
        stage_id,
        _diagnostic_preview(response_text),
    )
    try:
        return _extract_json_object(response_text)
    except (json.JSONDecodeError, ValueError) as exc:
        if not retry_on_json_error:
            raise
        _log_invalid_generation_json(
            event="personality_generation_invalid_json",
            stage_id=stage_id,
            system_prompt=system_prompt,
            response_text=response_text,
            parse_error=exc,
            extra_fields={"will_retry_repair": True},
        )
        repaired_text = await _call_generation_llm(
            stage_id=f"{stage_id}.repair",
            prompt=_json_repair_user_prompt(
                stage_id,
                response_text,
                exc,
            ),
            system_prompt=JSON_REPAIR_SYSTEM_PROMPT,
            max_tokens=max_tokens,
            temperature=0.0,
            llm_override=llm_override,
            adapter_resolver=adapter_resolver,
            adapter_factory=adapter_factory,
            stage_progress_callback=stage_progress_callback,
            notify_progress=False,
        )
        logger.info(
            "[AI Generate Personality] Stage %s repaired response preview: %s",
            stage_id,
            _diagnostic_preview(repaired_text),
        )
        try:
            return _extract_json_object(repaired_text)
        except (json.JSONDecodeError, ValueError) as repair_exc:
            repair_fields: dict[str, Any] = {
                "original_parse_error": _parse_error_summary(exc),
                "repair_parse_error": _parse_error_summary(repair_exc),
            }
            if full_content_logging_enabled():
                repair_fields["repair_output_error_context"] = (
                    _json_output_error_context(
                        repaired_text,
                        repair_exc,
                    )
                )
            _log_invalid_generation_json(
                event="personality_generation_json_repair_invalid",
                stage_id=stage_id,
                system_prompt=system_prompt,
                response_text=repaired_text,
                parse_error=repair_exc,
                extra_fields=repair_fields,
            )
            raise


async def _run_optional_generation_stage(
    *,
    stages: list[dict[str, str]],
    allowed_keys: Sequence[str],
    **kwargs: Any,
) -> dict[str, Any]:
    stage_id = str(kwargs["stage_id"])
    try:
        data = await _run_generation_stage(**kwargs)
        progress_callback = kwargs.get("stage_progress_callback")
        if callable(progress_callback):
            progress_callback(stage_id, "completed")
        stages.append({"stage_id": stage_id, "status": "completed"})
        return _pick_keys(data, allowed_keys)
    except Exception as exc:  # noqa: BLE001 - optional sections can be normalized later
        logger.warning(
            "[AI Generate Personality] Optional stage %s failed: %s",
            stage_id,
            exc,
        )
        progress_callback = kwargs.get("stage_progress_callback")
        if callable(progress_callback):
            progress_callback(stage_id, "failed")
        stages.append({"stage_id": stage_id, "status": "failed"})
        return {}
