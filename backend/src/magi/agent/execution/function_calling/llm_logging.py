"""Logging helpers for function-calling LLM calls."""

from __future__ import annotations

import json
import logging
from typing import Any

from ....config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
from ....utils.llm_logger import get_llm_logger, log_llm_request, log_llm_response

logger = logging.getLogger(__name__)
llm_logger = get_llm_logger("function_calling")


def log_tools_llm_request(
    *,
    request_id: str,
    model_name: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> None:
    log_llm_request(
        llm_logger,
        request_id=request_id,
        model=model_name,
        system_prompt=system_prompt,
        messages=messages,
        cache_boundary=SYSTEM_PROMPT_CACHE_BOUNDARY,
        tool_count=len(tools),
        tool_names=[str(tool.get("function", {}).get("name", "")) for tool in tools],
    )


def log_tools_llm_success(
    *,
    request_id: str,
    result: dict[str, Any],
    duration_ms: int,
) -> None:
    log_llm_response(
        llm_logger,
        request_id=request_id,
        response=json.dumps(result, ensure_ascii=False, default=str),
        success=True,
        duration_ms=duration_ms,
    )


def log_tools_llm_failure(
    *,
    request_id: str,
    model_name: str,
    tools: list[dict[str, Any]],
    exc: Exception,
    duration_ms: int,
) -> None:
    log_llm_response(
        llm_logger,
        request_id=request_id,
        response="",
        success=False,
        error=str(exc),
        duration_ms=duration_ms,
    )
    logger.error(f"[FunctionCalling] LLM call failed: {exc}")
    try:
        tools_blob = json.dumps(tools, ensure_ascii=False, default=str)
        logger.error(
            "[FunctionCalling] LLM call failed | request_id=%s | model=%s | tools=%s",
            request_id,
            model_name,
            tools_blob if len(tools_blob) <= 8000 else tools_blob[:8000] + "...",
        )
    except Exception:  # pragma: no cover - logging must not mask the original error
        pass


def log_final_llm_request(
    *,
    request_id: str,
    model_name: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
) -> None:
    log_llm_request(
        llm_logger,
        request_id=request_id,
        model=model_name,
        system_prompt=system_prompt,
        messages=messages,
        cache_boundary=SYSTEM_PROMPT_CACHE_BOUNDARY,
    )


def log_final_llm_success(
    *,
    request_id: str,
    content: str,
    duration_ms: int,
    metadata: dict[str, Any],
) -> None:
    log_llm_response(
        llm_logger,
        request_id=request_id,
        response=content,
        success=True,
        duration_ms=duration_ms,
        fallback_reason="function_calling_final_response_without_tools",
        **metadata,
    )


def log_final_llm_failure(
    *,
    request_id: str,
    exc: Exception,
    duration_ms: int,
) -> None:
    log_llm_response(
        llm_logger,
        request_id=request_id,
        response="",
        success=False,
        error=str(exc),
        duration_ms=duration_ms,
        fallback_reason="function_calling_final_response_without_tools",
    )


__all__ = [
    "log_final_llm_failure",
    "log_final_llm_request",
    "log_final_llm_success",
    "log_tools_llm_failure",
    "log_tools_llm_request",
    "log_tools_llm_success",
]
