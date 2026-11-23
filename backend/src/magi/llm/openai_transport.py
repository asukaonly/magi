"""Native OpenAI transports normalized to the bridge's completion records."""

from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator
from types import SimpleNamespace

from .output_limit import OutputLimitReached
from .stream_errors import IncompleteStreamError

from openai.types.chat import ChatCompletion, ChatCompletionChunk


_GPT_6 = re.compile(r"gpt-6(?:\.[12])?-(?:astra|sol|terra|luna)(?:-|$)")
_GPT_5_6 = {"gpt-5.6", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}
_DEFAULT_EFFORT_NONE = {"gpt-5.1", "gpt-5.2", "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano"}
_OPENAI_REASONING_CHAT = re.compile(r"(?:gpt-5|o[134])(?:[.-]|$)")


def _model_family(model: str) -> str:
    return re.sub(r"-\d{4}-\d{2}-\d{2}$", "", model.lower())


def openai_reasoning_effort(model: str, effort: str) -> str | None:
    """Resolve effort for recognized OpenAI models, including dated snapshots."""
    model = _model_family(model)
    if _GPT_6.match(model):
        if effort == "none" and model.startswith(
            ("gpt-6-astra", "gpt-6.1-sol", "gpt-6.2-astra", "gpt-6.2-sol")
        ):
            return "low"
        return effort
    if model in _GPT_5_6:
        return effort
    if model in _DEFAULT_EFFORT_NONE or model == "gpt-5.5":
        return "high" if effort == "max" else effort
    if model in {"gpt-5", "gpt-5-mini", "gpt-5-nano", "o1", "o3", "o3-mini", "o4-mini"}:
        return {"none": "low", "max": "high"}.get(effort, effort)
    return None


def _requires_responses(model: str, kwargs: dict[str, Any]) -> bool:
    if _GPT_6.match(model):
        return True
    if model not in _GPT_5_6:
        return False
    if kwargs.get("tools") and kwargs.get("reasoning_effort") != "none":
        return True
    return any(message.get("responses_reasoning") for message in kwargs["messages"])


def _responses_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    result = dict(kwargs)
    items: list[dict[str, Any]] = []
    for message in result.pop("messages"):
        role = message["role"]
        if role == "tool":
            items.append({"type": "function_call_output", "call_id": message["tool_call_id"],
                          "output": message.get("content") or ""})
            continue
        items.extend(message.get("responses_reasoning", []))
        content = message.get("content")
        if content:
            if isinstance(content, list):
                parts = []
                for part in content:
                    if part["type"] == "text":
                        parts.append({"type": "output_text" if role == "assistant" else "input_text",
                                      "text": part["text"]})
                    elif part["type"] == "image_url":
                        image = part["image_url"]
                        parts.append({"type": "input_image", "image_url": image["url"],
                                      "detail": image.get("detail", "auto")})
                    else:
                        raise ValueError(f"Unsupported Responses input content: {part['type']}")
                content = parts
            items.append({"role": role, "content": content})
        for call in message.get("tool_calls", []):
            items.append({"type": "function_call", "call_id": call["id"],
                          "name": call["function"]["name"], "arguments": call["function"]["arguments"]})
    result["input"] = items
    result["store"] = False
    tokens = result.pop("max_tokens", None)
    if tokens is not None:
        result["max_output_tokens"] = tokens
    effort = result.pop("reasoning_effort", "medium")
    effort = openai_reasoning_effort(result["model"], effort) or effort
    result["reasoning"] = {**result.get("reasoning", {}), "effort": effort}
    if effort != "none":
        for key in ("temperature", "top_p", "top_logprobs"):
            result.pop(key, None)
    result.pop("logprobs", None)
    result.pop("stream_options", None)
    response_format = result.pop("response_format", None)
    if response_format:
        if response_format["type"] == "json_schema":
            response_format = {"type": "json_schema", **response_format["json_schema"]}
        result["text"] = {**result.get("text", {}), "format": response_format}
    tool_choice = result.get("tool_choice")
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        result["tool_choice"] = {"type": "function", "name": tool_choice["function"]["name"]}
    if result.get("tools"):
        result["tools"] = [{"type": "function", **tool["function"],
                            "strict": tool["function"].get("strict", False)} for tool in result["tools"]]
    else:
        result.pop("tools", None)
        result.pop("tool_choice", None)
    return result


def _response_usage(response: Any) -> dict[str, Any] | None:
    usage = response.usage
    if usage is None:
        return None
    details = usage.input_tokens_details
    writes = getattr(details, "cache_write_tokens_details", None)
    if hasattr(writes, "model_dump"):
        writes = writes.model_dump()
    return {"prompt_tokens": usage.input_tokens, "completion_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "service_tier": getattr(response, "service_tier", None),
            "prompt_tokens_details": {"cached_tokens": getattr(details, "cached_tokens", 0),
                                      "cache_write_tokens": getattr(details, "cache_write_tokens", 0),
                                      "cache_write_tokens_details": writes},
            "completion_tokens_details": {"reasoning_tokens": getattr(usage.output_tokens_details, "reasoning_tokens", 0)}}


def _completion_from_response(response: Any) -> ChatCompletion:
    if response.status == "incomplete" and getattr(getattr(response, "incomplete_details", None), "reason", None) == "max_output_tokens":
        raise OutputLimitReached(SimpleNamespace(**(_response_usage(response) or {})), usage_format="openai")
    if response.status != "completed":
        # Partial tool arguments must never be executed after truncation or failure.
        raise RuntimeError(f"Responses request did not complete: {response.status}")
    content: list[str] = []
    calls: list[dict[str, Any]] = []
    reasoning: list[dict[str, Any]] = []
    for item in response.output:
        if item.type == "reasoning":
            reasoning.append(item.model_dump(exclude_none=True))
        elif item.type == "message":
            for part in item.content:
                if part.type == "output_text":
                    content.append(part.text)
                elif part.type == "refusal":
                    content.append(part.refusal)
        elif item.type == "function_call":
            if not item.call_id or not item.name or not isinstance(json.loads(item.arguments), dict):
                raise ValueError("Responses function call requires an ID, name and JSON object arguments")
            calls.append({"id": item.call_id, "type": "function",
                          "function": {"name": item.name, "arguments": item.arguments}})
        else:
            raise ValueError(f"Unsupported Responses output item: {item.type}")
    return ChatCompletion.model_validate({
        "id": response.id, "object": "chat.completion", "created": int(response.created_at),
        "model": response.model, "usage": _response_usage(response),
        "choices": [{"index": 0, "finish_reason": "tool_calls" if calls else "stop",
                     "message": {"role": "assistant", "content": "".join(content),
                                 "tool_calls": calls or None, "responses_reasoning": reasoning}}],
    })


async def _response_chunks(stream: Any, model: str) -> AsyncIterator[ChatCompletionChunk]:
    calls: dict[str, tuple[int, str, str]] = {}
    arguments: dict[str, str] = {}
    terminal = False
    async for event in stream:
        delta: dict[str, Any] = {}
        usage = None
        finish_reason = None
        if event.type in {"response.output_text.delta", "response.refusal.delta"}:
            delta["content"] = event.delta
        elif event.type == "response.reasoning_summary_text.delta":
            delta["reasoning_content"] = event.delta
        elif event.type == "response.output_item.added" and event.item.type == "function_call":
            item = event.item
            calls[item.id] = (len(calls), item.call_id, item.name)
            arguments[item.id] = item.arguments or ""
            delta["tool_calls"] = [{"index": calls[item.id][0], "id": item.call_id, "type": "function",
                                    "function": {"name": item.name, "arguments": item.arguments or ""}}]
        elif event.type == "response.function_call_arguments.delta":
            if event.item_id not in calls:
                raise ValueError("Responses tool arguments arrived without a function call")
            index, _, _ = calls[event.item_id]
            arguments[event.item_id] += event.delta
            delta["tool_calls"] = [{"index": index, "function": {"arguments": event.delta}}]
        elif event.type == "response.completed":
            completion = _completion_from_response(event.response)
            choice = completion.choices[0]
            received = [(call_id, name, arguments[item_id]) for item_id, (_, call_id, name) in calls.items()]
            expected = [(call.id, call.function.name, call.function.arguments) for call in choice.message.tool_calls or []]
            if received != expected:
                raise ValueError("Responses stream function calls do not match the completed response")
            delta["responses_reasoning"] = choice.message.responses_reasoning
            usage = completion.usage.model_dump() if completion.usage else None
            finish_reason = choice.finish_reason
            terminal = True
        elif event.type == "response.incomplete":
            _completion_from_response(event.response)
            raise RuntimeError("Responses stream ended with an incomplete response")
        elif event.type in {"response.failed", "error"}:
            raise RuntimeError(f"Responses stream failed: {event.type}")
        else:
            continue
        yield ChatCompletionChunk.model_validate({
            "id": "", "object": "chat.completion.chunk", "created": 0, "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}], "usage": usage,
        })
    if not terminal:
        raise IncompleteStreamError("Responses stream ended before completion")


async def _completion_chunks(stream: Any, model: str, *, responses: bool) -> AsyncIterator[Any]:
    try:
        if responses:
            async for chunk in _response_chunks(stream, model):
                yield chunk
        else:
            service_tier = None
            finish_reason = None
            usage = None
            async for chunk in stream:
                service_tier = getattr(chunk, "service_tier", None) or service_tier
                if getattr(chunk, "usage", None) is not None:
                    chunk.usage.service_tier = service_tier
                    usage = chunk.usage
                if getattr(chunk, "choices", None):
                    finish_reason = getattr(chunk.choices[0], "finish_reason", None) or finish_reason
                yield chunk
            if finish_reason == "length":
                raise OutputLimitReached(usage, usage_format="openai")
            if finish_reason is None:
                raise IncompleteStreamError("Chat completion stream ended before completion")
    finally:
        if hasattr(stream, "close"):
            await stream.close()
        elif hasattr(stream, "aclose"):
            await stream.aclose()


async def create_completion(client: Any, **kwargs: Any) -> Any:
    """Select the native endpoint and keep one internal completion shape."""
    if kwargs.get("max_tokens") is None:
        kwargs.pop("max_tokens", None)
    model = _model_family(kwargs["model"])
    if model.startswith(("kimi-k3.1", "minimax-m3.1-flash")):
        for key in ("temperature", "top_p", "n", "presence_penalty", "frequency_penalty"):
            kwargs.pop(key, None)
    if model.startswith("mimo-v2.6"):
        if kwargs.get("extra_body", {}).get("thinking", {}).get("type") != "disabled":
            kwargs.pop("temperature", None)
            kwargs.pop("top_p", None)
    responses = _requires_responses(model, kwargs)
    if responses:
        result = await client.responses.create(**_responses_kwargs(kwargs))
    else:
        reasoning_chat = _OPENAI_REASONING_CHAT.match(model)
        if "max_tokens" in kwargs and (
            reasoning_chat or model.startswith(("mimo-v2.6", "kimi-k3.1", "minimax-m3", "grok-4"))
        ):
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
        if reasoning_chat:
            default_effort = "none" if model in _DEFAULT_EFFORT_NONE else "medium"
            if kwargs.get("reasoning_effort", default_effort) != "none":
                for key in ("temperature", "top_p", "logprobs", "top_logprobs"):
                    kwargs.pop(key, None)
        kwargs["messages"] = [{k: v for k, v in message.items() if k != "responses_reasoning"}
                              for message in kwargs["messages"]]
        result = await client.chat.completions.create(**kwargs)
    if kwargs.get("stream"):
        return _completion_chunks(result, kwargs["model"], responses=responses)
    if responses:
        return _completion_from_response(result)
    if getattr(result, "choices", None) and getattr(result.choices[0], "finish_reason", None) == "length":
        raise OutputLimitReached(getattr(result, "usage", None), usage_format="openai")
    return result
