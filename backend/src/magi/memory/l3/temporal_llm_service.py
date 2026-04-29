"""Rule-side helpers for temporal L3 LLM summarization."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import Counter
from typing import Any

from ...config.loader import get_user_preference
from ...llm import LLMProviderBridge, LLMScenario, ScenarioLLMPool
from magi_plugin_sdk.i18n import get_current_language
from .models import (
    L3Candidate,
    TemporalEvidenceItem,
    TemporalEvidencePack,
    TemporalGenerationResult,
    TemporalSummaryLLMOutput,
)

logger = logging.getLogger(__name__)
_TOP_TERM_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")
_LATIN_WORD_PATTERN = re.compile(r"[A-Za-z]{3,}")
_SOURCE_LABELS_ZH = {
    "chat": "对话",
    "chrome_history": "浏览记录",
    "git_activity": "Git 活动",
    "system_media": "媒体播放",
    "netease_music": "网易云音乐",
    "calendar": "日历",
    "terminal_history": "终端记录",
}
_EVENT_TYPE_LABELS_ZH = {
    "UserMessage": "用户消息",
    "AIResponse": "助手回复",
    "TimelineEvent": "时间线事件",
    "TaskCompleted": "任务完成",
    "TaskCreated": "任务创建",
}
_STOP_TERMS = {
    "about",
    "after",
    "and",
    "are",
    "care",
    "but",
    "for",
    "from",
    "have",
    "into",
    "job",
    "jobs",
    "just",
    "more",
    "posts",
    "read",
    "several",
    "than",
    "that",
    "the",
    "their",
    "them",
    "they",
    "this",
    "want",
    "with",
    "year",
    "you",
    "your",
}
_CONSTRAINT_KEYWORDS = {
    "avoid",
    "budget",
    "cannot",
    "deadline",
    "hybrid",
    "must",
    "need",
    "prefer",
    "priority",
    "remote",
    "salary",
    "should",
    "time",
}
_LEGACY_FLAT_TIMEOUT_SECONDS = 3.0
_PERIOD_TIMEOUT_SECONDS = {
    "hour": 180.0,
    "day": 300.0,
    "week": 600.0,
    "month": 600.0,
    "quarter": 600.0,
    "year": 600.0,
}
_PERIOD_DISABLE_THINKING = {
    "hour": True,
    "day": False,
    "week": False,
    "month": False,
    "quarter": False,
    "year": False,
}
_PERIOD_FOCUS_INSTRUCTIONS = {
    "hour": (
        "- Hour focus: capture the local sequence, immediate context, and short-lived shifts inside this hour.\n"
        "- Avoid turning one hour of activity into a durable preference or long-term trend."
    ),
    "day": (
        "- Day focus: identify the main blocks of the day, attention shifts, explicit decisions, and repeated constraints.\n"
        "- Separate meaningful patterns from ordinary single-event noise."
    ),
    "week": (
        "- Week focus: synthesize durable themes, recurring interests, cross-source patterns, and notable changes across the week.\n"
        "- Prefer pattern-level interpretation over listing events one by one."
    ),
    "month": (
        "- Month focus: synthesize cross-week themes, stage changes, sustained interests, project progress, and unusually frequent activities across the month.\n"
        "- Prefer a timeline-oriented month recap over listing weekly summaries one by one."
    ),
    "quarter": (
        "- Long-window focus: synthesize durable themes, recurring interests, cross-source patterns, and notable changes across the window.\n"
        "- Prefer pattern-level interpretation over listing events one by one."
    ),
    "year": (
        "- Long-window focus: synthesize durable themes, recurring interests, cross-source patterns, and notable changes across the window.\n"
        "- Prefer pattern-level interpretation over listing events one by one."
    ),
}
_PERIOD_LABELS_ZH = {
    "hour": "这一小时",
    "day": "这一天",
    "week": "这一周",
    "month": "这个月",
    "quarter": "这个季度",
    "year": "这一年",
}


def _target_language_code() -> str:
    preferred = get_user_preference("language", None)
    language = str(preferred or get_current_language() or "en").lower()
    return "zh" if language.startswith("zh") else "en"


def _target_language_label() -> str:
    return "Simplified Chinese (zh-CN)" if _target_language_code() == "zh" else "English"


def _target_language_instruction() -> str:
    target = _target_language_label()
    return (
        f"- The target language is {target}.\n"
        f"- Write every user-facing generated field in {target}: content, key_topics, "
        "sentiment_summary natural-language strings, and change_and_pattern strings.\n"
        "- This language rule is mandatory even when evidence, rule_hints, or plugin_summary_features are written in another language.\n"
        "- Preserve event ids, entity ids, URLs, file paths, source names, product names, song titles, and quoted user text as evidence presents them."
    )


def _render_temporal_summary_system_prompt() -> str:
    return (
        TEMPORAL_SUMMARY_SYSTEM_PROMPT
        + "\nLanguage Rules:\n"
        + f"- Target language: {_target_language_label()}.\n"
        + "- All user-facing JSON string values MUST use the target language.\n"
        + "- Evidence text may be in another language; summarize it in the target language unless preserving a name, URL, ID, path, title, or direct quote.\n"
    )

TEMPORAL_SUMMARY_SYSTEM_PROMPT = """You generate temporal memory summaries for a local-first agent.

Rules:
- Use only the supplied evidence pack.
- Compress repetition and surface concrete changes, priorities, and recurring patterns.
- Do not invent entity ids, event ids, preferences, or psychological diagnoses.
- Return a JSON object with: content, key_topics, key_entities, sentiment_summary, change_and_pattern, importance_aggregate.
- If evidence is weak, stay conservative and summarize only explicit content.
"""

TEMPORAL_SUMMARY_OUTPUT_SCHEMA = {
    "content": "A concise temporal recap grounded in the evidence pack.",
    "key_topics": ["short_topic_label"],
    "key_entities": [{"entity_id": "optional_entity_id", "entity_type": "optional_entity_type"}],
    "sentiment_summary": {"tone": "optional_tone", "stress_level": 0.0},
    "change_and_pattern": {
        "changes": ["explicit shift observed in the window"],
        "patterns": ["recurring behavior or constraint grounded in evidence"],
    },
    "importance_aggregate": 0.0,
}


class TemporalSummaryLLMService:
    """Builds temporal evidence packs and later will host LLM generation helpers."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        llm_timeout_seconds: float = 3.0,
        min_event_count_for_llm: int = 2,
        scenario_llm_pool: ScenarioLLMPool | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        normalized_timeout = float(llm_timeout_seconds)
        self._llm_timeout_seconds = (
            None if normalized_timeout == _LEGACY_FLAT_TIMEOUT_SECONDS else normalized_timeout
        )
        self._min_event_count_for_llm = max(1, int(min_event_count_for_llm))
        self._scenario_llm_pool = scenario_llm_pool

    def build_evidence_pack(
        self,
        *,
        events: list[dict[str, Any]],
        summary_category: str,
        period_start: float,
        period_end: float,
    ) -> TemporalEvidencePack:
        """Build a compact evidence pack from already-fetched L1 events."""
        kept_events = [
            event
            for event in events
            if str(event.get("memory_domain") or "") != "runtime_telemetry"
            and str(event.get("retention_class") or "") != "disposable"
        ]
        evidence_items = [
            TemporalEvidenceItem(
                event_id=str(event.get("event_id") or ""),
                event_type=str(event.get("event_type") or ""),
                content=str(event.get("content") or ""),
                timestamp=float(event["timestamp"]) if event.get("timestamp") is not None else None,
                memory_domain=str(event.get("memory_domain") or "") or None,
                importance_score=float(event["importance_score"]) if event.get("importance_score") is not None else None,
            )
            for event in kept_events
            if str(event.get("event_id") or "").strip()
        ]
        source_event_ids = [item.event_id for item in evidence_items]
        importance_values = [item.importance_score for item in evidence_items if item.importance_score is not None]
        event_type_distribution: dict[str, int] = {}
        for item in evidence_items:
            event_type_distribution[item.event_type] = event_type_distribution.get(item.event_type, 0) + 1
        return TemporalEvidencePack(
            summary_category=summary_category,  # type: ignore[arg-type]
            period_start=float(period_start),
            period_end=float(period_end),
            source_event_count=len(source_event_ids),
            source_event_ids=source_event_ids,
            events=evidence_items,
            importance_aggregate=(sum(importance_values) / len(importance_values)) if importance_values else None,
            event_type_distribution=event_type_distribution,
            rule_hints=self._build_rule_hints(evidence_items, event_type_distribution),
        )

    def parse_llm_output(
        self,
        payload: dict[str, Any],
        *,
        pack: TemporalEvidencePack,
    ) -> tuple[L3Candidate, dict[str, Any]]:
        """Parse structured temporal LLM output into an L3 candidate and summary overrides."""
        content = str(payload.get("content") or "").strip()
        if not content:
            raise ValueError("Temporal LLM output requires non-empty content")
        output = TemporalSummaryLLMOutput(
            content=content,
            key_topics=[str(item).strip() for item in payload.get("key_topics", []) if str(item).strip()],
            key_entities=[
                item
                for item in payload.get("key_entities", [])
                if isinstance(item, dict)
            ],
            sentiment_summary=self._normalize_sentiment_summary(payload.get("sentiment_summary")),
            change_and_pattern=self._normalize_change_and_pattern(payload.get("change_and_pattern")),
            importance_aggregate=self._normalize_importance_aggregate(payload.get("importance_aggregate")),
        )
        self._validate_target_language(output)
        candidate = L3Candidate(
            summary_type="temporal",
            summary_category=pack.summary_category,
            content=output.content,
            source_event_ids=list(pack.source_event_ids),
        )
        summary_overrides: dict[str, Any] = {
            "key_topics": list(output.key_topics),
            "key_entities": list(output.key_entities),
            "sentiment_summary": output.sentiment_summary,
            "change_and_pattern": output.change_and_pattern,
        }
        if output.importance_aggregate is not None:
            summary_overrides["importance_aggregate"] = output.importance_aggregate
        return candidate, summary_overrides

    async def generate_temporal_candidate(
        self,
        pack: TemporalEvidencePack,
        *,
        fallback_summary: str,
    ) -> TemporalGenerationResult:
        """Try the model path and fall back to a rule summary on failure."""
        fallback = self._build_fallback_result(pack, fallback_summary)
        if not self._enabled:
            return fallback
        if pack.source_event_count < self._min_event_count_for_llm:
            return fallback
        timeout_seconds = self._timeout_seconds_for_pack(pack)
        disable_thinking = self._disable_thinking_for_pack(pack)
        try:
            payload = await asyncio.wait_for(
                self._call_temporal_model(
                    pack,
                    timeout_seconds=timeout_seconds,
                    disable_thinking=disable_thinking,
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "L3 temporal LLM call timed out",
                extra={
                    "summary_category": pack.summary_category,
                    "event_count": pack.source_event_count,
                    "timeout_seconds": timeout_seconds,
                    "thinking_enabled": not disable_thinking,
                },
            )
            return fallback
        except Exception:
            return fallback
        if not isinstance(payload, dict):
            return fallback
        try:
            candidate, summary_overrides = self.parse_llm_output(payload, pack=pack)
        except Exception:
            return fallback
        return TemporalGenerationResult(
            candidate=candidate,
            summary_overrides=summary_overrides,
            used_fallback=False,
        )

    async def _call_temporal_model(
        self,
        pack: TemporalEvidencePack,
        *,
        timeout_seconds: float | None = None,
        disable_thinking: bool | None = None,
    ) -> dict[str, Any] | None:
        """Model hook for temporal summary generation.

        The default implementation is intentionally inert until a real LLM caller
        is wired in by a later task.
        """
        llm_target = self._get_llm_target()
        if llm_target is None:
            return None
        resolved_timeout_seconds = timeout_seconds or self._timeout_seconds_for_pack(pack)
        resolved_disable_thinking = (
            disable_thinking if disable_thinking is not None else self._disable_thinking_for_pack(pack)
        )
        adapter, provider_bridge = llm_target
        prompt = self._render_temporal_summary_prompt(pack)
        system_prompt = _render_temporal_summary_system_prompt()
        started_at = time.perf_counter()
        provider = str(getattr(adapter, "provider_name", "unknown") or "unknown")
        model = str(getattr(adapter, "model_name", "unknown") or "unknown")
        log_context = {
            "request_kind": "memory:l3_temporal_summary",
            "provider": provider,
            "model": model,
            "event_count": pack.source_event_count,
            "summary_category": pack.summary_category,
            "timeout_seconds": resolved_timeout_seconds,
            "thinking_enabled": not resolved_disable_thinking,
        }
        logger.info("L3 temporal LLM call started", extra=log_context)
        try:
            response = await provider_bridge.chat_response(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                json_mode=True,
                disable_thinking=resolved_disable_thinking,
                timeout_seconds=resolved_timeout_seconds,
                event_context={
                    "request_kind": "memory:l3_temporal_summary",
                    "turn_id": pack.source_event_ids[0] if pack.source_event_ids else None,
                    "agent_id": "memory:l3",
                },
            )
        except Exception as exc:
            logger.warning("L3 temporal LLM call failed", extra={**log_context, "error": str(exc)})
            raise

        raw = response.content
        logger.info(
            "L3 temporal LLM call completed",
            extra={
                **log_context,
                "duration_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
                "response_char_count": len(raw or ""),
            },
        )
        try:
            parsed = json.loads(raw)
        except Exception:
            logger.warning("L3 temporal LLM returned invalid JSON", extra=log_context)
            return None
        return parsed if isinstance(parsed, dict) else None

    def _timeout_seconds_for_pack(self, pack: TemporalEvidencePack) -> float:
        if self._llm_timeout_seconds is not None:
            return self._llm_timeout_seconds
        return _PERIOD_TIMEOUT_SECONDS.get(str(pack.summary_category), _PERIOD_TIMEOUT_SECONDS["week"])

    def _disable_thinking_for_pack(self, pack: TemporalEvidencePack) -> bool:
        return _PERIOD_DISABLE_THINKING.get(str(pack.summary_category), False)

    def _build_fallback_result(
        self,
        pack: TemporalEvidencePack,
        fallback_summary: str,
    ) -> TemporalGenerationResult:
        raw_feature_lines = self._raw_plugin_summary_lines(pack)
        target_zh = _target_language_code() == "zh"
        fallback_content = self._build_fallback_content(
            pack,
            fallback_summary=fallback_summary,
            raw_feature_lines=raw_feature_lines,
        )
        candidate = L3Candidate(
            summary_type="temporal",
            summary_category=pack.summary_category,
            content=fallback_content,
            source_event_ids=list(pack.source_event_ids),
        )
        summary_overrides: dict[str, object] = {
            "importance_aggregate": pack.importance_aggregate,
            "event_type_distribution": dict(pack.event_type_distribution),
        }
        if raw_feature_lines:
            summary_overrides["plugin_summary_features"] = dict(pack.plugin_summary_features)
        if raw_feature_lines and not target_zh:
            stitched = [fallback_content, *raw_feature_lines]
            candidate.content = "\n".join(part for part in stitched if part).strip()
        return TemporalGenerationResult(
            candidate=candidate,
            summary_overrides=summary_overrides,
            used_fallback=True,
        )

    def _raw_plugin_summary_lines(self, pack: TemporalEvidencePack) -> list[str]:
        feature_lines: list[str] = []
        for feature in pack.plugin_summary_features.values():
            if not isinstance(feature, dict):
                continue
            raw_lines = feature.get("summary_lines")
            if not isinstance(raw_lines, list):
                continue
            for item in raw_lines:
                line = str(item).strip()
                if line and line not in feature_lines:
                    feature_lines.append(line)
        return feature_lines

    def _build_fallback_content(
        self,
        pack: TemporalEvidencePack,
        *,
        fallback_summary: str,
        raw_feature_lines: list[str],
    ) -> str:
        if _target_language_code() != "zh":
            return str(fallback_summary).strip()

        period_label = _PERIOD_LABELS_ZH.get(str(pack.summary_category), "这段时间")
        source_labels = self._zh_source_labels(pack.source_distribution)
        if source_labels:
            parts = [f"{period_label}的记忆主要围绕{self._join_zh(source_labels)}展开"]
        else:
            parts = [f"{period_label}留下了一组可用于回顾的活动线索"]
        feature_lines = self._build_zh_feature_lines(pack)[:3]
        parts.extend(feature_lines)
        top_terms = self._zh_top_terms(pack)
        if top_terms and not feature_lines:
            parts.append(f"反复出现的关键词包括 {self._join_zh(top_terms)}")
        if len(parts) == 1 and _CJK_PATTERN.search(str(fallback_summary)):
            parts.append(str(fallback_summary).strip())
        if len(parts) == 1 and raw_feature_lines:
            parts.append("插件提供了结构化摘要特征，可作为后续回顾的线索")
        return "。".join(part.strip().rstrip("。") for part in parts if part.strip()) + "。"

    def _zh_source_labels(self, source_distribution: dict[str, object]) -> list[str]:
        labels: list[str] = []
        for key in source_distribution:
            label = _SOURCE_LABELS_ZH.get(str(key), str(key).replace("_", " "))
            if label and label not in labels:
                labels.append(label)
        return labels[:4]

    def _join_zh(self, values: list[str]) -> str:
        cleaned = [item.strip() for item in values if item.strip()]
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0]
        if len(cleaned) == 2:
            return "和".join(cleaned)
        return "、".join(cleaned[:-1]) + f"和{cleaned[-1]}"

    def _zh_top_terms(self, pack: TemporalEvidencePack) -> list[str]:
        raw_terms = pack.rule_hints.get("top_terms") if isinstance(pack.rule_hints, dict) else None
        if not isinstance(raw_terms, list):
            return []
        terms = [str(item).strip() for item in raw_terms if str(item).strip()]
        return terms[:4]

    def _format_zh_distribution(
        self,
        distribution: dict[str, object],
        *,
        label_map: dict[str, str],
    ) -> str:
        entries: list[str] = []
        for key, value in distribution.items():
            label = label_map.get(str(key), str(key).replace("_", " "))
            count: int | None = None
            if isinstance(value, bool):
                count = None
            elif isinstance(value, (int, float)):
                count = int(value)
            elif isinstance(value, dict):
                raw_count = value.get("count") or value.get("event_count")
                if isinstance(raw_count, (int, float)) and not isinstance(raw_count, bool):
                    count = int(raw_count)
            entries.append(f"{label} {count} 条" if count is not None else label)
        return "、".join(entries[:4])

    def _build_zh_feature_lines(self, pack: TemporalEvidencePack) -> list[str]:
        lines: list[str] = []
        for feature in pack.plugin_summary_features.values():
            if not isinstance(feature, dict):
                continue
            focus_domain = str(feature.get("focus_domain") or "").strip()
            if focus_domain:
                lines.append(f"浏览活动主要集中在 {focus_domain}")
            top_domains = feature.get("top_domains")
            if isinstance(top_domains, list):
                domains = [str(item.get("domain") or "").strip() for item in top_domains if isinstance(item, dict)]
                domains = [domain for domain in domains if domain]
                if domains:
                    other_domains = [domain for domain in domains if domain != focus_domain]
                    domain_line = other_domains[:4] if other_domains else domains[:4]
                    lines.append(f"高频访问还包括 {'、'.join(domain_line)}")
        return lines

    def _validate_target_language(self, output: TemporalSummaryLLMOutput) -> None:
        if _target_language_code() != "zh":
            return
        for text in self._user_facing_strings(output):
            if self._looks_like_non_zh_user_text(text):
                raise ValueError("Temporal LLM output does not match target language zh-CN")

    def _user_facing_strings(self, output: TemporalSummaryLLMOutput) -> list[str]:
        strings = [output.content, *output.key_topics]
        if isinstance(output.sentiment_summary, dict):
            strings.extend(str(value) for value in output.sentiment_summary.values() if isinstance(value, str))
        if isinstance(output.change_and_pattern, dict):
            for value in output.change_and_pattern.values():
                if isinstance(value, list):
                    strings.extend(str(item) for item in value if isinstance(item, str))
                elif isinstance(value, str):
                    strings.append(value)
        return [item.strip() for item in strings if item.strip()]

    def _looks_like_non_zh_user_text(self, text: str) -> bool:
        if _CJK_PATTERN.search(text):
            return False
        return bool(_LATIN_WORD_PATTERN.search(text))

    def _render_temporal_summary_prompt(self, pack: TemporalEvidencePack) -> str:
        payload = {
            "summary_type": "temporal",
            "summary_category": pack.summary_category,
            "period_start": pack.period_start,
            "period_end": pack.period_end,
            "window_event_count": pack.window_event_count if pack.window_event_count is not None else pack.source_event_count,
            "source_event_count": pack.source_event_count,
            "omitted_event_count": pack.omitted_event_count,
            "source_event_ids": pack.source_event_ids,
            "importance_aggregate": pack.importance_aggregate,
            "event_type_distribution": pack.event_type_distribution,
            "rule_hints": pack.rule_hints,
            "plugin_summary_features": pack.plugin_summary_features,
            "source_distribution": pack.source_distribution,
            "selection_policy": pack.selection_policy,
            "previous_period_summaries": pack.previous_period_summaries,
            "child_period_summaries": pack.child_period_summaries,
            "events": [
                {
                    "event_id": item.event_id,
                    "event_type": item.event_type,
                    "timestamp": item.timestamp,
                    "memory_domain": item.memory_domain,
                    "importance_score": item.importance_score,
                    "content": item.content,
                }
                for item in pack.events
            ],
        }
        schema = json.dumps(TEMPORAL_SUMMARY_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
        evidence = json.dumps(payload, ensure_ascii=False, indent=2)
        period_focus = self._period_focus_instruction(pack)
        return (
            "Task:\n"
            "Write a temporal summary for the provided memory window.\n"
            "Use the rule_hints as guidance, not as independent evidence.\n"
            "When plugin_summary_features are present, use them to surface source-specific behavior patterns such as concentration, revisits, and session structure.\n"
            "Use source_distribution, window_event_count, and omitted_event_count to understand coverage and avoid treating representative events as exhaustive.\n"
            "Prioritize explicit changes, recurring constraints, and high-importance events.\n"
            "Use previous_period_summaries and child_period_summaries only for comparison and timeline continuity; the current evidence pack remains the source of truth.\n"
            "Do not promote old summary content into a current-window fact unless current evidence also supports it.\n"
            "Do not lead with raw event counts or internal event type names; mention counts only when they change the interpretation.\n\n"
            "Period Focus:\n"
            f"{period_focus}\n\n"
            "Output Requirements:\n"
            "- Return one JSON object only.\n"
            "- Keep content concise and evidence-grounded.\n"
            f"{_target_language_instruction()}\n"
            "- Use empty lists or nulls when a field has no support.\n\n"
            "Output JSON Schema:\n"
            f"{schema}\n\n"
            "Evidence Pack:\n"
            f"{evidence}\n"
        )

    def _period_focus_instruction(self, pack: TemporalEvidencePack) -> str:
        return _PERIOD_FOCUS_INSTRUCTIONS.get(
            str(pack.summary_category),
            _PERIOD_FOCUS_INSTRUCTIONS["week"],
        )

    def _get_adapter(self) -> Any | None:
        if self._scenario_llm_pool is None:
            return None
        try:
            return self._scenario_llm_pool.get(LLMScenario.MEMORY_SUMMARIZER)
        except Exception as exc:
            logger.debug("L3 temporal LLM adapter unavailable: %s", exc)
            return None

    def _get_llm_target(self) -> tuple[Any, LLMProviderBridge] | None:
        adapter = self._get_adapter()
        if adapter is None:
            return None
        return adapter, LLMProviderBridge(adapter)

    def _normalize_importance_aggregate(self, value: Any) -> float | None:
        if value is None:
            return None
        numeric = float(value)
        if numeric < 0.0 or numeric > 1.0:
            raise ValueError("importance_aggregate must be between 0.0 and 1.0")
        return numeric

    def _normalize_sentiment_summary(self, value: Any) -> dict[str, object] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("sentiment_summary must be an object")
        normalized: dict[str, object] = {}
        for key, item in value.items():
            key_str = str(key).strip()
            if not key_str:
                continue
            if key_str == "stress_level":
                stress_level = float(item)
                if stress_level < 0.0 or stress_level > 1.0:
                    raise ValueError("sentiment_summary.stress_level must be between 0.0 and 1.0")
                normalized[key_str] = stress_level
                continue
            if isinstance(item, (str, int, float, bool)) or item is None:
                normalized[key_str] = item
        return normalized or None

    def _normalize_change_and_pattern(self, value: Any) -> dict[str, object] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("change_and_pattern must be an object")
        normalized: dict[str, object] = {}
        for key in ("changes", "patterns"):
            raw = value.get(key)
            if raw is None:
                continue
            if not isinstance(raw, list) or any(not str(item).strip() for item in raw):
                raise ValueError(f"change_and_pattern.{key} must be a list of non-empty strings")
            normalized[key] = [str(item).strip() for item in raw]
        for key, item in value.items():
            if key in normalized or key in {"changes", "patterns"}:
                continue
            if isinstance(item, (str, int, float, bool)) or item is None:
                normalized[str(key)] = item
        return normalized or None

    def _build_rule_hints(
        self,
        evidence_items: list[TemporalEvidenceItem],
        event_type_distribution: dict[str, int],
    ) -> dict[str, object]:
        term_counter: Counter[str] = Counter()
        for item in evidence_items:
            for token in _TOP_TERM_PATTERN.findall(item.content.lower()):
                if token in _STOP_TERMS:
                    continue
                term_counter[token] += 1
        high_importance_event_ids = [
            item.event_id
            for item in sorted(
                evidence_items,
                key=lambda candidate: float(candidate.importance_score or 0.0),
                reverse=True,
            )[:3]
            if item.event_id
        ]
        repeated_event_types = [
            event_type
            for event_type, count in sorted(event_type_distribution.items())
            if count > 1
        ]
        ordered_items = sorted(
            evidence_items,
            key=lambda item: (float(item.timestamp) if item.timestamp is not None else float("inf")),
        )
        window_change_candidates = self._build_window_change_candidates(ordered_items)
        recurring_constraints = self._build_recurring_constraints(evidence_items)
        return {
            "top_terms": [term for term, _count in term_counter.most_common(5)],
            "high_importance_event_ids": high_importance_event_ids,
            "repeated_event_types": repeated_event_types,
            "window_change_candidates": window_change_candidates,
            "recurring_constraints": recurring_constraints,
        }

    def _build_window_change_candidates(
        self,
        evidence_items: list[TemporalEvidenceItem],
    ) -> list[dict[str, object]]:
        if len(evidence_items) < 2:
            return []
        early_terms = self._extract_ranked_terms(evidence_items[0].content)[:3]
        late_terms = self._extract_ranked_terms(evidence_items[-1].content)[:3]
        new_terms = [term for term in late_terms if term not in early_terms][:3]
        dropped_terms = [term for term in early_terms if term not in late_terms][:3]
        if not early_terms and not late_terms:
            return []
        return [
            {
                "kind": "first_last_focus_shift",
                "from_event_id": evidence_items[0].event_id,
                "to_event_id": evidence_items[-1].event_id,
                "early_terms": early_terms,
                "late_terms": late_terms,
                "new_terms": new_terms,
                "dropped_terms": dropped_terms,
            }
        ]

    def _build_recurring_constraints(
        self,
        evidence_items: list[TemporalEvidenceItem],
    ) -> list[dict[str, object]]:
        hits: dict[str, list[str]] = {}
        for item in evidence_items:
            content = item.content.lower()
            matched = [keyword for keyword in _CONSTRAINT_KEYWORDS if keyword in content]
            for keyword in matched:
                hits.setdefault(keyword, [])
                if item.event_id not in hits[keyword]:
                    hits[keyword].append(item.event_id)
        recurring = [
            {
                "keyword": keyword,
                "event_ids": event_ids,
            }
            for keyword, event_ids in sorted(hits.items())
            if len(event_ids) >= 2
        ]
        return recurring

    def _extract_ranked_terms(self, content: str) -> list[str]:
        counter: Counter[str] = Counter()
        for token in _TOP_TERM_PATTERN.findall(content.lower()):
            if token in _STOP_TERMS:
                continue
            counter[token] += 1
        return [term for term, _count in counter.most_common(5)]
