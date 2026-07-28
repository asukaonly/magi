"""Normalization of generated conversation registers and examples."""

from __future__ import annotations

from typing import Any, Dict

from .constants import REQUIRED_REGISTERS
from .normalization_primitives import (
    _ensure_dict,
    _string_field,
    _string_list,
)


REGISTER_ALIASES = {
    "ordinary": "chat",
    "ordinary_conversation": "chat",
    "casual": "chat",
    "daily": "chat",
    "daily_conversation": "chat",
    "conversation": "chat",
    "work": "task",
    "execution": "task",
    "task_execution": "task",
    "tool_use": "task",
    "planning": "analysis",
    "deep_analysis": "analysis",
    "support": "emotional",
    "emotional_support": "emotional",
    "care": "emotional",
    "safety": "crisis",
    "urgent": "crisis",
    "emergency": "crisis",
}


def _default_register(
    register: str,
    use_chinese: bool = False,
) -> dict[str, Any]:
    defaults = {
        "chat": (
            "Daily conversation and casual check-ins",
            "Keep personality low-intensity and ordinary; answer naturally without turning every reply into a performance.",
        ),
        "analysis": (
            "Deep discussion, planning, comparison, architecture, and synthesis",
            "Reason clearly, keep a visible point of view, and make personality secondary to judgment and usefulness.",
        ),
        "task": (
            "Execution, tool use, coding, debugging, and operational work",
            "Solve first, give concise progress updates, and keep style restrained while work is active.",
        ),
        "emotional": (
            "User vulnerability, fatigue, frustration, or support needs",
            "Lower sharpness, increase steadiness and care, and avoid using personality as a shield from the user's need.",
        ),
        "crisis": (
            "Safety, privacy, security, urgent risk, or high-stakes help",
            "Drop performance and give short, concrete, operational guidance with calm boundaries.",
        ),
    }
    chinese_defaults = {
        "chat": (
            "日常聊天和随口的问候",
            "保持低强度、平常的存在感；自然地回应，不把每条回复都变成表演。",
        ),
        "analysis": (
            "深入讨论、规划、比较、架构与综合判断",
            "清晰地推理，保留自己的观点，让风格让位于判断和实用性。",
        ),
        "task": (
            "执行、工具使用、写码、调试与操作性工作",
            "先解决问题，进展汇报简洁，工作进行中收敛风格。",
        ),
        "emotional": (
            "用户脆弱、疲惫、沮丧或需要支持",
            "收起锋利，语气放稳，多一分体贴，不用性格挡开用户的需要。",
        ),
        "crisis": (
            "安全、隐私、防护、紧急风险或高风险求助",
            "放下表演，给出简短、具体、可执行的指引，保持冷静的边界。",
        ),
    }
    description, behavior = (chinese_defaults if use_chinese else defaults)[register]
    return {
        "description": description,
        "behavior": behavior,
        "examples": [],
    }


def _normalize_register_id(
    value: Any,
    default_register: str = "chat",
) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in REQUIRED_REGISTERS:
        return normalized
    return REGISTER_ALIASES.get(normalized, default_register)


def _stringify_runtime_example(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return _string_field(value)

    user_text = _string_field(
        value.get("user_input") or value.get("user") or value.get("input") or value.get("prompt")
    )
    assistant_text = _string_field(
        value.get("assistant_output")
        or value.get("assistant_reply")
        or value.get("assistant")
        or value.get("reply")
        or value.get("response")
        or value.get("good_response")
        or value.get("output")
    )
    if assistant_text:
        return (
            f"[User: {user_text}]\nGood: {assistant_text}"
            if user_text
            else f"Good: {assistant_text}"
        )
    return _string_field(value.get("text") or value.get("example"))


def _collect_register_examples(
    value: Any,
    default_register: str,
) -> list[tuple[str, str]]:
    collected: list[tuple[str, str]] = []
    if isinstance(value, list):
        for item in value:
            collected.extend(
                _collect_register_examples(
                    item,
                    default_register,
                )
            )
        return collected

    if isinstance(value, dict):
        register = _normalize_register_id(
            value.get("register")
            or value.get("register_id")
            or value.get("mode")
            or value.get("category"),
            default_register,
        )
        if "examples" in value:
            collected.extend(
                _collect_register_examples(
                    value.get("examples"),
                    register,
                )
            )
            return collected
        example = _stringify_runtime_example(value)
        if example:
            collected.append((register, example))
        return collected

    example = _stringify_runtime_example(value)
    if example:
        collected.append((default_register, example))
    return collected


def _append_register_examples(
    registers: dict[str, Any],
    value: Any,
    default_register: str,
) -> None:
    for register, example in _collect_register_examples(
        value,
        default_register,
    ):
        item = registers.get(register)
        if not isinstance(item, dict):
            item = {}
            registers[register] = item
        examples = _string_list(item.get("examples"))
        if example not in examples:
            examples.append(example)
        item["examples"] = examples


def _complete_registers(
    payload: Dict[str, Any],
    use_chinese: bool = False,
) -> None:
    registers = _ensure_dict(payload, "registers")
    _append_register_examples(
        registers,
        registers.pop("examples", None),
        "chat",
    )
    for register, item in list(registers.items()):
        if not isinstance(item, dict):
            registers.pop(register, None)
    for register in REQUIRED_REGISTERS:
        item = registers.get(register)
        if not isinstance(item, dict):
            item = {}
            registers[register] = item
        defaults = _default_register(register, use_chinese)
        raw_examples = item.get("examples")
        item["description"] = _string_field(
            item.get("description"),
            defaults["description"],
        )
        item["behavior"] = _string_field(
            item.get("behavior"),
            defaults["behavior"],
        )
        item["examples"] = []
        _append_register_examples(
            registers,
            raw_examples,
            register,
        )
