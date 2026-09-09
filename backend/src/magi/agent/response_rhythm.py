"""Conversation rhythm segmentation for assistant responses."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Any

from magi.config import get_user_preference
from magi.agent.task_agents.common import AssistantResponsePlan, AssistantResponseSegment

_MAX_SEGMENTS = 6
_CJK_MS = 50
_LATIN_MS = 10
_FLOOR_MS = 1000
_CEIL_MS = 4000
_JITTER = 0.20
_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
SEGMENT_SENTINEL = "‖"
_LIST_ITEM_RE = re.compile(r"(?m)^\s*(?:[-*+]\s+|\d+[.)、]\s+|[一二三四五六七八九十]+[、.]\s*)")
_TABLE_ROW_RE = re.compile(r"(?m)^\s*\|[^\n|]+(?:\|[^\n|]+)+\|\s*$")
_CONFIG_LINE_RE = re.compile(r"(?m)^\s{0,4}[A-Za-z_][\w.-]*:\s+\S+")
_COMMAND_LINE_RE = re.compile(
    r"(?m)^\s*(?:\$\s+|(?:npm|pnpm|yarn|pip|pytest|python|uvicorn|cargo|git|docker|tauri)\b\s+)"
)
_STACK_TRACE_RE = re.compile(
    r"(?m)^\s*(?:Traceback \(most recent call last\)|File \".+\", line \d+|[A-Za-z0-9_.]+(?:Error|Exception):)"
)


def _compute_delay_ms(
    segment_text: str,
    *,
    rng: Any = None,
) -> int:
    """Estimate a human-like inter-bubble delay from the segment's own length.

    Models the time the sender spends "typing" this bubble: CJK chars are full
    units, latin chars are lighter. Result is jittered then clamped to a
    believable window so a long follow-up pauses longer and a short one snaps in.
    """
    text = str(segment_text or "")
    n_cjk = sum(1 for ch in text if _CJK_RE.match(ch))
    n_latin = sum(1 for ch in text if not ch.isspace() and not _CJK_RE.match(ch))
    base = n_cjk * _CJK_MS + n_latin * _LATIN_MS
    source = rng if rng is not None else random
    jitter = source.uniform(1.0 - _JITTER, 1.0 + _JITTER)
    value = base * jitter
    return int(max(_FLOOR_MS, min(value, _CEIL_MS)))


def split_on_sentinel(text: str) -> list[str]:
    """Split a core-LLM reply on the internal bubble boundary marker."""
    return [part.strip() for part in str(text or "").split(SEGMENT_SENTINEL) if part.strip()]


def strip_segmentation_sentinel(text: str) -> str:
    """Remove residual bubble markers before text reaches history or channels."""
    raw_text = str(text or "")
    if SEGMENT_SENTINEL not in raw_text:
        return raw_text
    parts = split_on_sentinel(raw_text)
    if not parts:
        return ""
    newline_joined = "\n".join(parts)
    if _detect_content_features(response_text=newline_joined).has_protected_structure:
        return newline_joined.strip()
    collapsed = " ".join(parts)
    return re.sub(r"[ \t]{2,}", " ", collapsed).strip()


def is_conversation_rhythm_enabled() -> bool:
    return bool(get_user_preference("conversation_rhythm_enabled", True))


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


class ResponseRhythmPlanner:
    """Build an internal multi-message presentation plan from final text."""

    async def plan(
        self,
        *,
        response_text: str,
        streamed: bool = False,
        ux_plan: dict[str, Any] | None = None,
    ) -> AssistantResponsePlan | None:
        if streamed or not self._is_enabled():
            return None
        if str((ux_plan or {}).get("assistant_surface_mode") or "final_only").strip() in {"none", "reaction_only"}:
            return None
        parts = split_on_sentinel(response_text)
        if len(parts) < 2 or len(parts) > _MAX_SEGMENTS:
            return None
        if _detect_content_features(response_text="\n".join(parts)).has_protected_structure:
            return None

        segments: list[AssistantResponseSegment] = []
        for index, content in enumerate(parts):
            delay_ms = 0 if index == 0 else _compute_delay_ms(content)
            segments.append(
                AssistantResponseSegment(
                    content=content,
                    intent="answer",
                    delay_ms=delay_ms,
                    segment_index=index,
                    source_unit_ids=[f"s{index + 1}"],
                )
            )
        return AssistantResponsePlan(
            mode="multi_message",
            aggregate_text="\n".join(parts),
            segments=segments,
        )

    @staticmethod
    def _is_enabled() -> bool:
        return is_conversation_rhythm_enabled()

    @staticmethod
    def _detect_content_features(*, response_text: str) -> _ContentFeatures:
        return _detect_content_features(response_text=response_text)


__all__ = [
    "ResponseRhythmPlanner",
    "is_conversation_rhythm_enabled",
    "split_on_sentinel",
    "strip_segmentation_sentinel",
]
