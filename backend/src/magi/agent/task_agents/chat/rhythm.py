"""Conversation rhythm planning for chat responses."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ....config import get_user_preference
from ....core.logger import get_logger
from ..common import AssistantResponsePlan, AssistantResponseSegment

logger = get_logger(__name__)

_MAX_SEGMENTS = 3
_MAX_UNITS = 12
_MIN_CONTENT_CHARS = 120
_MIN_CJK_CONTENT_CHARS = 48
_MIN_UNITS_FOR_RHYTHM = 2
_MIN_DELAY_MS = 1000
_DEFAULT_DELAY_MS = 1200
_MAX_DELAY_MS = 2400
_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_MARKDOWN_LIST_LINE_RE = re.compile(r"(?m)^\s{0,3}(?:[-*+]\s+|\d+[.)]\s+)")
_LIST_ITEM_RE = re.compile(r"(?m)^\s*(?:[-*+]\s+|\d+[.)、]\s+|[一二三四五六七八九十]+[、.]\s*)")
_TABLE_ROW_RE = re.compile(r"(?m)^\s*\|[^\n|]+(?:\|[^\n|]+)+\|\s*$")
_CONFIG_LINE_RE = re.compile(r"(?m)^\s{0,4}[A-Za-z_][\w.-]*:\s+\S+")
_COMMAND_LINE_RE = re.compile(
    r"(?m)^\s*(?:\$\s+|(?:npm|pnpm|yarn|pip|pytest|python|uvicorn|cargo|git|docker|tauri)\b\s+)"
)
_STACK_TRACE_RE = re.compile(
    r"(?m)^\s*(?:Traceback \(most recent call last\)|File \".+\", line \d+|[A-Za-z0-9_.]+(?:Error|Exception):)"
)


def is_conversation_rhythm_enabled() -> bool:
    enabled = get_user_preference("conversation_rhythm_enabled", True)
    mode = str(get_user_preference("conversation_rhythm_mode", "natural") or "natural").strip().lower()
    if mode == "off":
        return False
    if isinstance(enabled, bool):
        return enabled and mode in {"natural", "expressive"}
    if isinstance(enabled, str):
        normalized_enabled = enabled.strip().lower()
        if normalized_enabled in {"0", "false", "no", "off"}:
            return False
        if normalized_enabled in {"1", "true", "yes", "on"}:
            return mode in {"natural", "expressive"}
    return mode in {"natural", "expressive"}


@dataclass(slots=True)
class _RhythmUnit:
    unit_id: str
    text: str


@dataclass(slots=True)
class _ContentFeatures:
    has_code_block: bool
    has_table: bool
    has_command_block: bool
    has_config_block: bool
    has_stack_trace: bool
    list_item_count: int

    @property
    def has_protected_structure(self) -> bool:
        if self.has_code_block or self.has_table or self.has_command_block or self.has_config_block:
            return True
        if self.has_stack_trace:
            return True
        return self.list_item_count >= 3


class ResponseRhythmPlanner:
    """Build an internal multi-message presentation plan from final text."""

    def __init__(self, *, prompt_service: Any) -> None:
        self._prompt_service = prompt_service

    async def plan(
        self,
        *,
        user_message: str,
        response_text: str,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        streamed: bool = False,
    ) -> AssistantResponsePlan | None:
        if streamed or not self._is_enabled():
            return None
        if str((ux_plan or {}).get("assistant_surface_mode") or "final_only").strip() in {"none", "reaction_only"}:
            return None
        normalized_response = str(response_text or "").strip()
        if len(normalized_response) < self._min_content_chars(normalized_response):
            return None
        content_features = self._detect_content_features(
            response_text=normalized_response,
        )
        if content_features.has_protected_structure:
            return None
        units = self._split_units(normalized_response)
        if len(units) < _MIN_UNITS_FOR_RHYTHM or len(units) > _MAX_UNITS:
            return None
        try:
            raw_plan = await self._prompt_service.call_llm(
                system_prompt=self._build_system_prompt(),
                messages=[
                    {
                        "role": "user",
                        "content": self._build_user_payload(
                            user_message=user_message,
                            response_text=normalized_response,
                            execution_mode=execution_mode,
                            units=units,
                            content_features=content_features,
                        ),
                    }
                ],
                disable_thinking=True,
                json_mode=True,
                timeout_seconds=8.0,
                event_context={
                    "request_kind": "task_agent:chat_rhythm",
                    "agent_id": "chat_rhythm",
                },
            )
        except Exception as exc:
            logger.debug("Conversation rhythm planner call failed", error=str(exc))
            return None
        return self._parse_plan(
            raw_plan,
            units=units,
            aggregate_text=normalized_response,
        )

    @staticmethod
    def _is_enabled() -> bool:
        return is_conversation_rhythm_enabled()

    @staticmethod
    def _min_content_chars(response_text: str) -> int:
        return _MIN_CJK_CONTENT_CHARS if _CJK_RE.search(response_text) else _MIN_CONTENT_CHARS

    @staticmethod
    def _split_units(response_text: str) -> list[_RhythmUnit]:
        if "```" in response_text:
            return []
        if _MARKDOWN_LIST_LINE_RE.search(response_text):
            return []
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", response_text) if part.strip()]
        if len(paragraphs) < 2:
            paragraphs = [part.strip() for part in re.split(r"\n+", response_text) if part.strip()]
        if len(paragraphs) < 2:
            paragraphs = [
                part.strip()
                for part in re.split(r"(?<=[。！？])\s*|(?<=[.!?])\s+", response_text)
                if part.strip()
            ]
        units: list[_RhythmUnit] = []
        for index, text in enumerate(paragraphs, start=1):
            if not text:
                continue
            units.append(_RhythmUnit(unit_id=f"u{index}", text=text))
        return units

    @staticmethod
    def _detect_content_features(*, response_text: str) -> _ContentFeatures:
        config_line_count = len(_CONFIG_LINE_RE.findall(response_text))
        table_row_count = len(_TABLE_ROW_RE.findall(response_text))
        return _ContentFeatures(
            has_code_block="```" in response_text,
            has_table=table_row_count >= 2,
            has_command_block=bool(_COMMAND_LINE_RE.search(response_text)),
            has_config_block=config_line_count >= 2,
            has_stack_trace=bool(_STACK_TRACE_RE.search(response_text)),
            list_item_count=len(_LIST_ITEM_RE.findall(response_text)),
        )

    @staticmethod
    def _build_system_prompt() -> str:
        return """You are an internal chat presentation planner.

You do not answer the user. You only decide how to display an already finished assistant answer as one to three chat bubbles.

Rules:
- Output valid JSON only.
- Do not rewrite, summarize, translate, add, or remove user-visible content.
- Use only the provided unit ids.
- Cover every unit exactly once, in the original order.
- Use at most three groups.
- Prefer one group unless multiple units are truly separate conversational moves.
- Prefer two groups for most splittable answers.
- Use three groups only for long answers with three distinct moves; never split into three just because three sentence units exist.
- Use one group when the answer is short, terse, transactional, or splitting would hurt meaning.
- Technical explanations, architecture notes, implementation plans, API/protocol/configuration details, debugging analysis, and source-code-related answers should usually be one group. If a technical answer is conversational enough to split, use at most two groups and keep the technical body intact.
- Never add fake hesitation, filler, or dramatic pauses; every group must carry useful content.
- Delays must be integers between 1000 and 2400 milliseconds except the first group.
- The first group delay should be 0.

Schema:
{
  "groups": [
    {"unit_ids": ["u1"], "intent": "acknowledge|answer|explain|tradeoff|next_step|afterthought", "delay_ms": 0}
  ]
}
""".strip()

    @staticmethod
    def _build_user_payload(
        *,
        user_message: str,
        response_text: str,
        execution_mode: str | None,
        units: list[_RhythmUnit],
        content_features: _ContentFeatures,
    ) -> str:
        payload = {
            "user_message": str(user_message or ""),
            "execution_mode": execution_mode,
            "canonical_answer": response_text,
            "content_features": {
                "protected_structure": content_features.has_protected_structure,
                "has_table": content_features.has_table,
                "has_command_block": content_features.has_command_block,
                "has_config_block": content_features.has_config_block,
                "has_stack_trace": content_features.has_stack_trace,
                "list_item_count": content_features.list_item_count,
            },
            "units": [{"id": unit.unit_id, "text": unit.text} for unit in units],
        }
        return json.dumps(payload, ensure_ascii=False)

    def _parse_plan(
        self,
        raw_plan: str,
        *,
        units: list[_RhythmUnit],
        aggregate_text: str,
    ) -> AssistantResponsePlan | None:
        try:
            parsed = json.loads(str(raw_plan or "").strip())
        except json.JSONDecodeError:
            logger.debug("Conversation rhythm planner returned invalid JSON")
            return None
        if not isinstance(parsed, dict):
            return None
        groups = parsed.get("groups")
        if not isinstance(groups, list) or not groups:
            return None
        if len(groups) > _MAX_SEGMENTS:
            return None
        if len(groups) >= 3 and len(aggregate_text) < self._min_three_segment_chars(aggregate_text):
            return None

        unit_lookup = {unit.unit_id: unit for unit in units}
        expected_ids = [unit.unit_id for unit in units]
        flattened_ids: list[str] = []
        segments: list[AssistantResponseSegment] = []
        for index, group in enumerate(groups):
            if not isinstance(group, dict):
                return None
            raw_unit_ids = group.get("unit_ids")
            if not isinstance(raw_unit_ids, list) or not raw_unit_ids:
                return None
            unit_ids = [str(unit_id).strip() for unit_id in raw_unit_ids if str(unit_id).strip()]
            if not unit_ids or any(unit_id not in unit_lookup for unit_id in unit_ids):
                return None
            flattened_ids.extend(unit_ids)
            content = self._join_group_content([unit_lookup[unit_id] for unit_id in unit_ids])
            if not content:
                return None
            delay_ms = self._coerce_delay_ms(group.get("delay_ms"), first=index == 0)
            intent = self._normalize_intent(group.get("intent"))
            segments.append(
                AssistantResponseSegment(
                    content=content,
                    intent=intent,
                    delay_ms=delay_ms,
                    segment_index=index,
                    source_unit_ids=unit_ids,
                )
            )
        if flattened_ids != expected_ids:
            return None
        if len(segments) < 2:
            return None
        return AssistantResponsePlan(
            mode="multi_message",
            aggregate_text=aggregate_text,
            segments=segments,
        )

    @staticmethod
    def _coerce_delay_ms(value: Any, *, first: bool) -> int:
        if first:
            return 0
        try:
            delay = int(value)
        except (TypeError, ValueError):
            delay = _DEFAULT_DELAY_MS
        return max(_MIN_DELAY_MS, min(delay, _MAX_DELAY_MS))

    @staticmethod
    def _min_three_segment_chars(response_text: str) -> int:
        return 120 if _CJK_RE.search(response_text) else 260

    @staticmethod
    def _normalize_intent(value: Any) -> str:
        intent = str(value or "answer").strip().lower()
        allowed = {"acknowledge", "answer", "explain", "tradeoff", "next_step", "afterthought"}
        return intent if intent in allowed else "answer"

    @staticmethod
    def _join_group_content(units: list[_RhythmUnit]) -> str:
        return "\n".join(unit.text.strip() for unit in units if unit.text.strip()).strip()


__all__ = ["ResponseRhythmPlanner", "is_conversation_rhythm_enabled"]
